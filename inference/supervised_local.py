"""监督分类——本地影像版（GF-2 / GF-7 等 4 波段 GeoTIFF）

为什么单独一个模块：
在线版（supervised.py）走 Sentinel-2 的 6 波段（含短波红外），特征 12 维；
本地高分影像通常只有 4 波段（蓝/绿/红/近红外，没有 SWIR），
NDBI/BSI 算不出来，只能做 7 维特征：4 波段 + NDVI + NDWI + 亮度。

好处是分辨率高（0.5 m vs 10 m），选点精度、边界贴合度完全不同档次。
口径不变：OA/Kappa 只对本 AOI 本景有效；10m/0.5m 都分不出采坑内部台阶。
"""

from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
from scipy import ndimage

DISCLAIMER = (
    "精度指标（OA/Kappa/PA/UA）只对本次分析的影像与 AOI 有效，不能外推到其它矿区；"
    "本结果为地表覆盖分类，不是储量或品位数据。"
)

CLASS_COLORS = {
    "PIT": (120, 120, 120),
    "DUMP": (176, 137, 96),
    "TAILINGS": (226, 218, 196),
    "BARE": (196, 168, 130),
    "ROAD": (250, 214, 90),
    "VEGETATION": (76, 175, 80),
    "WATER": (33, 130, 214),
}

CLASS_LABELS = {
    "PIT": "露天采坑", "DUMP": "排土场/废石堆", "TAILINGS": "尾矿设施",
    "BARE": "裸地/施工扰动", "ROAD": "道路/工业设施",
    "VEGETATION": "植被", "WATER": "水体",
}

_ALIAS = {
    "采坑": "PIT", "露天采坑": "PIT", "排土场": "DUMP", "废石堆": "DUMP",
    "尾矿": "TAILINGS", "尾矿设施": "TAILINGS", "裸地": "BARE", "扰动区": "BARE",
    "道路": "ROAD", "植被": "VEGETATION", "水体": "WATER",
}

FEATURE_NAMES = ["红", "绿", "蓝", "近红外", "NDVI", "NDWI", "亮度"]


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _postprocess(mask: np.ndarray, min_px: int) -> np.ndarray:
    if not mask.any():
        return mask
    opened = ndimage.binary_opening(mask, structure=np.ones((3, 3), dtype=bool))
    if not opened.any():
        opened = mask
    labels, n = ndimage.label(opened)
    if n == 0:
        return opened
    sizes = ndimage.sum(opened, labels, range(1, n + 1))
    keep = np.zeros_like(opened)
    for idx, size in enumerate(sizes, start=1):
        if size >= min_px:
            keep |= labels == idx
    return keep


def _class_png(classes_arr: np.ndarray, labels: list[str]) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    h, w = classes_arr.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for i, code in enumerate(labels, start=1):
        color = CLASS_COLORS.get(code, (150, 150, 150))
        rgba[classes_arr == i] = (*color, 255)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _to_float(arr: np.ndarray, dtype: str) -> np.ndarray:
    """统一到 0-1 反射率量级（uint8 直接 /255，uint16 按 10000 折算）"""
    a = arr.astype(np.float32)
    if dtype.startswith("uint8"):
        return a / 255.0
    if dtype.startswith("uint16"):
        return a / 10000.0
    return a


def classify_local(payload: dict[str, Any]) -> dict[str, Any]:
    """本地影像监督分类

    payload:
      path        影像绝对路径
      aoi         可选；为空则用整幅影像
      samples     [{classType, lng, lat}]
      maxDim      栅格最大边长（默认 1600，0.5m 影像足够细）
      minSamples  每类最少样本
      minAreaPx   最小图斑像元
    """
    import rasterio
    from affine import Affine
    from rasterio.warp import transform as warp_transform
    from rasterio.windows import from_bounds

    path = payload.get("path")
    if not path:
        raise ValueError("缺少影像路径")
    aoi = payload.get("aoi") or []
    samples_in = payload.get("samples") or []
    max_dim = int(payload.get("maxDim") or 1600)
    min_samples = int(payload.get("minSamples") or 8)
    min_px = int(payload.get("minAreaPx") or 30)

    if not samples_in:
        raise ValueError("还没有样本点：请先在图上一类一类地点选样本")

    with rasterio.open(path) as ds:
        if ds.count < 4:
            raise ValueError(
                f"该影像只有 {ds.count} 个波段，监督分类需要 4 波段（蓝/绿/红/近红外）。"
                "请上传含近红外的高分影像（GF-2/GF-7 四波段）")
        if ds.crs is None:
            raise ValueError("影像没有坐标系，无法按经纬度取样")

        if len(aoi) >= 3:
            lngs = [p[0] for p in aoi]
            lats = [p[1] for p in aoi]
            xs, ys = warp_transform("EPSG:4326", ds.crs,
                                    [min(lngs), max(lngs)], [min(lats), max(lats)])
            win = from_bounds(xs[0], ys[0], xs[1], ys[1], ds.transform)
            win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
            if win.width < 2 or win.height < 2:
                raise ValueError("AOI 不在影像范围内，请重新圈选")
        else:
            win = rasterio.windows.Window(0, 0, ds.width, ds.height)

        # 降采样到 maxDim 以内（0.5m 整幅 6144² 直接算会很慢）
        scale = max(1.0, max(win.width, win.height) / max_dim)
        out_h = max(2, int(win.height / scale))
        out_w = max(2, int(win.width / scale))
        data = ds.read([1, 2, 3, 4], window=win, out_shape=(4, out_h, out_w))
        dtype = ds.dtypes[0]
        transform = ds.window_transform(win) * Affine.scale(win.width / out_w, win.height / out_h)
        crs = ds.crs

    aoi_fallback = False
    if aoi and len(aoi) >= 3:
        from affine import Affine as _Affine
        from rasterio.features import geometry_mask
        from shapely.geometry import Polygon
        from shapely.ops import transform as shp_transform

        poly = Polygon(aoi)

        def _mask_with(flip: bool):
            """把经纬度多边形投到像素坐标后生成掩膜

            rasterio 的 rasterize 约定 y 向下，而 shapely 用右手系；
            这里两种朝向都算一遍，取有效像元多的那个——比猜一个方向稳。
            """
            def to_px(x, y, z=None):
                col, row = ~transform * (x, y)
                return col, (out_h - 1 - row) if flip else row

            poly_px = shp_transform(to_px, poly)
            m = geometry_mask([poly_px], out_shape=(out_h, out_w),
                              transform=_Affine.identity(), invert=True)
            return m

        m_flip = _mask_with(True)
        m_plain = _mask_with(False)
        valid = m_flip if m_flip.sum() >= m_plain.sum() else m_plain
        if valid.sum() < 10:
            # 两种朝向都几乎为空：多为 AOI 与影像不相交，退回整幅并提示
            valid = np.ones((out_h, out_w), dtype=bool)
            aoi_fallback = True
        else:
            aoi_fallback = False
    else:
        valid = np.ones((out_h, out_w), dtype=bool)

    blue = _to_float(data[0], dtype)
    green = _to_float(data[1], dtype)
    red = _to_float(data[2], dtype)
    nir = _to_float(data[3], dtype)

    def norm(a, b):
        return np.divide(a - b, a + b, out=np.zeros_like(a), where=(a + b) != 0)

    ndvi = norm(nir, red)
    ndwi = norm(green, nir)
    brightness = (red + green + blue) / 3.0
    cube = np.stack([red, green, blue, nir, ndvi, ndwi, brightness], axis=-1).astype(np.float32)

    # 样本 → 像素
    rows, cols, ys_lbl = [], [], []
    seen: set[tuple[int, int]] = set()
    dropped = 0
    for s in samples_in:
        raw = str(s.get("classType", "")).strip()
        code = _ALIAS.get(raw, raw)
        if code not in CLASS_COLORS:
            continue
        try:
            px, py = warp_transform("EPSG:4326", crs, [float(s["lng"])], [float(s["lat"])])
            col, row = ~transform * (px[0], py[0])
            r, c = int(row), int(col)
        except Exception:  # noqa: BLE001
            dropped += 1
            continue
        if r < 0 or c < 0 or r >= out_h or c >= out_w or not valid[r, c]:
            dropped += 1
            continue
        if (r, c) in seen:
            dropped += 1
            continue
        seen.add((r, c))
        rows.append(r)
        cols.append(c)
        ys_lbl.append(code)

    if not ys_lbl:
        raise ValueError("样本点全部落在 AOI 外或影像范围外，请重新选点")

    labels = [c for c in CLASS_COLORS if c in set(ys_lbl)]
    if len(labels) < 2:
        raise ValueError("至少需要两个类别才能分类：请补充其它地物的样本")

    counts = {c: ys_lbl.count(c) for c in labels}
    short = {c: n for c, n in counts.items() if n < min_samples}
    if short:
        detail = "、".join(f"{CLASS_LABELS.get(c, c)} {n} 个" for c, n in short.items())
        raise ValueError(f"样本太少，每类至少 {min_samples} 个：{detail}")

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, cohen_kappa_score,
                                 confusion_matrix, precision_recall_fscore_support)
    from sklearn.model_selection import train_test_split

    X = cube[rows, cols, :]
    y = np.array(ys_lbl)
    can_split = min(counts.values()) >= 4 and len(y) >= 20
    if can_split:
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.35, stratify=y, random_state=42)
    else:
        X_tr, y_tr = X, y
        X_te, y_te = X, y

    clf = RandomForestClassifier(n_estimators=200, min_samples_leaf=2,
                                 class_weight="balanced", oob_score=can_split,
                                 n_jobs=-1, random_state=42)
    clf.fit(X_tr, y_tr)
    y_pred = clf.predict(X_te)
    acc = float(accuracy_score(y_te, y_pred))
    kappa = float(cohen_kappa_score(y_te, y_pred))
    cm = confusion_matrix(y_te, y_pred, labels=labels).tolist()
    precision, recall, f1, support = precision_recall_fscore_support(
        y_te, y_pred, labels=labels, zero_division=0)

    pred = clf.predict(cube.reshape(-1, cube.shape[-1])).reshape(out_h, out_w)
    pred[~valid] = ""
    total_px = int(valid.sum())

    # 矢量化：复用 sentinel 的形态指标实现（已在生产链路上验证过）
    import sentinel as sentinel_mod

    out_classes: list[dict] = []
    features_by_class: dict[str, list] = {}
    class_arr = np.zeros((out_h, out_w), dtype=np.uint8)
    for i, code in enumerate(labels):
        mask = _postprocess(pred == code, min_px)
        class_arr[mask] = i + 1
        px = int(mask.sum())
        feats, stats = sentinel_mod._vectorize_with_shape(mask, transform, str(crs), code, {}, 1)
        features_by_class[code] = feats
        out_classes.append({
            "classType": code,
            "label": CLASS_LABELS.get(code, code),
            "color": "#%02x%02x%02x" % CLASS_COLORS.get(code, (150, 150, 150)),
            "areaHa": _r(float(stats.get("totalAreaHa") or 0.0)),
            "pixelCount": px,
            "pctOfAoi": _r(px / total_px * 100) if total_px else 0.0,
            "featureCount": len(feats),
            "sampleCount": counts.get(code, 0),
            "precision": _r(precision[i] * 100, 1),
            "recall": _r(recall[i] * 100, 1),
            "f1": _r(f1[i] * 100, 1),
            "producerAccuracy": _r(recall[i] * 100, 1),
            "userAccuracy": _r(precision[i] * 100, 1),
            "validationCount": int(support[i]),
        })

    warnings: list[str] = []
    if aoi_fallback:
        warnings.append("AOI 掩膜计算异常，已按整幅影像处理")
    if dropped:
        warnings.append(f"{dropped} 个样本落在影像外/无效像元/重复像元，已忽略")
    if not can_split:
        warnings.append("样本量偏少，未做训练/验证拆分，OA 与 Kappa 会偏高，仅作参考")
    warnings.append("本结果基于本地高分影像，精度只对本景与本 AOI 有效")

    importance = sorted(
        ({"name": FEATURE_NAMES[i], "importance": _r(v * 100, 1)}
         for i, v in enumerate(clf.feature_importances_)),
        key=lambda x: -x["importance"])

    return {
        "scene": {"id": None, "datetime": None, "cloudCover": None,
                  "source": "LOCAL", "path": path},
        "grid": {"width": out_w, "height": out_h, "featureCount": cube.shape[-1],
                 "validPixels": total_px},
        "classes": out_classes,
        "features": features_by_class,
        "accuracy": {
            "overallAccuracy": _r(acc * 100, 1),
            "kappa": _r(kappa, 3),
            "oobScore": _r(float(clf.oob_score_) * 100, 1) if can_split else None,
            "labels": labels,
            "labelNames": [CLASS_LABELS.get(c, c) for c in labels],
            "confusionMatrix": cm,
            "sampleCount": len(y),
            "validationCount": len(y_te),
            "split": "65/35 分层抽样" if can_split else "未拆分（样本不足）",
        },
        "featureImportance": importance,
        "imageBase64": _class_png(class_arr, labels),
        "method": "随机森林（200 棵）+ 7 维特征（4 波段 + NDVI + NDWI + 亮度），本地高分影像",
        "samples": [{"classType": c, "count": counts.get(c, 0)} for c in labels],
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }

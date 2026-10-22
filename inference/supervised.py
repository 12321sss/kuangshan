"""监督分类（精细模式）：人工选样本 → 随机森林 → 混淆矩阵 / OA / Kappa

与 classify.py 的分工：
- classify.py：指数阈值法，秒级、零人工，用于演示与粗看，但答不出"准确率多少"
- 本模块：要选样本，十几秒出结果，**能给出 OA/Kappa 与各类 PA·UA**，
  这是方案表 7 的硬要求，也是客户必问的那句话

设计要点：
1. 特征 = 6 个原始波段 + 6 个指数（NDVI/MNDWI/NDBI/NDMI/BSI/亮度）。
   指数进特征能显著提升"采坑 vs 排土场 vs 尾矿"这类同属不透水面的可分性。
2. 样本按**像元坐标**去重：同一像元点两次会被当成两个样本，导致精度虚高。
3. 训练/验证 65:35 分层抽样：用训练样本自评会虚高 10-20 个百分点。
4. 后处理做形态学开运算 + 最小图斑过滤，去掉椒盐噪声。
5. 类别不平衡（采坑面积远小于植被）必须 class_weight="balanced"。

口径红线：
- 10m 分辨率分不出采坑内部台阶，结论只能到"采坑整体 vs 周边"
- OA/Kappa 只代表**本 AOI 本景**的精度，不能外推到其它矿区
"""

from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
from scipy import ndimage

import sentinel as sentinel_mod

DISCLAIMER = (
    "精度指标（OA/Kappa/PA/UA）只对本次分析的 AOI 与影像有效，不能外推到其它矿区；"
    "本结果为地表覆盖分类，不是储量或品位数据。"
)

# 分类配色（与前端地图、报告图例保持一致）
CLASS_COLORS = {
    "PIT": (120, 120, 120),
    "DUMP": (176, 137, 96),
    "TAILINGS": (226, 218, 196),
    "BARE": (196, 168, 130),
    "ROAD": (250, 214, 90),
    "VEGETATION": (76, 175, 80),
    "WATER": (33, 130, 214),
}

# 允许前端传中文类别名
_ALIAS = {
    "采坑": "PIT", "露天采坑": "PIT",
    "排土场": "DUMP", "废石堆": "DUMP",
    "尾矿": "TAILINGS", "尾矿设施": "TAILINGS",
    "裸地": "BARE", "扰动区": "BARE",
    "道路": "ROAD",
    "植被": "VEGETATION",
    "水体": "WATER",
}

FEATURE_NAMES = [
    "B02 蓝", "B03 绿", "B04 红", "B08 近红外", "B11 短波红外1", "B12 短波红外2",
    "NDVI", "MNDWI", "NDBI", "NDMI", "BSI", "亮度",
]


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _build_features(bands: dict[str, np.ndarray]) -> np.ndarray:
    """6 波段 + 6 指数 → (H, W, 12) 特征立方体"""
    b2 = bands["B02"].astype(np.float32) / 10000.0
    b3 = bands["B03"].astype(np.float32) / 10000.0
    b4 = bands["B04"].astype(np.float32) / 10000.0
    b8 = bands["B08"].astype(np.float32) / 10000.0
    b11 = bands["B11"].astype(np.float32) / 10000.0
    b12 = bands["B12"].astype(np.float32) / 10000.0

    def norm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.divide(a - b, a + b, out=np.zeros_like(a), where=(a + b) != 0)

    ndvi = norm(b8, b4)
    mndwi = norm(b3, b11)
    ndbi = norm(b11, b8)
    ndmi = norm(b8, b11)
    bsi = np.divide((b11 + b4) - (b8 + b2), (b11 + b4) + (b8 + b2),
                    out=np.zeros_like(b4), where=((b11 + b4) + (b8 + b2)) != 0)
    brightness = (b2 + b3 + b4) / 3.0

    cube = np.stack([b2, b3, b4, b8, b11, b12,
                     ndvi, mndwi, ndbi, ndmi, bsi, brightness], axis=-1)
    return cube.astype(np.float32)


def _lonlat_to_pixel(lng: float, lat: float, transform, crs) -> tuple[int, int] | None:
    """经纬度 → 栅格行列号（先转到影像 CRS，再按仿射逆变换取像素）"""
    try:
        from rasterio.warp import transform as warp_transform
        xs, ys = warp_transform("EPSG:4326", crs, [lng], [lat])
        col, row = ~transform * (xs[0], ys[0])
        return int(row), int(col)
    except Exception:  # noqa: BLE001
        return None


def _postprocess(mask: np.ndarray, min_px: int) -> np.ndarray:
    """形态学开运算去椒盐 + 最小图斑过滤"""
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
    """分类结果图（无数据像元透明）"""
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


def classify(payload: dict[str, Any]) -> dict[str, Any]:
    """跑一次监督分类

    payload:
      aoi            分析区环
      samples        [{"classType":"PIT","lng":116.02,"lat":26.47}, ...]
      start / end    日期范围
      maxCloud       云量上限
      maxDim         栅格最大边长（控制耗时，默认 1024）
      minSamples     每类最少样本数（默认 8）
      minAreaPx      最小图斑像元数（默认 30）
    """
    aoi = payload.get("aoi") or []
    samples_in = payload.get("samples") or []
    start = payload.get("start") or ""
    end = payload.get("end") or ""
    max_cloud = float(payload.get("maxCloud") or 20)
    max_dim = int(payload.get("maxDim") or 1024)
    min_samples = int(payload.get("minSamples") or 8)

    if len(aoi) < 3:
        raise ValueError("分析区至少需要 3 个点")
    if not samples_in:
        raise ValueError("还没有样本点：请先在地图上一类一类地点选样本")

    # ---- 1. 找影像 ----
    scene = sentinel_mod.search_scene(aoi, start, end, max_cloud)
    if scene is None:
        raise ValueError(
            f"{start} ~ {end} 没有云量低于 {max_cloud}% 的影像，请放宽云量或换时间段")

    # ---- 2. 取波段（B11/B12 是 20m，clip_aoi 会按同一地理范围对齐到 10m 网格）----
    need = ["B02", "B03", "B04", "B08", "B11", "B12"]
    clipped = sentinel_mod.clip_aoi(scene, aoi, need, max_dim=max_dim)
    bands = clipped["bands"]
    cube = _build_features(bands)
    h, w, n_feat = cube.shape

    ref_meta = clipped["meta"]["B04"]
    transform, crs = ref_meta["transform"], ref_meta["crs"]

    # ---- 3. 有效像元：AOI 外已被 clip_aoi 置 0，这里要求关键波段都 >0 ----
    valid = (bands["B02"] > 0) & (bands["B04"] > 0) & (bands["B08"] > 0) & (bands["B11"] > 0)
    if valid.sum() < 100:
        raise ValueError("AOI 内有效像元太少（可能是云覆盖或 AOI 超出影像范围）")

    # ---- 4. 样本 → 像元，按像元去重（同一点两个样本会让精度虚高）----
    rows, cols, ys = [], [], []
    seen: set[tuple[int, int]] = set()
    dropped = 0
    for s in samples_in:
        raw_code = str(s.get("classType", "")).strip()
        code = _ALIAS.get(raw_code, raw_code)
        if code not in CLASS_COLORS:
            continue
        px = _lonlat_to_pixel(float(s["lng"]), float(s["lat"]), transform, crs)
        if px is None:
            dropped += 1
            continue
        r, c = px
        if r < 0 or c < 0 or r >= h or c >= w or not valid[r, c]:
            dropped += 1
            continue
        if (r, c) in seen:
            dropped += 1
            continue
        seen.add((r, c))
        rows.append(r)
        cols.append(c)
        ys.append(code)

    if not ys:
        raise ValueError("样本点全部落在 AOI 外或无效像元上，请重新选点")

    labels = [c for c in CLASS_COLORS if c in set(ys)]
    if len(labels) < 2:
        raise ValueError("至少需要两个类别才能分类：请补充其它地物的样本")

    counts = {c: ys.count(c) for c in labels}
    short = {c: n for c, n in counts.items() if n < min_samples}
    if short:
        detail = "、".join(f"{sentinel_mod.CLASS_LABELS.get(c, c)} {n} 个" for c, n in short.items())
        raise ValueError(
            f"样本太少，每类至少 {min_samples} 个：{detail}。"
            "建议每类 20-40 个，且分散在各类图斑各处，不要全挤在一处")

    X = cube[rows, cols, :]
    y = np.array(ys)

    # ---- 5. 训练（留出验证集，否则精度虚高）----
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, cohen_kappa_score,
                                 confusion_matrix, precision_recall_fscore_support)
    from sklearn.model_selection import train_test_split

    can_split = min(counts.values()) >= 4 and len(y) >= 20
    if can_split:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.35, stratify=y, random_state=42)
    else:
        X_tr, y_tr = X, y
        X_te, y_te = X, y

    clf = RandomForestClassifier(
        n_estimators=200, min_samples_leaf=2, class_weight="balanced",
        oob_score=can_split, n_jobs=-1, random_state=42)
    clf.fit(X_tr, y_tr)

    y_pred = clf.predict(X_te)
    acc = float(accuracy_score(y_te, y_pred))
    kappa = float(cohen_kappa_score(y_te, y_pred))
    cm = confusion_matrix(y_te, y_pred, labels=labels).tolist()
    precision, recall, f1, support = precision_recall_fscore_support(
        y_te, y_pred, labels=labels, zero_division=0)

    # ---- 6. 全图分类 + 后处理 ----
    pred = clf.predict(cube.reshape(-1, n_feat)).reshape(h, w)
    pred[~valid] = ""

    min_px = int(payload.get("minAreaPx") or 30)
    out_classes: list[dict] = []
    features_by_class: dict[str, list[dict]] = {}
    class_arr = np.zeros((h, w), dtype=np.uint8)
    total_px = int(valid.sum())

    for i, code in enumerate(labels):
        mask = _postprocess(pred == code, min_px)
        class_arr[mask] = i + 1
        px = int(mask.sum())
        feats, stats = sentinel_mod._vectorize_with_shape(mask, transform, crs, code, {}, 1)
        features_by_class[code] = feats
        out_classes.append({
            "classType": code,
            "label": sentinel_mod.CLASS_LABELS.get(code, code),
            "color": "#%02x%02x%02x" % CLASS_COLORS.get(code, (150, 150, 150)),
            "areaHa": _r(float(stats.get("totalAreaHa") or 0.0)),
            "pixelCount": px,
            "pctOfAoi": _r(px / total_px * 100) if total_px else 0.0,
            "featureCount": len(feats),
            "sampleCount": counts.get(code, 0),
            "precision": _r(precision[i] * 100, 1),
            "recall": _r(recall[i] * 100, 1),
            "f1": _r(f1[i] * 100, 1),
            # 制图精度/用户精度：客户更习惯这两个叫法
            "producerAccuracy": _r(recall[i] * 100, 1),
            "userAccuracy": _r(precision[i] * 100, 1),
            "validationCount": int(support[i]),
        })

    warnings: list[str] = []
    if dropped:
        warnings.append(f"{dropped} 个样本因落在 AOI 外/无效像元/重复像元被忽略")
    if not can_split:
        warnings.append("样本量偏少，未做训练/验证拆分，OA 与 Kappa 会明显偏高，仅作参考")
    if max(counts.values()) > 6 * min(counts.values()):
        warnings.append("各类样本量差异较大（超过 6 倍），少数类精度可能不稳定")
    warnings.append("10m 分辨率分不出采坑内部台阶，分类结论只到「采坑整体 vs 周边」")

    importance = sorted(
        ({"name": FEATURE_NAMES[i], "importance": _r(v * 100, 1)}
         for i, v in enumerate(clf.feature_importances_)),
        key=lambda x: -x["importance"])

    return {
        "scene": {
            "id": scene.get("id"),
            "datetime": scene.get("datetime"),
            "cloudCover": scene.get("cloudCover"),
        },
        "grid": {"width": w, "height": h, "featureCount": n_feat,
                 "validPixels": total_px},
        "classes": out_classes,
        "features": features_by_class,
        "accuracy": {
            "overallAccuracy": _r(acc * 100, 1),
            "kappa": _r(kappa, 3),
            "oobScore": _r(float(clf.oob_score_) * 100, 1) if can_split else None,
            "labels": labels,
            "labelNames": [sentinel_mod.CLASS_LABELS.get(c, c) for c in labels],
            "confusionMatrix": cm,
            "sampleCount": len(y),
            "validationCount": len(y_te),
            "split": "65/35 分层抽样" if can_split else "未拆分（样本不足）",
        },
        "featureImportance": importance,
        "imageBase64": _class_png(class_arr, labels),
        "method": "随机森林（200 棵）+ 12 维特征（6 波段 + 6 指数），形态学后处理 + 最小图斑过滤",
        "samples": [{"classType": c, "count": counts.get(c, 0)} for c in labels],
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }

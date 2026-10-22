"""分类结果 × 指数结果 叠加分析（融合）

设计见 docs/18。三层能力：
- L1 叠加显示：分类填充 + 指数描边 + 差异三色（本模块出 diff 几何与底图）
- L2 差异分析：交集 / 仅分类 / 仅指数 + IoU + 待核查斑块
- L3 融合产品：按类的三种策略（指数优先 / 仅一致 / 指数补充）

为什么用矢量而不是栅格对齐：
两套结果都已矢量化，几何叠加最准；栅格对齐还要处理两套网格的偏移与重采样，
反而引入额外误差。面积统一换算到局部米制（按中心纬度余弦），与其它模块口径一致。

口径红线（很重要）：
- IoU / 一致率只是**两种方法的一致性**，不是精度，不能写成"分类精度 xx%"
- 不一致区域只能说"建议核查"，不能断言"分类错了"——指数法同样会被阴影欺骗
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

DISCLAIMER = (
    "叠加分析用于两套解译结果的一致性核查：IoU/一致率为方法间一致性，非精度指标；"
    "不一致区域应现场核实，不能据此判定某一方错误。"
)

# 与监督分类、前端保持同一套配色
CLASS_COLORS = {
    "PIT": (120, 120, 120),
    "DUMP": (176, 137, 96),
    "TAILINGS": (226, 218, 196),
    "BARE": (196, 168, 130),
    "ROAD": (250, 214, 90),
    "VEGETATION": (76, 175, 80),
    "WATER": (33, 130, 214),
    "DIFF_ONLY_CLASSIFIED": (239, 108, 0),
    "DIFF_ONLY_INDEX": (30, 136, 229),
    "DIFF_BOTH": (110, 110, 110),
}

STRATEGIES = {"INDICES_FIRST", "INTERSECT_ONLY", "UNION_ADD"}

STRATEGY_LABEL = {
    "INDICES_FIRST": "指数优先",
    "INTERSECT_ONLY": "仅保留一致",
    "UNION_ADD": "指数补充",
}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), 2) if n == 2 else round(float(v), n)


# ---------------------------------------------------------------------------
# 几何工具：经纬度 ↔ 局部米制
# ---------------------------------------------------------------------------

def _feature_to_polygon(feature: dict) -> Polygon | MultiPolygon | None:
    """GeoJSON Feature → shapely 几何（经纬度坐标，暂不投影）"""
    from shapely.geometry import shape

    geom = feature.get("geometry") if feature.get("type") == "Feature" else feature
    if not geom:
        return None
    try:
        g = shape(geom)
    except Exception:  # noqa: BLE001
        return None
    return None if g.is_empty else g


def _union(features: list[dict]) -> Any:
    polys = [p for p in (_feature_to_polygon(f) for f in features or []) if p is not None]
    if not polys:
        return None
    try:
        return unary_union(polys)
    except Exception:  # noqa: BLE001
        return polys[0]


def _lat0_of(geom) -> float:
    try:
        return float(geom.centroid.y)
    except Exception:  # noqa: BLE001
        return 26.0


class _Projector:
    """按中心纬度做等距近似的局部米制投影（几十公里内误差可忽略）"""

    def __init__(self, lat0: float):
        self.lat0 = lat0
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110540.0

    def to_m(self, g):
        def fwd(coords):
            return [(x * self.kx, y * self.ky) for x, y in coords]

        geoms = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        out = []
        for p in geoms:
            if not isinstance(p, Polygon) or p.is_empty:
                continue
            out.append(Polygon(fwd(list(p.exterior.coords)),
                               [fwd(list(r.coords)) for r in p.interiors]))
        if not out:
            return None
        return unary_union(out) if len(out) > 1 else out[0]

    def to_geo(self, g):
        if g is None or g.is_empty:
            return None
        geoms = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        out = []
        for p in geoms:
            if not isinstance(p, Polygon) or p.is_empty:
                continue
            out.append(Polygon([(x / self.kx, y / self.ky) for x, y in p.exterior.coords],
                               [[(x / self.kx, y / self.ky) for x, y in r.coords]
                                for r in p.interiors]))
        if not out:
            return None
        return unary_union(out) if len(out) > 1 else out[0]


def _area_ha(geom_m) -> float:
    return float(geom_m.area) / 10000.0 if geom_m is not None and not geom_m.is_empty else 0.0


def _explode(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if isinstance(g, Polygon)]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _patches(geom_m, proj: _Projector, min_ha: float, top: int) -> list[dict]:
    """差异几何 → 待核查斑块（面积 + 中心经纬度），按面积降序取前 N"""
    out = []
    for p in _explode(geom_m):
        ha = p.area / 10000.0
        if ha < min_ha:
            continue
        c = p.centroid
        out.append({
            "lng": _r(c.x / proj.kx, 6),
            "lat": _r(c.y / proj.ky, 6),
            "areaHa": _r(ha),
        })
    out.sort(key=lambda x: -x["areaHa"])
    return out[:top]


def _geojson(geom_m, proj: _Projector) -> list[dict]:
    """米制几何 → GeoJSON Feature 列表（WGS84）"""
    geo = proj.to_geo(geom_m)
    if geo is None:
        return []
    feats = []
    for i, p in enumerate(_explode(geo)):
        feats.append({
            "type": "Feature",
            "properties": {"id": i},
            "geometry": mapping(p),
        })
    return feats


# ---------------------------------------------------------------------------
# L2 差异分析
# ---------------------------------------------------------------------------

def compare(payload: dict[str, Any]) -> dict[str, Any]:
    classified: dict[str, list] = payload.get("classified") or {}
    indices: dict[str, list] = payload.get("indices") or {}
    options = payload.get("options") or {}
    min_ha = float(options.get("minPatchHa") or 0.2)
    top_n = int(options.get("topPatches") or 10)
    with_image = bool(options.get("withImage", True))

    pairs_in = payload.get("pairs") or []
    if not pairs_in:
        common = [c for c in classified if c in indices]
        pairs_in = [{"classType": c, "strategy": "INDICES_FIRST"} for c in common]

    if not pairs_in:
        raise ValueError(
            "两套结果没有同类型的地物可配对：请确认分类结果与指数结果包含同类（如都有水体）")

    # 统一投影中心：用所有几何的中心纬度
    all_geom = None
    for feats in list(classified.values()) + list(indices.values()):
        g = _union(feats)
        if g is not None:
            all_geom = g if all_geom is None else unary_union([all_geom, g])
    lat0 = _lat0_of(all_geom) if all_geom is not None else 26.0
    proj = _Projector(lat0)

    results = []
    for item in pairs_in:
        cls = item.get("classType")
        if not cls:
            continue
        A = proj.to_m(_union(classified.get(cls) or []))
        B = proj.to_m(_union(indices.get(cls) or []))
        a_ha = _area_ha(A)
        b_ha = _area_ha(B)

        if A is None and B is None:
            results.append({
                "classType": cls,
                "available": False,
                "reason": "两边都没有该类地物",
                "classifiedHa": 0, "indicesHa": 0, "bothHa": 0,
                "onlyClassifiedHa": 0, "onlyIndicesHa": 0,
                "iou": 0, "agreementPct": 0,
                "onlyClassifiedPatches": [], "onlyIndicesPatches": [],
            })
            continue

        both = A.intersection(B) if (A is not None and B is not None) else None
        only_a = A.difference(B) if (A is not None and B is not None) else A
        only_b = B.difference(A) if (A is not None and B is not None) else B

        both_ha = _area_ha(both)
        only_a_ha = _area_ha(only_a)
        only_b_ha = _area_ha(only_b)
        union_ha = _area_ha(A.union(B)) if (A is not None and B is not None) else max(a_ha, b_ha)
        iou = both_ha / union_ha if union_ha > 0 else 0.0
        agreement = both_ha / a_ha * 100 if a_ha > 0 else 0.0
        missing = only_a_ha / a_ha * 100 if a_ha > 0 else 0.0
        extra = only_b_ha / b_ha * 100 if b_ha > 0 else 0.0

        results.append({
            "classType": cls,
            "available": True,
            "classifiedHa": _r(a_ha),
            "indicesHa": _r(b_ha),
            "bothHa": _r(both_ha),
            "onlyClassifiedHa": _r(only_a_ha),
            "onlyIndicesHa": _r(only_b_ha),
            "iou": _r(iou, 3),
            "agreementPct": _r(agreement, 1),
            "missingPct": _r(missing, 1),
            "extraPct": _r(extra, 1),
            "onlyClassifiedPatches": _patches(only_a, proj, min_ha, top_n),
            "onlyIndicesPatches": _patches(only_b, proj, min_ha, top_n),
            "finding": _finding(cls, a_ha, b_ha, both_ha, iou, only_a_ha, only_b_ha),
            "diff": {
                "both": _geojson(both, proj),
                "onlyClassified": _geojson(only_a, proj),
                "onlyIndices": _geojson(only_b, proj),
            },
        })

    ok = [r for r in results if r.get("available")]
    avg_iou = sum(r["iou"] for r in ok) / len(ok) if ok else 0.0
    total_both = sum(r["bothHa"] for r in ok)
    total_only_a = sum(r["onlyClassifiedHa"] for r in ok)
    total_only_b = sum(r["onlyIndicesHa"] for r in ok)

    image = None
    image_meta: dict = {}
    if with_image:
        image, image_meta = _diff_png(classified, indices, [r["classType"] for r in ok], proj)

    return {
        "pairs": results,
        "summary": {
            "pairCount": len(ok),
            "avgIou": _r(avg_iou, 3),
            "bothHa": _r(total_both),
            "onlyClassifiedHa": _r(total_only_a),
            "onlyIndicesHa": _r(total_only_b),
            "conclusion": _summary_text(ok, avg_iou),
        },
        "imageBase64": image,
        "imageMeta": image_meta,
        "legend": [
            {"label": "两边一致", "color": "#6e6e6e"},
            {"label": "仅分类有", "color": "#ef6c00"},
            {"label": "仅指数有", "color": "#1e88e5"},
        ],
        "disclaimer": DISCLAIMER,
    }


def _finding(cls, a_ha, b_ha, both_ha, iou, only_a, only_b) -> str:
    name = {"WATER": "水体", "VEGETATION": "植被", "PIT": "采坑", "BARE": "裸地扰动",
            "DUMP": "排土场", "TAILINGS": "尾矿", "ROAD": "道路"}.get(cls, cls)
    if a_ha <= 0 and b_ha <= 0:
        return f"{name}：两套结果都没有提取到"
    if a_ha <= 0:
        return f"{name}：分类未提取，指数提取 {b_ha:.2f} ha（分类可能漏提）"
    if b_ha <= 0:
        return f"{name}：分类提取 {a_ha:.2f} ha，指数未提取（该类指数判据可能偏严）"
    if iou >= 0.75:
        return f"{name}：一致性好（IoU {iou:.2f}），分类 {a_ha:.2f} ha / 指数 {b_ha:.2f} ha"
    if iou >= 0.5:
        return (f"{name}：基本一致（IoU {iou:.2f}）。仅分类 {only_a:.2f} ha、"
                f"仅指数 {only_b:.2f} ha，建议抽查边界差异")
    return (f"{name}：差异较大（IoU {iou:.2f}）。仅分类 {only_a:.2f} ha、仅指数 {only_b:.2f} ha，"
            "需现场核实后再决定采用哪一套")


def _summary_text(ok: list[dict], avg_iou: float) -> str:
    if not ok:
        return "没有可比较的地物类别"
    worst = min(ok, key=lambda r: r["iou"])
    if avg_iou >= 0.75:
        base = f"两类结果整体一致（平均 IoU {avg_iou:.2f}），可直接采用"
    elif avg_iou >= 0.5:
        base = f"两类结果基本一致（平均 IoU {avg_iou:.2f}），差异区域建议抽查"
    else:
        base = f"两类结果差异明显（平均 IoU {avg_iou:.2f}），建议逐类确认后再融合"
    return f"{base}；一致性最低的是 {worst['classType']}（IoU {worst['iou']}）"


# ---------------------------------------------------------------------------
# L3 融合
# ---------------------------------------------------------------------------

def merge(payload: dict[str, Any]) -> dict[str, Any]:
    """按类的策略融合，返回每类最终几何（WGS84）与面积变化

    未参与的类原样保留分类结果——不能因为只关心水体就把其它类丢掉。
    """
    classified: dict[str, list] = payload.get("classified") or {}
    indices: dict[str, list] = payload.get("indices") or {}
    pairs_in = payload.get("pairs") or []
    if not pairs_in:
        raise ValueError("缺少融合配对：请先做一次差异分析，再选择每类的策略")

    all_cls = sorted(set(classified.keys()) | set(indices.keys()))
    all_geom = None
    for feats in list(classified.values()) + list(indices.values()):
        g = _union(feats)
        if g is not None:
            all_geom = g if all_geom is None else unary_union([all_geom, g])
    proj = _Projector(_lat0_of(all_geom) if all_geom is not None else 26.0)

    strategy_of = {}
    for item in pairs_in:
        cls = item.get("classType")
        st = (item.get("strategy") or "INDICES_FIRST").upper()
        if cls:
            if st not in STRATEGIES:
                raise ValueError(f"不支持的融合策略：{st}")
            strategy_of[cls] = st

    out_classes: list[dict] = []
    features: dict[str, list] = {}
    for cls in all_cls:
        A = proj.to_m(_union(classified.get(cls) or []))
        B = proj.to_m(_union(indices.get(cls) or []))
        st = strategy_of.get(cls)

        if st == "INDICES_FIRST" and B is not None:
            final, source = B, "指数"
        elif st == "INTERSECT_ONLY" and A is not None and B is not None:
            final, source = A.intersection(B), "一致部分"
        elif st == "UNION_ADD" and (A is not None or B is not None):
            if A is None:
                final = B
            elif B is None:
                final = A
            else:
                final = A.union(B)
            source = "分类∪指数"
        else:
            final, source = A, "分类"

        if final is None or final.is_empty:
            continue
        feats = _geojson(final, proj)
        features[cls] = feats
        out_classes.append({
            "classType": cls,
            "strategy": st or "KEEP_CLASSIFIED",
            "strategyLabel": STRATEGY_LABEL.get(st, "保留分类结果") if st else "保留分类结果",
            "source": source,
            "classifiedHa": _r(_area_ha(A)),
            "indicesHa": _r(_area_ha(B)),
            "finalHa": _r(_area_ha(final)),
            "deltaHa": _r(_area_ha(final) - _area_ha(A)),
            "featureCount": len(feats),
        })

    # 融合底图：只画最终结果
    image = None
    image_meta: dict = {}
    if payload.get("withImage", True):
        image, image_meta = _merge_png(features)

    total = sum(c["finalHa"] for c in out_classes)
    return {
        "classes": out_classes,
        "features": features,
        "summary": {
            "classCount": len(out_classes),
            "totalAreaHa": _r(total),
            "fusedClasses": [c["classType"] for c in out_classes if c["strategy"] != "KEEP_CLASSIFIED"],
            "note": "只有标注了策略的类别被替换/合并，其余类别原样保留分类结果",
        },
        "imageBase64": image,
        "imageMeta": image_meta,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# 出图（只出底图，图例与文字由前端合成，避免后端中文字体缺失）
# ---------------------------------------------------------------------------

def _grid(geom_list, target_px: int = 640):
    """算栅格网格：返回 (transform, shape, mpp)"""
    from affine import Affine

    valid = [g for g in geom_list if g is not None and not g.is_empty]
    if not valid:
        return None, (1, 1), 1.0
    minx = min(g.bounds[0] for g in valid)
    miny = min(g.bounds[1] for g in valid)
    maxx = max(g.bounds[2] for g in valid)
    maxy = max(g.bounds[3] for g in valid)
    span = max(maxx - minx, maxy - miny, 1.0)
    mpp = max(1.0, span / target_px)
    w = max(1, int(math.ceil((maxx - minx) / mpp)))
    h = max(1, int(math.ceil((maxy - miny) / mpp)))
    return Affine.translation(minx, maxy) * Affine.scale(mpp, -mpp), (h, w), mpp


def _diff_png(classified, indices, class_list, proj: _Projector) -> str | None:
    try:
        from PIL import Image
        from rasterio import features as riof
    except ImportError:
        return None

    layers = []
    for cls in class_list:
        A = proj.to_m(_union(classified.get(cls) or []))
        B = proj.to_m(_union(indices.get(cls) or []))
        if A is None and B is None:
            continue
        both = A.intersection(B) if (A is not None and B is not None) else None
        only_a = A.difference(B) if (A is not None and B is not None) else A
        only_b = B.difference(A) if (A is not None and B is not None) else B
        layers.append((both, only_a, only_b))

    flat = [g for trio in layers for g in trio if g is not None]
    transform, shape, _mpp = _grid(flat)
    if transform is None:
        return None, {}
    h, w = shape
    rgb = np.full((h, w, 3), 255, dtype=np.uint8)

    def paint(geom, color):
        if geom is None or geom.is_empty:
            return
        mask = riof.rasterize([(geom, 1)], out_shape=(h, w), transform=transform,
                              fill=0, all_touched=True, dtype=np.uint8)
        rgb[mask.astype(bool)] = color

    for both, only_a, only_b in layers:
        paint(both, CLASS_COLORS["DIFF_BOTH"])
        paint(only_a, CLASS_COLORS["DIFF_ONLY_CLASSIFIED"])
        paint(only_b, CLASS_COLORS["DIFF_ONLY_INDEX"])

    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), {"mPerPixel": _r(_mpp, 2), "width": w, "height": h}


def _merge_png(features: dict[str, list]) -> tuple[str | None, dict]:
    try:
        from PIL import Image
        from rasterio import features as riof
    except ImportError:
        return None

    geoms = {}
    for cls, feats in features.items():
        g = _union(feats)
        if g is not None:
            geoms[cls] = g
    if not geoms:
        return None, {}

    proj = _Projector(_lat0_of(next(iter(geoms.values()))))
    gm = {k: proj.to_m(v) for k, v in geoms.items()}
    transform, shape, _mpp = _grid(list(gm.values()))
    if transform is None:
        return None, {}
    h, w = shape
    rgb = np.full((h, w, 3), 255, dtype=np.uint8)
    for cls, g in gm.items():
        if g is None:
            continue
        mask = riof.rasterize([(g, 1)], out_shape=(h, w), transform=transform,
                              fill=0, all_touched=True, dtype=np.uint8)
        rgb[mask.astype(bool)] = CLASS_COLORS.get(cls, (150, 150, 150))
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), {"mPerPixel": _r(_mpp, 2), "width": w, "height": h}

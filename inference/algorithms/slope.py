"""
边坡单元与三区扰动识别

核心思路（见 docs/13）：
边坡失稳不是"坡陡就滑"，而是三种力学扰动导致抗滑力不足：
  ① 坡脚被切（under-cutting）—— 最危险，失去支撑，最易突发失稳
  ② 坡体被削（坡面高程下降，抗滑体量减少、坡角变陡）
  ③ 坡顶堆载（排土场堆在坡顶，下滑力增大）

这三件事恰好都能用「遥感提取的边界 + DEM」算出来：
  - 切脚：坡脚点（单元最低点）到采坑边界的最短距离
  - 削坡：坡面中部高程是否低于周边（需两期 DEM，当前仅静态判断陡缓）
  - 堆载：排土场/尾矿边界是否覆盖坡顶缓冲区

输出以「边坡单元」为基本单位——一个采坑会被切成 5-15 个朝向不同的单元，
每个单元独立给指标与风险等级，避免"全矿区一个平均分"稀释掉最危险的边坡。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# 边坡带的坡度下限：低于此视为平台/缓坡，不构成需要评估的边坡
# 取 10° 而非 15°：南方丘陵矿区大量边坡在 10–20° 区间，
# 用 15° 会把真实边坡整片滤掉（实测宁都河源坡度均值仅 7°）
MIN_SLOPE_DEG = 10.0
# 单个边坡单元的最小面积（像元数），过小说明是碎片
MIN_UNIT_PIXELS = 20
# 坡向扇区数（8 = 每 45° 一个朝向）
ASPECT_SECTORS = 8
# 坡脚的「被切」判定距离（米）：坡脚到采坑边界小于此值视为已切脚
TOE_CUT_DIST_M = 10.0
# 坡顶堆载的缓冲距离（米）
CREST_LOAD_BUFFER_M = 20.0

DISCLAIMER = (
    "本结果为「潜在失稳风险筛查」，基于 10m 级 DEM 与影像解译边界推断地表形态，"
    "不构成边坡稳定性评价，不给安全系数。岩土参数、地下水、结构面产状需现场勘察，"
    "涉及安全生产的决策必须以有资质单位的专项评估为准。"
)


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _to_local_meters(ring: list[list[float]], lat0: float):
    """经纬度环 → 局部米制 Polygon（小范围等距圆柱近似）"""
    from shapely.geometry import Polygon

    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    pts = [(p[0] * kx, p[1] * ky) for p in ring if len(p) >= 2]
    if len(pts) < 3:
        return None
    return Polygon(pts)


def _feature_to_meters(feature: dict, lat0: float):
    """GeoJSON Feature → 局部米制 geometry"""
    from shapely.geometry import Polygon, shape
    from shapely.ops import unary_union

    geom = feature.get("geometry") if feature.get("type") == "Feature" else feature
    if not geom:
        return None
    try:
        g = shape(geom)
    except Exception:  # noqa: BLE001
        return None
    if g.is_empty:
        return None
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    polys = []
    geoms = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
    for p in geoms:
        if p.geom_type != "Polygon":
            continue
        coords = [(x * kx, y * ky) for x, y in p.exterior.coords]
        if len(coords) >= 4:
            polys.append(Polygon(coords))
    if not polys:
        return None
    return unary_union(polys)


def _rasterize(features: list[dict], out_shape: tuple[int, int], transform) -> np.ndarray | None:
    """GeoJSON 要素 → 0/1 掩膜（与 DEM 网格对齐）"""
    from rasterio import features as riof

    shapes = []
    for f in features:
        geom = f.get("geometry") if f.get("type") == "Feature" else f
        if geom:
            shapes.append((geom, 1))
    if not shapes:
        return None
    try:
        return riof.rasterize(shapes, out_shape=out_shape, transform=transform, fill=0, dtype="uint8")
    except Exception:  # noqa: BLE001
        return None


def _laplacian_curvature(elev: np.ndarray, mpp: float) -> np.ndarray:
    """剖面曲率近似（拉普拉斯）

    正值 = 局部低洼（凹，汇水），负值 = 局部凸起（脊，凸形坡）。
    工程上凸形坡坡脚附近应力集中，相对更易失稳。
    这里用 5 点拉普拉斯近似，不是严格的坡向剖面曲率，指标仅用于相对比较。
    """
    z = np.pad(elev.astype(np.float32), 1, mode="edge")
    lap = (z[:-2, 1:-1] + z[2:, 1:-1] + z[1:-1, :-2] + z[1:-1, 2:] - 4.0 * z[1:-1, 1:-1])
    return (lap / (mpp ** 2)).astype(np.float32)


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """边坡单元识别与失稳风险分级

    输入：
      aoi         分析范围环（矿权或扰动范围）
      facilities  [{"classType": "PIT"|"DUMP"|"TAILINGS", "features": [GeoJSON Feature...]}]
      zoom        DEM 级别（默认 14）
      maxDim      栅格最大边长（默认 512）

    输出：单元列表（含三区扰动指标与风险等级）+ 统计 + 专题图
    """
    from scipy import ndimage
    from affine import Affine
    from . import dem as dem_mod

    aoi = payload.get("aoi") or []
    if len(aoi) < 3:
        raise ValueError("分析范围至少需要 3 个点")

    facilities = payload.get("facilities") or []
    zoom = int(payload.get("zoom") or 14)
    max_dim = int(payload.get("maxDim") or 512)

    lat0 = sum(p[1] for p in aoi) / len(aoi)
    lngs = [p[0] for p in aoi]
    lats = [p[1] for p in aoi]

    # ---- 1. 地形 ----
    win = dem_mod.read_dem_window(min(lngs), min(lats), max(lngs), max(lats),
                                  zoom=zoom, max_dim=max_dim)
    elev = win["elevation"]
    mpp = win["mPerPixel"]
    slope, aspect = dem_mod.slope_aspect(elev, mpp)
    curv = _laplacian_curvature(elev, mpp)
    h, w = slope.shape

    b = win["bounds"]
    transform = Affine((b["east"] - b["west"]) / w, 0, b["west"],
                       0, -(b["north"] - b["south"]) / h, b["north"])

    # ---- 2. 设施掩膜（哪个像元属于采坑/排土场/尾矿）----
    facility_masks: dict[str, np.ndarray] = {}
    for item in facilities:
        ct = item.get("classType")
        mask = _rasterize(item.get("features") or [], (h, w), transform)
        if mask is not None:
            facility_masks[ct] = mask

    if not facility_masks:
        return {
            "available": False,
            "message": "没有可用的采坑/排土场/尾矿边界。请先在「遥感提取」页提取这些地物并保存，"
                       "边坡单元需要设施边界才能圈定。",
            "units": [],
            "disclaimer": DISCLAIMER,
        }

    disturbed = np.zeros((h, w), dtype=np.uint8)
    for m in facility_masks.values():
        disturbed |= (m > 0).astype(np.uint8)

    # ---- 3. 边坡带 = 扰动区 ∩ 坡度达标 ----
    band = (disturbed > 0) & (slope >= MIN_SLOPE_DEG)

    # ---- 4. 连通域（同片连续的边坡）----
    labels, n_comp = ndimage.label(band)

    # 诊断信息：解释"为什么单元数为 0"，避免用户以为是系统故障
    diag = {
        "slopeMeanDeg": _r(float(slope.mean()), 1),
        "slopeP90Deg": _r(float(np.percentile(slope, 90)), 1),
        "steepPixelsInDisturbed": int(band.sum()),
        "disturbedPixels": int((disturbed > 0).sum()),
        "minSlopeDeg": MIN_SLOPE_DEG,
        "minUnitPixels": MIN_UNIT_PIXELS,
    }

    if n_comp == 0:
        return {
            "available": True,
            "units": [],
            "summary": {
                "unitCount": 0, "high": 0, "higher": 0, "medium": 0, "low": 0,
                "totalAreaHa": 0, "maxSlopeHeightM": 0, "cutToeCount": 0,
                "note": f"扰动区内没有坡度 ≥{MIN_SLOPE_DEG:.0f}° 的连片边坡。"
                        f"全区平均坡度 {diag['slopeMeanDeg']}°，P90 {diag['slopeP90Deg']}°，"
                        f"扰动区内达标像元仅 {diag['steepPixelsInDisturbed']} 个。",
            },
            "diagnostics": diag,
            "imageBase64": None,
            "disclaimer": DISCLAIMER,
        }

    # ---- 5. 米制几何：用于坡脚到边界的距离计算 ----
    pit_polys = []
    for ct in ("PIT",):
        for item in facilities:
            if item.get("classType") != ct:
                continue
            for f in item.get("features") or []:
                g = _feature_to_meters(f, lat0)
                if g is not None:
                    pit_polys.append(g)
    pit_union = None
    if pit_polys:
        from shapely.ops import unary_union
        pit_union = unary_union(pit_polys)

    dump_polys = []
    for ct in ("DUMP", "TAILINGS"):
        for item in facilities:
            if item.get("classType") != ct:
                continue
            for f in item.get("features") or []:
                g = _feature_to_meters(f, lat0)
                if g is not None:
                    dump_polys.append(g)
    dump_union = None
    if dump_polys:
        from shapely.ops import unary_union
        dump_union = unary_union(dump_polys)

    from shapely.geometry import Point

    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0

    def px_to_lnglat(r: int, c: int) -> tuple[float, float]:
        """栅格行列 → 经纬度（像元中心）"""
        lng = b["west"] + (c + 0.5) * (b["east"] - b["west"]) / w
        lat = b["north"] - (r + 0.5) * (b["north"] - b["south"]) / h
        return lng, lat

    units: list[dict[str, Any]] = []
    sector_grid = ((aspect + 360.0 / ASPECT_SECTORS / 2.0) % 360.0 // (360.0 / ASPECT_SECTORS)).astype(np.int32)

    for lbl in range(1, n_comp + 1):
        comp = labels == lbl
        if comp.sum() < MIN_UNIT_PIXELS:
            continue
        # 该连通域所属设施（取覆盖最多的那个）
        fac_votes: dict[str, int] = {}
        for ct, m in facility_masks.items():
            fac_votes[ct] = int((comp & (m > 0)).sum())
        facility = max(fac_votes.items(), key=lambda x: x[1])[0] if fac_votes else "PIT"

        # 按坡向扇区再拆：同一片边坡若呈环形（如采坑四周），朝向差别很大，必须分开
        secs = sector_grid[comp]
        for sec in np.unique(secs):
            sub = comp & (sector_grid == sec)
            px = int(sub.sum())
            if px < MIN_UNIT_PIXELS:
                continue

            ys, xs = np.nonzero(sub)
            sub_elev = elev[ys, xs]
            sub_slope = slope[ys, xs]
            sub_curv = curv[ys, xs]

            # 坡脚 = 最低点；坡顶 = 最高点
            i_toe = int(np.argmin(sub_elev))
            i_crest = int(np.argmax(sub_elev))
            toe_r, toe_c = int(ys[i_toe]), int(xs[i_toe])
            crest_r, crest_c = int(ys[i_crest]), int(xs[i_crest])
            toe_lng, toe_lat = px_to_lnglat(toe_r, toe_c)
            crest_lng, crest_lat = px_to_lnglat(crest_r, crest_c)

            slope_height = float(sub_elev[i_crest] - sub_elev[i_toe])
            area_ha = px * (mpp ** 2) / 10000.0
            mean_slope = float(sub_slope.mean())
            p95_slope = float(np.percentile(sub_slope, 95))
            mean_curv = float(sub_curv.mean())
            aspect_deg = float(sec) * (360.0 / ASPECT_SECTORS) + (180.0 / ASPECT_SECTORS)

            # ---- 三区扰动 ----
            # ① 切脚距离
            toe_dist = None
            if pit_union is not None:
                try:
                    toe_pt = Point(toe_lng * kx, toe_lat * ky)
                    toe_dist = float(pit_union.boundary.distance(toe_pt))
                except Exception:  # noqa: BLE001
                    toe_dist = None

            # ② 坡脚被切比例：坡脚周围 R 内的采坑覆盖率
            toe_cut_ratio = 0.0
            if pit_union is not None and toe_dist is not None:
                r_px = max(2, int(round(TOE_CUT_DIST_M / mpp)))
                r0, r1 = max(0, toe_r - r_px), min(h, toe_r + r_px + 1)
                c0, c1 = max(0, toe_c - r_px), min(w, toe_c + r_px + 1)
                pit_mask_any = np.zeros((h, w), dtype=np.uint8)
                for ct in ("PIT",):
                    if ct in facility_masks:
                        pit_mask_any |= (facility_masks[ct] > 0).astype(np.uint8)
                patch = pit_mask_any[r0:r1, c0:c1]
                toe_cut_ratio = float(patch.mean()) if patch.size else 0.0

            # ③ 坡顶堆载：仅对**采坑边坡**有意义
            #   排土场/尾矿本身就是堆体，判断"坡顶是否有堆载"是同义反复；
            #   堆体边坡的稳定性由自身堆高与坡角决定，走下面的堆高判据。
            top_loaded = False
            if facility == "PIT" and dump_union is not None:
                try:
                    crest_pt = Point(crest_lng * kx, crest_lat * ky)
                    top_loaded = bool(dump_union.distance(crest_pt) <= CREST_LOAD_BUFFER_M)
                except Exception:  # noqa: BLE001
                    top_loaded = False

            # ---- 分级（按 docs/13 判据）----
            reasons: list[str] = []
            level = "低"

            cut_toe = toe_dist is not None and toe_dist <= TOE_CUT_DIST_M
            if cut_toe and slope_height > 50:
                level = "高"
                reasons.append(f"坡脚距采坑边界 {_r(toe_dist, 1)}m（已切脚）且坡高 {_r(slope_height, 0)}m")
            if toe_cut_ratio > 0.3 and mean_slope > 35:
                level = "高"
                reasons.append(f"坡脚被切比例 {_r(toe_cut_ratio * 100, 0)}%、平均坡度 {_r(mean_slope, 1)}°")
            if level == "低" and top_loaded and mean_slope > 30:
                level = "较高"
                reasons.append(f"坡顶有堆载且平均坡度 {_r(mean_slope, 1)}°")
            if level == "低" and slope_height > 80:
                level = "较高"
                reasons.append(f"坡高 {_r(slope_height, 0)}m（高边坡）")
            # 堆体（排土场/尾矿）自身稳定性：堆得越高越陡越危险
            if level == "低" and facility in ("DUMP", "TAILINGS") and slope_height > 30 and mean_slope > 25:
                level = "较高"
                reasons.append(
                    f"堆体边坡：堆高 {_r(slope_height, 0)}m、坡度 {_r(mean_slope, 1)}°，"
                    "堆体自身稳定性需关注")
            if level == "低" and (mean_slope > 35 or slope_height > 60):
                level = "中"
                reasons.append(f"平均坡度 {_r(mean_slope, 1)}°、坡高 {_r(slope_height, 0)}m")
            if level == "低" and not reasons:
                reasons.append(
                    f"坡度 {_r(mean_slope, 1)}°、坡高 {_r(slope_height, 0)}m，"
                    f"未触发判据（坡脚距采坑 {_r(toe_dist, 0) if toe_dist is not None else '未知'}m）")

            units.append({
                "id": len(units) + 1,
                "label": int(lbl),
                "sector": int(sec),
                "facility": facility,
                "areaHa": _r(area_ha, 3),
                "pixelCount": px,
                "centerLng": _r(px_to_lnglat(int(ys.mean()), int(xs.mean()))[0], 6),
                "centerLat": _r(px_to_lnglat(int(ys.mean()), int(xs.mean()))[1], 6),
                "toeLng": _r(toe_lng, 6),
                "toeLat": _r(toe_lat, 6),
                "crestLng": _r(crest_lng, 6),
                "crestLat": _r(crest_lat, 6),
                "slopeHeightM": _r(max(slope_height, 0), 1),
                "meanSlopeDeg": _r(mean_slope, 1),
                "maxSlopeDeg": _r(p95_slope, 1),
                "aspectDeg": _r(aspect_deg, 0),
                "curvature": _r(mean_curv, 4),
                "toeDistanceM": _r(toe_dist, 1) if toe_dist is not None else None,
                "toeCutRatio": _r(toe_cut_ratio * 100, 1),
                "topLoaded": top_loaded,
                "riskLevel": level,
                "reasons": reasons,
            })

    # ---- 6. 排序与统计 ----
    order = {"高": 0, "较高": 1, "中": 2, "低": 3}
    units.sort(key=lambda u: (order.get(u["riskLevel"], 9), -u["slopeHeightM"]))

    summary = {
        "unitCount": len(units),
        "high": sum(1 for u in units if u["riskLevel"] == "高"),
        "higher": sum(1 for u in units if u["riskLevel"] == "较高"),
        "medium": sum(1 for u in units if u["riskLevel"] == "中"),
        "low": sum(1 for u in units if u["riskLevel"] == "低"),
        "totalAreaHa": _r(sum(u["areaHa"] for u in units), 2),
        "maxSlopeHeightM": _r(max((u["slopeHeightM"] for u in units), default=0), 1),
        "cutToeCount": sum(1 for u in units if u["toeDistanceM"] is not None and u["toeDistanceM"] <= TOE_CUT_DIST_M),
    }

    return {
        "available": True,
        "units": units[:60],       # 前端只展示前 60 个，避免一次渲染过多
        "summary": summary,
        "diagnostics": diag,
        "imageBase64": _units_png(labels, band, sector_grid, units, slope.shape),
        "legend": [
            {"label": "高", "color": "#d32f2f"},
            {"label": "较高", "color": "#ff9800"},
            {"label": "中", "color": "#ffd54f"},
            {"label": "低", "color": "#8bc34a"},
        ],
        "disclaimer": DISCLAIMER,
        "precision": {
            "groundResolutionM": _r(mpp, 1),
            "minSlopeDeg": MIN_SLOPE_DEG,
            "toeCutDistM": TOE_CUT_DIST_M,
            "limitation": "10m 级 DEM 无法分辨台阶坡面角与坑内细节；坡高为像元级最高最低差，"
                          "受 DEM 垂直误差（±5-10m）影响，精度约 ±10m。"
                          "切脚距离基于解译边界，边界精度约 1-2 像元。",
        },
    }


def _units_png(labels: np.ndarray, band: np.ndarray, sector_grid: np.ndarray,
               units: list[dict], shape: tuple[int, int]) -> str | None:
    """边坡单元专题图：按各单元实际风险等级着色（高红/较高橙/中黄/低绿）

    背景用浅灰标出非边坡区，便于一眼看出边坡带位置与危险单元分布。
    """
    import base64
    import io

    from PIL import Image

    color_map = {
        "高": (211, 47, 47),
        "较高": (255, 152, 0),
        "中": (255, 213, 79),
        "低": (139, 195, 74),
    }
    h, w = shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[~band] = (240, 242, 245)

    for u in units:
        m = (labels == u["label"]) & (sector_grid == u["sector"])
        if m.any():
            rgb[m] = color_map.get(u["riskLevel"], (200, 200, 200))

    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

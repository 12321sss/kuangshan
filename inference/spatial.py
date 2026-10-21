"""空间关系与专项风险：坑内积水 / 尾矿水面 / 排土场汇流 / 道路切坡 / 采坑形态 / 生态缓冲区

为什么单独一个模块：
这六项的共同点是「**两个已有图层叠一下就能得出结论**」——水体叠采坑、道路叠陡坡、
排土场叠汇流路径、缓冲区叠植被。它们不需要新数据源，但需要把几何对齐到同一栅格网格，
否则面积、占比、长度都算不准。几何叠加用 rasterize 做，比逐多边形求交快且稳
（解译结果常有几千个小碎斑，逐对求交会很慢）。

口径红线：
- 只输出「潜在风险筛查」，不报实测侵蚀量、不给安全系数
- 汇流用的是「相对低洼度代理」，不是 D8 水文算法，结论只能用于定位排查位置
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import numpy as np
from affine import Affine
from rasterio import features as riof
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

import dem as dem_mod
import risk as risk_mod

DISCLAIMER = (
    "本页为潜在风险筛查：所有结论基于公开 10m 级地形与影像解译结果，"
    "用于指出需要现场核查的位置，不构成稳定性评价，不给出安全系数与侵蚀量。"
)

# 等级 → 配色（与安全评估保持一致，避免同一平台两套颜色语义）
LEVEL_COLOR = {
    "高": "#d32f2f",
    "较高": "#ff9800",
    "中": "#ffd54f",
    "低": "#8bc34a",
    "不可用": "#b0b6be",
}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _polygon_of(features: list[dict], lat0: float):
    """一组 GeoJSON Feature → 合并后的米制多边形（用于算周长/形状指数）"""
    polys = []
    for f in features or []:
        p = risk_mod._feature_to_polygon(f, lat0)
        if p is not None:
            polys.append(p)
    if not polys:
        return None
    try:
        merged = unary_union(polys)
        return merged
    except Exception:  # noqa: BLE001
        return polys[0]


def _rasterize(geom, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """shapely/GeoJSON 几何 → 布尔栅格（对齐 DEM 网格）"""
    if geom is None:
        return np.zeros(shape, dtype=bool)
    try:
        geoms = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    except Exception:  # noqa: BLE001
        geoms = [geom]
    out = np.zeros(shape, dtype=np.uint8)
    # 这里传入的几何是"米制"坐标，但栅格 transform 是地理坐标，
    # 所以调用方必须先转回经纬度再栅格化（见 _to_geo）。
    shapes = [(g, 1) for g in geoms if g is not None and not g.is_empty]
    if not shapes:
        return out.astype(bool)
    out = riof.rasterize(shapes, out_shape=shape, transform=transform,
                         fill=0, all_touched=True, dtype=np.uint8)
    return out.astype(bool)


def _to_geo(geom, lat0: float):
    """米制多边形 → 经纬度多边形（kx/ky 反算），供栅格化使用"""
    if geom is None:
        return None
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0

    def conv_ring(coords):
        return [(x / kx, y / ky) for x, y in coords]

    try:
        geoms = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    except Exception:  # noqa: BLE001
        return None
    out = []
    for g in geoms:
        if not isinstance(g, Polygon) or g.is_empty:
            continue
        out.append(Polygon(conv_ring(list(g.exterior.coords)),
                           [conv_ring(list(r.coords)) for r in g.interiors]))
    if not out:
        return None
    return unary_union(out) if len(out) > 1 else out[0]


def _px_area_ha(mask: np.ndarray, mpp: float) -> float:
    return float(mask.sum()) * mpp * mpp / 10000.0


def _item(key: str, label: str, level: str, finding: str, advice: str,
          metrics: list[dict] | None = None, available: bool | None = None,
          note: str = "") -> dict:
    # 等级为「不可用」时默认不算入可用项，避免汇总时把"没数据"当成"低风险"
    if available is None:
        available = level != "不可用"
    return {
        "key": key,
        "label": label,
        "available": available,
        "level": level,
        "color": LEVEL_COLOR.get(level, "#b0b6be"),
        "finding": finding,
        "advice": advice,
        "metrics": metrics or [],
        "note": note,
    }


def _m(label: str, value: Any, unit: str = "", hint: str = "") -> dict:
    return {"label": label, "value": value, "unit": unit, "hint": hint}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    classes: dict[str, list[dict]] = payload.get("classes") or {}
    permit = payload.get("permit") or []
    prev_water = payload.get("prevWater") or []
    prev_pit = payload.get("prevPit") or []
    buffer_km = float(payload.get("bufferKm") or 2.0)
    cut_deg = float(payload.get("slopeCutDeg") or 15.0)
    zoom = int(payload.get("zoom") or 14)
    max_dim = int(payload.get("maxDim") or 768)

    # ---- 分析范围：矿权优先；没有就用所有地物的外包框 ----
    ring = permit
    if len(ring) < 3:
        pts = []
        for feats in classes.values():
            for f in feats:
                g = (f.get("geometry") or {})
                for ring_pts in _all_rings(g):
                    pts.extend(ring_pts)
        if len(pts) < 3:
            raise ValueError("没有可用的分析范围：既没有矿权边界，解译结果也为空")
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ring = [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]]

    lat0 = sum(p[1] for p in ring) / len(ring)
    lng0 = sum(p[0] for p in ring) / len(ring)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    west, east, south, north = min(xs), max(xs), min(ys), max(ys)

    # DEM 窗口要**包住缓冲区**，否则缓冲区落在窗口外统计不出来（初期就踩过这个坑）。
    # 扩边按纬度换算成度，经度再按 cos(lat) 收紧。
    pad_km = max(0.0, min(buffer_km, 3.0)) if buffer_km > 0 else 0.0
    d_lat = pad_km / 110.54
    d_lng = pad_km / (111.32 * max(math.cos(math.radians(lat0)), 0.2))
    west, east = west - d_lng, east + d_lng
    south, north = south - d_lat, north + d_lat

    # ---- DEM：六项里三项要用坡度/汇流 ----
    win = dem_mod.read_dem_window(west, south, east, north, zoom=zoom, max_dim=max_dim)
    elev = win["elevation"]
    h, w = elev.shape
    mpp = float(win["mPerPixel"])
    slope, _aspect = dem_mod.slope_aspect(elev, mpp)
    # 用窗口实际范围构造变换，保证栅格与几何严格对齐
    transform = Affine.translation(west, north) * Affine.scale((east - west) / w, -(north - south) / h)

    def mask_of(class_key: str) -> np.ndarray:
        feats = classes.get(class_key) or []
        if not feats:
            return np.zeros((h, w), dtype=bool)
        geo = _to_geo(_polygon_of(feats, lat0), lat0)
        return _rasterize(geo, transform, (h, w))

    m_water = mask_of("WATER")
    m_pit = mask_of("PIT")
    m_dump = mask_of("DUMP")
    m_tail = mask_of("TAILINGS")
    m_road = mask_of("ROAD")
    m_veg = mask_of("VEGETATION")
    m_dist = m_pit | m_dump | m_tail | m_road

    items: list[dict] = []

    # ---------------- B6 坑内积水 ----------------
    if not m_pit.any():
        items.append(_item("pond_in_pit", "坑内积水", "不可用",
                           "尚未提取采坑，无法判断坑内积水",
                           "先在遥感提取页提取「露天采坑」，再做本项检查"))
    elif not m_water.any():
        items.append(_item("pond_in_pit", "坑内积水", "低",
                           "采坑范围内没有检出水面",
                           "保持常规巡查；雨季加密一次影像核查",
                           [_m("采坑面积", _r(_px_area_ha(m_pit, mpp)), "ha")]))
    else:
        both = m_water & m_pit
        pond_ha = _px_area_ha(both, mpp)
        pit_ha = _px_area_ha(m_pit, mpp)
        ratio = pond_ha / pit_ha * 100 if pit_ha > 0 else 0
        if ratio >= 15:
            level = "高"
            finding = f"坑内积水 {_r(pond_ha)} ha，占采坑 {_r(ratio, 1)}%，已达采坑面积的 1/6 以上"
            advice = "优先核查排水系统是否失效、坑底是否贯通旧巷道；雨季前必须落实强排能力"
        elif ratio >= 5:
            level = "较高"
            finding = f"坑内积水 {_r(pond_ha)} ha，占采坑 {_r(ratio, 1)}%"
            advice = "核查坑底集水区与排水沟是否淤堵，关注水位上涨速率"
        else:
            level = "中"
            finding = f"坑内积水 {_r(pond_ha)} ha，占采坑 {_r(ratio, 1)}%，规模有限"
            advice = "纳入常规巡查，雨季复核一次"
        items.append(_item("pond_in_pit", "坑内积水", level, finding, advice,
                           [_m("坑内水面", _r(pond_ha), "ha"),
                            _m("占采坑比例", _r(ratio, 1), "%"),
                            _m("采坑面积", _r(pit_ha), "ha")]))

    # ---------------- B7 尾矿库水面变化 ----------------
    if not m_tail.any():
        items.append(_item("tailings_water", "尾矿库水面", "不可用",
                           "尚未提取尾矿设施，无法做水面变化判断",
                           "先提取「尾矿设施」；有历史期数据时再开启变化对比"))
    else:
        cur = m_water & m_tail
        cur_ha = _px_area_ha(cur, mpp)
        tail_ha = _px_area_ha(m_tail, mpp)
        metrics = [_m("当前水面", _r(cur_ha), "ha"), _m("尾矿设施面积", _r(tail_ha), "ha")]
        prev_ha = None
        if prev_water:
            geo = _to_geo(_polygon_of(prev_water, lat0), lat0)
            m_prev = _rasterize(geo, transform, (h, w)) & m_tail
            prev_ha = _px_area_ha(m_prev, mpp)
            delta = cur_ha - prev_ha
            pct = (delta / prev_ha * 100) if prev_ha > 0.01 else None
            metrics += [_m("上一期水面", _r(prev_ha), "ha"),
                        _m("变化", ("+" if delta >= 0 else "") + str(_r(delta)), "ha")]
            if pct is not None:
                metrics.append(_m("变化幅度", ("+" if pct >= 0 else "") + str(_r(pct, 1)), "%"))
            if pct is not None and pct >= 20:
                level, finding = "高", f"尾矿库水面较上期扩大 {_r(pct, 1)}%（{_r(delta)} ha），需核查排渗与库水位"
                advice = "核对库水位与设计洪水位、检查排渗设施；水面持续扩大是溃坝风险的前兆信号"
            elif pct is not None and pct >= 8:
                level, finding = "较高", f"尾矿库水面较上期扩大 {_r(pct, 1)}%，呈上升趋势"
                advice = "关注库水位变化速率，结合排渗观测数据一并判断"
            else:
                level = "低" if pct is None or abs(pct) < 8 else "中"
                finding = (f"尾矿库水面 {_r(cur_ha)} ha，较上期变化 {_r(delta)} ha，未见异常"
                           if prev_ha is not None else
                           f"尾矿库水面 {_r(cur_ha)} ha（缺少上一期水体结果，未做变化判断）")
                advice = "保持常规监测；建议按季度积累水面数据以便趋势判断"
        else:
            level = "中"
            finding = f"尾矿库水面 {_r(cur_ha)} ha（缺少上一期水体结果，未做变化判断）"
            advice = "补齐上一期水体提取后即可判断水面变化"
        items.append(_item("tailings_water", "尾矿库水面", level, finding, advice, metrics,
                           note="" if prev_ha is not None else "缺少历史期数据，仅给现状"))

    # ---------------- B8 排土场汇流路径 ----------------
    if not m_dump.any():
        items.append(_item("dump_flow", "排土场汇流路径", "不可用",
                           "尚未提取排土场，无法判断是否压占汇水通道",
                           "先提取「排土场/废石堆」"))
    else:
        flow = dem_mod.flow_proxy(slope, elev)
        base = flow[m_dist] if m_dist.any() else flow
        thr = float(np.percentile(base, 85)) if base.size else 0.0
        on_flow = m_dump & (flow >= thr) & (flow > 0)
        dump_ha = _px_area_ha(m_dump, mpp)
        flow_ha = _px_area_ha(on_flow, mpp)
        ratio = flow_ha / dump_ha * 100 if dump_ha > 0 else 0
        if ratio >= 25:
            level = "较高"
            finding = f"排土场约 {_r(ratio, 0)}%（{_r(flow_ha)} ha）压占相对低洼汇水区"
            advice = "核查坡脚截排水沟与拦挡设施；强降雨时该类部位易形成泥石流物源"
        elif ratio >= 10:
            level = "中"
            finding = f"排土场约 {_r(ratio, 0)}%（{_r(flow_ha)} ha）位于相对低洼汇水区"
            advice = "检查排土场周边排水走向，避免堆体堵塞自然沟道"
        else:
            level = "低"
            finding = f"排土场与汇水通道重叠很小（{_r(ratio, 1)}%）"
            advice = "维持常规排水维护"
        items.append(_item("dump_flow", "排土场汇流路径", level, finding, advice,
                           [_m("排土场面积", _r(dump_ha), "ha"),
                            _m("压占汇水面积", _r(flow_ha), "ha"),
                            _m("压占比例", _r(ratio, 1), "%")],
                           note="汇流为相对低洼度代理，用于定位排查位置，非水文计算"))

    # ---------------- B9 道路切坡 ----------------
    if not m_road.any():
        items.append(_item("road_cut", "道路切坡", "不可用",
                           "尚未提取道路/工业设施，无法判断切坡段",
                           "先提取「道路/工业设施」"))
    else:
        cut = m_road & (slope >= cut_deg)
        road_ha = _px_area_ha(m_road, mpp)
        cut_ha = _px_area_ha(cut, mpp)
        ratio = cut_ha / road_ha * 100 if road_ha > 0 else 0
        max_slope = float(slope[cut].max()) if cut.any() else 0.0
        if ratio >= 20:
            level = "较高"
            finding = f"{_r(ratio, 0)}% 的道路（{_r(cut_ha)} ha）位于 ≥{int(cut_deg)}° 坡面，最大坡度 {_r(max_slope, 1)}°"
            advice = "重点核查切坡段边坡支护与排水；该类路段雨后易发生小型塌方"
        elif ratio >= 8:
            level = "中"
            finding = f"{_r(ratio, 0)}% 的道路位于陡坡段，最大坡度 {_r(max_slope, 1)}°"
            advice = "对陡坡段做一次现场排查，关注边坡有无裂缝、渗水"
        else:
            level = "低"
            finding = f"道路基本沿平缓地形展布（陡坡段占 {_r(ratio, 1)}%）"
            advice = "维持常规巡查"
        items.append(_item("road_cut", "道路切坡", level, finding, advice,
                           [_m("道路面积", _r(road_ha), "ha"),
                            _m("陡坡段面积", _r(cut_ha), "ha"),
                            _m("陡坡段占比", _r(ratio, 1), "%")]))

    # ---------------- C4 生态缓冲区 ----------------
    ring_ring = [[float(p[0]), float(p[1])] for p in ring]
    permit_poly_m = risk_mod._to_local_meters(ring_ring, lat0)
    if permit_poly_m is None:
        items.append(_item("eco_buffer", "生态缓冲区", "不可用",
                           "矿权边界无效，无法生成缓冲区", "检查导入的矿权边界是否闭合"))
    else:
        buf_m = permit_poly_m.buffer(buffer_km * 1000.0)
        buffer_only_m = buf_m.difference(permit_poly_m)
        m_buffer = _rasterize(_to_geo(buffer_only_m, lat0), transform, (h, w))
        m_inside = _rasterize(_to_geo(permit_poly_m, lat0), transform, (h, w))
        buf_px = int(m_buffer.sum())
        in_px = int(m_inside.sum())
        veg_feats = classes.get("VEGETATION") or []
        # 关键校验：植被是在某个 AOI 范围内提取的，缓冲区常在 AOI 之外。
        # 若不在提取范围内就算「缓冲区植被占比」，会得出「缓冲区一片荒芜」的假结论。
        veg_bbox = _bbox_of_features(veg_feats)
        veg_cover_pct = 0.0
        if veg_bbox and buf_px > 0:
            m_bbox = _rasterize(_bbox_polygon(veg_bbox), transform, (h, w))
            veg_cover_pct = float((m_buffer & m_bbox).sum()) / buf_px * 100

        if not m_veg.any():
            items.append(_item("eco_buffer", "生态缓冲区", "不可用",
                               "尚未提取植被，无法比较缓冲区内外的植被状况",
                               "先提取「植被」，再做缓冲区分析"))
        elif buf_px < 50:
            items.append(_item("eco_buffer", "生态缓冲区", "不可用",
                               "缓冲区落在影像/地形窗口之外，无法统计",
                               "把缓冲区半径改小，或先在边界管理里导入完整的矿权范围"))
        elif veg_cover_pct < 80:
            items.append(_item("eco_buffer", "生态缓冲区", "不可用",
                               f"植被提取范围只覆盖缓冲区的 {_r(veg_cover_pct, 0)}%，"
                               f"据此比较内外差异会得出错误结论",
                               "把缓冲区半径改小；或在包含缓冲区的外扩范围内重新提取植被后再分析",
                               [_m("植被覆盖到的缓冲区比例", _r(veg_cover_pct, 0), "%",
                                   "低于 80% 判为不可比")],
                               note="植被解译结果只在其 AOI 范围内有效，不能外推到范围外"))
        else:
            veg_buf = (m_veg & m_buffer).sum() / buf_px * 100
            veg_in = (m_veg & m_inside).sum() / in_px * 100 if in_px > 0 else 0.0
            gap = veg_buf - veg_in
            metrics = [_m("缓冲区植被占比", _r(veg_buf, 1), "%", f"半径 {buffer_km} km"),
                       _m("矿区内植被占比", _r(veg_in, 1), "%"),
                       _m("内外差", ("+" if gap >= 0 else "") + str(_r(gap, 1)), "%")]
            if gap >= 15:
                level = "较高"
                finding = f"缓冲区植被占比 {_r(veg_buf, 1)}%，高出矿区内部 {_r(gap, 1)} 个百分点，扰动影响集中"
                advice = "把缓冲区作为生态修复与水土保持的重点关注带，按年度对比其植被变化"
            elif gap >= 5:
                level = "中"
                finding = f"缓冲区植被略优于矿区内部（差 {_r(gap, 1)} 个百分点）"
                advice = "按季度跟踪缓冲带植被变化，作为扰动扩散的早期信号"
            else:
                level = "低"
                finding = f"缓冲区与矿区内部植被占比接近（差 {_r(gap, 1)} 个百分点）"
                advice = "植被梯度不明显，可结合裸地占比进一步判断扩散趋势"
            items.append(_item("eco_buffer", "生态缓冲区", level, finding, advice, metrics,
                               note="缓冲区为环带状（不含矿区内部）；对比口径为植被像元占比"))

    # ---------------- A3 采坑二维形态 ----------------
    if not m_pit.any():
        items.append(_item("pit_shape", "采坑形态", "不可用",
                           "尚未提取采坑，无法计算形态指标", "先提取「露天采坑」"))
        pit_shapes = []
    else:
        pit_poly = _polygon_of(classes.get("PIT") or [], lat0)
        pit_shapes = []
        if pit_poly is not None:
            geoms = list(pit_poly.geoms) if isinstance(pit_poly, MultiPolygon) else [pit_poly]
            geoms = sorted([g for g in geoms if g.area > 1000], key=lambda g: -g.area)[:5]
            prev_radius = None
            if prev_pit:
                prev_poly = _polygon_of(prev_pit, lat0)
                if prev_poly is not None and prev_poly.area > 0:
                    prev_radius = math.sqrt(prev_poly.area / math.pi)
            for idx, g in enumerate(geoms, 1):
                area_ha = g.area / 10000.0
                perim = g.length
                # 形状指数：4πA/P²，正圆=1，越接近 0 说明边界越曲折/多向扩张
                shape_index = (4 * math.pi * g.area / (perim * perim)) if perim > 0 else 0
                radius = math.sqrt(g.area / math.pi)
                adv = _r(radius - prev_radius, 1) if prev_radius else None
                pit_shapes.append({
                    "id": idx,
                    "areaHa": _r(area_ha),
                    "perimeterM": _r(perim, 0),
                    "shapeIndex": _r(shape_index, 3),
                    "equivRadiusM": _r(radius, 1),
                    "advanceM": adv,
                })
            if pit_shapes:
                worst = max(pit_shapes, key=lambda s: s["areaHa"])
                adv_txt = (f"最大采坑边界等效推进 {worst['advanceM']} m"
                           if worst.get("advanceM") is not None else "缺少上一期采坑结果，未算推进速度")
                level = "中" if worst["shapeIndex"] < 0.35 else "低"
                items.append(_item("pit_shape", "采坑形态", level,
                                   f"识别 {len(pit_shapes)} 个采坑，最大 {worst['areaHa']} ha，"
                                   f"形状指数 {worst['shapeIndex']}；{adv_txt}",
                                   "形状指数偏低说明多方向扩张，建议核对是否按设计境界推进；"
                                   "推进速度按等效半径估算，用于趋势判断而非精确测量",
                                   [_m("采坑数", len(pit_shapes), "个"),
                                    _m("最大采坑", worst["areaHa"], "ha"),
                                    _m("形状指数", worst["shapeIndex"], "", "1=正圆，越低越曲折"),
                                    _m("最大周长", worst["perimeterM"], "m")],
                                   note="形态指标基于 10m 影像解译边界，边界锯齿会影响周长类指标"))
                worst_shape = {"shapeIndex": worst["shapeIndex"]}

    # ---- 7. 专题图（把风险叠加关系画出来，比看数字直观）----
    image = _overlay_png(m_pit, m_dump, m_tail, m_road, m_water, slope, cut_deg)

    # ---- 汇总 ----
    order = {"高": 0, "较高": 1, "中": 2, "低": 3, "不可用": 4}
    usable = [i for i in items if i["available"]]
    top = sorted(usable, key=lambda i: order.get(i["level"], 9))
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "available": len(usable),
            "high": sum(1 for i in usable if i["level"] == "高"),
            "higher": sum(1 for i in usable if i["level"] == "较高"),
            "medium": sum(1 for i in usable if i["level"] == "中"),
            "low": sum(1 for i in usable if i["level"] == "低"),
            "headline": (top[0]["finding"] if top else "没有可评估的空间关系项"),
        },
        "pitShapes": pit_shapes,
        "grid": {"width": w, "height": h, "mPerPixel": _r(mpp, 2), "zoom": zoom},
        "imageBase64": image,
        "legend": [
            {"label": "采坑", "color": "#9e9e9e"},
            {"label": "排土场", "color": "#c49a6c"},
            {"label": "尾矿", "color": "#e0d6c3"},
            {"label": "水体", "color": "#1e88e5"},
            {"label": "道路", "color": "#fdd835"},
            {"label": f"陡坡(≥{int(cut_deg)}°)", "color": "#ef5350"},
        ],
        "disclaimer": DISCLAIMER,
    }


def _bbox_of_features(features: list[dict]) -> tuple[float, float, float, float] | None:
    """一组要素的经纬度外包框；用于判断"解译结果到底覆盖了多大范围" """
    xs: list[float] = []
    ys: list[float] = []
    for f in features or []:
        for ring in _all_rings(f.get("geometry") or {}):
            for p in ring:
                xs.append(p[0])
                ys.append(p[1])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_polygon(bbox: tuple[float, float, float, float]) -> Polygon:
    w, s, e, n = bbox
    return Polygon([(w, s), (e, s), (e, n), (w, n)])


def _all_rings(geom: dict) -> list[list[list[float]]]:
    """GeoJSON 几何 → 所有外环坐标（用于拿不到边界时估算外包框）"""
    if not geom:
        return []
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"][0]] if geom.get("coordinates") else []
    if t == "MultiPolygon":
        return [p[0] for p in geom.get("coordinates") or [] if p]
    return []


def _overlay_png(m_pit, m_dump, m_tail, m_road, m_water, slope, cut_deg) -> str | None:
    """叠加关系专题图：底图为陡坡（红），叠加各类设施与水体"""
    try:
        from PIL import Image
    except ImportError:
        return None

    h, w = slope.shape
    rgb = np.full((h, w, 3), 255, dtype=np.uint8)
    # 陡坡作为底：越陡越红
    steep = slope >= cut_deg
    rgb[steep] = (254, 205, 210)
    rgb[slope >= cut_deg + 10] = (239, 154, 154)

    def paint(mask, color, alpha=1.0):
        if not mask.any():
            return
        c = np.array(color, dtype=np.float32)
        cur = rgb[mask].astype(np.float32)
        rgb[mask] = (cur * (1 - alpha) + c * alpha).astype(np.uint8)

    paint(m_pit, (158, 158, 158), 0.85)
    paint(m_dump, (196, 154, 108), 0.85)
    paint(m_tail, (224, 214, 195), 0.9)
    paint(m_road, (253, 216, 53), 0.9)
    paint(m_water, (30, 136, 229), 0.9)

    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

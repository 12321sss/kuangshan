"""
矿山开采安全风险评估（多因子融合）

设计目标：回答「这座矿山是否在安全地开采」——不只要一个分数，
更要给出「哪块地危险、为什么危险、该去核查什么」。

四层因子体系（权重可配置）：
  A 形态风险  terrain   0.25   坡度陡峭度、地形起伏、采坑内陡坡占比
  B 扩张风险  expansion 0.25   采坑扩张速率(ha/年)、边界推进速度(m/年)、扰动新增速率
  C 越界风险  encroach  0.20   采坑超出矿权边界的面积占比
  D 覆盖风险  coverage  0.15   植被覆盖不足、裸地占比高
  E 水文风险  hydrology 0.15   低洼汇水、坑内积水、排土场位于汇水路径

输出三层：
  1. 总分 + 5 维分项（每项带证据数值与建议核查方式）
  2. 风险分级栅格图（PNG，叠加到三维地球）
  3. 风险热点清单（位置、面积、主导因子、建议）

口径红线（写进响应，前端与报告必须原样展示）：
  本结果定位为**潜在安全风险筛查**，不是边坡稳定性评价，
  不给安全系数，不使用「该边坡稳定/不稳定」的表述；
  遥感可观测的是地表形态与覆盖变化，岩土参数、地下水、结构面
  需现场勘察与工程手段，不在模型能力范围内。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 权重与分级
# ---------------------------------------------------------------------------
# AHP 判断矩阵（6×6），顺序与 _DIM_KEYS 一致
# 取值依据：矿山开采安全中「形态（边坡）」与「扩张强度」是主导风险；
# 越界涉及合规、覆盖与水文反映地表稳定性、生态质量作为综合状态分量。
_AHP_MATRIX = np.array([
    #  形态   扩张   越界   覆盖   水文   生态
    [1.0,   1.0,  1.5,  2.0,  2.0,  3.0],   # 形态风险
    [1.0,   1.0,  1.5,  2.0,  2.0,  3.0],   # 扩张风险
    [1/1.5, 1/1.5, 1.0, 1.5,  1.5,  2.0],   # 越界风险
    [1/2.0, 1/2.0, 1/1.5, 1.0, 1.0,  1.5],  # 覆盖风险
    [1/2.0, 1/2.0, 1/1.5, 1.0, 1.0,  1.5],  # 水文风险
    [1/3.0, 1/3.0, 1/2.0, 1/1.5, 1/1.5, 1.0],  # 生态风险
])

# 随机一致性指标 RI（Saaty）
_RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}

_DIM_KEYS = ["terrain", "expansion", "encroach", "coverage", "hydrology", "ecology"]
_DIM_LABELS = {
    "terrain": "形态风险", "expansion": "扩张风险", "encroach": "越界风险",
    "coverage": "覆盖风险", "hydrology": "水文风险", "ecology": "生态风险",
}


def ahp_weights() -> dict[str, Any]:
    """AHP 求权重 + 一致性检验（CR < 0.1 表示判断矩阵可接受）。

    用 AHP 而非直接拍权重，是为了让权重可追溯、可复核、可通过一致性检验，
    报告里能写明「权重经 AHP 一致性检验，CR=x」。
    """
    a = _AHP_MATRIX
    n = a.shape[0]
    weights = (a / a.sum(axis=0)).mean(axis=1)
    lam_max = float(np.mean((a @ weights) / weights))
    ci = (lam_max - n) / (n - 1) if n > 2 else 0.0
    ri = _RI.get(n, 1.45)
    cr = ci / ri if ri > 0 else 0.0
    return {
        "weights": [round(float(w), 4) for w in weights],
        "lambdaMax": round(lam_max, 4),
        "CI": round(ci, 4),
        "CR": round(cr, 4),
        "consistent": cr < 0.1,
        "note": "CR < 0.1，判断矩阵一致性可接受" if cr < 0.1
                else "CR ≥ 0.1，判断矩阵一致性不足，需调整",
    }


_AHP = ahp_weights()
DIMENSIONS = [(k, _DIM_LABELS[k], w) for k, w in zip(_DIM_KEYS, _AHP["weights"])]

LEVELS = [
    (20, "低", "#4caf50"),
    (40, "较低", "#aed581"),
    (60, "中", "#ffd54f"),
    (80, "较高", "#ff9800"),
    (101, "高", "#d32f2f"),
]

DISCLAIMER = (
    "本结果为「潜在安全风险筛查」，基于公开遥感影像与地形数据的地表指标推断，"
    "不构成边坡稳定性评价，不给出安全系数。岩土力学参数、地下水条件、"
    "结构面产状等需现场勘察；涉及安全生产的决策必须以有资质单位的专项评估为准。"
)


def _level_of(score: float) -> tuple[str, str]:
    for limit, label, color in LEVELS:
        if score < limit:
            return label, color
    return "高", "#d32f2f"


def _safety_level(safety_index: float) -> str:
    """安全指数（100-风险分）对应的等级措辞，供报告直接引用"""
    if safety_index >= 80:
        return "安全"
    if safety_index >= 60:
        return "基本安全"
    if safety_index >= 40:
        return "需关注"
    if safety_index >= 20:
        return "风险较高"
    return "高风险"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


# ---------------------------------------------------------------------------
# 几何工具（经纬度 → 局部米制，避免 shapely 用度数算面积）
# ---------------------------------------------------------------------------
def _to_local_meters(ring: list[list[float]], lat0: float):
    """经纬度环 → 局部米制坐标（等距圆柱近似）

    小范围（几十公里内）误差可忽略；直接拿度数算面积会得到度数²，
    数量级完全错误，必须先投影。
    """
    from shapely.geometry import Polygon

    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    pts = [(p[0] * kx, p[1] * ky) for p in ring if len(p) >= 2]
    if len(pts) < 3:
        return None
    return Polygon(pts)


def _feature_to_polygon(feature: dict, lat0: float):
    """GeoJSON Feature（WGS84）→ 局部米制 Polygon"""
    from shapely.geometry import Polygon, shape

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
    if g.geom_type == "Polygon":
        coords = [(x * kx, y * ky) for x, y in g.exterior.coords]
        return Polygon(coords) if len(coords) >= 4 else None
    if g.geom_type == "MultiPolygon":
        polys = []
        for p in g.geoms:
            coords = [(x * kx, y * ky) for x, y in p.exterior.coords]
            if len(coords) >= 4:
                polys.append(Polygon(coords))
        if not polys:
            return None
        from shapely.ops import unary_union
        return unary_union(polys)
    return None


# ---------------------------------------------------------------------------
# A 形态风险
# ---------------------------------------------------------------------------
def _terrain_risk(terrain: dict | None, pit_ratio_of_aoi: float) -> dict[str, Any]:
    """坡度陡峭度 + 起伏 + 采坑内陡坡集中度

    评分逻辑（0-100，越高越危险）：
      陡坡占比 ≥25% → 满分区间；15-25% 线性过渡
      平均坡度 >15° → 加分
      起伏 >300m → 加分（高陡地形）
    """
    evidence: list[str] = []
    if not terrain:
        return {
            "score": 40.0,
            "confidence": "low",
            "evidence": ["缺少地形数据，按中性分 40 计（建议先做地形分析）"],
            "advice": "补做地形分析后再看该项",
        }

    s = terrain
    steep_pct = float(s.get("steepPct") or 0)
    slope_mean = float(s.get("slopeMean") or 0)
    relief = float(s.get("reliefM") or 0)

    # 陡坡占比：25% 即达 100 分
    score_steep = _clamp(steep_pct / 25.0 * 100)
    # 平均坡度：15° 达 100 分
    score_slope = _clamp(slope_mean / 15.0 * 100)
    # 起伏：300m 达 100 分
    score_relief = _clamp(relief / 300.0 * 100)

    score = 0.5 * score_steep + 0.3 * score_slope + 0.2 * score_relief

    evidence.append(f"陡坡(≥15°)占比 {steep_pct}%")
    evidence.append(f"平均坡度 {slope_mean}°（P90 {s.get('slopeP90')}°）")
    evidence.append(f"地形起伏 {relief} m")
    if pit_ratio_of_aoi > 0:
        evidence.append(f"采坑面积占分析区 {_r(pit_ratio_of_aoi * 100)}%")

    advice = (
        "优先核查陡坡集中区（坡度≥25°）的边帮与台阶状况；"
        "若采坑已形成高陡边坡，需现场量测台阶坡面角与坡高"
    )
    return {"score": _r(score), "confidence": "medium", "evidence": evidence, "advice": advice}


# ---------------------------------------------------------------------------
# B 扩张风险
# ---------------------------------------------------------------------------
def _expansion_risk(trend: dict | None) -> dict[str, Any]:
    """扩张速率风险

    评分逻辑：
      采坑扩张 ≥20 ha/年 → 100 分（硬岩露天矿年推进 20ha 已属高速）
      边界推进 ≥30 m/年 → 100 分（等效半径年增长，参考露天矿常规推进速度）
      扰动新增 ≥50 ha/年 → 100 分
    """
    evidence: list[str] = []
    if not trend or not trend.get("periods"):
        return {
            "score": 30.0,
            "confidence": "low",
            "evidence": ["时序期数不足，无法计算扩张速率（至少需 2 期）"],
            "advice": "补充历史期次解译后重算",
        }

    periods = int(trend.get("periods") or 0)
    pit_rate = float(trend.get("pitGrowthHaPerYear") or 0)
    edge_rate = float(trend.get("edgeAdvanceMPerYear") or 0)
    disturb_rate = float(trend.get("disturbGrowthHaPerYear") or 0)

    score_pit = _clamp(abs(pit_rate) / 20.0 * 100)
    score_edge = _clamp(abs(edge_rate) / 30.0 * 100)
    score_dist = _clamp(abs(disturb_rate) / 50.0 * 100)

    score = 0.45 * score_pit + 0.35 * score_edge + 0.20 * score_dist

    evidence.append(f"采坑扩张 {_r(pit_rate)} ha/年（共 {periods} 期）")
    evidence.append(f"边界等效推进 {_r(edge_rate)} m/年")
    evidence.append(f"扰动新增 {_r(disturb_rate)} ha/年")
    if trend.get("reliable") is False:
        evidence.append("注意：首期缺少部分地物记录，扩张速率已置零处理，该项得分偏低不代表真实扩张弱")
        score = min(score, 35.0)
    if pit_rate < 0:
        evidence.append("注意：采坑面积为负增长，可能是回填、边界修订或解译口径变化，需核查")

    return {
        "score": _r(score),
        "confidence": "high" if periods >= 3 else "medium",
        "evidence": evidence,
        "advice": "核对扩张速率与采矿设计产能是否匹配；突增期需比对生产台账",
    }


# ---------------------------------------------------------------------------
# C 越界风险
# ---------------------------------------------------------------------------
def _encroach_risk(encroach: dict) -> dict[str, Any]:
    """采坑超出矿权边界的比例

    评分逻辑：越界占比 ≥3% 即高风险（越界开采属重大合规问题，
    阈值故意设得很严——哪怕少量也需要复核，但评分不直接判违规）。
    """
    evidence: list[str] = []
    if not encroach.get("available"):
        return {
            "score": 20.0,
            "confidence": "low",
            "evidence": ["未提供矿权边界，无法做越界判定"],
            "advice": "在项目里登记矿权边界后可自动检测",
        }

    pct = float(encroach.get("pctOfDisturbance") or 0)   # 越界面积 / 扰动总面积
    area_ha = float(encroach.get("areaHa") or 0)

    score = _clamp(pct / 3.0 * 100)
    evidence.append(f"越界面积 {_r(area_ha)} ha，占扰动总面积 {_r(pct)}%")
    if area_ha > 0:
        evidence.append("越界判定基于影像解译的扰动边界与登记矿权边界的叠加，两者来源与日期不同")
    advice = (
        "越界区域需先确认是否为解译边界误差（影像配准、边界日期不一致），"
        "再核对采矿许可范围；确认越界属重大事项，应按管理规定上报"
    )
    return {"score": _r(score), "confidence": "medium", "evidence": evidence, "advice": advice}


# ---------------------------------------------------------------------------
# D 覆盖风险
# ---------------------------------------------------------------------------
def _ecology_risk(rsei_stats: dict | None) -> dict[str, Any]:
    """生态风险：基于遥感生态指数 RSEI

    RSEI 越低说明生态质量越差（植被稀疏、地表裸露、湿度低、干度大），
    地表抗蚀与固土能力弱，间接抬高水土流失与边坡失稳风险。

    RSEI 为三因子版本（绿度/湿度/干度），不含热环境维度——
    Sentinel-2 没有热红外波段，详见 ecology.py 的口径说明。
    """
    if not rsei_stats or rsei_stats.get("mean") is None:
        return {
            "score": 40.0,
            "confidence": "low",
            "evidence": ["未计算 RSEI，按中性偏保守分计入"],
            "advice": "在提取页执行一次生态指数计算可获得该维度",
        }

    mean = float(rsei_stats["mean"])
    # RSEI 0.75 以上视为生态良好（风险 0），0 则风险满分
    score = _clamp((0.75 - mean) / 0.75 * 100)

    evidence = [f"RSEI 均值 {mean:.3f}"]
    levels = rsei_stats.get("levels") or []
    poor = sum(l["pct"] for l in levels if l.get("label") in ("差", "较差"))
    if levels:
        evidence.append(f"生态「差/较差」等级共占 {poor:.1f}%")

    if mean < 0.3:
        advice = "生态质量偏低，建议核查裸地扩张与植被恢复措施落实情况"
    elif mean < 0.55:
        advice = "生态质量中等，关注裸地与水系周边的植被恢复"
    else:
        advice = "生态质量尚可，保持常规监测"

    return {
        "score": round(score, 2),
        "confidence": "high",
        "evidence": evidence,
        "advice": advice,
        "rseiMean": round(mean, 4),
        "rseiPoorPct": round(poor, 2) if levels else None,
    }


def _coverage_risk(classes_ha: dict[str, float], aoi_ha: float) -> dict[str, Any]:
    """植被覆盖不足 + 裸地占比高

    说明：这里用的是「解译面积占分析区的比例」作为覆盖度代理，
    并非像元级 FVC 反演（后者需要逐像元 NDVI，成本高），
    两者口径不同，报告中须注明。
    """
    evidence: list[str] = []
    if aoi_ha <= 0:
        return {
            "score": 40.0,
            "confidence": "low",
            "evidence": ["分析区面积未知，按中性分计"],
            "advice": "先完成圈选与解译",
        }

    veg = classes_ha.get("VEGETATION", 0.0)
    bare = classes_ha.get("BARE", 0.0)
    disturbed = sum(classes_ha.get(k, 0.0) for k in ("PIT", "DUMP", "TAILINGS", "BARE", "ROAD"))

    veg_ratio = veg / aoi_ha if aoi_ha else 0
    disturbed_ratio = min(1.0, disturbed / aoi_ha) if aoi_ha else 0

    # 植被占比越低越危险（有植被 60% 以上视为健康）
    score_veg = _clamp((1.0 - min(veg_ratio / 0.6, 1.0)) * 100)
    # 扰动占比越高越危险（50% 达满分）
    score_dist = _clamp(disturbed_ratio / 0.5 * 100)

    score = 0.55 * score_veg + 0.45 * score_dist

    evidence.append(f"植被面积占比 {_r(veg_ratio * 100)}%（按解译面积统计）")
    evidence.append(f"扰动类合计占比 {_r(disturbed_ratio * 100)}%（采坑+排土场+尾矿+裸地+道路）")
    evidence.append(f"裸地面积 {_r(bare)} ha")
    return {
        "score": _r(score),
        "confidence": "medium",
        "evidence": evidence,
        "advice": "重点看植被持续下降与裸地扩张的叠加区；复绿评估需连续多期植被信号，单期不足以判定",
    }


# ---------------------------------------------------------------------------
# E 水文风险
# ---------------------------------------------------------------------------
def _hydrology_risk(terrain: dict | None, pond_pct: float, dump_on_flow: bool) -> dict[str, Any]:
    """低洼汇水 + 坑内积水 + 排土场位于汇水路径

    评分逻辑：
      低洼汇水占比 ≥5% → 100 分
      排土场位于汇水路径 → 直接加 30 分（泥石流/溃散风险显著抬高）
    """
    evidence: list[str] = []
    score = 30.0
    if terrain:
        score_pond = _clamp(pond_pct / 5.0 * 100)
        score = 0.7 * score_pond + 0.3 * 30.0
        evidence.append(f"低洼汇水候选区占 {_r(pond_pct)}%")
    else:
        evidence.append("缺少地形数据，汇水判断不可用")

    if dump_on_flow:
        score = _clamp(score + 30)
        evidence.append("排土场/尾矿设施存在与低洼汇水区重叠，堆体稳定性风险抬高")

    return {
        "score": _r(score),
        "confidence": "medium" if terrain else "low",
        "evidence": evidence,
        "advice": "核查坑内排水能力与排土场截排水设施；雨季前后对比影像可观察冲刷痕迹",
    }


# ---------------------------------------------------------------------------
# 风险栅格与热点
# ---------------------------------------------------------------------------
def build_risk_grid(
    slope: np.ndarray,
    pond: np.ndarray,
    shape_mask: np.ndarray | None,
    outside_mask: np.ndarray | None,
) -> np.ndarray:
    """栅格级风险合成（0-100）

    权重：坡度 0.40、汇水 0.15、位于扰动区内 0.25、越界 0.20
    栅格风险主要用于「定位热点」，与区域级 5 维评分是两套视角，
    不追求数值一致。
    """
    slope_n = np.clip(slope / 30.0, 0, 1)          # 30° 视为满分
    pond_n = np.clip(pond / max(float(np.percentile(pond, 95)), 1.0), 0, 1)
    in_dist = (shape_mask > 0).astype(np.float32) if shape_mask is not None else np.zeros_like(slope_n)
    out_permit = (outside_mask > 0).astype(np.float32) if outside_mask is not None else np.zeros_like(slope_n)

    grid = 100.0 * (0.40 * slope_n + 0.15 * pond_n + 0.25 * in_dist + 0.20 * out_permit)
    return np.clip(grid, 0, 100).astype(np.float32)


def extract_hotspots(
    grid: np.ndarray, mpp: float, west: float, north: float,
    threshold: float = 60.0, max_points: int = 10, min_pixels: int = 12,
) -> list[dict[str, Any]]:
    """从风险栅格中提取热点（连通域 + 中心点）

    用简易 4 邻域连通域（BFS），避免引入 scipy。
    """
    mask = grid >= threshold
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    cur = 0
    hotspots: list[dict[str, Any]] = []

    for r0 in range(h):
        for c0 in range(w):
            if not mask[r0, c0] or labels[r0, c0]:
                continue
            cur += 1
            stack = [(r0, c0)]
            labels[r0, c0] = cur
            pixels: list[tuple[int, int]] = []
            while stack:
                y, x = stack.pop()
                pixels.append((y, x))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = cur
                        stack.append((ny, nx))
            if len(pixels) < min_pixels:
                continue
            ys = np.array([p[0] for p in pixels])
            xs = np.array([p[1] for p in pixels])
            cy, cx = float(ys.mean()), float(xs.mean())
            area_ha = len(pixels) * (mpp ** 2) / 10000.0
            # 网格左上角是 (west, north)，像素单位换算回经纬度
            lng = west + cx * _deg_per_px(mpp, north)
            lat = north - cy * _deg_per_px(mpp, north)
            mean_score = float(grid[ys, xs].mean())
            hotspots.append({
                "lng": _r(lng, 6),
                "lat": _r(lat, 6),
                "areaHa": _r(area_ha, 3),
                "score": _r(mean_score, 1),
                "maxScore": _r(float(grid[ys, xs].max()), 1),
                "pixelCount": len(pixels),
            })

    hotspots.sort(key=lambda x: (x["score"] * x["areaHa"]), reverse=True)
    return hotspots[:max_points]


def _deg_per_px(mpp: float, lat: float) -> float:
    """米/像素 → 度/像素（经向近似，用于反算热点坐标）"""
    return mpp / (111320.0 * max(math.cos(math.radians(lat)), 1e-6))


def risk_png(grid: np.ndarray) -> bytes:
    """风险栅格 → 5 级彩色 PNG"""
    import io
    from PIL import Image

    rgb = np.zeros((*grid.shape, 3), dtype=np.uint8)
    for limit, _label, color in LEVELS:
        hexc = color.lstrip("#")
        rgb[grid < limit] = tuple(int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _rasterize_geoms(features: list[dict], out_shape: tuple[int, int],
                     transform) -> np.ndarray | None:
    """GeoJSON 要素 → 0/1 掩膜（与 DEM 网格对齐）

    transform 为经纬度仿射变换（DEM 窗口的 bounds 推得），
    要素坐标为 WGS84，两者一致，无需重投影。
    """
    from rasterio import features as riof

    shapes = []
    for f in features:
        geom = f.get("geometry") if f.get("type") == "Feature" else f
        if geom:
            shapes.append((geom, 1))
    if not shapes:
        return None
    try:
        out = riof.rasterize(shapes, out_shape=out_shape, transform=transform,
                             fill=0, dtype="uint8")
        return out
    except Exception:  # noqa: BLE001
        return None


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    """安全风险评估主流程

    输入（前端/Java 汇总后传入）：
      aoi               分析区环（通常是矿权边界或扰动范围）
      permitBoundary    矿权边界环（用于越界检测，可为空）
      classes           各类地物的 GeoJSON 要素列表（含 classType）
      trend             时序趋势（扩张速率等）
      withGrid          是否生成风险栅格图与热点（默认 true，需读 DEM）
      zoom              DEM 放大级别（默认 14）
    """
    from shapely.ops import unary_union

    aoi = payload.get("aoi") or []
    permit = payload.get("permitBoundary") or []
    classes_payload = payload.get("classes") or []
    trend = payload.get("trend")
    pond_pct = float(payload.get("pondPct") or 0)

    if len(aoi) < 3:
        raise ValueError("分析区环至少需要 3 个点")

    lat0 = sum(p[1] for p in aoi) / len(aoi)

    # ---- 各类型几何汇总（D2 并集去重的基础）----
    class_polys: dict[str, Any] = {}
    class_area_ha: dict[str, float] = {}
    for item in classes_payload:
        ct = item.get("classType")
        feats = item.get("features") or []
        polygons = [p for p in (_feature_to_polygon(f, lat0) for f in feats) if p is not None]
        if not polygons:
            continue
        merged = unary_union(polygons)
        class_polys[ct] = merged
        class_area_ha[ct] = float(merged.area) / 10000.0

    # 扰动类并集（先合并再算面积，避免采坑/裸地/排土场重叠导致重复计面积）
    disturbed_keys = ("PIT", "DUMP", "TAILINGS", "BARE", "ROAD")
    disturbed_polys = [class_polys[k] for k in disturbed_keys if k in class_polys]
    disturbed_union = unary_union(disturbed_polys) if disturbed_polys else None
    disturbed_ha = float(disturbed_union.area) / 10000.0 if disturbed_union else 0.0

    aoi_poly = _to_local_meters(aoi, lat0)
    aoi_ha = float(aoi_poly.area) / 10000.0 if aoi_poly else 0.0

    # ---- B5 越界检测 ----
    encroach: dict[str, Any] = {"available": False, "areaHa": 0.0, "pctOfDisturbance": 0.0}
    if permit and len(permit) >= 3 and disturbed_union is not None:
        permit_poly = _to_local_meters(permit, lat0)
        if permit_poly is not None and not permit_poly.is_empty:
            outside = disturbed_union.difference(permit_poly)
            outside_ha = float(outside.area) / 10000.0
            encroach = {
                "available": True,
                "areaHa": _r(outside_ha),
                "pctOfDisturbance": _r(outside_ha / disturbed_ha * 100) if disturbed_ha > 0 else 0.0,
                "permitAreaHa": _r(float(permit_poly.area) / 10000.0),
                "note": "扰动边界来自影像解译，矿权边界来自登记数据，两者来源与日期可能不一致",
            }

    # ---- 地形数据 + 栅格风险图（可选，失败不影响评分）----
    terrain: dict | None = None
    grid_payload: dict[str, Any] = {}
    if payload.get("withGrid", True):
        try:
            import dem as dem_mod

            lngs = [p[0] for p in aoi]
            lats = [p[1] for p in aoi]
            win = dem_mod.read_dem_window(min(lngs), min(lats), max(lngs), max(lats),
                                          zoom=int(payload.get("zoom") or 14), max_dim=512)
            elev = win["elevation"]
            mpp = win["mPerPixel"]
            slope, _aspect = dem_mod.slope_aspect(elev, mpp)
            pond = dem_mod.flow_proxy(slope, elev)
            terrain = dem_mod.terrain_summary(elev, slope)

            thr_pond = float(np.percentile(pond, 95)) if pond.size else 0.0
            pond_mask = (pond >= max(thr_pond, 1.0)) & (slope < 10)
            pond_pct = _r(float(pond_mask.mean()) * 100, 2)

            # 与 DEM 网格对齐的经纬度仿射变换
            from affine import Affine
            b = win["bounds"]
            h, w = slope.shape
            tr = Affine((b["east"] - b["west"]) / w, 0, b["west"],
                        0, -(b["north"] - b["south"]) / h, b["north"])

            shape_mask = _rasterize_geoms(
                [f for item in classes_payload
                 if item.get("classType") in disturbed_keys
                 for f in (item.get("features") or [])],
                (h, w), tr)
            permit_mask = None
            if permit and len(permit) >= 3:
                permit_mask = _rasterize_geoms([{"type": "Polygon", "coordinates": [permit]}], (h, w), tr)

            outside_mask = None
            if shape_mask is not None and permit_mask is not None:
                outside_mask = ((shape_mask > 0) & (permit_mask == 0)).astype(np.uint8)

            risk_grid = build_risk_grid(slope, pond, shape_mask, outside_mask)
            # 热点阈值自适应：优先用 60 分（明确的较高风险），
            # 若整片区域都偏低（如平缓林地），退到 P90 相对阈值，
            # 保证「找出相对最需要关注的位置」而不是直接返回空清单
            p90 = float(np.percentile(risk_grid, 90)) if risk_grid.size else 0.0
            hot_thr = 60.0 if p90 >= 60 else max(45.0, min(p90, 60.0))
            hotspots = extract_hotspots(risk_grid, mpp, b["west"], b["north"],
                                        threshold=hot_thr, min_pixels=8)

            import base64
            grid_payload = {
                "riskImageBase64": base64.b64encode(risk_png(risk_grid)).decode(),
                "hotspots": hotspots,
                "hotspotThreshold": _r(hot_thr, 1),
                "grid": {"width": int(w), "height": int(h), "mPerPixel": _r(mpp, 2),
                         "zoom": win["zoom"]},
                "levelStats": [
                    {"label": lb, "color": c,
                     "pct": _r(float(((risk_grid >= (0 if i == 0 else LEVELS[i - 1][0]))
                                      & (risk_grid < limit)).mean()) * 100, 2)}
                    for i, (limit, lb, c) in enumerate(LEVELS)
                ],
                "legend": [{"label": lb, "color": c} for _lim, lb, c in LEVELS],
            }
        except Exception as e:  # noqa: BLE001
            grid_payload = {"gridError": f"风险栅格生成失败：{e}"}

    # ---- 排土场是否落在低洼汇水区 ----
    dump_on_flow = bool(pond_pct >= 3.0 and ("DUMP" in class_polys or "TAILINGS" in class_polys))

    # ---- 五维评分 ----
    pit_ratio = class_area_ha.get("PIT", 0.0) / aoi_ha if aoi_ha > 0 else 0.0
    dim_payload = {
        "terrain": _terrain_risk(terrain, pit_ratio),
        "expansion": _expansion_risk(trend),
        "encroach": _encroach_risk(encroach),
        "coverage": _coverage_risk(class_area_ha, aoi_ha),
        "hydrology": _hydrology_risk(terrain, pond_pct, dump_on_flow),
        "ecology": _ecology_risk(payload.get("rsei")),
    }

    dimensions = []
    total = 0.0
    for key, label, weight in DIMENSIONS:
        d = dim_payload[key]
        total += d["score"] * weight
        dimensions.append({
            "key": key,
            "label": label,
            "weight": weight,
            "score": d["score"],
            "weighted": _r(d["score"] * weight, 1),
            "confidence": d.get("confidence", "medium"),
            "evidence": d.get("evidence", []),
            "advice": d.get("advice", ""),
        })

    label, color = _level_of(total)

    # 面积自检：矢量化存在边界阶梯效应，各类面积之和可能略超分析区；
    # 若明显超出（>5%）说明类别间存在重叠或投影误差，必须提示而不是隐藏
    sum_by_class = sum(class_area_ha.values())
    area_check = None
    if aoi_ha > 0 and sum_by_class > aoi_ha * 1.05:
        area_check = (
            f"各类面积之和 {_r(sum_by_class)} ha 超过分析区 {_r(aoi_ha)} ha 约 "
            f"{_r((sum_by_class / aoi_ha - 1) * 100)}%，说明类别间存在重叠或矢量化边界误差，"
            "面积统计建议人工复核"
        )

    result: dict[str, Any] = {
        "score": {
            "total": _r(total, 1),
            "level": label,
            "color": color,
            "dimensions": dimensions,
            # 权重方法：AHP 层次分析法，附一致性检验结果供报告引用
            "weightMethod": "AHP 层次分析法",
            "ahp": _AHP,
            # 安全指数视角：客户更习惯「分数越高越安全」，与风险分互补
            "safetyIndex": _r(100.0 - total, 1),
            "safetyLevel": _safety_level(100.0 - total),
        },
        "encroachment": encroach,
        "terrain": terrain,
        "areaSummary": {
            "aoiHa": _r(aoi_ha),
            "disturbanceHa": _r(disturbed_ha),
            "sumOfClassesHa": _r(sum_by_class),
            "byClass": {k: _r(v) for k, v in sorted(class_area_ha.items(), key=lambda x: -x[1])},
            "note": "扰动面积为各类地物的并集（已消除重叠），不等于各类面积之和",
            "check": area_check,
        },
        "disclaimer": DISCLAIMER,
    }
    result.update(grid_payload)
    return result


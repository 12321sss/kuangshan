"""
矿山安全指数 MSI（Mine Safety Index）

方法依据
--------
矿山地质环境/开采安全评价的主流方法是**层次分析法(AHP) + 多因子加权综合评价**：
  1. 建立评价因子体系（坡度、起伏度、汇水、开采强度、植被、生态）
  2. 用 AHP 构造判断矩阵求因子权重，并做一致性检验（CR < 0.1）
  3. 各因子归一化为 0~100 的「危险度」得分
  4. 加权求和得综合危险度，取补得安全指数

参考的文献方向（评价体系思路一致，权重按本项目数据可得性调整）：
  - 矿山地质环境影响评估中的 AHP 加权综合评价
  - PSR（压力-状态-响应）模型在矿区生态安全评价中的应用
  - 遥感生态指数 RSEI 作为生态状态分量的引入（徐涵秋 2013）

**口径红线（必须遵守）**
----------------------
本指数是**遥感与地形数据支撑的风险筛查指标**，不是边坡稳定性的工程计算结果。
- 不能替代边坡稳定性验算、地质勘察、安全设施检测
- 不能输出「安全/不安全」的法律结论，只能给「风险筛查等级」
- 10m 级 DEM 无法计算台阶坡面角、坑深、体积（见 dem.py 精度说明）

因子体系（6 项，全部可量化）
--------------------------
| 因子 | 数据来源 | 含义 | 方向 |
|------|---------|------|------|
| 边坡坡度风险 | DEM 坡度 | 陡坡(≥25°)占比越高，边坡失稳风险越大 | 越大越危险 |
| 地形起伏风险 | DEM 高程 | 相对高差越大，崩塌滑坡势能越高 | 越大越危险 |
| 汇水积水风险 | DEM 低洼分析 | 低洼平坦区占比，排水不畅/积水风险 | 越大越危险 |
| 开采扩张强度 | 时序解译 | 采坑等扰动面积年增长越快，人为扰动越强 | 越大越危险 |
| 植被覆盖状况 | NDVI | 植被覆盖度低，地表抗蚀与固土能力弱 | 越低越危险 |
| 生态质量 | RSEI | 综合生态质量差，环境承载力弱 | 越低越危险 |
"""
from __future__ import annotations

from typing import Any

import numpy as np

# AHP 判断矩阵（6×6）：行/列顺序与 FACTORS 一致
# 取值说明：1=同等重要，3=稍重要，5=明显重要，7=强烈重要，9=极端重要
# 依据：矿山开采安全中「边坡」与「开采强度」是主导风险，坡度优先于生态指标
_AHP_MATRIX = np.array([
    # 坡度  起伏  汇水  扩张  植被  生态
    [1.0,   3.0,  3.0,  2.0,  3.0,  4.0],   # 边坡坡度风险
    [1/3,   1.0,  2.0,  1/2,  2.0,  3.0],   # 地形起伏风险
    [1/3,   1/2,  1.0,  1/2,  1.0,  2.0],   # 汇水积水风险
    [1/2,   2.0,  2.0,  1.0,  2.0,  3.0],   # 开采扩张强度
    [1/3,   1/2,  1.0,  1/2,  1.0,  2.0],   # 植被覆盖状况
    [1/4,   1/3,  1/2,  1/3,  1/2,  1.0],   # 生态质量
])

# 随机一致性指标 RI（n=1..9），用于 CR 检验
_RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}

FACTORS = [
    {"key": "slope",    "label": "边坡坡度风险", "source": "DEM 坡度"},
    {"key": "relief",   "label": "地形起伏风险", "source": "DEM 高程"},
    {"key": "water",    "label": "汇水积水风险", "source": "DEM 低洼分析"},
    {"key": "expand",   "label": "开采扩张强度", "source": "时序解译"},
    {"key": "veget",    "label": "植被覆盖状况", "source": "NDVI"},
    {"key": "rsei",     "label": "生态质量",     "source": "RSEI"},
]

# 安全等级（MSI 越高越安全）
MSI_LEVELS = [
    (85, "安全",     "#1a9850", "各项指标处于正常范围，保持常规监测。"),
    (70, "基本安全", "#a6d96a", "整体可控，建议关注得分偏高的单项指标。"),
    (55, "需关注",   "#fee08b", "存在明显薄弱环节，建议现场核查并加强监测频次。"),
    (40, "风险较高", "#fc8d59", "多项指标偏离正常，建议专项排查并制定整改措施。"),
    (0,  "高风险",   "#d73027", "多项指标严重偏离，建议立即组织专业勘查与安全评估。"),
]


def ahp_weights(matrix: np.ndarray | None = None) -> dict[str, Any]:
    """AHP 求权重 + 一致性检验。

    流程：判断矩阵 → 列归一化 → 行均值得权重 → 算 λmax → CI=(λmax-n)/(n-1) → CR=CI/RI
    CR < 0.1 视为判断矩阵一致性可接受。
    """
    a = _AHP_MATRIX if matrix is None else matrix
    n = a.shape[0]
    col_sum = a.sum(axis=0)
    normalized = a / col_sum
    weights = normalized.mean(axis=1)

    # 一致性检验
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
        "note": "CR < 0.1 表示判断矩阵一致性可接受" if cr < 0.1
                else "CR ≥ 0.1，判断矩阵一致性不足，需调整因子相对重要性",
    }


def _clamp_score(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, v)))


def compute_msi(*, terrain: dict | None = None, ecology_stats: dict | None = None,
                vegetation_pct: float | None = None,
                expansion_pct: float | None = None) -> dict[str, Any]:
    """计算矿山安全指数。

    参数（都可为 None，缺失项按中性 50 分处理并在结果里标注）：
      terrain        : dem.terrain_summary 的结果（含 steepPct/reliefM/slopeMean）
      ecology_stats  : ecology.rsei_levels 的结果（含 mean）
      vegetation_pct : 植被覆盖率(%)
      expansion_pct  : 采坑/扰动面积年增长率(%)，正数表示扩张

    返回总分、等级、各因子明细、主要风险项、建议。
    """
    aw = ahp_weights()
    weights = dict(zip([f["key"] for f in FACTORS], aw["weights"]))
    scores: list[dict[str, Any]] = []
    missing: list[str] = []

    # ---- 因子 1：边坡坡度风险（陡坡占比越高分越高）----
    if terrain and terrain.get("steepPct") is not None:
        steep = float(terrain["steepPct"])
        # 实测矿区：陡坡 <5% 属平缓，>30% 陡坡集中
        v = _clamp_score(steep / 30.0 * 100)
        detail = f"陡坡(≥25°)占比 {steep}%"
    else:
        v = 50.0
        missing.append("坡度")
        detail = "未提供 DEM 地形数据"

    # ---- 因子 2：地形起伏风险 ----
    if terrain and terrain.get("reliefM") is not None:
        relief = float(terrain["reliefM"])
        # 起伏 <50m 平缓，>300m 山地
        v2 = _clamp_score((relief - 50) / 250 * 100)
        detail2 = f"相对高差 {relief}m"
    else:
        v2 = 50.0
        missing.append("起伏度")
        detail2 = "未提供 DEM 地形数据"

    # ---- 因子 3：汇水积水风险 ----
    if terrain and terrain.get("pondPct") is not None:
        pond = float(terrain["pondPct"])
        v3 = _clamp_score(pond / 15.0 * 100)   # >15% 低洼积水区属显著
        detail3 = f"低洼汇水候选区 {pond}%"
    else:
        v3 = 50.0
        missing.append("汇水")
        detail3 = "未提供低洼汇水分析"

    # ---- 因子 4：开采扩张强度 ----
    if expansion_pct is not None:
        exp = float(expansion_pct)
        v4 = _clamp_score(max(0.0, exp) / 20.0 * 100)   # 年扩张 20% 视为高强度
        detail4 = f"扰动面积年变化 {exp:+.1f}%"
    else:
        v4 = 50.0
        missing.append("扩张强度")
        detail4 = "未提供多期解译对比"

    # ---- 因子 5：植被覆盖状况（覆盖率越低越危险）----
    if vegetation_pct is not None:
        veg = float(vegetation_pct)
        v5 = _clamp_score((60.0 - veg) / 60.0 * 100)
        detail5 = f"植被覆盖率 {veg}%"
    else:
        v5 = 50.0
        missing.append("植被")
        detail5 = "未提供植被解译结果"

    # ---- 因子 6：生态质量（RSEI 越低越危险）----
    if ecology_stats and ecology_stats.get("mean") is not None:
        r = float(ecology_stats["mean"])
        v6 = _clamp_score((0.75 - r) / 0.75 * 100)
        detail6 = f"RSEI 均值 {r}"
    else:
        v6 = 50.0
        missing.append("生态质量")
        detail6 = "未计算 RSEI"

    for f, score, detail in zip(FACTORS,
                                [v, v2, v3, v4, v5, v6],
                                [detail, detail2, detail3, detail4, detail5, detail6]):
        scores.append({
            "key": f["key"],
            "label": f["label"],
            "source": f["source"],
            "dangerScore": round(score, 1),
            "weight": weights[f["key"]],
            "contribution": round(score * weights[f["key"]], 2),
            "detail": detail,
        })

    total_danger = sum(s["contribution"] for s in scores)
    msi = _clamp_score(100.0 - total_danger)

    level, color, advice = "需关注", "#fee08b", ""
    for limit, name, col, adv in MSI_LEVELS:
        if msi >= limit:
            level, color, advice = name, col, adv
            break

    # 主要风险项：危险度得分最高的两项（排除缺失的）
    ranked = sorted([s for s in scores if s["detail"] != "未提供" ],
                    key=lambda x: x["dangerScore"], reverse=True)
    top_risks = [s for s in ranked[:2] if s["dangerScore"] >= 40]

    return {
        "msi": round(msi, 1),
        "level": level,
        "levelColor": color,
        "totalDanger": round(total_danger, 2),
        "factors": scores,
        "topRisks": [{"label": s["label"], "score": s["dangerScore"], "detail": s["detail"]}
                     for s in top_risks],
        "advice": advice,
        "ahp": aw,
        "dataCompleteness": round((6 - len(missing)) / 6 * 100, 0),
        "missingFactors": missing,
        "disclaimer": (
            "本指数为遥感与地形数据支撑的**风险筛查**结果，不是边坡稳定性工程计算结果，"
            "不能替代地质勘察、边坡验算与安全设施检测，也不构成安全合规结论。"
            + (f"（本次缺失因子：{'、'.join(missing)}，相关项按中性值计入）" if missing else "")
        ),
    }

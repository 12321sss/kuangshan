"""形变证据 → 风险提级规则（形变作为「直接证据」覆盖六维 AHP 打分）。

设计原则
--------
六维 AHP（形态/扩张/越界/覆盖/水文/生态）打分保持不变——它们是「间接指标」
（陡≠滑），历史数据可比、口径稳定。形变是「直接证据」（坡体确实在动），
不做第七维加权（会稀释、且要重算 AHP 一致性），而是作为**规则覆盖**：

    v 或 a 超阈值 → 风险等级提级（+1 或 +2），并写明依据。

这样形变只「抬升」不「拉平」：一个其它维度都正常、但实测在快速蠕滑的坡，
会被形变证据直接推到高风险，而不是被另外五个低风险维度稀释掉。

阈值（可配置，默认参考滑坡速度分类 Cruden & Varnes 1996）
--------------------------------------------------------
- 速度 |v| ≥ 30 mm/yr（缓慢以上）→ 提一级
- 速度 |v| ≥ 100 mm/yr（快速）→ 提两级
- 加速度 a ≥ 20 mm/yr²（明显加速）→ 提一级（叠加）

只依赖 numpy，可被脚本与测试直接调用。
"""
from __future__ import annotations

from typing import Any


def deformation_overlay(
    score: float,
    velocity_mmyr: float | None,
    acceleration_mmyr2: float | None,
    reliable: bool = True,
) -> dict[str, Any]:
    """形变证据的规则覆盖。

    参数
    ----
    score：六维 AHP 加权后的风险分（0~100）
    velocity_mmyr：测点/区域的最大形变速率（mm/yr），None 表示无数据
    acceleration_mmyr2：加速度（mm/yr²），None 表示无数据
    reliable：形变数据是否可靠（信噪比达标）。不可靠则不覆盖，只提示。

    返回
    ----
    { adjusted_score, uplift, level_from, level_to, evidence, applied }
    """
    if velocity_mmyr is None and acceleration_mmyr2 is None:
        return {"adjusted_score": score, "uplift": 0, "evidence": [],
                "applied": False, "reliable": reliable}

    if not reliable:
        return {
            "adjusted_score": score, "uplift": 0,
            "evidence": ["形变数据信噪比不足，不参与风险提级（避免把噪声当形变）"],
            "applied": False, "reliable": False,
        }

    uplift = 0
    evidence: list[str] = []

    v = abs(velocity_mmyr) if velocity_mmyr is not None else 0.0
    a = acceleration_mmyr2 if acceleration_mmyr2 is not None else 0.0

    if v >= 100:
        uplift = max(uplift, 2)
        evidence.append(f"形变速率 {v:.0f} mm/yr（快速蠕滑），风险提两级")
    elif v >= 30:
        uplift = max(uplift, 1)
        evidence.append(f"形变速率 {v:.0f} mm/yr（缓慢以上），风险提一级")

    if a >= 20:
        uplift = max(uplift, 1)
        evidence.append(f"形变加速度 {a:.0f} mm/yr²（明显加速），风险提一级")

    if uplift == 0:
        if velocity_mmyr is not None:
            evidence.append(f"形变速率 {v:.0f} mm/yr 处于稳定区间，不额外提级")
        return {"adjusted_score": score, "uplift": 0,
                "evidence": evidence, "applied": False, "reliable": True}

    adjusted = min(100.0, score + uplift * 10.0)  # 每级 +10 分
    return {
        "adjusted_score": round(adjusted, 1),
        "uplift": uplift,
        "evidence": evidence,
        "applied": True,
        "reliable": True,
    }

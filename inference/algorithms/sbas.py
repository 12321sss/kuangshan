"""SBAS 时序形变解算（A 阶段核心算法）。

把 NISAR GUNW 的多期解缠干涉图，反演出每个像元的累积位移时间序列与平均速率。

原理
----
GUNW 每景是「reference 与 secondary 两个时刻」之间的解缠相位差 φ，
即 φ(t_ref→t_sec) = 累积位移在 [t_ref, t_sec] 上的增量（LOS 方向）。

把时间轴上的每个**采集时刻**看成未知量 m_i（该时刻的累积位移，参考时刻取 0），
则每景给出一个线性方程：

    m[sec] - m[ref] = d_obs            （d_obs = φ·λ/(4π)）

N 景 → N 个方程、K 个未知时刻（K ≈ N+1），加一个约束「参考时刻 = 0」，
即得每个时刻的累积位移；对时间做线性拟合得**平均速率**。

参考区归零
----------
InSAR 单景有长波大气/轨道残差（整体偏移，实测可到上百 mm），必须选一块
**稳定参考区**，把每景相位减去参考区中位值。这是 SBAS 里最关键也最容易被
忽略的一步——不做它，速率场会整体偏出一个假常数。

局限（写入产品，不掩盖）
------------------------
- 80m 网格：形变场是「区域量级」，不是单体量级
- 观测仅数月：速率对短期扰动敏感，不构成长期趋势结论
- 单轨只有 LOS 视线向，不等于垂直沉降；需升降轨联合才能分解

只依赖 numpy/scipy，不依赖 fastapi，可被脚本与测试直接调用。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class Pair:
    """一个干涉对（一期 GUNW）的解算输入。

    t_ref / t_sec：参考/次要采集时刻，单位**年**（小数年，速率才能直接是 mm/yr）
    phase：解缠相位（弧度），shape (H, W)，无效处为 NaN
    coherence：相干性 0~1，同 shape，作权重；缺省为全 1
    """
    t_ref: float
    t_sec: float
    phase: np.ndarray
    coherence: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.coherence is None:
            self.coherence = np.ones_like(self.phase, dtype=np.float32)


def phase_to_los_mm(phase: np.ndarray, wavelength_m: float) -> np.ndarray:
    """解缠相位（弧度）→ LOS 位移（毫米）。

    φ = 4π/λ · ΔR（ΔR 为单程距离变化，往返光程差 2ΔR），故 ΔR = φ·λ/(4π)。
    正值 = 地面向卫星靠近（LOS 缩短）。
    """
    return phase * (wavelength_m / (4 * math.pi)) * 1000.0


def reference_correction(pairs: list[Pair], ref_mask: np.ndarray) -> list[Pair]:
    """参考区归零：每景相位减去参考区内有效像元相位的中位数。

    ref_mask：与 phase 同 shape 的布尔掩膜，True = 稳定参考像元。
    """
    out: list[Pair] = []
    for p in pairs:
        ref = np.where(ref_mask & np.isfinite(p.phase), p.phase, np.nan)
        if not np.isfinite(ref).any():
            raise ValueError("参考区内没有有效像元，请调整 ref_mask")
        offset = float(np.nanmedian(ref))
        out.append(Pair(p.t_ref, p.t_sec, p.phase - offset, p.coherence))
    return out


def solve(pairs: list[Pair], wavelength_m: float = 0.2439,
          min_valid_pct: float = 0.3) -> dict[str, Any]:
    """反演累积位移时序 + 平均速率场。

    参数
    ----
    wavelength_m：雷达波长。NISAR L 波段 1.229GHz → 0.2439m。
    min_valid_pct：某像元至少要有多少比例的期次有效才参与解算。

    返回
    ----
    times / displacement_mm(T,H,W) / velocity_mmyr(H,W) /
    valid_mask(H,W) / quality
    """
    if len(pairs) < 2:
        raise ValueError("SBAS 至少需要 2 个干涉对")

    times = sorted({p.t_ref for p in pairs} | {p.t_sec for p in pairs})
    t_idx = {t: i for i, t in enumerate(times)}
    T = len(times)

    # 相位 → 位移（mm）
    disp = [phase_to_los_mm(p.phase, wavelength_m) for p in pairs]
    # 相干性权重：低相干降权（<0.2 压到近 0）
    coh = [np.clip(p.coherence if p.coherence is not None
                   else np.ones_like(p.phase), 0, 1) for p in pairs]

    H, W = pairs[0].phase.shape
    # 每景一行：m[sec]-m[ref]=d，加参考约束 m[0]=0
    A = np.zeros((len(pairs) + 1, T))
    for k, p in enumerate(pairs):
        A[k, t_idx[p.t_ref]] = -1.0
        A[k, t_idx[p.t_sec]] = 1.0
    A[-1, 0] = 1.0  # 参考时刻约束

    # 逐像元加权最小二乘：m = (A^T W A)^-1 A^T W d
    # T 通常只有 ~9，用 3x 小矩阵逐个像元解，代码最直白，8 期×几千像元很快
    disp_arr = np.stack(disp, axis=0)            # (K,H,W)
    coh_arr = np.stack(coh, axis=0)
    K = len(pairs)

    # 有效像元：至少 min_valid_pct 比例期次有效
    valid_count = np.isfinite(disp_arr).sum(axis=0)
    good = valid_count >= max(2, int(round(min_valid_pct * K)))

    displacement = np.full((T, H, W), np.nan, dtype=np.float64)

    for r in range(H):
        for c in range(W):
            if not good[r, c]:
                continue
            d = disp_arr[:, r, c]
            # 剔除该像元无效（NaN）的期次方程，否则 NaN 会污染整个解
            finite = np.isfinite(d)
            if not finite.any():
                continue
            d = d[finite]
            w = np.where(coh_arr[:, r, c][finite] < 0.2, 1e-3,
                         coh_arr[:, r, c][finite])
            A_sub = A[:-1][finite]                        # 去掉参考约束行，按 finite 取子集
            d_ext = np.concatenate([d, [0.0]])            # 参考约束
            w_ext = np.concatenate([w, [1e6]])            # 参考约束极大权重
            A_ext = np.vstack([A_sub, A[-1]])             # 参考约束行始终保留
            Wm = np.diag(w_ext)
            AtWA = A_ext.T @ Wm @ A_ext
            AtWd = A_ext.T @ Wm @ d_ext
            try:
                m = np.linalg.lstsq(AtWA, AtWd, rcond=None)[0]
            except np.linalg.LinAlgError:
                continue
            # 末端无约束的节点：反演的最小范数解会给它们填 0，但这是假值。
            # 判断每个时刻节点是否被有效连接覆盖，未覆盖的置 NaN。
            covered = np.zeros(T, dtype=bool)
            covered[0] = True                             # 参考时刻有约束
            for k in range(A_sub.shape[0]):
                for ti in range(T):
                    if A_sub[k, ti] != 0:
                        covered[ti] = True
            m[~covered] = np.nan
            displacement[:, r, c] = m

    # 平均速率：逐像元对「有真实观测的时间区间」做线性拟合。
    # 关键：不能直接用位移序列的全局最小二乘——缺失期会被最小范数解填成
    # 偏离真实值的点，污染斜率。这里按每个像元的「首末有效时刻」线性拟合，
    # 对匀速形变（SBAS 的默认假设）是最稳健的速率估计。
    t = np.asarray(times, dtype=np.float64)
    velocity = np.full((H, W), np.nan, dtype=np.float64)
    for r in range(H):
        for c in range(W):
            if not good[r, c]:
                continue
            d = displacement[:, r, c]
            # 有效（非 NaN）时刻
            tv = np.isfinite(d)
            if tv.sum() < 2:
                continue
            tt = t[tv]
            dd = d[tv]
            tc = tt - tt.mean()
            denom = float(tc @ tc)
            if denom > 1e-12:
                velocity[r, c] = float((tc @ dd) / denom)

    # 质量指标：位移时序对均值的平均偏离（mm）
    resid = displacement - np.nanmean(displacement, axis=0)
    rms_mm = float(np.nanmean(np.sqrt(np.nanmean(resid ** 2, axis=0))))

    return {
        "times": times,
        "displacement_mm": displacement.astype(np.float32),
        "velocity_mmyr": velocity.astype(np.float32),
        "valid_mask": good,
        "reference_time": times[0],
        "quality": {
            "n_pairs": len(pairs),
            "n_times": T,
            "n_valid_pixels": int(good.sum()),
            "rms_mm": round(rms_mm, 2),
            "note": "LOS 视线向；速率=累积位移对时间线性拟合斜率；"
                    "观测期短，速率不构成长期趋势结论",
        },
    }

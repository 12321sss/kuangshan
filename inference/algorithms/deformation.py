"""形变时序分析（速度 / 加速度 / 失稳时刻外推）。

在 sbas.solve 产出「累积位移时序」之后，进一步提取判定指标：

1. 速度 v：累积位移对时间的斜率（稳健回归，抗离群点）
2. 加速度 a：速度随时间的二阶变化（二次拟合系数 × 2）
3. 失稳时刻外推：Fukuzono 倒数速度法

原理（Fukuzono, 1985）
------------------------
滑坡临滑前普遍满足经验关系：

    1/v 随时间近似线性下降，外推到 1/v = 0 的时刻 t_f，
    即预测的失稳（完全破坏）时刻。

这是滑坡预警里最经典、也最被工程界接受的方法——比单纯设速度阈值更有
物理依据。对每个形变像元/测点，若有足够长、且在加速的时序，就给出 t_f。

局限（必须如实标注）
--------------------
- 加速度与倒数速度外推**对噪声极其敏感**：时序太短（<1 年）或未做大气
  校正时，二阶导会把噪声放大，外推结果不可信。
- 本模块对「数据不够」返回 insufficient=True，而不是硬算一个假时刻。

只依赖 numpy/scipy，不依赖 fastapi，可被脚本与测试直接调用。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class TrendResult:
    """单测点（单像元）的时序分析结果"""
    velocity_mmyr: float
    acceleration_mmyr2: float
    velocity_r2: float        # 速度线性拟合的 R²
    accel_r2: float           # 加速度二次拟合的 R²
    accelerating: bool         # 是否在加速（加速度显著为正）
    insufficient: bool         # 数据不足以可靠判定
    tf_days: float | None = None   # 倒数速度外推的失稳天数（None=不可外推）


def theil_sen_slope(t: np.ndarray, d: np.ndarray) -> float:
    """Theil-Sen 稳健斜率：所有点对斜率的中位数。

    比最小二乘抗离群点（时序里常有单期大气残差造成的坏点）。
    t 单位年，d 单位 mm → 返回 mm/yr。
    """
    t = np.asarray(t, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    n = len(t)
    if n < 2:
        return 0.0
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dt = t[j] - t[i]
            if dt > 0:
                slopes.append((d[j] - d[i]) / dt)
    if not slopes:
        return 0.0
    return float(np.median(slopes))


def analyze_timeseries(times: list[float], disp: np.ndarray,
                       min_points: int = 6) -> TrendResult:
    """单测点时序 → 速度/加速度/失稳外推。

    times：时间轴（年）
    disp：累积位移（mm），与 times 等长
    min_points：少于该点数则 insufficient=True
    """
    t = np.asarray(times, dtype=np.float64)
    d = np.asarray(disp, dtype=np.float64)

    valid = np.isfinite(t) & np.isfinite(d)
    t, d = t[valid], d[valid]
    if len(t) < min_points:
        return TrendResult(0.0, 0.0, 0.0, 0.0, False, True, None)

    # 1. 速度：Theil-Sen 斜率
    v = theil_sen_slope(t, d)

    # 2. 加速度：二次拟合 d = c0 + c1*t + c2*t²，a = 2*c2
    #    中心化时间避免病态
    tc = t - t.mean()
    A = np.c_[np.ones_like(tc), tc, tc ** 2]
    coef, *_ = np.linalg.lstsq(A, d, rcond=None)
    accel = 2.0 * coef[2]

    # R²
    def r2(y_true, y_pred):
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    d_lin = coef[0] + coef[1] * tc
    v_r2 = r2(d, d_lin)
    a_r2 = r2(d, A @ coef)

    # 加速判定：加速度显著为正且二次拟合明显优于线性
    accelerating = accel > 0 and a_r2 > v_r2 + 0.02

    # 3. 倒数速度外推（Fukuzono）
    #    用滑动窗口速度序列 1/v(t)，对时间线性回归，外推 1/v=0
    tf_days = _fukuzono(t, d, v)

    return TrendResult(
        velocity_mmyr=float(v),
        acceleration_mmyr2=float(accel),
        velocity_r2=float(v_r2),
        accel_r2=float(a_r2),
        accelerating=bool(accelerating),
        insufficient=False,
        tf_days=tf_days,
    )


def _fukuzono(t: np.ndarray, d: np.ndarray, v: float,
              window: int = 3) -> float | None:
    """Fukuzono 倒数速度外推。

    用滑窗速度序列的倒数 1/v_k 对窗口中心时间线性回归，
    外推到 1/v = 0 的时刻。仅当速度在加速（斜率下降）时才外推。
    """
    n = len(t)
    if n < window + 2 or v <= 0:
        return None

    inv_v = []
    tc = []
    for k in range(n - window + 1):
        seg_t = t[k:k + window]
        seg_d = d[k:k + window]
        dt = seg_t[-1] - seg_t[0]
        if dt <= 0:
            continue
        vk = (seg_d[-1] - seg_d[0]) / dt
        if vk > 1e-6:
            inv_v.append(1.0 / vk)
            tc.append((seg_t[0] + seg_t[-1]) / 2.0)

    if len(inv_v) < 3:
        return None
    tc = np.asarray(tc)
    inv_v = np.asarray(inv_v)
    # 线性回归 1/v = a*t + b；失稳时刻 t_f = -b/a
    A = np.c_[np.ones_like(tc), tc]
    coef, *_ = np.linalg.lstsq(A, inv_v, rcond=None)
    a, b = coef[1], coef[0]
    if abs(a) < 1e-12:
        return None
    tf_year = -b / a
    # 只有当 1/v 在下降（a<0，即速度在增加）时才外推
    if a >= 0:
        return None
    tf_days = (tf_year - tc[-1]) * 365.25
    # 外推太远（>5 年）或已过去，视为不可外推
    if tf_days <= 0 or tf_days > 365.25 * 5:
        return None
    return float(tf_days)


def velocity_level(velocity_mmyr: float) -> dict:
    """速度分级（参考 Cruden & Varnes 1996 的滑坡速度分类，单位换算为 mm/yr）。

    返回 {level, label, range}。仅作工程参考，阈值需结合矿区实测标定。
    """
    v = abs(velocity_mmyr)
    if v < 10:
        return {"level": 1, "label": "极缓慢", "range": "<10 mm/yr"}
    if v < 30:
        return {"level": 2, "label": "缓慢", "range": "10-30 mm/yr"}
    if v < 100:
        return {"level": 3, "label": "中等", "range": "30-100 mm/yr"}
    if v < 300:
        return {"level": 4, "label": "快速", "range": "100-300 mm/yr"}
    return {"level": 5, "label": "极快速", "range": ">300 mm/yr"}

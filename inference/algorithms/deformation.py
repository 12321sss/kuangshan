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


def summarize_field(
    velocity: np.ndarray,
    acceleration: np.ndarray,
    tf_days: np.ndarray | None = None,
    xs: np.ndarray | None = None,
    ys: np.ndarray | None = None,
    top_n: int = 10,
    accel_thr: float = 20.0,
    decel_thr: float = -20.0,
) -> dict[str, Any]:
    """把形变场汇总成「空间化证据」，供安全评估直接引用。

    单个标量（全区最大速率）会掩盖「局部快速蠕滑但整体平均不高」的危险情况，
    也无法回答「哪里在动、动得多快、整体什么趋势」。本函数把速度/加速度/
    失稳时刻三个场压成一份结构化证据：

      - 危险测点清单：按风险排序的 top_n 个像元（速度越快、在加速、可外推失稳的越靠前）
      - 趋势分布：加速 / 稳定 / 减速 像元占比
      - 整体趋势研判：加速 / 稳定 / 减速 / 数据不足，附依据与置信度

    只依赖 numpy，可单测。是「形变 → 安全分析」桥接的关键一环。

    参数
    ----
    velocity / acceleration：同 shape (H,W)，无效处 NaN
    tf_days：失稳外推天数 (H,W)，NaN 表示不可外推；可传 None
    xs / ys：像元中心坐标（经度 / 纬度），长度 W / H；缺省用列号 / 行号
    top_n：返回的危险测点数量
    accel_thr / decel_thr：加速 / 减速判定的加速度阈值（mm/yr²）

    返回
    ----
    { n_valid, n_forecastable, velocity, trend, verdict, hotspots, note }
    """
    v = np.asarray(velocity, dtype=np.float64)
    a = np.asarray(acceleration, dtype=np.float64)
    if v.shape != a.shape:
        raise ValueError("velocity 与 acceleration 形状不一致")

    valid = np.isfinite(v) & np.isfinite(a)
    n_valid = int(valid.sum())
    out: dict[str, Any] = {
        "n_valid": n_valid,
        "n_forecastable": 0,
        "hotspots": [],
    }

    if n_valid == 0:
        out["verdict"] = {"type": "数据不足", "confidence": "low",
                          "basis": "无有效形变像元"}
        out["trend"] = {"accelerating": 0, "stable": 0, "decelerating": 0}
        return out

    # ---- 趋势分布 ----
    acc_n = int((a[valid] >= accel_thr).sum())
    dec_n = int((a[valid] <= decel_thr).sum())
    stable_n = n_valid - acc_n - dec_n
    out["trend"] = {
        "accelerating": acc_n,
        "stable": stable_n,
        "decelerating": dec_n,
        "pctAccelerating": round(acc_n / n_valid * 100, 1),
        "pctDecelerating": round(dec_n / n_valid * 100, 1),
    }

    # ---- 可外推失稳时刻的像元数 ----
    forecastable = np.zeros(v.shape, dtype=bool)
    if tf_days is not None:
        tf = np.asarray(tf_days, dtype=np.float64)
        forecastable = valid & np.isfinite(tf) & (tf > 0)
        out["n_forecastable"] = int(forecastable.sum())

    # ---- 速度统计（用绝对值衡量「动得多快」）----
    absv = np.abs(v[valid])
    out["velocity"] = {
        "median": round(float(np.median(absv)), 2),
        "p5": round(float(np.percentile(absv, 5)), 2),
        "p95": round(float(np.percentile(absv, 95)), 2),
        "maxAbs": round(float(absv.max()), 2),
    }

    # ---- 危险测点：按综合风险排序 ----
    # 排序键 = 速度项（|v|/100）+ 加速项（0.3）+ 失稳项（0.4）。
    # 速度是主项，加速与可外推失稳是「危险征兆」的加权加分。
    vv = v[valid]
    aa = a[valid]
    ff = forecastable[valid]
    risk_score = np.abs(vv) / 100.0 \
        + (aa >= accel_thr).astype(float) * 0.3 \
        + ff.astype(float) * 0.4

    rows, cols = np.nonzero(valid)
    order = np.argsort(-risk_score)[:top_n]
    for idx in order:
        r_, c_ = int(rows[idx]), int(cols[idx])
        x = float(xs[c_]) if xs is not None else float(c_)
        y = float(ys[r_]) if ys is not None else float(r_)
        lv = velocity_level(float(vv[idx]))
        tf_val = None
        if tf_days is not None:
            tfi = float(tf[r_, c_])
            if np.isfinite(tfi) and tfi > 0:
                tf_val = round(tfi, 1)
        out["hotspots"].append({
            "x": round(x, 6),
            "y": round(y, 6),
            "velocity": round(float(vv[idx]), 2),
            "acceleration": round(float(aa[idx]), 2),
            "tfDays": tf_val,
            "severity": lv["level"],
            "severityLabel": lv["label"],
        })

    # ---- 整体趋势研判 ----
    acc_ratio = acc_n / n_valid
    dec_ratio = dec_n / n_valid
    med_a = float(np.median(a[valid]))
    if acc_ratio >= 0.5:
        verdict = {"type": "整体加速", "confidence": "high",
                   "basis": f"{acc_n}/{n_valid} 像元在加速（加速度≥{accel_thr} mm/yr²）"}
    elif acc_ratio >= 0.3 or med_a >= accel_thr:
        verdict = {"type": "局部加速", "confidence": "medium",
                   "basis": f"{acc_n}/{n_valid} 像元在加速（{round(acc_ratio*100,1)}%），中位加速度 {round(med_a,1)} mm/yr²"}
    elif dec_ratio >= 0.3:
        verdict = {"type": "整体减速", "confidence": "medium",
                   "basis": f"{dec_n}/{n_valid} 像元在减速（{round(dec_ratio*100,1)}%）"}
    else:
        verdict = {"type": "整体稳定", "confidence": "medium",
                   "basis": f"加速/减速像元占比均 < 30%，中位速率 {round(float(np.median(absv)),1)} mm/yr"}
    out["verdict"] = verdict
    out["note"] = ("单轨 LOS 视线向；趋势研判基于当前观测期，"
                   "信噪比不足时应将可靠度标注为低，不作为失稳判定依据")
    return out


def build_evidence(
    velocity: np.ndarray,
    acceleration: np.ndarray,
    tf_days: np.ndarray | None,
    snr: float,
    xs: np.ndarray | None = None,
    ys: np.ndarray | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """把形变场 + 信噪比组装成 risk.evaluate 可直接消费的「形变证据」dict。

    这是「形变 → 安全分析」的桥接函数：run_deformation.py 产出速度/加速度/
    失稳时刻三个场后，调本函数得到一份结构化证据，再原样传进 risk 的
    deformation 字段。字段名与 risk 侧约定对齐：

      velocityMmyr     规则覆盖用的速度标量（场最大 |v|）
      accelerationMmyr2 规则覆盖用的加速度标量（正向加速的 P95）
      reliable          信噪比是否达标（不达标时 risk 侧不提级，只提示）
      summary / verdict / hotspots / nForecastable   空间化明细

    只依赖 numpy，可单测。
    """
    v = np.asarray(velocity, dtype=np.float64)
    a = np.asarray(acceleration, dtype=np.float64)

    summary = summarize_field(v, a, tf_days, xs, ys, top_n)
    reliable = bool(snr >= 0.3)

    # 规则覆盖用的两个标量
    vel = summary["velocity"]["maxAbs"] if summary["n_valid"] > 0 else None
    # 加速度取「正向加速」方向的 P95，避免被单个极端像元主导；
    # 减速方向不参与提级（提级判定看的是「在加速」）
    pos_a = a[np.isfinite(a) & (a > 0)]
    if pos_a.size >= 5:
        acc = round(float(np.percentile(pos_a, 95)), 2)
    elif pos_a.size:
        acc = round(float(pos_a.max()), 2)
    else:
        acc = None

    hotspots = summary.get("hotspots", [])
    n_forecastable = summary.get("n_forecastable", 0)
    if not reliable:
        # 口径红线：信噪比不足时，倒数速度外推的「失稳时刻」是噪声假象，
        # 必须清空具体天数、失稳像元数置 None，绝不给客户一个看起来精确的假预警。
        hotspots = [{**h, "tfDays": None} for h in hotspots]
        n_forecastable = None

    return {
        "velocityMmyr": vel,
        "accelerationMmyr2": acc,
        "reliable": reliable,
        "snr": round(float(snr), 3),
        "summary": summary,
        "verdict": summary.get("verdict"),
        "hotspots": hotspots,
        "nForecastable": n_forecastable,
        "note": summary.get("note", ""),
    }


# ---------------------------------------------------------------------------
# 多时间尺度趋势分析
# ---------------------------------------------------------------------------
#
# 为什么需要多尺度：单一「年均速率」会把关键信息抹平——一个整体年均 10 mm/yr
# 的坡，可能前 10 个月几乎不动、最后 2 个月突然 80 mm/yr，年均值看起来"很稳定"，
# 但这恰恰是临滑前兆。月尺度 / 周尺度速率序列能把这个变化暴露出来。
#
# 但时间尺度受**采样间隔**硬约束（口径红线，不能硬凑）：
#   Sentinel-1 / NISAR 均为 12 天重访 →
#     年窗口 ≈ 30 个点（很好）、季窗口 ≈ 7 个点（可以）、
#     月窗口 ≈ 2.5 个点（勉强算速率）、周窗口 < 1 个点（**物理上不可分辨**）。
# 不可分辨的尺度必须明确标注 available=False，绝不给客户一个看起来精确的假周速率。

#: 尺度名 → 窗口天数
SCALES: dict[str, float] = {
    "annual": 365.25,
    "quarterly": 91.3,
    "monthly": 30.4,
    "weekly": 7.0,
}


def _sliding_rates(t: np.ndarray, d: np.ndarray,
                   win_yr: float, step_yr: float) -> tuple[list[float], list[float]]:
    """滑动窗口算速率序列。

    窗口中心从 t[0]+win/2 滑到 t[-1]-win/2，步长 step_yr；
    每个窗口内用 Theil-Sen 稳健斜率（抗单期大气残差造成的坏点）。

    返回 (窗口中心时间列表, 速率列表)。
    """
    t0, t1 = float(t[0]), float(t[-1])
    if t1 - t0 < win_yr:
        return [], []
    centers: list[float] = []
    rates: list[float] = []
    c = t0 + win_yr / 2.0
    while c <= t1 - win_yr / 2.0 + 1e-9:
        lo, hi = c - win_yr / 2.0, c + win_yr / 2.0
        mask = (t >= lo) & (t <= hi)
        if int(mask.sum()) >= 2:
            centers.append(round(float(c), 4))
            rates.append(round(float(theil_sen_slope(t[mask], d[mask])), 2))
        c += step_yr
    return centers, rates


def analyze_multiscale(
    times: list[float],
    disp: np.ndarray,
    scales: tuple[str, ...] | None = None,
    min_points_per_window: int = 2,
) -> dict[str, Any]:
    """多时间尺度趋势分析（年 / 季 / 月 / 周）。

    对每个尺度给出：
      - 是否可分辨（采样间隔决定的硬约束，不可分辨就明说，不硬算）
      - 尺度内代表性速率（滑动窗口速率序列的中位数，抗离群）
      - 速率序列（看形变在恶化还是收敛）
      - 速率变化率（速率序列的斜率，即该尺度上的加速度）
      - 波动幅度（速率序列的 P90-P10，反映不稳定程度）

    参数
    ----
    times：观测时刻（小数年），升序
    disp：累积位移（mm），与 times 等长
    scales：要分析的尺度名（默认全部：annual/quarterly/monthly/weekly）
    min_points_per_window：一个窗口内至少几个点才算得出速率（默认 2）

    返回
    ----
    {scale: {available, reason, windowDays, nWindows, velocityMmYr,
             velocitySeries, rateChangeMmYr2, variabilityMmYr, centers}}
    """
    t = np.asarray(times, dtype=np.float64)
    d = np.asarray(disp, dtype=np.float64)
    valid = np.isfinite(t) & np.isfinite(d)
    t, d = t[valid], d[valid]

    names = scales or tuple(SCALES.keys())
    out: dict[str, Any] = {}

    if len(t) < 2:
        for name in names:
            out[name] = {
                "available": False,
                "reason": f"有效观测点仅 {len(t)} 个，无法做任何尺度趋势",
                "windowDays": SCALES.get(name),
            }
        return out

    # 采样间隔（天）——决定各尺度的可分辨性
    dt_days = float(np.median(np.diff(t))) * 365.25

    for name in names:
        win_days = SCALES[name]
        win_yr = win_days / 365.25
        span_yr = float(t[-1] - t[0])
        pts_per_window = win_days / dt_days if dt_days > 0 else 0.0

        # 不可分辨：窗口内点太少，或总跨度不足两个窗口
        if pts_per_window < min_points_per_window:
            out[name] = {
                "available": False,
                "reason": (f"采样间隔约 {dt_days:.0f} 天，{win_days:.0f} 天窗口内"
                           f"仅约 {pts_per_window:.1f} 个观测点（需 ≥{min_points_per_window}），"
                           f"该尺度物理上不可分辨"),
                "windowDays": win_days,
                "samplingIntervalDays": round(dt_days, 1),
            }
            continue
        if span_yr < 2 * win_yr:
            out[name] = {
                "available": False,
                "reason": (f"总观测跨度 {span_yr * 365.25:.0f} 天 < 2 个 {win_days:.0f} 天窗口，"
                           f"无法形成有意义的速率序列"),
                "windowDays": win_days,
                "samplingIntervalDays": round(dt_days, 1),
            }
            continue

        # 步长取采样间隔（每来一个观测就滑一步），但至少 1 天避免死循环
        step_yr = max(dt_days / 365.25, 1.0 / 365.25)
        centers, rates = _sliding_rates(t, d, win_yr, step_yr)

        if len(rates) < 2:
            out[name] = {
                "available": False,
                "reason": f"该尺度仅得到 {len(rates)} 个有效窗口，不足以形成序列",
                "windowDays": win_days,
                "samplingIntervalDays": round(dt_days, 1),
            }
            continue

        r = np.asarray(rates, dtype=np.float64)
        cen = np.asarray(centers, dtype=np.float64)

        # 速率变化率：速率序列对时间的线性斜率（该尺度上的"加速度"）
        # 只在窗口数 ≥3 时给，否则两点拟合无意义
        rate_change = None
        if len(r) >= 3:
            cc = cen - cen.mean()
            denom = float(cc @ cc)
            if denom > 1e-12:
                rate_change = round(float((cc @ r) / denom), 2)

        out[name] = {
            "available": True,
            "windowDays": win_days,
            "samplingIntervalDays": round(dt_days, 1),
            "pointsPerWindow": round(pts_per_window, 1),
            "nWindows": int(len(r)),
            # 代表速率用中位数：避免某个窗口被单期大气残差带偏
            "velocityMmYr": round(float(np.median(r)), 2),
            "velocitySeries": [round(float(x), 2) for x in r],
            "centers": centers,
            # 速率变化率（mm/yr²）：>0 表示该尺度上形变在加速
            "rateChangeMmYr2": rate_change,
            "variabilityMmYr": round(float(np.percentile(r, 90) - np.percentile(r, 10)), 2),
            "minMmYr": round(float(r.min()), 2),
            "maxMmYr": round(float(r.max()), 2),
            "trendDirection": ("加速" if (rate_change or 0) > 1.0
                               else "减速" if (rate_change or 0) < -1.0 else "平稳"),
        }

    return out

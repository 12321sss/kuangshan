"""SBAS 算法的单元测试：用合成时序验证反演正确性。

不依赖真实 NISAR 数据——构造已知速率/累积位移的相位，反演后应能还原。
"""
from __future__ import annotations

import numpy as np
import pytest

from algorithms.sbas import Pair, phase_to_los_mm, reference_correction, solve

LAM = 0.2439  # NISAR L 波段


def _phase_from_disp(disp_mm: float, lam: float = LAM) -> float:
    """位移(mm) → 相位(弧度)"""
    return disp_mm / 1000.0 * (4 * np.pi / lam)


def test_phase_to_los_roundtrip():
    """相位与位移换算应可逆"""
    for d in (0.0, 10.0, -37.7):
        assert abs(phase_to_los_mm(_phase_from_disp(d), LAM) - d) < 1e-6


def _build_pairs(times, vel_mmyr, coherence=0.9):
    """构造一个 H=2,W=2 的合成干涉对序列，累积位移 = vel * (t - t0)"""
    pairs = []
    t0 = times[0]
    shape = (2, 2)
    for i in range(len(times) - 1):
        t_ref, t_sec = times[i], times[i + 1]
        # 累积位移（mm）
        d_ref = vel_mmyr * (t_ref - t0)
        d_sec = vel_mmyr * (t_sec - t0)
        # 相位差
        ph = np.full(shape, _phase_from_disp(d_sec - d_ref))
        coh = np.full(shape, coherence, dtype=np.float32)
        pairs.append(Pair(t_ref, t_sec, ph, coh))
    return pairs


def test_solve_recovers_linear_velocity():
    """匀速形变：反演速率应精确还原"""
    times = [2026.0, 2026.1, 2026.2, 2026.3, 2026.4]
    pairs = _build_pairs(times, vel_mmyr=50.0)
    res = solve(pairs)
    v = res["velocity_mmyr"]
    # 所有像元速率都应是 50（容差内）
    valid = res["valid_mask"]
    assert valid.all()
    assert np.allclose(v[valid], 50.0, atol=1e-4)


def test_solve_recovers_nonlinear_timeseries():
    """非均匀时间采样也能正确还原累积位移"""
    times = [2026.0, 2026.15, 2026.22, 2026.5, 2026.9]
    pairs = _build_pairs(times, vel_mmyr=-30.0)
    res = solve(pairs)
    d = res["displacement_mm"]
    # 每个时刻的累积位移应 = vel*(t-t0)
    t0 = res["times"][0]
    for i, t in enumerate(res["times"]):
        expect = -30.0 * (t - t0)
        assert np.allclose(d[i][res["valid_mask"]], expect, atol=1e-3)


def test_solve_needs_at_least_two_pairs():
    with pytest.raises(ValueError):
        solve([Pair(2026.0, 2026.1, np.zeros((2, 2)))])


def test_reference_correction_removes_offset():
    """参考区归零：应把参考区的中位相位减成接近 0"""
    times = [2026.0, 2026.1, 2026.2]
    shape = (3, 3)
    # 第一景：全图相位 = 5 rad（纯大气偏移），参考区 mask 前两列
    ph = np.full(shape, 5.0)
    p = Pair(times[0], times[1], ph, np.ones(shape))
    ref_mask = np.zeros(shape, dtype=bool)
    ref_mask[:, :2] = True
    corr = reference_correction([p], ref_mask)
    # 参考区中位 5.0，减去后全图应接近 0
    assert np.allclose(corr[0].phase, 0.0, atol=1e-6)


def test_solve_handles_nan_pixels():
    """含 NaN 的像元应被跳过，其余正常解算。

    注意：把 NaN 放在**时间轴末端**的一期（模拟「后期失相干」）。
    若放在中间，时间轴会断成两段、该像元速率物理上不可唯一确定，
    lstsq 只会给出最小范数解——那不是 bug，是数据本身的信息缺失。
    """
    times = [2026.0, 2026.1, 2026.2, 2026.3]
    pairs = _build_pairs(times, vel_mmyr=20.0)
    # 把 (0,0) 像元的最后一景（2026.2→2026.3）相位设为 NaN
    pairs[-1].phase[0, 0] = np.nan
    res = solve(pairs, min_valid_pct=0.5)
    v = res["velocity_mmyr"]
    # (0,0) 前 3/4 期有效，仍应解出 20（末端缺失不影响已有区间的斜率）
    assert np.isclose(v[0, 0], 20.0, atol=1e-3)
    # 其他像元正常
    assert np.allclose(v[1, 1], 20.0, atol=1e-4)

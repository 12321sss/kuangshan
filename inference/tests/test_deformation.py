"""形变时序分析（速度/加速度/倒数速度外推）的单元测试。"""
from __future__ import annotations

import numpy as np
import pytest

from algorithms.deformation import (
    TrendResult,
    analyze_timeseries,
    theil_sen_slope,
    velocity_level,
)


def _linear_timeseries(n=20, vel=50.0, t0=2026.0):
    """匀速形变：d = vel*(t-t0)"""
    t = np.linspace(t0, t0 + 2.0, n)  # 2 年
    d = vel * (t - t0)
    return list(t), d


def test_theil_sen_slope_robust():
    """Theil-Sen 应精确还原匀速斜率，且抗离群点"""
    t, d = _linear_timeseries(vel=30.0)
    assert abs(theil_sen_slope(np.array(t), d) - 30.0) < 1e-6

    # 加一个离群点
    d2 = d.copy()
    d2[10] += 500.0
    v = theil_sen_slope(np.array(t), d2)
    assert abs(v - 30.0) < 5.0  # 抗离群，偏差应远小于最小二乘


def test_analyze_timeseries_constant_velocity():
    """匀速：速度精确、加速度≈0、非加速"""
    t, d = _linear_timeseries(vel=40.0)
    r = analyze_timeseries(t, d)
    assert not r.insufficient
    assert abs(r.velocity_mmyr - 40.0) < 1.0
    assert abs(r.acceleration_mmyr2) < 1.0
    assert not r.accelerating
    assert r.tf_days is None  # 匀速不加速，不外推


def test_analyze_timeseries_accelerating():
    """加速形变（二次曲线）应检测到正加速度"""
    t = np.linspace(2026.0, 2028.0, 30)
    d = 10 * (t - 2026.0) ** 2  # d = 10*(dt)^2，a = 20 mm/yr²
    r = analyze_timeseries(list(t), d)
    assert not r.insufficient
    assert r.acceleration_mmyr2 > 10  # 应为正
    assert r.accelerating


def test_analyze_timeseries_insufficient():
    """点太少 → insufficient"""
    t, d = _linear_timeseries(n=4)
    r = analyze_timeseries(t, d, min_points=6)
    assert r.insufficient


def test_velocity_level():
    assert velocity_level(5)["label"] == "极缓慢"
    assert velocity_level(50)["level"] == 3
    assert velocity_level(500)["label"] == "极快速"

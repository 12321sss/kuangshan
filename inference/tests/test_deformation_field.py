"""形变场空间化汇总（summarize_field）的单元测试。"""
from __future__ import annotations

import numpy as np

from algorithms.deformation import summarize_field


def _field(vel=30.0, accel=0.0, n=8, m=10):
    v = np.full((n, m), vel, dtype=np.float64)
    a = np.full((n, m), accel, dtype=np.float64)
    return v, a


def test_empty_field_insufficient():
    v = np.full((5, 5), np.nan)
    a = np.full((5, 5), np.nan)
    r = summarize_field(v, a)
    assert r["verdict"]["type"] == "数据不足"
    assert r["n_valid"] == 0


def test_stable_field():
    v, a = _field(vel=5.0, accel=0.0)
    r = summarize_field(v, a)
    assert r["n_valid"] == 80
    assert r["verdict"]["type"] == "整体稳定"
    assert r["velocity"]["median"] == 5.0
    # 无加速、无失稳外推
    assert r["trend"]["accelerating"] == 0
    assert r["n_forecastable"] == 0


def test_hotspots_sorted_by_risk():
    """速度快的像元应排在危险测点清单前面"""
    v = np.zeros((4, 4), dtype=np.float64)
    v[2, 3] = 150.0     # 最快的
    v[0, 0] = 40.0
    a = np.zeros((4, 4), dtype=np.float64)
    r = summarize_field(v, a, top_n=3)
    hs = r["hotspots"]
    assert len(hs) == 3
    assert hs[0]["velocity"] == 150.0
    # 最快像元坐标（缺省用行列号）
    assert hs[0]["x"] == 3 and hs[0]["y"] == 2
    assert hs[0]["severityLabel"] == "快速"


def test_trend_distribution_and_verdict():
    """一半像元加速 → 整体/局部加速判定"""
    v = np.full((10, 10), 30.0)
    a = np.zeros((10, 10))
    a[:5, :] = 30.0        # 前 5 行加速
    r = summarize_field(v, a)
    assert r["trend"]["accelerating"] == 50
    assert r["trend"]["pctAccelerating"] == 50.0
    assert r["verdict"]["type"] == "整体加速"
    assert r["verdict"]["confidence"] == "high"


def test_forecastable_count_with_tf():
    v, a = _field(vel=40.0)
    tf = np.full((8, 10), np.nan)
    tf[0, 0] = 30.0
    tf[1, 1] = 60.0
    r = summarize_field(v, a, tf_days=tf)
    assert r["n_forecastable"] == 2


def test_xy_coordinates_passthrough():
    """传入真实经纬度时，热点坐标应原样返回"""
    v, a = _field(vel=60.0)
    v[0, 0] = 120.0
    xs = np.linspace(114.87, 114.93, 10)
    ys = np.linspace(28.57, 28.62, 8)
    r = summarize_field(v, a, xs=xs, ys=ys, top_n=1)
    h = r["hotspots"][0]
    assert h["x"] == pytest_approx(114.87)
    assert h["y"] == pytest_approx(28.57)


def pytest_approx(x):
    """本文件内轻量近似（避免 import pytest 到算法层依赖）"""
    import pytest
    return pytest.approx(x, rel=1e-5)

"""形变规则覆盖的单元测试。"""
from __future__ import annotations

from algorithms.deformation_risk import deformation_overlay


def test_no_data_no_change():
    r = deformation_overlay(55.0, None, None)
    assert r["adjusted_score"] == 55.0
    assert r["uplift"] == 0
    assert not r["applied"]


def test_unreliable_no_change():
    """信噪比不足时，不覆盖，只提示"""
    r = deformation_overlay(55.0, 80.0, 30.0, reliable=False)
    assert r["adjusted_score"] == 55.0
    assert not r["applied"]
    assert any("信噪比" in e for e in r["evidence"])


def test_slow_velocity_uplifts_one():
    """30~100 mm/yr 提一级（+10）"""
    r = deformation_overlay(50.0, 40.0, None)
    assert r["uplift"] == 1
    assert r["adjusted_score"] == 60.0
    assert r["applied"]


def test_fast_velocity_uplifts_two():
    """≥100 mm/yr 提两级（+20）"""
    r = deformation_overlay(50.0, 150.0, None)
    assert r["uplift"] == 2
    assert r["adjusted_score"] == 70.0


def test_acceleration_uplifts_one():
    """加速度明显也提一级"""
    r = deformation_overlay(50.0, 10.0, 25.0)
    assert r["uplift"] == 1
    assert r["adjusted_score"] == 60.0


def test_velocity_and_acceleration_stack_capped():
    """速度+加速度叠加，但提级封顶在 100 分"""
    r = deformation_overlay(90.0, 150.0, 30.0)
    assert r["adjusted_score"] == 100.0  # 90 + 20 封顶
    assert r["uplift"] == 2


def test_stable_velocity_no_change():
    """稳定速率不覆盖"""
    r = deformation_overlay(50.0, 5.0, 0.0)
    assert r["uplift"] == 0
    assert not r["applied"]

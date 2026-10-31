"""多时间尺度趋势分析（analyze_multiscale）的单元测试。

重点验证两条：
  1. **口径红线**：采样间隔不足时，对应尺度必须明确不可用，不能硬凑出假周速率
  2. **跨尺度一致性**：匀速形变下，各可用尺度给出的速率应一致
"""
from __future__ import annotations

import numpy as np

from algorithms.deformation import SCALES, analyze_multiscale


def _series(n=40, interval_days=12.0, vel=20.0, t0=2026.0, accel=None):
    """构造等间隔观测序列。

    interval_days=12 模拟 Sentinel-1 / NISAR 的 12 天重访。
    accel：二次项系数（mm/yr²），None 表示匀速。
    """
    t = np.array([t0 + i * interval_days / 365.25 for i in range(n)])
    dt = t - t0
    if accel is None:
        d = vel * dt
    else:
        d = vel * dt + 0.5 * accel * dt * dt
    return list(t), d


def test_weekly_unresolvable_with_12day_sampling():
    """12 天重访 → 周尺度必须判为不可用（这是口径红线，不能给假周速率）"""
    # n=80 × 12 天 ≈ 2.6 年，保证年/季/月尺度都有足够跨度
    t, d = _series(n=80, interval_days=12.0)
    res = analyze_multiscale(t, d)

    assert res["weekly"]["available"] is False
    assert "不可分辨" in res["weekly"]["reason"]
    # 月尺度：12 天采样，30 天窗口 ≈ 2.5 点，勉强可用
    assert res["monthly"]["available"] is True
    # 年尺度：80 期 × 12 天 ≈ 2.6 年，够两个年窗口
    assert res["annual"]["available"] is True


def test_monthly_unresolvable_with_monthly_sampling():
    """30 天重访 → 月尺度不可分辨（每窗口只有 1 个点）"""
    t, d = _series(n=24, interval_days=30.0)
    res = analyze_multiscale(t, d)
    assert res["monthly"]["available"] is False
    assert res["quarterly"]["available"] is True


def test_constant_velocity_consistent_across_scales():
    """匀速形变：各可用尺度的速率都应接近真值"""
    t, d = _series(n=80, interval_days=12.0, vel=20.0)
    res = analyze_multiscale(t, d)

    for name in ("annual", "quarterly", "monthly"):
        r = res[name]
        assert r["available"] is True, f"{name} 应可用"
        assert abs(r["velocityMmYr"] - 20.0) < 2.0, f"{name} 速率偏差过大：{r['velocityMmYr']}"
        # 匀速 → 速率序列应基本无变化
        assert abs(r["rateChangeMmYr2"] or 0) < 5.0


def test_accelerating_detected_at_coarse_scale():
    """加速形变：年尺度的速率变化率应为正"""
    t, d = _series(n=80, interval_days=12.0, vel=10.0, accel=30.0)
    res = analyze_multiscale(t, d)
    ann = res["annual"]
    assert ann["available"] is True
    assert ann["rateChangeMmYr2"] is not None
    assert ann["rateChangeMmYr2"] > 0, "加速形变的速率变化率应为正"
    assert ann["trendDirection"] == "加速"


def test_insufficient_points_all_unavailable():
    """只有 1 个点 → 所有尺度都不可用，且给出原因"""
    t, d = _series(n=1)
    res = analyze_multiscale(t, d)
    for name in SCALES:
        assert res[name]["available"] is False
        assert res[name]["reason"]


def test_span_too_short():
    """跨度不足两个窗口 → 该尺度不可用（不硬算）"""
    t, d = _series(n=10, interval_days=12.0)   # 120 天，不足两个年窗口
    res = analyze_multiscale(t, d)
    assert res["annual"]["available"] is False
    assert "跨度" in res["annual"]["reason"]


def test_result_is_json_serializable():
    """返回结构必须可直接 JSON 序列化（要经 API 返回给前端）"""
    import json
    t, d = _series(n=80)
    res = analyze_multiscale(t, d)
    s = json.dumps(res, ensure_ascii=False)
    assert len(s) > 0

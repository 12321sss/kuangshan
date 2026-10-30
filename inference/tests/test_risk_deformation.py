"""形变证据接入风险评估的集成测试（走 HTTP 端点）。

验证：形变证据通过 /api/v1/risk/evaluate 传入后，能触发规则覆盖提级，
且结果里带出形变证据。
"""
from __future__ import annotations

# 用在线 Sentinel-2 或本地数据都需要网络/影像，这里用一个最小 AOI + 空 classes，
# 只验证「形变规则覆盖」这条新增链路，不验证六维打分的具体数值。
AOI = [[116.018, 26.470], [116.026, 26.470], [116.026, 26.476], [116.018, 26.476]]


def _base_payload(**extra):
    payload = {
        "aoi": AOI,
        "classes": [],
        "withGrid": False,   # 不读 DEM，测试只关心形变覆盖
    }
    payload.update(extra)
    return payload


def test_risk_without_deformation(client):
    resp = client.post("/api/v1/risk/evaluate", json=_base_payload())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 无形变证据时，deformation 字段应为 null
    assert data.get("deformation") is None
    assert "score" in data


def test_risk_deformation_uplifts_level(client):
    """快速蠕滑的形变证据应触发提级"""
    base = client.post("/api/v1/risk/evaluate", json=_base_payload()).json()["data"]
    base_total = base["score"]["total"]

    resp = client.post("/api/v1/risk/evaluate", json=_base_payload(
        deformation={"velocityMmyr": 150.0, "accelerationMmyr2": 30.0,
                     "reliable": True},
    ))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # 形变证据应被应用
    assert data["deformation"]["applied"] is True
    assert data["deformation"]["uplift"] >= 2
    # 总分应高于基线（提级生效）
    assert data["score"]["total"] > base_total
    # 有提级依据
    assert any("形变" in e for e in data["deformation"]["evidence"])


def test_risk_deformation_unreliable_no_uplift(client):
    """信噪比不足的形变证据不应提级，但要提示"""
    base = client.post("/api/v1/risk/evaluate", json=_base_payload()).json()["data"]

    resp = client.post("/api/v1/risk/evaluate", json=_base_payload(
        deformation={"velocityMmyr": 150.0, "accelerationMmyr2": 30.0,
                     "reliable": False},
    ))
    data = resp.json()["data"]

    assert data["deformation"]["applied"] is False
    assert data["score"]["total"] == base["score"]["total"]  # 不提级
    assert any("信噪比" in e for e in data["deformation"]["evidence"])

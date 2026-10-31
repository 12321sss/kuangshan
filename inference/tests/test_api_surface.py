"""API 契约回归测试。

这个文件是重构的「护栏」：任何人删路由、改错前缀、少挂一个 router，
这里立刻红。清单按 URL 前缀分组，与 app/routers/ 一一对应。
"""
from __future__ import annotations

# (方法, 路径) —— 28 个方法 / 27 条路径，与前端和 Java 侧的调用一一对应
EXPECTED_ENDPOINTS = {
    ("GET", "/health"),
    ("GET", "/api/v1/class-types"),
    ("GET", "/api/v1/scenes"),
    ("POST", "/api/v1/inference/submit"),
    ("GET", "/api/v1/inference/{task_id}/status"),
    ("POST", "/api/v1/sentinel/extract"),
    ("POST", "/api/v1/sentinel/extract-async"),
    ("POST", "/api/v1/sentinel/search"),
    ("POST", "/api/v1/sentinel/preview"),
    ("POST", "/api/v1/sentinel/diff-heatmap"),
    ("POST", "/api/v1/sentinel/export-geotiff"),
    ("POST", "/api/v1/sentinel/demo-bundle"),
    ("GET", "/api/v1/sentinel/demo-bundle/{bundle_id}"),
    ("POST", "/api/v1/terrain/analyze"),
    ("POST", "/api/v1/risk/evaluate"),
    ("POST", "/api/v1/slope/analyze"),
    ("POST", "/api/v1/classify/supervised"),
    ("POST", "/api/v1/classify/local"),
    ("POST", "/api/v1/monitor/availability"),
    ("POST", "/api/v1/monitor/change-events"),
    ("POST", "/api/v1/spatial/analyze"),
    ("POST", "/api/v1/aoi/import"),
    ("GET", "/api/v1/imagery/inspect"),
    ("POST", "/api/v1/imagery/inspect"),
    ("POST", "/api/v1/fusion/compare"),
    ("POST", "/api/v1/fusion/merge"),
    ("POST", "/api/v1/report/generate"),
    ("POST", "/api/v1/ecology/rsei"),
    ("POST", "/api/v1/deformation/multiscale"),
    ("GET", "/api/v1/deformation/results"),
    ("POST", "/api/v1/deformation/submit"),
}


def test_endpoint_surface_is_stable(client):
    spec = client.get("/openapi.json").json()
    actual = {
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
    }
    missing = EXPECTED_ENDPOINTS - actual
    added = actual - EXPECTED_ENDPOINTS
    assert not missing, f"路由丢失（前端/Java 会 404）: {sorted(missing)}"
    assert not added, f"出现未登记的新路由，请同步更新本清单与文档: {sorted(added)}"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["service"] == "rs-platform-inference"
    assert body["version"]


def test_class_types_returns_seven_classes(client):
    data = client.get("/api/v1/class-types").json()["data"]
    # 七类矿山地物 + 历史兼容类型（BUILDING / MOUNTAIN）
    assert {"PIT", "DUMP", "TAILINGS", "BARE", "VEGETATION", "ROAD", "WATER"} <= set(data)


def test_task_status_of_unknown_id(client):
    body = client.get("/api/v1/inference/not-exist/status").json()
    assert body["code"] == 404
    assert body["data"] is None


def test_request_id_header_present(client):
    # 中间件给每个请求打 request id，排查时用于对齐前后端日志
    assert client.get("/health").headers.get("X-Request-ID")

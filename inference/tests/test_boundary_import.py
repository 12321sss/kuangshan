"""边界文件导入测试：GeoJSON / KML 走完整 HTTP 链路（base64 → 解析 → WGS84 环）。

口径：转换失败的坐标系一律报错，不做兜底猜测——偏几百米的边界比报错危险得多。
"""
from __future__ import annotations

import base64
import json

GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "测试矿区"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[116.018, 26.470], [116.026, 26.470],
                             [116.026, 26.476], [116.018, 26.476], [116.018, 26.470]]],
        },
    }],
}

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<name>KML 测试</name>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
116.018,26.470,0 116.026,26.470,0 116.026,26.476,0 116.018,26.476,0 116.018,26.470,0
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>
"""


def _post(client, filename: str, content: str):
    return client.post("/api/v1/aoi/import", json={
        "filename": filename,
        "contentBase64": base64.b64encode(content.encode("utf-8")).decode(),
    })


def test_import_geojson(client):
    resp = _post(client, "boundary.geojson", json.dumps(GEOJSON))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["sourceFormat"] == "GeoJSON"
    assert data["summary"]["featureCount"] == 1

    feature = data["features"][0]
    assert feature["vertexCount"] >= 4
    assert feature["outer"][0][0] == feature["outer"][-1][0]  # 首尾闭合
    # 0.008° × 0.006° 在该纬度约 79 ha，只验证量级
    assert 50 < feature["areaHa"] < 120


def test_import_kml(client):
    resp = _post(client, "boundary.kml", KML)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["sourceFormat"] == "KML"
    assert data["sourceCrs"] == "EPSG:4326"


def test_import_rejects_empty_payload(client):
    resp = client.post("/api/v1/aoi/import", json={})
    assert resp.status_code == 400
    assert "文件" in resp.json()["detail"]


def test_import_rejects_unknown_format(client):
    resp = _post(client, "boundary.txt", "not a boundary at all")
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]

"""影像元数据自动识别测试（需要一个真实 GeoTIFF）。"""
from __future__ import annotations


def test_inspect_geotiff(client, test_tif):
    resp = client.get("/api/v1/imagery/inspect", params={"path": str(test_tif)})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["crs"].startswith("EPSG:")
    assert data["width"] > 0 and data["height"] > 0
    assert data["bandCount"] >= 3
    # 地面分辨率应为个位数米级（亚米~十米），不是投影米
    assert data["resolutionM"] and 0 < data["resolutionM"] < 100

    b = data["bounds"]
    assert b["west"] < b["east"] and b["south"] < b["north"]
    assert -180 <= b["west"] <= 180 and -90 <= b["south"] <= 90

    # 预览图必须生成，否则前端选完影像看不到东西
    assert data["previewBase64"]
    assert data["areaKm2"] > 0


def test_inspect_reports_error_for_missing_file(client):
    resp = client.get("/api/v1/imagery/inspect", params={"path": "Z:/definitely/not/here.tif"})
    assert resp.status_code in (400, 500)
    assert resp.json().get("detail")

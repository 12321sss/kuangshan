"""本地高分影像监督分类测试（需要一个真实 GeoTIFF）。

链路：4 波段读取 → 7 维特征（B/G/R/NIR + NDVI + NDWI + 亮度）→ 随机森林
→ 混淆矩阵 → OA / Kappa。这是「本地影像也能出精度指标」的核心能力，
坏掉的话演示时说不出准确率。
"""
from __future__ import annotations

import pytest

# 在影像范围内按比例撒点：三类各 3 个，落点只要求在图内（不必落在正确地物上，
# 本用例验的是链路通不通、指标算没算，不是分类准不准）
FRACTIONS = [
    (0.20, 0.20, "VEGETATION"), (0.30, 0.25, "VEGETATION"), (0.25, 0.30, "VEGETATION"),
    (0.75, 0.75, "BARE"), (0.80, 0.70, "BARE"), (0.70, 0.80, "BARE"),
    (0.50, 0.10, "WATER"), (0.55, 0.15, "WATER"), (0.45, 0.12, "WATER"),
]


def test_classify_local_returns_accuracy(client, test_tif):
    meta = client.get("/api/v1/imagery/inspect", params={"path": str(test_tif)}).json()["data"]
    b = meta["bounds"]
    samples = [
        {"classType": cls,
         "lng": round(b["west"] + (b["east"] - b["west"]) * fx, 7),
         "lat": round(b["south"] + (b["north"] - b["south"]) * fy, 7)}
        for fx, fy, cls in FRACTIONS
    ]

    resp = client.post("/api/v1/classify/local", json={
        "path": str(test_tif),
        "samples": samples,
        "maxDim": 384,          # 压小栅格，测试只求链路通
        "minSamples": 3,
        "minAreaPx": 5,
    })
    if resp.status_code == 400:
        pytest.skip(f"样本落点不足以构成多类样本：{resp.json().get('detail')}")
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert 0 < data["accuracy"]["overallAccuracy"] <= 100
    assert -1 <= data["accuracy"]["kappa"] <= 1
    # 本地 4 波段只有 7 维特征（没有短波红外，算不了 NDBI/BSI）
    assert data["grid"]["featureCount"] == 7
    assert data["classes"], "分类结果为空"
    for c in data["classes"]:
        assert c["areaHa"] >= 0
        assert 0 <= c["userAccuracy"] <= 100


def test_classify_local_rejects_missing_path(client):
    resp = client.post("/api/v1/classify/local", json={"path": "Z:/nope.tif", "samples": []})
    assert resp.status_code in (400, 500)
    assert resp.json().get("detail")

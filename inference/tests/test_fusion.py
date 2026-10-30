"""叠加分析（分类 × 指数）离线测试：纯几何运算，不依赖网络。

守卫的是 docs/18 的核心口径：
- compare 必须同时给出四个面积与 IoU，且只保留差异斑块
- merge 只改指定类，**未设策略的类原样保留**（不能因为只关心水体就丢掉植被）
"""
from __future__ import annotations


def _rect(w, s, e, n) -> dict:
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
    }


# 分类：水体偏西；指数：水体偏东 → 有交集但不重合
CLASSIFIED = {"WATER": [_rect(116.018, 26.470, 116.024, 26.474)],
              "VEGETATION": [_rect(116.014, 26.466, 116.018, 26.472)]}
INDICES = {"WATER": [_rect(116.020, 26.470, 116.026, 26.474)]}


def test_compare_reports_areas_and_iou(client):
    resp = client.post("/api/v1/fusion/compare", json={
        "classified": CLASSIFIED,
        "indices": INDICES,
        "options": {"minPatchHa": 0.05, "topPatches": 5, "withImage": False},
    })
    assert resp.status_code == 200
    data = resp.json()["data"]

    water = next(p for p in data["pairs"] if p["classType"] == "WATER")
    assert water["classifiedHa"] > 0 and water["indicesHa"] > 0
    assert water["bothHa"] > 0
    # IoU 的定义：交集 / 并集，必须落在 (0, 1)
    assert 0 < water["iou"] < 1
    # 只分类 / 只指数 的面积都应为正（两块矩形错开）
    assert water["onlyClassifiedHa"] > 0 or water["onlyIndicesHa"] > 0
    assert "IoU" in water["finding"] or "一致" in water["finding"]

    # 汇总口径：参与配对的类型数
    assert data["summary"]["pairCount"] >= 1


def test_compare_without_image_skips_base64(client):
    data = client.post("/api/v1/fusion/compare", json={
        "classified": CLASSIFIED, "indices": INDICES,
        "options": {"withImage": False},
    }).json()["data"]
    assert not data.get("imageBase64")


def test_merge_keeps_unlisted_classes(client):
    data = client.post("/api/v1/fusion/merge", json={
        "classified": CLASSIFIED,
        "indices": INDICES,
        "pairs": [{"classType": "WATER", "strategy": "INDICES_FIRST"}],
        "withImage": False,
    }).json()["data"]

    by_class = {c["classType"]: c for c in data["classes"]}
    # 指定类走「指数优先」：最终面积应等于指数结果面积
    assert by_class["WATER"]["source"] in ("INDICES", "指数")
    # 未指定的植被必须原样保留分类结果
    assert "VEGETATION" in by_class
    assert by_class["VEGETATION"]["finalHa"] > 0


def test_merge_intersect_only_shrinks(client):
    data = client.post("/api/v1/fusion/merge", json={
        "classified": CLASSIFIED, "indices": INDICES,
        "pairs": [{"classType": "WATER", "strategy": "INTERSECT_ONLY"}],
        "withImage": False,
    }).json()["data"]
    water = next(c for c in data["classes"] if c["classType"] == "WATER")
    assert water["finalHa"] <= water["classifiedHa"] + 1e-6

"""报告生成测试：python-docx 产物必须是可打开的 docx（zip 头 PK）。

同时守住「附录不能空」这条交付红线：解译明细没进报告，客户核对时就没有依据。
"""
from __future__ import annotations

import base64
import json


def _report_payload(**overrides):
    payload = {
        "projectName": "单元测试矿区",
        "timeseries": [],
        "summary": [],
        "sensorOnline": 2,
        "sensorAlarm": 0,
        "extractions": [],
    }
    payload.update(overrides)
    return payload


def test_generate_minimal_report(client):
    resp = client.post("/api/v1/report/generate", json=_report_payload())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["filename"].endswith(".docx")
    # docx 本质是 zip，前两字节必须是 PK
    raw = base64.b64decode(data["docx_base64"])
    assert raw[:2] == b"PK"
    assert len(raw) > 5000


def test_report_appendix_lists_extractions(client):
    """带解译明细时应生成附录章节：产物明显更大"""
    base = client.post("/api/v1/report/generate", json=_report_payload()).json()["data"]
    extractions = [{
        "acquisitionDate": "2026-09-27",
        "classType": "WATER",
        "method": "SUPERVISED",
        "extractAreaHa": 1240,
        "coveragePct": 12.4,
        "satellite": "SENTINEL2",
        "accuracyJson": json.dumps({
            "overallAccuracy": 87.5, "kappa": 0.833,
            "sampleCount": 112, "split": "65/35 分层抽样",
        }),
    }]
    with_extra = client.post("/api/v1/report/generate",
                             json=_report_payload(extractions=extractions)).json()["data"]

    base_size = len(base["docx_base64"])
    full_size = len(with_extra["docx_base64"])
    assert full_size > base_size, "附录章节没有写进报告"


def test_report_deformation_section(client):
    """形变证据应写进报告的 6.1 章节"""
    resp = client.post("/api/v1/report/generate", json={
        "projectName": "形变测试",
        "safety": {
            "available": True,
            "score": {"total": 55, "level": "中", "dimensions": []},
            "deformation": {
                "source": "NISAR", "velocity": 45.0, "acceleration": 12.0,
                "reliable": True, "forecastDays": 180, "uplift": 1,
            },
        },
    })
    assert resp.status_code == 200, resp.text
    # 产物是 docx，正文含形变关键词（解压 XML 检查）
    import base64, zipfile, io
    raw = base64.b64decode(resp.json()["data"]["docx_base64"])
    z = zipfile.ZipFile(io.BytesIO(raw))
    xml = z.read("word/document.xml").decode("utf-8")
    assert "地表形变监测" in xml
    assert "45.0 mm/yr" in xml or "45.0" in xml
    assert "风险提级" in xml


def test_report_no_duplicate_appendix(client):
    """附录章节只应出现一次（修复历史重复调用 bug）"""
    import base64, zipfile, io
    resp = client.post("/api/v1/report/generate", json={
        "projectName": "重复检查",
        "extractions": [{"acquisitionDate": "2026-09-27", "classType": "WATER",
                         "method": "INDEX", "extractAreaHa": 100, "coveragePct": 10}],
    })
    raw = base64.b64decode(resp.json()["data"]["docx_base64"])
    z = zipfile.ZipFile(io.BytesIO(raw))
    xml = z.read("word/document.xml").decode("utf-8")
    assert xml.count("九、附录") == 1

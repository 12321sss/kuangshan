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

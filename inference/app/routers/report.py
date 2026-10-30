"""报告生成：基于数据库真实统计产出 Word 报告。"""
from __future__ import annotations

import base64
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from algorithms import report as report_gen

router = APIRouter(tags=["report"])


# ---------------------------------------------------------------------------
# 报告生成（S4）：基于数据库真实统计生成 Word 报告
# ---------------------------------------------------------------------------


class ReportRequest(BaseModel):
    """报告生成请求：Java 汇总好真实数据后传入"""
    projectName: str = "默认项目"
    generatedAt: str | None = None
    timeseries: list[dict] = []
    summary: list[dict] = []
    forecast: dict = {}
    sensorOnline: int = 0
    sensorAlarm: int = 0
    # 解译明细（可选）：传入则报告增加「附录：遥感解译成果明细 + 分类精度」章节
    # 曾经漏声明这个字段：前端和 Java 都在传，Pydantic 静默丢弃，附录永远是空的
    extractions: list[dict] = []
    # 生态指数 RSEI 结果（可选）：传入则报告增加「五、生态质量评价（RSEI）」章节
    rsei: dict | None = None
    # 安全风险评估结果（可选）：传入则报告增加「六、开采安全风险评估」章节
    # 注意：字段必须显式声明，Pydantic 会丢弃未声明字段，漏写会导致章节静默消失
    safety: dict | None = None


@router.post("/api/v1/report/generate")
def generate_report(req: ReportRequest):
    """生成矿山稳定性/安全性报告，返回 docx 字节流（base64）"""
    data = req.model_dump()
    if not data.get("generatedAt"):
        data["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        docx_bytes = report_gen.generate_report(data)
        return {
            "code": 0, "message": "success",
            "data": {
                "filename": f"矿山监测报告-{data['projectName']}.docx",
                "docx_base64": base64.b64encode(docx_bytes).decode(),
            },
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"报告生成失败: {e}") from e

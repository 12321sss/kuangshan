"""
矿山稳定性/安全性报告生成（S4）

基于数据库真实统计（时序变化、解译结果、传感器监测）生成 Word 报告。
python-docx 模板化，结论措辞规则化 —— 严格遵守口径红线：
  - 输出「潜在水土流失风险筛查」，不报实测侵蚀量
  - 「持续复绿」≠「生态修复成功」
  - 预测是趋势外推，带不确定性
"""
from __future__ import annotations

import io
from datetime import datetime

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x0D, 0x94, 0x88)  # 品牌青绿


def _add_kv(doc: Document, label: str, value: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(f"{label}：")
    r.bold = True
    p.add_run(str(value))


def _add_note(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x86, 0x90, 0x9C)


def generate_report(data: dict) -> bytes:
    """生成报告，返回 docx 字节流。

    data 结构（由 Java 汇总后传入）：
      {
        "projectName": str,
        "generatedAt": str,
        "timeseries": [{"date", "totalAreaHa", "byClass": {...}}, ...],
        "summary": [{"classType", "totalAreaHa", "recordCount"}, ...],
        "forecast": {"insufficient", "forecast": [{"date","areaHa","lowerHa","upperHa"}]},
        "sensorOnline": int, "sensorAlarm": int,
      }
    """
    doc = Document()

    # ---- 标题 ----
    title = doc.add_heading("矿山遥感监测综合分析报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ---- 一、矿区概况 ----
    _add_heading(doc, "一、矿区概况", level=1)
    _add_kv(doc, "监测项目", data.get("projectName", "-"))
    _add_kv(doc, "报告生成时间", data.get("generatedAt", datetime.now().strftime("%Y-%m-%d %H:%M")))
    _add_kv(doc, "数据来源", "Sentinel-2 遥感影像在线解译 + 传感器监测（全部来自数据库真实记录）")

    # ---- 二、地物时序变化 ----
    _add_heading(doc, "二、地物面积时序变化", level=1)
    ts = data.get("timeseries", [])
    if not ts:
        doc.add_paragraph("当前项目暂无解译记录。")
    else:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text = "影像日期"
        hdr[1].text = "合计面积(km²)"
        hdr[2].text = "较上期变化(km²)"
        for row in ts:
            cells = table.add_row().cells
            cells[0].text = str(row.get("date", "-"))
            cells[1].text = f"{row.get('totalAreaHa', 0) / 100:.2f}"
            chg = row.get("changeHa", 0)
            cells[2].text = f"{chg / 100:+.2f}"

    # ---- 三、地物构成 ----
    _add_heading(doc, "三、地物构成", level=1)
    summary = data.get("summary", [])
    if summary:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text = "地物类型"
        hdr[1].text = "累计面积(km²)"
        hdr[2].text = "记录数"
        for c in summary:
            cells = table.add_row().cells
            cells[0].text = str(c.get("classType", "-"))
            cells[1].text = f"{c.get('totalAreaHa', 0) / 100:.2f}"
            cells[2].text = str(c.get("recordCount", 0))

    # ---- 四、采坑趋势外推 ----
    _add_heading(doc, "四、采坑扩张趋势（外推）", level=1)
    forecast = data.get("forecast", {})
    if forecast.get("insufficient"):
        doc.add_paragraph("采坑类真实提取记录不足 2 期，无法做趋势外推。")
    else:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text = "外推日期"
        hdr[1].text = "面积中值(km²)"
        hdr[2].text = "区间下限(km²)"
        hdr[3].text = "区间上限(km²)"
        for f in forecast.get("forecast", []):
            cells = table.add_row().cells
            cells[0].text = str(f.get("date", "-"))
            cells[1].text = f"{f.get('areaHa', 0) / 100:.2f}"
            cells[2].text = f"{f.get('lowerHa', 0) / 100:.2f}"
            cells[3].text = f"{f.get('upperHa', 0) / 100:.2f}"
        _add_note(doc, "注：趋势外推非实测结果，实际扩张速率受采矿计划、地形与政策等因素影响。")

    # ---- 五、传感器监测概况 ----
    _add_heading(doc, "五、传感器监测概况", level=1)
    _add_kv(doc, "在线设备数", str(data.get("sensorOnline", 0)))
    _add_kv(doc, "未处理告警数", str(data.get("sensorAlarm", 0)))

    # ---- 六、结论与口径说明 ----
    _add_heading(doc, "六、结论与口径说明", level=1)
    doc.add_paragraph("本报告输出为「潜在水土流失风险筛查」，非实测侵蚀量。")
    doc.add_paragraph("「持续复绿」仅表示植被覆盖度回升，不等于生态修复成功。")
    _add_note(doc, "本报告由智慧矿山平台自动生成，数据可追溯到每次解译记录。")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

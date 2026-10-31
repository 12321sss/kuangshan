"""形变趋势分析接口（多时间尺度：年 / 季 / 月 / 周）。

职责边界：本接口只做「时序数据 → 趋势指标」的纯计算，不碰数据库、不碰文件。
数据来源（SBAS 反演结果、解缠产物、人工测点）由调用方（Java 后端 / 前端）准备好传入。
这样算法能力可以被任意数据源复用，也便于单测。

为什么拆 multiScale 单独成接口而不是塞进 risk/evaluate：
  - risk/evaluate 是「一次性打分」，趋势分析是「时序诊断」，输入输出结构完全不同；
  - 前端展示趋势曲线需要原始速率序列，塞进风险评估响应会让响应体膨胀且耦合。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms.deformation import SCALES, analyze_multiscale

router = APIRouter(tags=["deformation"])


class MultiscaleRequest(BaseModel):
    """多时间尺度趋势分析请求。"""

    times: list[float] = Field(
        ..., min_length=2,
        description="观测时刻，小数年（如 2026.5 表示 2026 年年中），需升序")
    displacement: list[float] = Field(
        ..., min_length=2,
        description="累积位移（mm，LOS 视线向），与 times 等长")
    scales: list[str] | None = Field(
        None,
        description=f"要分析的尺度，可选 {list(SCALES)}；不传则全部分析")


class MultiscaleData(BaseModel):
    """响应体（字段与 analyze_multiscale 返回一致）。"""

    spanDays: float
    samplingIntervalDays: float
    availableScales: list[str]
    unavailableScales: dict[str, str]   # 尺度 → 不可用原因
    scales: dict


@router.post("/api/v1/deformation/multiscale")
def multiscale_trend(req: MultiscaleRequest):
    """多时间尺度形变趋势分析。

    对年 / 季 / 月 / 周分别给出速率、速率变化率、波动幅度；
    **采样间隔不足的尺度会明确返回不可用及原因**，不会硬凑一个假速率——
    12 天重访的 SAR 数据在物理上无法分辨周尺度形变，这是口径红线。
    """
    if len(req.times) != len(req.displacement):
        raise HTTPException(status_code=400,
                            detail=f"times({len(req.times)}) 与 displacement"
                                   f"({len(req.displacement)}) 长度不一致")

    if req.scales:
        unknown = [s for s in req.scales if s not in SCALES]
        if unknown:
            raise HTTPException(status_code=400,
                                detail=f"未知尺度 {unknown}，可选 {list(SCALES)}")

    try:
        result = analyze_multiscale(
            req.times, req.displacement,
            scales=tuple(req.scales) if req.scales else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"趋势分析失败: {e}") from e

    available = [k for k, v in result.items() if v.get("available")]
    unavailable = {k: v.get("reason", "") for k, v in result.items()
                   if not v.get("available")}

    # 跨度与采样间隔从任一字段取（analyze_multiscale 已在各尺度里给出）
    span_days = 0.0
    dt_days = 0.0
    for v in result.values():
        if v.get("samplingIntervalDays"):
            dt_days = float(v["samplingIntervalDays"])
        if v.get("windowDays") and v.get("nWindows"):
            span_days = max(span_days, float(v["windowDays"]) * v["nWindows"])

    data = {
        "spanDays": round(span_days, 1),
        "samplingIntervalDays": dt_days,
        "availableScales": available,
        "unavailableScales": unavailable,
        "scales": result,
    }
    return {"code": 0, "message": "success", "data": data}


# ---------------------------------------------------------------------------
# 形变分析结果读取（读 inference 产出的结果 JSON，供前端热力图 / 大屏消费）
# ---------------------------------------------------------------------------
_RESULT_DIR = Path(__file__).resolve().parents[2] / ".cache" / "nisar" / "result"


@router.get("/api/v1/deformation/results")
def deformation_results():
    """读取已产出的形变分析结果（单轨趋势 + 升降轨联合）。

    扫描 .cache/nisar/result/ 下的 JSON，返回：
      - fusion：升降轨联合结果（含 verticalField / eastWestField 场数组）
      - tracks：各轨道单轨结果（含 velocityField / accelerationField、hotspots、verdict）

    数据由 scripts/analyze_*.py 产出；本接口只读、不算，保证前端秒开。
    """
    import json

    out: dict[str, Any] = {"fusion": None, "tracks": []}

    # 升降轨联合结果
    for f in sorted(_RESULT_DIR.glob("fusion_*.json")):
        try:
            out["fusion"] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

    # 各轨道单轨结果
    for f in sorted(_RESULT_DIR.glob("track*/deformation_result.json")):
        try:
            out["tracks"].append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    return {"code": 0, "message": "success", "data": out}

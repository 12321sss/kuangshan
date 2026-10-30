"""周尺度监测：影像可用性（L1）+ 突变事件检测（L2）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import change as change_mod

router = APIRouter(tags=["monitor"])


# ---------------------------------------------------------------------------
# 周尺度监测：影像可用性（L1）+ 突变事件检测（L2）
# ---------------------------------------------------------------------------


class AvailabilityRequest(BaseModel):
    aoi: list[list[float]]
    days: int = Field(30, description="往前看多少天")
    maxCloud: float = Field(20, description="云量上限 %")


@router.post("/api/v1/monitor/availability")
def monitor_availability(req: AvailabilityRequest):
    """L1：最近 N 天有没有可用影像（没有就说没有，不能报「无变化」）"""
    try:
        data = change_mod.availability({
            "aoi": req.aoi,
            "days": max(3, min(req.days, 365)),
            "maxCloud": max(1, min(req.maxCloud, 100)),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"影像可用性检查失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}


class ChangeRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]]
    d1Start: str
    d1End: str
    d2Start: str
    d2End: str
    maxCloud: float = 20
    minAreaHa: float = Field(0.2, description="斑块最小面积（公顷）")
    maxDim: int = Field(768)
    withImage: bool = Field(True, alias="withImage")


@router.post("/api/v1/monitor/change-events")
def monitor_change_events(req: ChangeRequest):
    """L2：两期指数差值 → 突变斑块（新增水体/裸地、植被恢复、水体消失）"""
    try:
        data = change_mod.detect({
            "aoi": req.aoi,
            "d1Start": req.d1Start,
            "d1End": req.d1End,
            "d2Start": req.d2Start,
            "d2End": req.d2End,
            "maxCloud": req.maxCloud,
            "minAreaHa": max(0.01, req.minAreaHa),
            "maxDim": max(256, min(req.maxDim, 1536)),
            "withImage": req.withImage,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"突变检测失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

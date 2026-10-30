"""边坡单元划分与三区扰动识别。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import slope as slope_mod

router = APIRouter(tags=["slope"])


# ---------------------------------------------------------------------------
# 边坡单元与三区扰动识别（docs/13 阶段一）
# ---------------------------------------------------------------------------


class SlopeRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="分析范围环（矿权或扰动范围）")
    facilities: list[dict] = Field(
        default_factory=list,
        description='[{"classType":"PIT"|"DUMP"|"TAILINGS","features":[GeoJSON Feature...]}]')
    zoom: int = Field(14, description="DEM 级别")
    maxDim: int = Field(512, alias="maxDim", description="栅格最大边长")


@router.post("/api/v1/slope/analyze")
def slope_analyze(req: SlopeRequest):
    """边坡单元识别：划分坡面、算切脚/削坡/堆载三区扰动、给失稳风险分级

    口径：潜在失稳风险筛查，不构成边坡稳定性评价、不给安全系数。
    """
    try:
        data = slope_mod.analyze({
            "aoi": req.aoi,
            "facilities": req.facilities,
            "zoom": max(10, min(req.zoom, 15)),
            "maxDim": max(128, min(req.maxDim, 1024)),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"边坡分析失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

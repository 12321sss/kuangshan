"""空间关系与专项风险（坑内积水、尾矿水面、缓冲区、采坑形态等）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import spatial as spatial_mod

router = APIRouter(tags=["spatial"])


# ---------------------------------------------------------------------------
# 空间关系与专项风险（B6/B7/B8/B9/C4/A3）
# ---------------------------------------------------------------------------


class SpatialRequest(BaseModel):
    model_config = {"populate_by_name": True}

    permit: list[list[float]] = Field(default_factory=list, description="矿权范围环")
    classes: dict[str, list[dict]] = Field(
        default_factory=dict,
        description='按类型分组的 GeoJSON Feature，如 {"WATER":[Feature...],"PIT":[...]}')
    prevWater: list[dict] = Field(default_factory=list, description="上一期水体要素（可选）")
    prevPit: list[dict] = Field(default_factory=list, description="上一期采坑要素（可选）")
    bufferKm: float = Field(2.0, description="生态缓冲区半径（km）")
    slopeCutDeg: float = Field(15.0, description="陡坡阈值（度）")
    zoom: int = Field(14)
    maxDim: int = Field(768)


@router.post("/api/v1/spatial/analyze")
def spatial_analyze(req: SpatialRequest):
    """空间叠加类专项风险：坑内积水、尾矿水面、排土场汇流、道路切坡、缓冲区、采坑形态

    口径：全部为潜在风险筛查，汇流使用相对低洼度代理而非水文算法。
    """
    try:
        data = spatial_mod.analyze({
            "permit": req.permit,
            "classes": req.classes,
            "prevWater": req.prevWater,
            "prevPit": req.prevPit,
            "bufferKm": req.bufferKm,
            "slopeCutDeg": req.slopeCutDeg,
            "zoom": max(10, min(req.zoom, 15)),
            "maxDim": max(256, min(req.maxDim, 1024)),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"空间分析失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

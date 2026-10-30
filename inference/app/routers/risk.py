"""开采安全风险评估（多因子融合）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import risk as risk_mod

router = APIRouter(tags=["risk"])


# ---------------------------------------------------------------------------
# 开采安全风险评估（多因子融合）
# ---------------------------------------------------------------------------


class RiskRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="分析区环 [[lng,lat],...]")
    permitBoundary: list[list[float]] | None = Field(
        None, alias="permitBoundary", description="矿权边界（用于越界检测）")
    classes: list[dict] = Field(default_factory=list,
                                description='[{"classType":"PIT","features":[GeoJSON Feature...]}]')
    trend: dict | None = Field(None, description="扩张速率等时序趋势")
    # 生态维度输入：{mean, levels, sceneId, datetime}，由 /api/v1/ecology/rsei 得到
    # 注意：Pydantic 会丢弃未声明字段，漏写会导致生态维永远按中性分计算
    rsei: dict | None = Field(None, description="RSEI 生态指数统计")
    # 形态维度的单元级输入：/api/v1/slope/analyze 返回的 units
    # 注意：Pydantic 会丢弃未声明字段——这个坑已经踩过两次（report 的 safety、这里的 slopeUnits），
    # 新增入参字段时必须同步在模型里声明
    slopeUnits: list[dict] = Field(default_factory=list, alias="slopeUnits",
                                   description="边坡单元列表（用于形态维度最差聚合）")
    # 形变证据（可选）：{velocityMmyr, accelerationMmyr2, reliable}
    # 由形变时序分析得到，做规则覆盖提级（直接证据，不参与六维 AHP 加权）
    # 注意：Pydantic 会丢弃未声明字段，漏写会导致形变证据静默失效
    deformation: dict | None = Field(None, description="形变证据（速度/加速度/可信度）")
    withGrid: bool = Field(True, alias="withGrid", description="是否生成风险栅格图与热点")
    zoom: int = Field(14, description="DEM 放大级别")


@router.post("/api/v1/risk/evaluate")
def risk_evaluate(req: RiskRequest):
    """开采安全风险评估：五维评分 + 风险分级图 + 热点清单

    口径：潜在安全风险筛查，不是边坡稳定性评价，不给安全系数。
    """
    try:
        data = risk_mod.evaluate({
            "aoi": req.aoi,
            "permitBoundary": req.permitBoundary,
            "classes": req.classes,
            "trend": req.trend,
            "rsei": req.rsei,
            "slopeUnits": req.slopeUnits,
            "deformation": req.deformation,
            "withGrid": req.withGrid,
            "zoom": max(10, min(req.zoom, 15)),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"风险评估失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

"""分类结果 × 指数结果 叠加分析（一致性 + 融合）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import fusion as fusion_mod

router = APIRouter(tags=["fusion"])


# ---------------------------------------------------------------------------
# 分类结果 × 指数结果 叠加分析（融合，docs/18）
# ---------------------------------------------------------------------------


class FusionPair(BaseModel):
    classType: str
    strategy: str = Field("INDICES_FIRST", description="INDICES_FIRST/INTERSECT_ONLY/UNION_ADD")


class FusionRequest(BaseModel):
    classified: dict[str, list[dict]] = Field(default_factory=dict, description="分类结果 {类型:[Feature]}")
    indices: dict[str, list[dict]] = Field(default_factory=dict, description="指数结果 {类型:[Feature]}")
    pairs: list[FusionPair] = Field(default_factory=list)
    options: dict = Field(default_factory=dict)
    withImage: bool = Field(True, alias="withImage")


@router.post("/api/v1/fusion/compare")
def fusion_compare(req: FusionRequest):
    """L2 差异分析：交集/仅分类/仅指数 + IoU + 待核查斑块

    口径：IoU 为方法间一致性，不是精度；不一致区域只能建议核查。
    """
    try:
        data = fusion_mod.compare({
            "classified": req.classified,
            "indices": req.indices,
            "pairs": [p.model_dump() for p in req.pairs],
            "options": req.options or {},
            "withImage": req.withImage,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"叠加分析失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}


@router.post("/api/v1/fusion/merge")
def fusion_merge(req: FusionRequest):
    """L3 融合：按类策略（指数优先/仅一致/指数补充）生成最终结果"""
    try:
        data = fusion_mod.merge({
            "classified": req.classified,
            "indices": req.indices,
            "pairs": [p.model_dump() for p in req.pairs],
            "withImage": req.withImage,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"融合失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

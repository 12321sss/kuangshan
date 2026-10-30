"""监督分类：在线 Sentinel-2（12 维特征）与本地高分影像（7 维特征）。

两条链路分开是因为波段不同：S2 有短波红外（B11/B12），本地 GF 影像只有 4 波段。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import supervised as supervised_mod
from algorithms import supervised_local as local_mod

from ..schemas import SamplePoint

router = APIRouter(tags=["classification"])


# ---------------------------------------------------------------------------
# 监督分类（精细模式）：选样本 → 随机森林 → 混淆矩阵 / OA / Kappa
# ---------------------------------------------------------------------------


class SamplePoint(BaseModel):
    classType: str = Field(..., description="PIT/DUMP/TAILINGS/BARE/ROAD/VEGETATION/WATER")
    lng: float
    lat: float


class ClassifyRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="分析区环（WGS84）")
    samples: list[SamplePoint] = Field(default_factory=list)
    start: str = Field(..., description="影像起始日期 YYYY-MM-DD")
    end: str = Field(..., description="影像结束日期 YYYY-MM-DD")
    maxCloud: float = Field(20, description="云量上限 %")
    maxDim: int = Field(1024, description="栅格最大边长，控制耗时")
    minSamples: int = Field(8, description="每类最少样本数")
    minAreaPx: int = Field(30, description="最小图斑像元数")


@router.post("/api/v1/classify/supervised")
def classify_supervised(req: ClassifyRequest):
    """监督分类：能给出 OA/Kappa/各类 PA·UA，用于回答「准确率多少」

    口径：精度只对本 AOI 与本景有效；10m 分辨率分不出采坑内部台阶。
    """
    try:
        data = supervised_mod.classify({
            "aoi": req.aoi,
            "samples": [s.model_dump() for s in req.samples],
            "start": req.start,
            "end": req.end,
            "maxCloud": req.maxCloud,
            "maxDim": max(256, min(req.maxDim, 2048)),
            "minSamples": max(3, req.minSamples),
            "minAreaPx": max(1, req.minAreaPx),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"监督分类失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}


class ClassifyLocalRequest(BaseModel):
    model_config = {"populate_by_name": True}

    path: str = Field(..., description="本地影像绝对路径")
    aoi: list[list[float]] = Field(default_factory=list, description="为空则用整幅影像")
    samples: list[SamplePoint] = Field(default_factory=list)
    maxDim: int = Field(1600)
    minSamples: int = Field(8)
    minAreaPx: int = Field(30)


@router.post("/api/v1/classify/local")
def classify_local_api(req: ClassifyLocalRequest):
    """本地高分影像监督分类（4 波段：蓝/绿/红/近红外，7 维特征）"""
    try:
        data = local_mod.classify_local({
            "path": req.path,
            "aoi": req.aoi,
            "samples": [s.model_dump() for s in req.samples],
            "maxDim": max(256, min(req.maxDim, 4096)),
            "minSamples": max(3, req.minSamples),
            "minAreaPx": max(1, req.minAreaPx),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"本地影像分类失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

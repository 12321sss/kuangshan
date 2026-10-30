"""系统与数据源：存活探针、七类地物目录、Sentinel-2 场景检索。"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from algorithms import sentinel as aws_sentinel
from algorithms import sentinel_source

from ..config import APP_VERSION, SERVICE_NAME

router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# 场景检索（在线提取的数据源）
# ---------------------------------------------------------------------------
@router.get("/health")
def health():
    return {"status": "UP", "service": SERVICE_NAME,
            "version": APP_VERSION, "time": time.time()}


@router.get("/api/v1/class-types")
def class_types():
    """七类地物中文名（统一对齐实施方案表 6 的分类体系与用词）"""
    return {"code": 0, "message": "success", "data": dict(aws_sentinel.CLASS_LABELS)}


@router.get("/api/v1/scenes")
def scenes(
    lng: float = Query(..., description="AOI 中心经度"),
    lat: float = Query(..., description="AOI 中心纬度"),
    start: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    maxCloud: float = Query(15.0, description="云量上限(%)"),
    limit: int = Query(20, description="最多返回场景数"),
    level: str = Query("MSIL1C", description="处理级别 MSIL1C / MSIL2A"),
):
    """检索 Sentinel-2 场景：在线提取的数据来源"""
    try:
        found = sentinel_source.search(
            lng, lat, start, end,
            max_cloud=maxCloud, limit=limit, level=level,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502,
                            detail=f"Sentinel-2 检索失败: {e}") from e
    return {
        "code": 0,
        "message": "success",
        "data": [
            {
                "productId": s.product_id,
                "name": s.name,
                "date": s.acquisition_date.isoformat(),
                "cloudCover": round(s.cloud_cover, 2),
                "tileId": s.tile_id,
                "platform": s.platform,
                "level": s.processing_level,
                "bounds": list(s.bounds),
                "center": list(s.center),
                "sizeMb": s.size_mb,
                "hasQuicklook": bool(s.quicklook_url),
            }
            for s in found
        ],
    }

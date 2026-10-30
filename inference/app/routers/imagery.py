"""影像元数据自动识别：读 GeoTIFF 自带的 CRS/范围/分辨率/日期。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from algorithms import imagery_probe

router = APIRouter(tags=["imagery"])


# ---------------------------------------------------------------------------
# 影像元数据自动识别（GeoTIFF 自带 CRS/范围/分辨率/日期）
# ---------------------------------------------------------------------------


class ImageryInspectRequest(BaseModel):
    path: str = Field(..., description="服务器本地影像绝对路径")


@router.get("/api/v1/imagery/inspect")
def imagery_inspect_get(path: str = Query(..., description="服务器本地影像绝对路径")):
    """GET 版本：避免 Windows 路径反斜杠在 JSON 里来回转义"""
    return _imagery_inspect_impl(path)


@router.post("/api/v1/imagery/inspect")
def imagery_inspect(req: ImageryInspectRequest):
    """读影像自带的坐标系、范围、分辨率、波段数与日期（文件名兜底）"""
    return _imagery_inspect_impl(req.path)


def _imagery_inspect_impl(path: str):
    try:
        data = imagery_probe.inspect(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"影像识别失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}

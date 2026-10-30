"""边界文件导入：SHP / GeoJSON / KML → 统一 WGS84 AOI 环。"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import aoi_import as aoi_mod

router = APIRouter(tags=["boundary"])


# ---------------------------------------------------------------------------
# 边界文件导入（docs/12 阶段一）：SHP / GeoJSON / KML → 统一 AOI 环
# ---------------------------------------------------------------------------
class AoiFileItem(BaseModel):
    filename: str
    contentBase64: str


class AoiImportRequest(BaseModel):
    # 单文件（旧调用方式，保持兼容）
    filename: str | None = Field(None, description="原始文件名，用于判断格式")
    contentBase64: str | None = Field(None, description="文件二进制内容的 base64")
    # 多文件（shp/shx/dbf/prj 分开选中的场景）
    files: list[AoiFileItem] = Field(default_factory=list, description="多个文件一起提交")
    sourceCrs: str | None = Field(None, description="用户手选的坐标系，如 EPSG:4547")


@router.post("/api/v1/aoi/import")
def aoi_import(req: AoiImportRequest):
    """解析客户给的边界文件，输出 WGS84 经纬度环 + 面积 + 坐标系说明

    - 支持 zip 整套、单文件、以及 shp/shx/dbf/prj 多文件分开提交
    - sourceCrs 用于兜底：CAD 导出的 .shp 常没有 .prj，此时只能由用户指定坐标系

    注意：转换失败的坐标系一律报错，不做兜底猜测——偏几百米的边界比报错危险得多。
    """
    pairs: list[tuple[str, bytes]] = []
    candidates = list(req.files)
    if not candidates and req.filename and req.contentBase64:
        candidates = [AoiFileItem(filename=req.filename, contentBase64=req.contentBase64)]
    if not candidates:
        raise HTTPException(status_code=400, detail="没有收到文件内容")

    total = 0
    for it in candidates:
        try:
            raw = base64.b64decode(it.contentBase64)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400,
                                detail=f"文件 {it.filename} 不是合法 base64: {e}") from e
        total += len(raw)
        if total > 60 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件合计超过 60MB，请先裁剪或简化边界")
        pairs.append((it.filename, raw))

    try:
        data = aoi_mod.import_boundary_files(
            [{"filename": n, "content": c} for n, c in pairs], req.sourceCrs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"边界解析失败: {e}") from e

    return {"code": 0, "message": "success", "data": data}

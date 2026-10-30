"""上传影像解译：本地文件 → 指数阈值法 → 回调 Java 落库。

链路：Java 调 /inference/submit 拿 taskId → 本服务后台线程算 → 回调 Java。
查进度走 /inference/{task_id}/status（前端轮询）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms.classify import CLASS_LABELS, classify

from ..geo import aoi_area_ha, aoi_bounds
from ..logging_setup import get_logger
from ..schemas import SubmitResponse
from ..tasks import get_task, post_callback, submit_task, update_task

router = APIRouter(tags=["extraction"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 解译任务
# ---------------------------------------------------------------------------
class SubmitRequest(BaseModel):
    imagePath: str = Field(..., description="影像在磁盘上的路径")
    satellite: str = Field(..., description="SENTINEL2 / LANDSAT9 / GF2")
    classType: str = Field(..., description="七类地物之一")
    algoType: str = Field("INDEX", description="当前仅 INDEX（指数法）")
    aoi: list[list[float]] | None = Field(None, description="AOI 环 [[lng,lat],...]")
    thresholds: dict[str, float] | None = None
    callbackUrl: str = Field(..., description="任务完成后回调的 Java 接口")
    # 上下文透传：计算完成后原样带回Java，否则回调落库时 projectId/imageryId 为 0
    projectId: int | None = None
    imageryId: int | None = None
    name: str | None = None
    # 拍摄日期（YYYY-MM-DD）：Java 下发后需原样带回，否则落库为 NULL，
    # 时序播放按日期排序会全部退化
    acquisitionDate: str | None = None


def _run_task(task_id: str, req: dict[str, Any]) -> None:
    """后台线程执行真实解译并回调 Java"""
    try:
        update_task(task_id, "RUNNING", 10)

        result = classify(
            path=req["imagePath"],
            satellite=req["satellite"],
            class_type=req["classType"],
            aoi_bounds=req["aoiBounds"],
            thresholds=req.get("thresholds"),
        )

        payload = {
            "taskId": task_id,
            "status": "SUCCESS" if result.polygons else "EMPTY",
            "classType": result.class_type,
            "label": result.label,
            "polygons": result.polygons,
            "pixelCount": result.pixel_count,
            "extractAreaHa": result.extract_area_ha,
            "aoiAreaHa": req["aoiAreaHa"],
            "stats": result.stats,
            # 上下文回传，Java 侧据此落库到正确项目
            "projectId": req.get("projectId"),
            "imageryId": req.get("imageryId"),
            "name": req.get("name"),
            "satellite": req.get("satellite"),
            "acquisitionDate": req.get("acquisitionDate"),
            # AOI 回传：Java 侧据此计算指纹，识别同一区域的不同期结果
            "aoi": req.get("aoi"),
            "error": None,
        }

        # 回调 Java（失败不影响本地结果留存，便于排查）
        err = post_callback(req["callbackUrl"], payload)
        if err:
            payload["callbackError"] = err

        update_task(task_id, payload["status"], 100, result=payload)

    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        log.exception("解译任务异常")
        update_task(task_id, "FAILED", 100, error=detail)
        post_callback(req["callbackUrl"], {
            "taskId": task_id, "status": "FAILED", "error": detail,
        })


@router.post("/api/v1/inference/submit", response_model=SubmitResponse)
def submit(req: SubmitRequest):
    """提交解译任务：立即返回 taskId，实际计算在后台线程执行"""
    if req.classType not in CLASS_LABELS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的地物类别: {req.classType}")
    if req.satellite.upper() not in ("SENTINEL2", "LANDSAT9", "GF2", "GF7", "UPLOAD"):
        raise HTTPException(status_code=400,
                            detail=f"不支持的数据源: {req.satellite}")

    payload = {
        "imagePath": req.imagePath,
        "satellite": req.satellite,
        "classType": req.classType,
        "aoiBounds": aoi_bounds(req.aoi),
        "aoiAreaHa": aoi_area_ha(req.aoi),
        "thresholds": req.thresholds,
        "callbackUrl": req.callbackUrl,
        "aoi": req.aoi,
        "projectId": req.projectId,
        "imageryId": req.imageryId,
        "name": req.name,
        "acquisitionDate": req.acquisitionDate,
    }
    task_id = submit_task(_run_task, payload)
    return SubmitResponse(taskId=task_id, status="PENDING")


@router.get("/api/v1/inference/{task_id}/status")
def status(task_id: str):
    snapshot = get_task(task_id)
    if snapshot is None:
        return {"code": 404, "message": f"任务不存在: {task_id}", "data": None}
    return {
        "code": 0,
        "message": "success",
        "data": {
            "taskId": task_id,
            "status": snapshot.get("status"),
            "progress": snapshot.get("progress"),
            "extractAreaHa": snapshot.get("extractAreaHa"),
            "error": snapshot.get("error"),
        },
    }

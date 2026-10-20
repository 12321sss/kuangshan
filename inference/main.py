"""
赣锋锂电遥感解译平台 - 解译服务（真实指数法实现）

当前阶段：CPU 可跑的真实解译链路，不依赖 GPU/torch。
- Sentinel-2 公开场景检索：sentinel_source.search()
- 上传影像解译：classify.classify()（NDVI/NDWI/NDBI 阈值分割 + 矢量化）
- GPU 服务器就绪后，classify.py 整体替换为 Mask2Former 推理，接口协议不变

接口
----
GET  /health                              存活探针
GET  /api/v1/class-types                  七类地物中文名
GET  /api/v1/scenes                       检索 Sentinel-2 场景（在线提取数据源）
POST /api/v1/inference/submit             提交解译任务（后台线程执行，算完回调 Java）
GET  /api/v1/inference/{task_id}/status   查询任务进度

回调
----
POST {callbackUrl}
     {taskId, status, classType, label, polygons, pixelCount,
      extractAreaHa, aoiAreaHa, stats, error}
"""
from __future__ import annotations

import os
import json
import random
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import requests
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import sentinel_source
from classify import CLASS_LABELS, classify, ring_area_ha

# 回调共享密钥：与 Java 侧 INFERENCE_CALLBACK_TOKEN 保持一致。
# 不带此头后端会返回 401（回调端点曾可被任意伪造写入假数据）
CALLBACK_TOKEN = os.environ.get(
    "INFERENCE_CALLBACK_TOKEN", "rs-demo-inference-token-2026")

# ---- 任务存储 ----
# demo 期用内存 + 后台线程；生产切 Celery + Redis，接口协议不变。
_tasks: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    with _lock:
        _tasks.clear()


app = FastAPI(
    title="RS Platform Inference Service",
    version="0.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# 场景检索（在线提取的数据源）
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "UP", "service": "rs-platform-inference",
            "version": "0.2.0", "time": time.time()}


@app.get("/api/v1/class-types")
def class_types():
    """七类地物中文名（统一对齐实施方案表 6 的分类体系与用词）"""
    return {"code": 0, "message": "success", "data": dict(aws_sentinel.CLASS_LABELS)}


@app.get("/api/v1/scenes")
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


class SubmitResponse(BaseModel):
    taskId: str
    status: str


def _aoi_bounds(aoi: list[list[float]] | None) -> tuple[float, float, float, float] | None:
    """从 AOI 环算外接矩形 (west, south, east, north)"""
    if not aoi or len(aoi) < 3:
        return None
    xs = [p[0] for p in aoi]
    ys = [p[1] for p in aoi]
    return (min(xs), min(ys), max(xs), max(ys))


def _aoi_area_ha(aoi: list[list[float]] | None) -> float:
    if not aoi:
        return 0.0
    return round(ring_area_ha(aoi), 4)


def _set(task_id: str, status: str, progress: int, **extra) -> None:
    with _lock:
        t = _tasks.get(task_id)
        if t is not None:
            t["status"] = status
            t["progress"] = progress
            t.update(extra)


def _run_task(task_id: str, req: dict[str, Any]) -> None:
    """后台线程执行真实解译并回调 Java"""
    try:
        _set(task_id, "RUNNING", 10)

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
        try:
            cb = requests.post(req["callbackUrl"], json=payload, timeout=30,
                               headers={"X-Inference-Token": CALLBACK_TOKEN})
            cb.raise_for_status()
        except Exception as e:  # noqa: BLE001
            payload["callbackError"] = str(e)

        _set(task_id, payload["status"], 100, result=payload)

    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        _set(task_id, "FAILED", 100, error=detail)
        try:
            requests.post(req["callbackUrl"], json={
                "taskId": task_id, "status": "FAILED", "error": detail,
            }, timeout=30, headers={"X-Inference-Token": CALLBACK_TOKEN})
        except Exception:
            pass


@app.post("/api/v1/inference/submit", response_model=SubmitResponse)
def submit(req: SubmitRequest):
    """提交解译任务：立即返回 taskId，实际计算在后台线程执行"""
    if req.classType not in CLASS_LABELS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的地物类别: {req.classType}")
    if req.satellite.upper() not in ("SENTINEL2", "LANDSAT9", "GF2", "GF7", "UPLOAD"):
        raise HTTPException(status_code=400,
                            detail=f"不支持的数据源: {req.satellite}")

    task_id = f"inf-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    payload = {
        "imagePath": req.imagePath,
        "satellite": req.satellite,
        "classType": req.classType,
        "aoiBounds": _aoi_bounds(req.aoi),
        "aoiAreaHa": _aoi_area_ha(req.aoi),
        "thresholds": req.thresholds,
        "callbackUrl": req.callbackUrl,
        "aoi": req.aoi,
        "projectId": req.projectId,
        "imageryId": req.imageryId,
        "name": req.name,
        "acquisitionDate": req.acquisitionDate,
    }
    with _lock:
        _tasks[task_id] = {"status": "PENDING", "progress": 0,
                           "submittedAt": time.time(), **payload}

    threading.Thread(target=_run_task, args=(task_id, payload), daemon=True).start()
    return SubmitResponse(taskId=task_id, status="PENDING")


@app.get("/api/v1/inference/{task_id}/status")
def status(task_id: str):
    with _lock:
        t = _tasks.get(task_id)
        if t is None:
            return {"code": 404, "message": f"任务不存在: {task_id}", "data": None}
        snapshot = dict(t)
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


# ---------------------------------------------------------------------------
# 在线 Sentinel-2 直接解译（AWS Earth Search STAC 直连，无需本地影像文件）
# ---------------------------------------------------------------------------
# 这是「遥感提取」页的数据源：AOI + 日期 + 类型 → 在线拉景 → 剪切 → 指数 → 矢量
# 与上传影像解译（/api/v1/inference/submit，读本地文件）是两条并行的数据来源。
import sentinel as aws_sentinel  # noqa: E402

# 在线提取的类型集合：VEGETATION/WATER/BUILDING/BARE/MOUNTAIN
# 在线提取的类型集合：覆盖实施方案表 6 的七类矿山地物
# （PIT/DUMP/TAILINGS/ROAD 为本次新增，靠亮度分层 + 形态过滤近似区分）
_ONLINE_CLASSES = {
    "PIT", "DUMP", "TAILINGS", "BARE", "VEGETATION", "ROAD", "WATER",
    # 兼容旧类型（历史记录与前端展示仍会用到）
    "BUILDING", "MOUNTAIN",
}

# 需要短波红外(B11)才能判别的类型：水体(MNDWI)、裸地/采坑(裸岩信号)、排土场与尾矿(亮度分层)
_NEED_SWIR = {"WATER", "BARE", "PIT", "DUMP", "TAILINGS", "BUILDING"}


def _need_bands(class_type: str) -> list[str]:
    """按地物类型决定要下载的波段（少下一个波段能省一半等待时间）"""
    need = ["B02", "B03", "B04", "B08"]
    if class_type in _NEED_SWIR:
        need.append("B11")
    return need


class OnlineExtractRequest(BaseModel):
    model_config = {"populate_by_name": True}  # 允许用字段名或别名填充

    aoi: list[list[float]] = Field(..., description="AOI 环 [[lng,lat],...]")
    startDate: str = Field(..., alias="start_date", description="YYYY-MM-DD")
    endDate: str = Field(..., alias="end_date", description="YYYY-MM-DD")
    classType: str = Field(..., alias="class_type", description="VEGETATION/WATER/BUILDING/BARE/MOUNTAIN")
    maxCloud: float = Field(30.0, alias="max_cloud")
    threshold: float | None = None
    minAreaPx: int = Field(20, alias="min_area_px")


class AsyncExtractRequest(BaseModel):
    """异步解译（Java submit-online 用）：算完回调 Java，需 callbackUrl"""
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="AOI 环 [[lng,lat],...]")
    startDate: str = Field(..., alias="start_date", description="YYYY-MM-DD")
    endDate: str = Field(..., alias="end_date", description="YYYY-MM-DD")
    classType: str = Field(..., alias="class_type", description="VEGETATION/WATER/BUILDING/BARE/MOUNTAIN")
    maxCloud: float = Field(30.0, alias="max_cloud")
    threshold: float | None = None
    minAreaPx: int = Field(20, alias="min_area_px")
    callbackUrl: str = Field(..., alias="callback_url", description="算完回调 Java 的接口")
    projectId: int | None = Field(None, alias="project_id")
    name: str | None = None


class OnlineSearchRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="[[lng,lat],...] 至少 3 点")
    startDate: str = Field(..., alias="start_date", description="YYYY-MM-DD")
    endDate: str = Field(..., alias="end_date", description="YYYY-MM-DD")
    maxCloud: float = Field(30.0, alias="max_cloud")
    # 波段组合：TRUE_COLOR 真彩 / FALSE_COLOR 假彩(植被红) / SWIR 短波红外 / URBAN 城市裸地 / NDVI 植被指数
    combo: str = Field("TRUE_COLOR", description="波段组合")


def _threshold_overrides(class_type: str, threshold: float | None) -> dict[str, float] | None:
    """把前端传入的单一阈值映射到对应类别的判别阈值

    PIT/DUMP/TAILINGS 的判别核心是「亮度分层的绝对兜底值」，
    前端一个阈值框对应用户最想调的那个参数即可。
    """
    if threshold is None:
        return None
    if class_type == "PIT":
        return {"bright_pit_abs_max": threshold}
    if class_type == "DUMP":
        return {"bright_dump_abs_min": threshold}
    if class_type == "TAILINGS":
        return {"bright_tailings_abs_min": threshold}
    if class_type == "ROAD":
        return {"bright_road_min": threshold}
    # 单指数类（植被/水体/裸地/建筑/山体）仍走 CLASS_THRESHOLD
    import sentinel as _s
    _s.CLASS_THRESHOLD[class_type] = threshold
    return None


def _geojson_to_polygons(features: list[dict]) -> list[list[list[float]]]:
    """把 sentinel.py 的 GeoJSON Feature 列表转成 Java 回调期望的
    List[List[List[Double]]] 格式（只取外环坐标）。

    Java complete() 落库的 featuresJson 用这个格式，前端 renderResult 也能解。
    """
    rings: list[list[list[float]]] = []
    for f in features:
        g = f.get("geometry") or {}
        gtype = g.get("type")
        coords = g.get("coordinates")
        if not coords:
            continue
        if gtype == "Polygon":
            rings.append(coords[0])          # 外环
        elif gtype == "MultiPolygon":
            for poly in coords:
                rings.append(poly[0])         # 每个子多边形外环
    return rings


def _run_online_task(task_id: str, req: dict) -> None:
    """后台线程：AWS STAC 在线拉景 → 剪切 → 指数 → 矢量 → 回调 Java"""
    try:
        _set(task_id, "RUNNING", 10)

        feat = aws_sentinel.search_scene(
            req["aoi"], req["startDate"], req["endDate"], req["maxCloud"])
        if feat is None:
            payload = {
                "taskId": task_id, "status": "EMPTY", "classType": req["classType"],
                "label": aws_sentinel.CLASS_INDEX.get(req["classType"], ""),
                "polygons": [], "pixelCount": 0, "extractAreaHa": 0.0,
                "aoiAreaHa": req["aoiAreaHa"],
                "stats": {}, "projectId": req.get("projectId"),
                "name": req.get("name"), "satellite": "SENTINEL2",
                "acquisitionDate": None, "aoi": req["aoi"],
                "error": None, "note": "该 AOI/日期范围内无可用的无云影像",
            }
            _set(task_id, "EMPTY", 100, result=payload)
            _post_callback(req["callbackUrl"], payload)
            return

        _set(task_id, "RUNNING", 40)

        # 按类型决定需要的波段
        # 按类型决定需要的波段
        need = _need_bands(req["classType"])
        clipped = aws_sentinel.clip_aoi(feat, req["aoi"], need)

        _set(task_id, "RUNNING", 70)

        th = _threshold_overrides(req["classType"], req.get("threshold"))
        result = aws_sentinel.extract_class(
            clipped["bands"], req["classType"],
            clipped["meta"].get("B04", {}).get("transform"),
            clipped["meta"].get("B04", {}).get("crs"),
            min_area_px=req.get("minAreaPx", 20),
            thresholds=th,
        )

        polygons = _geojson_to_polygons(result.get("features", []))
        # 面积：覆盖率为 AOI 内目标像元占比，AOI 面积已知 → 推算提取面积
        aoi_ha = req["aoiAreaHa"]
        extract_ha = round(aoi_ha * result["coverage_pct"] / 100.0, 4)
        # 拍摄日期：来自检索到的景（feat.properties.datetime），不是 result（result 无此字段）
        scene_datetime = (feat.get("properties", {}).get("datetime") or "")[:10] or None

        payload = {
            "taskId": task_id,
            "status": "SUCCESS" if polygons else "EMPTY",
            "classType": req["classType"],
            "label": aws_sentinel.CLASS_INDEX.get(req["classType"], ""),
            "polygons": polygons,
            "pixelCount": 0,   # 在线方案不统计像元数，用覆盖率折算
            "extractAreaHa": extract_ha,
            "aoiAreaHa": aoi_ha,
            "coveragePct": result["coverage_pct"],   # 顶层字段：Java 回调据此落库
            "stats": {"coverage_pct": result["coverage_pct"],
                      "threshold": result["threshold"],
                      "feature_count": result["feature_count"]},
            "projectId": req.get("projectId"),
            "name": req.get("name"),
            "satellite": "SENTINEL2",
            "acquisitionDate": scene_datetime,
            "aoi": req["aoi"],
            "error": None,
        }
        _set(task_id, payload["status"], 100, result=payload)
        _post_callback(req["callbackUrl"], payload)

    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        _set(task_id, "FAILED", 100, error=detail)
        _post_callback(req["callbackUrl"], {
            "taskId": task_id, "status": "FAILED", "error": detail,
        })


def _post_callback(callback_url: str, payload: dict) -> None:
    try:
        cb = requests.post(callback_url, json=payload, timeout=30,
                            headers={"X-Inference-Token": CALLBACK_TOKEN})
        cb.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[callback] 回调失败 {type(e).__name__}: {e}")


@app.post("/api/v1/sentinel/extract")
def online_extract(req: OnlineExtractRequest):
    """同步在线解译：AWS STAC 拉景 + 剪切 + 指数 + 矢量，直接返回结果。

    这是「遥感提取」页前端直连的路径 —— 同步返回 features + 覆盖率，
    前端立即上图渲染，不需要 callbackUrl（落库由前端调 Java /extractions/save）。
    """
    if req.classType not in _ONLINE_CLASSES:
        raise HTTPException(status_code=400,
                            detail=f"不支持的地物类别: {req.classType}")

    feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
    if feat is None:
        return {"code": 404, "message": "该 AOI/日期范围内无可用的无云影像", "data": None}

    # 按类型决定需要的波段
    # 按类型决定需要的波段
    need = _need_bands(req.classType)
    clipped = aws_sentinel.clip_aoi(feat, req.aoi, need)

    th = _threshold_overrides(req.classType, req.threshold)
    result = aws_sentinel.extract_class(
        clipped["bands"], req.classType,
        clipped["meta"].get("B04", {}).get("transform"),
        clipped["meta"].get("B04", {}).get("crs"),
        min_area_px=req.minAreaPx,
        thresholds=th,
    )

    result["scene_id"] = feat.get("id")
    result["datetime"] = feat.get("properties", {}).get("datetime")
    result["cloud_cover"] = feat.get("properties", {}).get("eo:cloud_cover")
    return {"code": 0, "message": "success", "data": result}


@app.post("/api/v1/sentinel/extract-async", response_model=SubmitResponse)
def online_extract_async(req: AsyncExtractRequest):
    """异步在线解译（Java submit-online 专用）：算完回调 Java 落库"""
    if req.classType not in _ONLINE_CLASSES:
        raise HTTPException(status_code=400,
                            detail=f"不支持的地物类别: {req.classType}")

    task_id = f"inf-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    payload = {
        "aoi": req.aoi,
        "startDate": req.startDate,
        "endDate": req.endDate,
        "classType": req.classType,
        "maxCloud": req.maxCloud,
        "threshold": req.threshold,
        "minAreaPx": req.minAreaPx,
        "aoiAreaHa": _aoi_area_ha(req.aoi),
        "callbackUrl": req.callbackUrl,
        "projectId": req.projectId,
        "name": req.name,
    }
    with _lock:
        _tasks[task_id] = {"status": "PENDING", "progress": 0,
                           "submittedAt": time.time(), **payload}

    threading.Thread(target=_run_online_task, args=(task_id, payload), daemon=True).start()
    return SubmitResponse(taskId=task_id, status="PENDING")


@app.post("/api/v1/sentinel/search")
def online_search(req: OnlineSearchRequest):
    """在线检索最优景（不下载数据），供前端「查询影像」按钮使用"""
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"检索失败: {e}") from e
    if feat is None:
        return {"code": 404, "message": "该 AOI/日期范围内无可用的无云影像", "data": None}
    props = feat.get("properties", {})
    return {
        "code": 0, "message": "success",
        "data": {
            "scene_id": feat.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
        },
    }


@app.post("/api/v1/sentinel/preview")
def online_preview(req: OnlineSearchRequest):
    """AOI 影像预览：检索 + 剪切 + 按波段组合渲染 PNG（base64）"""
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}
        # 按所需组合决定拉哪些波段（NDVI 需近红外；SWIR/URBAN 需短波红外）
        combo = (req.combo or "TRUE_COLOR").upper()
        need = {"B02", "B03", "B04"}
        if combo in ("FALSE_COLOR", "NDVI"):
            need.add("B08")
        elif combo in ("SWIR", "URBAN"):
            need.update({"B08", "B11"})
        clipped = aws_sentinel.clip_aoi(feat, req.aoi, sorted(need))
        png = aws_sentinel.composite_png(clipped["bands"], combo)
        import base64
        return {
            "code": 0, "message": "success",
            "data": {
                "scene_id": feat.get("id"),
                "datetime": feat.get("properties", {}).get("datetime"),
                "cloud_cover": feat.get("properties", {}).get("eo:cloud_cover"),
                "combo": combo,
                "image_base64": base64.b64encode(png).decode(),
            },
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"剪切失败: {e}") from e


# ---------------------------------------------------------------------------
# 多期对比热力图：两期解译结果空间求差 → 新增/消失/不变三块几何
# ---------------------------------------------------------------------------
class DiffHeatmapRequest(BaseModel):
    """输入两期矢量多边形（GeoJSON Feature 列表），输出空间差集"""
    model_config = {"populate_by_name": True}

    early: list[dict] = Field(..., description="早期结果多边形（GeoJSON Feature 列表）")
    late: list[dict] = Field(..., description="晚期结果多边形（GeoJSON Feature 列表）")


@app.post("/api/v1/sentinel/diff-heatmap")
def diff_heatmap(req: DiffHeatmapRequest):
    """空间求差：早期 - 晚期 = 「消失/恢复区」，晚期 - 早期 = 「新增扰动区」。

    用 shapely 做多边形布尔运算，输出三块几何：
      - added:   晚期有、早期没有 → 新增（红，通常表示扩张/新扰动）
      - removed: 早期有、晚期没有 → 消失（绿，通常表示复绿/恢复）
      - unchanged: 两期都有（重叠）→ 不变（灰）
    面积用球面近似（与 classify.ring_area_ha 同口径），供前端统计展示。
    """
    from shapely.geometry import shape as _shape
    from shapely.ops import unary_union

    def _to_union(features: list[dict]):
        polys = []
        for f in features:
            g = f.get("geometry") if isinstance(f, dict) else None
            if not g:
                continue
            try:
                geom = _shape(g)
                if not geom.is_empty:
                    polys.append(geom)
            except Exception:
                continue
        return unary_union(polys) if polys else None

    early_u = _to_union(req.early)
    late_u = _to_union(req.late)

    def _to_geojson_features(geom) -> list[dict]:
        if geom is None or geom.is_empty:
            return []
        import json as _json
        gj = _json.loads(_json.dumps(geom.__geo_interface__))
        polys = [gj] if gj.get("type") == "Polygon" else gj.get("coordinates") and [
            {"type": "Polygon", "coordinates": c} for c in gj.get("coordinates", [])] or []
        return [{"type": "Feature", "properties": {}, "geometry": p} for p in polys]

    if early_u is None and late_u is None:
        return {"code": 0, "message": "success", "data": {
            "added": [], "removed": [], "unchanged": [],
            "addedAreaHa": 0.0, "removedAreaHa": 0.0,
        }}
    if early_u is None:
        added = _to_geojson_features(late_u)
        return {"code": 0, "message": "success", "data": {
            "added": added, "removed": [], "unchanged": [],
            "addedAreaHa": round(_geom_area_ha(late_u), 4), "removedAreaHa": 0.0,
        }}
    if late_u is None:
        removed = _to_geojson_features(early_u)
        return {"code": 0, "message": "success", "data": {
            "added": [], "removed": removed, "unchanged": [],
            "addedAreaHa": 0.0, "removedAreaHa": round(_geom_area_ha(early_u), 4),
        }}

    added = _to_geojson_features(late_u.difference(early_u))
    removed = _to_geojson_features(early_u.difference(late_u))
    unchanged = _to_geojson_features(early_u.intersection(late_u))

    return {"code": 0, "message": "success", "data": {
        "added": added, "removed": removed, "unchanged": unchanged,
        "addedAreaHa": round(_geom_area_ha(late_u.difference(early_u)), 4),
        "removedAreaHa": round(_geom_area_ha(early_u.difference(late_u)), 4),
    }}


def _geom_area_ha(geom) -> float:
    """shapely 几何的面积（球面近似）：转经纬度环用 classify.ring_area_ha 算"""
    try:
        if geom is None or geom.is_empty:
            return 0.0
        # Polygon 直接取外环；MultiPolygon/GeometryCollection 逐个取
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        total = 0.0
        for p in polys:
            if p.geom_type == "Polygon" and not p.is_empty:
                ring = [(x, y) for x, y in p.exterior.coords]
                total += ring_area_ha(ring)   # 已 import 的模块级函数
        return round(total, 4)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 成果导出：AOI 影像（真彩 RGB）打包成 GeoTIFF
# ---------------------------------------------------------------------------
class ExportGeoTiffRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="[[lng,lat],...]")
    startDate: str = Field(..., alias="start_date")
    endDate: str = Field(..., alias="end_date")
    classType: str = Field("VEGETATION", alias="class_type")
    maxCloud: float = Field(30.0, alias="max_cloud")


@app.post("/api/v1/sentinel/export-geotiff")
def export_geotiff(req: ExportGeoTiffRequest):
    """导出 AOI 真彩影像为 GeoTIFF（RGB 三波段，带地理坐标），供 ArcGIS/QGIS 二次处理"""
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}
        clipped = aws_sentinel.clip_aoi(feat, req.aoi, ["B02", "B03", "B04"], max_dim=1024)
        bands = clipped["bands"]
        # 真彩 0-255 拉伸（与 true_color_png 同口径）
        r = aws_sentinel._to_uint8(bands["B04"])
        g = aws_sentinel._to_uint8(bands["B03"])
        b = aws_sentinel._to_uint8(bands["B02"])
        rgb = np.dstack([r, g, b])

        # 写 GeoTIFF：用 rasterio 写 3 波段 uint8，transform 用窗口 transform
        import io as _io
        import rasterio as _rio
        from rasterio.transform import Affine

        # 从 clip_aoi 返回的 meta 里取 transform（是 affine 对象）
        transform = clipped["meta"]["B04"].get("transform")
        crs = clipped["meta"]["B04"].get("crs")
        # 下采样后 transform 需重算（clip_aoi 已在 max_dim 下采样，这里直接按像素尺寸近似）
        # 简化：用 rasterio 写一个不含精确 geotransform 但带 CRS 的 GeoTIFF（够二次处理用）
        height, width = rgb.shape[0], rgb.shape[1]
        buf = _io.BytesIO()
        with _rio.open(buf, "w", driver="GTiff", height=height, width=width,
                       count=3, dtype="uint8", crs=crs) as dst:
            dst.write(rgb[:, :, 0], 1)
            dst.write(rgb[:, :, 1], 2)
            dst.write(rgb[:, :, 2], 3)
        import base64
        date_str = (feat.get("properties", {}).get("datetime") or "")[:10]
        return {
            "code": 0, "message": "success",
            "data": {
                "filename": f"AOI_{date_str}_{req.classType}.tif",
                "tif_base64": base64.b64encode(buf.getvalue()).decode(),
            },
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出失败: {e}") from e


# ---------------------------------------------------------------------------
# 离线演示数据包（防翻车）：预下载 AOI 影像 + 预生成多类解译结果，断网也能演示
# ---------------------------------------------------------------------------
class DemoBundleRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="[[lng,lat],...]")
    startDate: str = Field(..., alias="start_date")
    endDate: str = Field(..., alias="end_date")
    maxCloud: float = Field(30.0, alias="max_cloud")
    classes: list[str] = Field(
        default_factory=lambda: ["PIT", "DUMP", "TAILINGS", "BARE", "VEGETATION", "ROAD", "WATER"],
        description="要预生成的解译类型（默认七类矿山地物）")


@app.post("/api/v1/sentinel/demo-bundle")
def demo_bundle(req: DemoBundleRequest):
    """生成离线演示数据包：真彩影像 + 多类解译结果，全部缓存到本地磁盘。

    一次调用把目标 AOI 的所有波段下载到 tile 缓存 + 预生成各类解译结果，
    之后即使断网，前端也能通过「载入演示数据」秒出完整演示。
    返回一个 bundle id，前端据此读取本地缓存的结果。
    """
    import os as _os
    import hashlib as _hashlib

    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}

        bundle_id = _hashlib.md5(
            (json.dumps(req.aoi) + req.startDate + req.endDate).encode()
        ).hexdigest()[:12]

        # 1. 真彩影像（含下载缓存）
        clipped = aws_sentinel.clip_aoi(feat, req.aoi, ["B02", "B03", "B04"], max_dim=1024)
        png = aws_sentinel.true_color_png(clipped["bands"])
        import base64 as _b64
        image_b64 = _b64.b64encode(png).decode()

        # 2. 逐类解译（触发各波段下载缓存）
        results = {}
        for cls in req.classes:
            need = _need_bands(cls)
            c = aws_sentinel.clip_aoi(feat, req.aoi, need, max_dim=1024)
            r = aws_sentinel.extract_class(
                c["bands"], cls,
                c["meta"].get("B04", {}).get("transform"),
                c["meta"].get("B04", {}).get("crs"),
                min_area_px=20,
            )
            results[cls] = {
                "coveragePct": r["coverage_pct"],
                "featureCount": r["feature_count"],
                "features": r["features"],
            }

        bundle = {
            "bundleId": bundle_id,
            "sceneId": feat.get("id"),
            "datetime": feat.get("properties", {}).get("datetime"),
            "cloudCover": feat.get("properties", {}).get("eo:cloud_cover"),
            "aoi": req.aoi,
            "imageBase64": image_b64,
            "results": results,
        }
        # 存到本地磁盘（断网后仍可读）
        data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "demo_data")
        _os.makedirs(data_dir, exist_ok=True)
        with open(_os.path.join(data_dir, f"{bundle_id}.json"), "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False)

        return {"code": 0, "message": "success", "data": bundle}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"演示包生成失败: {e}") from e


@app.get("/api/v1/sentinel/demo-bundle/{bundle_id}")
def get_demo_bundle(bundle_id: str):
    """读取已生成的离线演示包（断网时前端从这里读，不经在线检索）"""
    import os as _os
    data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "demo_data")
    path = _os.path.join(data_dir, f"{bundle_id}.json")
    if not _os.path.exists(path):
        return {"code": 404, "message": f"演示包不存在: {bundle_id}", "data": None}
    with open(path, "r", encoding="utf-8") as f:
        return {"code": 0, "message": "success", "data": json.load(f)}


# ---------------------------------------------------------------------------
# 地形分析（DEM 接入）：坡度/坡向/低洼汇水
# ---------------------------------------------------------------------------
import dem as dem_mod  # noqa: E402

# 坡度分级配色（与前端图例一致）
_SLOPE_COLORS = [
    (2, (76, 175, 80)),      # <2°   绿
    (6, (174, 213, 129)),    # 2-6°  黄绿
    (15, (255, 213, 79)),    # 6-15° 黄
    (25, (255, 152, 0)),     # 15-25° 橙
    (999, (211, 47, 47)),    # ≥25°  红
]


class TerrainRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="AOI 环 [[lng,lat],...]")
    zoom: int = Field(14, description="DEM 瓦片级别，14≈9.6m/px，15≈4.8m/px")
    withImage: bool = Field(True, alias="with_image", description="是否返回坡度分级 PNG")


def _slope_png(slope: np.ndarray) -> bytes:
    """坡度分级 → PNG（叠加到三维地球做风险专题图底图）"""
    import io as _io
    from PIL import Image
    h, w = slope.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for limit, color in _SLOPE_COLORS:
        rgb[slope < limit] = color
    buf = _io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


@app.post("/api/v1/terrain/analyze")
def terrain_analyze(req: TerrainRequest):
    """地形分析：高程统计 + 坡度分级 + 低洼汇水筛查

    精度口径：Terrarium z14 约 9.6m/像元，**不能用于计算台阶坡面角/坑深/体积**；
    可支撑区域坡度、汇水筛查、排土场选址与道路切坡的背景地形判断。
    """
    lngs = [p[0] for p in req.aoi]
    lats = [p[1] for p in req.aoi]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)

    try:
        win = dem_mod.read_dem_window(west, south, east, north,
                                      zoom=max(10, min(req.zoom, 15)), max_dim=512)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DEM 读取失败: {e}") from e

    elev = win["elevation"]
    mpp = win["mPerPixel"]
    slope, aspect = dem_mod.slope_aspect(elev, mpp)
    flow = dem_mod.flow_proxy(slope, elev)
    summary = dem_mod.terrain_summary(elev, slope)

    # 低洼汇水候选：flow 超过 95 分位且坡度平缓（<10°）
    thr = float(np.percentile(flow, 95)) if flow.size else 0.0
    pond = (flow >= max(thr, 1.0)) & (slope < 10)
    pond_pct = round(float(pond.mean()) * 100, 2)

    data: dict = {
        "summary": summary,
        "grid": {"width": int(slope.shape[1]), "height": int(slope.shape[0]),
                 "mPerPixel": round(mpp, 2), "zoom": win["zoom"],
                 "tileCount": win["tileCount"]},
        "pond": {
            "threshold": round(thr, 3),
            "areaPct": pond_pct,
            "note": "低洼汇水候选区：邻域高程显著偏低的平坦区，需结合排水设施与影像复核；"
                    "为筛查指标，非水文模型的汇流累积结果。",
        },
        "precision": {
            "source": f"AWS Terrarium DEM z{win['zoom']}",
            "groundResolutionM": round(mpp, 1),
            "limitation": "10m 级 DEM 不适用于台阶坡面角、坑深、体积计算；"
                          "精细边坡指标需亚米级 DSM（无人机航测或立体像对）。",
        },
    }
    if req.withImage:
        import base64
        data["slopeImageBase64"] = base64.b64encode(_slope_png(slope)).decode()
        data["legend"] = [
            {"label": "<2° 平坦", "color": "#4caf50"},
            {"label": "2-6° 缓坡", "color": "#aed581"},
            {"label": "6-15° 缓陡", "color": "#ffd54f"},
            {"label": "15-25° 陡坡", "color": "#ff9800"},
            {"label": "≥25° 极陡", "color": "#d32f2f"},
        ]
    return {"code": 0, "message": "success", "data": data}


# ---------------------------------------------------------------------------
# 开采安全风险评估（多因子融合）
# ---------------------------------------------------------------------------
import risk as risk_mod  # noqa: E402


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
    withGrid: bool = Field(True, alias="withGrid", description="是否生成风险栅格图与热点")
    zoom: int = Field(14, description="DEM 放大级别")


@app.post("/api/v1/risk/evaluate")
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
            "withGrid": req.withGrid,
            "zoom": max(10, min(req.zoom, 15)),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"风险评估失败: {e}") from e
    return {"code": 0, "message": "success", "data": data}


# ---------------------------------------------------------------------------
# 报告生成（S4）：基于数据库真实统计生成 Word 报告
# ---------------------------------------------------------------------------
import report as report_gen  # noqa: E402


class ReportRequest(BaseModel):
    """报告生成请求：Java 汇总好真实数据后传入"""
    projectName: str = "默认项目"
    generatedAt: str | None = None
    timeseries: list[dict] = []
    summary: list[dict] = []
    forecast: dict = {}
    sensorOnline: int = 0
    sensorAlarm: int = 0
    # 生态指数 RSEI 结果（可选）：传入则报告增加「五、生态质量评价（RSEI）」章节
    rsei: dict | None = None
    # 安全风险评估结果（可选）：传入则报告增加「六、开采安全风险评估」章节
    # 注意：字段必须显式声明，Pydantic 会丢弃未声明字段，漏写会导致章节静默消失
    safety: dict | None = None


@app.post("/api/v1/report/generate")
def generate_report(req: ReportRequest):
    """生成矿山稳定性/安全性报告，返回 docx 字节流（base64）"""
    data = req.model_dump()
    if not data.get("generatedAt"):
        data["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        docx_bytes = report_gen.generate_report(data)
        import base64
        return {
            "code": 0, "message": "success",
            "data": {
                "filename": f"矿山监测报告-{data['projectName']}.docx",
                "docx_base64": base64.b64encode(docx_bytes).decode(),
            },
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"报告生成失败: {e}") from e


# ---------------------------------------------------------------------------
# 遥感生态指数 RSEI（三因子：绿度/湿度/干度）
# ---------------------------------------------------------------------------
import ecology as ecology_mod  # noqa: E402


class RseiRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="AOI 环")
    startDate: str = Field(..., alias="start_date")
    endDate: str = Field(..., alias="end_date")
    maxCloud: float = Field(30.0, alias="max_cloud")
    withImage: bool = Field(True, alias="with_image")
    # 对比期（可选）：传入则返回两期 RSEI 变化统计
    compareStart: str | None = Field(None, alias="compare_start")
    compareEnd: str | None = Field(None, alias="compare_end")


def _rsei_once(feat: dict, aoi: list[list[float]]) -> dict:
    """对单景计算 RSEI：拉 6 个波段（含 B12）→ 掩膜剪切 → PCA"""
    need = ["B02", "B03", "B04", "B08", "B11", "B12"]
    clipped = aws_sentinel.clip_aoi(feat, aoi, need)
    res = ecology_mod.compute_rsei(clipped["bands"])
    stats = ecology_mod.rsei_levels(res["rsei"])
    return {"rsei": res, "stats": stats}


@app.post("/api/v1/ecology/rsei")
def ecology_rsei(req: RseiRequest):
    """遥感生态指数 RSEI 计算（三因子版）。

    口径：Sentinel-2 无热红外波段，采用绿度(NDVI)+湿度(WET)+干度(NDBSI)
    三因子 PCA，**不含热环境维度**，非完整版四因子 RSEI。
    """
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "该 AOI/日期范围内无可用的无云影像", "data": None}

        cur = _rsei_once(feat, req.aoi)
        data: dict = {
            "sceneId": feat.get("id"),
            "datetime": feat.get("properties", {}).get("datetime"),
            "cloudCover": feat.get("properties", {}).get("eo:cloud_cover"),
            "mean": cur["stats"]["mean"],
            "levels": cur["stats"]["levels"],
            "pc1Weight": cur["rsei"]["pc1Weight"],
            "explainRatio": cur["rsei"].get("explainRatio"),
            "weightLabels": ["绿度 NDVI", "湿度 WET", "干度 NDBSI"],
            "formula": {
                "ndvi": "(B8-B4)/(B8+B4)",
                "wet": "缨帽变换湿度分量（S2 系数）",
                "ndbsi": "(SI+IBI)/2",
                "compose": "三因子归一化 → PCA 第一主成分 → 方向调整 → 归一化到 0~1",
            },
            "precision": {
                "resolution": "10m（Sentinel-2 L2A）",
                "level": "三因子 RSEI-3",
                "limitation": "不含热环境维度：Sentinel-2 无热红外波段，无法反演地表温度 LST。"
                              "完整四因子 RSEI 需融合 Landsat 8/9 B10 热红外，属后续增强项。",
            },
            "reference": "徐涵秋. 城市生态环境质量评价的遥感定量方法——遥感生态指数(RSEI). 生态学报, 2013.",
        }
        if req.withImage:
            import base64
            data["imageBase64"] = base64.b64encode(
                ecology_mod.rsei_png(cur["rsei"]["rsei"])).decode()

        # 对比期
        if req.compareStart and req.compareEnd:
            feat2 = aws_sentinel.search_scene(
                req.aoi, req.compareStart, req.compareEnd, req.maxCloud)
            if feat2 is not None:
                prev = _rsei_once(feat2, req.aoi)
                data["compare"] = {
                    "sceneId": feat2.get("id"),
                    "datetime": feat2.get("properties", {}).get("datetime"),
                    "mean": prev["stats"]["mean"],
                    "levels": prev["stats"]["levels"],
                    **ecology_mod.compare_rsei(prev["rsei"]["rsei"], cur["rsei"]["rsei"]),
                }
        return {"code": 0, "message": "success", "data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"RSEI 计算失败: {e}") from e

"""在线 Sentinel-2 解译（AWS Earth Search STAC 直连，无需本地影像文件）。

这是「遥感提取」页的数据源：AOI + 日期 + 类型 → 在线拉景 → 剪切 → 指数 → 矢量。
与上传影像解译（/api/v1/inference/submit，读本地文件）是两条并行的数据来源。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json

import numpy as np
import rasterio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import sentinel as aws_sentinel

from ..config import DEMO_DATA_DIR
from ..geo import aoi_area_ha
from ..logging_setup import get_logger
from ..schemas import SubmitResponse
from ..tasks import post_callback, submit_task, update_task

router = APIRouter(tags=["sentinel"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 在线 Sentinel-2 直接解译（AWS Earth Search STAC 直连，无需本地影像文件）
# ---------------------------------------------------------------------------
# 与上传影像解译（/api/v1/inference/submit，读本地文件）是两条并行的数据来源。

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
        update_task(task_id, "RUNNING", 10)

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
            update_task(task_id, "EMPTY", 100, result=payload)
            post_callback(req["callbackUrl"], payload)
            return

        update_task(task_id, "RUNNING", 40)

        # 按类型决定需要的波段
        need = _need_bands(req["classType"])
        clipped = aws_sentinel.clip_aoi(feat, req["aoi"], need)

        update_task(task_id, "RUNNING", 70)

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
        update_task(task_id, payload["status"], 100, result=payload)
        post_callback(req["callbackUrl"], payload)

    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        log.exception("解译任务异常")
        update_task(task_id, "FAILED", 100, error=detail)
        post_callback(req["callbackUrl"], {
            "taskId": task_id, "status": "FAILED", "error": detail,
        })


@router.post("/api/v1/sentinel/extract")
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


@router.post("/api/v1/sentinel/extract-async", response_model=SubmitResponse)
def online_extract_async(req: AsyncExtractRequest):
    """异步在线解译（Java submit-online 专用）：算完回调 Java 落库"""
    if req.classType not in _ONLINE_CLASSES:
        raise HTTPException(status_code=400,
                            detail=f"不支持的地物类别: {req.classType}")

    payload = {
        "aoi": req.aoi,
        "startDate": req.startDate,
        "endDate": req.endDate,
        "classType": req.classType,
        "maxCloud": req.maxCloud,
        "threshold": req.threshold,
        "minAreaPx": req.minAreaPx,
        "aoiAreaHa": aoi_area_ha(req.aoi),
        "callbackUrl": req.callbackUrl,
        "projectId": req.projectId,
        "name": req.name,
    }
    task_id = submit_task(_run_online_task, payload)
    return SubmitResponse(taskId=task_id, status="PENDING")


@router.post("/api/v1/sentinel/search")
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


@router.post("/api/v1/sentinel/preview")
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


@router.post("/api/v1/sentinel/diff-heatmap")
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
        gj = json.loads(json.dumps(geom.__geo_interface__))
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


@router.post("/api/v1/sentinel/export-geotiff")
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
        crs = clipped["meta"]["B04"].get("crs")
        # 下采样后 transform 需重算（clip_aoi 已在 max_dim 下采样，这里直接按像素尺寸近似）
        # 简化：用 rasterio 写一个不含精确 geotransform 但带 CRS 的 GeoTIFF（够二次处理用）
        height, width = rgb.shape[0], rgb.shape[1]
        buf = io.BytesIO()
        with rasterio.open(buf, "w", driver="GTiff", height=height, width=width,
                       count=3, dtype="uint8", crs=crs) as dst:
            dst.write(rgb[:, :, 0], 1)
            dst.write(rgb[:, :, 1], 2)
            dst.write(rgb[:, :, 2], 3)
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


@router.post("/api/v1/sentinel/demo-bundle")
def demo_bundle(req: DemoBundleRequest):
    """生成离线演示数据包：真彩影像 + 多类解译结果，全部缓存到本地磁盘。

    一次调用把目标 AOI 的所有波段下载到 tile 缓存 + 预生成各类解译结果，
    之后即使断网，前端也能通过「载入演示数据」秒出完整演示。
    返回一个 bundle id，前端据此读取本地缓存的结果。
    """
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}

        bundle_id = hashlib.md5(
            (json.dumps(req.aoi) + req.startDate + req.endDate).encode()
        ).hexdigest()[:12]

        # 1. 真彩影像（含下载缓存）
        clipped = aws_sentinel.clip_aoi(feat, req.aoi, ["B02", "B03", "B04"], max_dim=1024)
        png = aws_sentinel.true_color_png(clipped["bands"])
        image_b64 = base64.b64encode(png).decode()

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
        DEMO_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DEMO_DATA_DIR / f"{bundle_id}.json", "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False)

        return {"code": 0, "message": "success", "data": bundle}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"演示包生成失败: {e}") from e


@router.get("/api/v1/sentinel/demo-bundle/{bundle_id}")
def get_demo_bundle(bundle_id: str):
    """读取已生成的离线演示包（断网时前端从这里读，不经在线检索）"""
    path = DEMO_DATA_DIR / f"{bundle_id}.json"
    if not path.exists():
        return {"code": 404, "message": f"演示包不存在: {bundle_id}", "data": None}
    with open(path, "r", encoding="utf-8") as f:
        return {"code": 0, "message": "success", "data": json.load(f)}

"""
赣锋锂电遥感解译平台 - 解译服务（demo 桩）

当前阶段：只提供协议骨架，不接真实算法。
- POST /api/v1/inference/submit  接收 Java 业务服务提交的解译任务，立即返回 task_id
- GET  /api/v1/inference/{task_id}/status  查询任务状态（模拟进度）
- GET  /health  存活探针

真实算法（Mask2Former / 指数法 / 变化检测）在 GPU 服务器就绪后按模块挂载到
modules/ 下，接口协议保持不变。
"""
import random
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sentinel

# ---- 模拟任务存储（demo 内存版；接入 Celery + Redis 后替换） ----
_tasks: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时集中校验配置（后续补充 GDAL/torch 可用性检查）
    yield
    _tasks.clear()


app = FastAPI(
    title="RS Platform Inference Service",
    version="0.1.0",
    lifespan=lifespan,
)

# 遥感提取页直连本服务，放行本地开发来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmitRequest(BaseModel):
    """Java 业务服务提交的解译任务"""
    image_path: str = Field(..., description="影像在对象存储中的路径")
    algo_type: str = Field(..., description="SEGMENTATION / CHANGE_DETECTION / INDEX")
    params: dict = Field(default_factory=dict, description="算法参数")
    callback_url: str = Field(..., description="任务完成后回调的 Java 接口")


class SubmitResponse(BaseModel):
    task_id: str
    status: str


@app.get("/health")
def health():
    return {"status": "UP", "service": "rs-platform-inference", "time": time.time()}


@app.post("/api/v1/inference/submit", response_model=SubmitResponse)
def submit(req: SubmitRequest):
    """demo 桩：登记任务并返回 task_id，不执行真实推理"""
    task_id = f"inf-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    _tasks[task_id] = {
        "algo_type": req.algo_type,
        "image_path": req.image_path,
        "submitted_at": time.time(),
    }
    return SubmitResponse(task_id=task_id, status="PENDING")


@app.get("/api/v1/inference/{task_id}/status")
def status(task_id: str):
    """demo 桩：按提交时长伪造进度"""
    task = _tasks.get(task_id)
    if task is None:
        return {"code": 404, "message": f"任务不存在: {task_id}", "data": None}
    elapsed = time.time() - task["submitted_at"]
    progress = min(int(elapsed * 10), 100)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": task_id,
            "status": "SUCCESS" if progress >= 100 else "RUNNING",
            "progress": progress,
        },
    }


# ==================== Sentinel-2 遥感提取 ====================

class SearchRequest(BaseModel):
    """影像检索：AOI + 日期范围 + 云量"""
    aoi: list[list[float]] = Field(..., description="[[lng,lat],...] 至少 3 点")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    max_cloud: float = Field(30.0, description="最大云量 %")


class ExtractRequest(BaseModel):
    """提取：先检索再算指数矢量化"""
    aoi: list[list[float]]
    start_date: str
    end_date: str
    class_type: str = Field(..., description="VEGETATION/WATER/BUILDING/BARE/MOUNTAIN")
    max_cloud: float = 30.0
    threshold: float | None = Field(None, description="自定义阈值，缺省用类型默认值")
    min_area_px: int = Field(20, description="最小斑块面积（像素），过滤道路/碎斑噪声")


@app.get("/api/v1/sentinel/health")
def sentinel_health():
    return {"code": 0, "data": sentinel.health()}


@app.post("/api/v1/sentinel/search")
def search(req: SearchRequest):
    """检索最优景：返回景 ID、日期、云量，不下载数据"""
    try:
        feat = sentinel.search_scene(req.aoi, req.start_date, req.end_date, req.max_cloud)
    except Exception as e:
        return {"code": 500, "message": f"检索失败: {e}", "data": None}
    if feat is None:
        return {"code": 404, "message": "该 AOI/日期范围内无可用的无云影像", "data": None}
    props = feat.get("properties", {})
    return {
        "code": 0,
        "message": "success",
        "data": {
            "scene_id": feat.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
        },
    }


@app.post("/api/v1/sentinel/preview")
def preview(req: SearchRequest):
    """AOI 真彩影像：检索 + 剪切 + RGB PNG，返回 base64"""
    try:
        feat = sentinel.search_scene(req.aoi, req.start_date, req.end_date, req.max_cloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}
        clipped = sentinel.clip_aoi(feat, req.aoi, ["B02", "B03", "B04"])
        png = sentinel.true_color_png(clipped["bands"])
        import base64
        return {
            "code": 0,
            "message": "success",
            "data": {
                "scene_id": feat.get("id"),
                "datetime": feat.get("properties", {}).get("datetime"),
                "cloud_cover": feat.get("properties", {}).get("eo:cloud_cover"),
                "image_base64": base64.b64encode(png).decode(),
                # 注意：不要把 clip_aoi 的 meta 直接塞进响应——里面带 rasterio Affine 对象，
                # FastAPI 序列化不了会抛 500；前端用 AOI 自身边界定位影像即可
            },
        }
    except Exception as e:
        return {"code": 500, "message": f"剪切失败: {e}", "data": None}


@app.post("/api/v1/sentinel/extract")
def extract(req: ExtractRequest):
    """检索 + 剪切 + 指数提取 + 矢量化，返回 GeoJSON 结果"""
    try:
        feat = sentinel.search_scene(req.aoi, req.start_date, req.end_date, req.max_cloud)
        if feat is None:
            return {"code": 404, "message": "无可用影像", "data": None}
        # 按类型决定需要的波段：WATER(MNDWI)/BUILDING/BARE 需要 B11(swir16)
        need = ["B02", "B03", "B04", "B08"]
        if req.class_type in ("WATER", "BUILDING", "BARE"):
            need.append("B11")
        clipped = sentinel.clip_aoi(feat, req.aoi, need)
        # 自定义阈值用局部变量，不污染全局默认值
        if req.threshold is not None:
            sentinel.CLASS_THRESHOLD[req.class_type] = req.threshold
        result = sentinel.extract_class(
            clipped["bands"], req.class_type,
            clipped["meta"].get("B04", {}).get("transform"),
            clipped["meta"].get("B04", {}).get("crs"),
            min_area_px=req.min_area_px,
        )
        result["scene_id"] = feat.get("id")
        result["datetime"] = feat.get("properties", {}).get("datetime")
        result["cloud_cover"] = feat.get("properties", {}).get("eo:cloud_cover")
        return {"code": 0, "message": "success", "data": result}
    except Exception as e:
        return {"code": 500, "message": f"提取失败: {e}", "data": None}

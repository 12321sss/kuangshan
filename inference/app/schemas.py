"""跨路由共用的请求/响应模型。

只放**被多个路由引用**的模型；单个路由专用的模型留在各自的 routers/*.py 里，
避免这里变成第二个大杂烩。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SubmitResponse(BaseModel):
    """异步任务的统一返回：taskId + 初始状态"""
    taskId: str
    status: str


class SamplePoint(BaseModel):
    """监督分类的样本点（在线 Sentinel-2 与本地高分影像共用）"""
    classType: str = Field(..., description="PIT/DUMP/TAILINGS/BARE/ROAD/VEGETATION/WATER")
    lng: float
    lat: float

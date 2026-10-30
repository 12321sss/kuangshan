"""赣锋锂电遥感解译平台 · 解译服务（FastAPI）。

分层
----
    main.py          uvicorn 入口，只调 create_app()
    app/             应用装配：配置、日志、中间件、任务、路由
    app/routers/     HTTP 层：解析请求 → 调算法 → 拼响应（不含业务计算）
    algorithms/      算法层：纯计算，不依赖 FastAPI，可被脚本/测试直接调用

为什么这么分
------------
原来 1488 行的 main.py 把 28 个端点、Pydantic 模型、后台线程、回调、
算法调用全堆在一起，改一处要滚很久，也没法单独测算法。
现在按 URL 前缀拆开，每个文件 40–570 行，职责单一。

启动
----
    uvicorn main:app --port 8010 --host 127.0.0.1
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import APP_VERSION, SERVICE_NAME
from .logging_setup import configure_logging, get_logger
from .middleware import RequestLogMiddleware
from .routers import ALL_ROUTERS
from .tasks import clear_tasks

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("%s v%s 启动，已挂载 %d 组路由", SERVICE_NAME, APP_VERSION, len(ALL_ROUTERS))
    yield
    # 进程退出：demo 期任务表在内存里，清掉避免下次启动看到脏数据
    clear_tasks()
    log.info("%s 已停止", SERVICE_NAME)


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title="RS Platform Inference Service",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    # 请求 ID + 耗时日志：解译接口动辄几十秒，排查时靠它对齐前端/Java 日志
    application.add_middleware(RequestLogMiddleware)
    for router in ALL_ROUTERS:
        application.include_router(router)
    return application


__all__ = ["create_app"]

"""请求日志中间件：给每个请求一个 ID 并记录耗时。

为什么要它
----------
解译接口有几个是几十秒级的（在线拉景、监督分类），出问题时要能一眼看出
「哪个请求、花了多久、返回什么状态」。之前只有 uvicorn 的默认 access log，
既没有请求 ID 也不带耗时，和 Java 侧日志对不上。

响应头会带回 X-Request-ID，前端/Java 可以打在错误提示里，便于反查。
"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .logging_setup import get_logger

log = get_logger("request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            cost = (time.perf_counter() - started) * 1000
            log.exception("%s %s 未捕获异常 耗时=%.0fms req=%s",
                          request.method, request.url.path, cost, request_id)
            raise
        cost = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        # 健康检查太频繁，只记 debug，免得刷屏
        level = log.debug if request.url.path == "/health" else log.info
        level("%s %s -> %s 耗时=%.0fms req=%s",
              request.method, request.url.path, response.status_code, cost, request_id)
        return response

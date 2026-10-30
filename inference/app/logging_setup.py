"""日志：统一的初始化与取 logger 入口。

原来全项目用 print，出问题只能靠翻控制台。这里统一走 logging：
- 级别由 INFERENCE_LOG_LEVEL 控制（默认 INFO）
- 格式带时间、级别、模块名，便于和 Java 侧日志对照排查
- 单个 handler 指向 stdout，容器/命令行都能收
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def configure_logging() -> None:
    """初始化根 logger（幂等：重复调用不会叠加 handler）"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.environ.get("INFERENCE_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers = [handler]
    # uvicorn 自带的 access log 与本项目的请求日志重复，降噪
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

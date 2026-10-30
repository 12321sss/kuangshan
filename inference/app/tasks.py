"""任务注册表与回调。

定位
----
把「提交任务 / 更新进度 / 查状态 / 算完回调 Java」这四件事从路由里抽出来，
路由只负责解析请求和拼响应，任务生命周期集中在这里。

当前实现
--------
demo 期：进程内字典 + 后台线程，重启即丢（可接受，解译是可重算的）。
生产期：换成 Celery + Redis，**只要保持本模块的函数签名不变**，路由层不用改。

线程安全
--------
所有读写都过 `_lock`；对外只返回快照副本，避免调用方拿到可变引用后改到任务表。
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable

import requests

from .config import CALLBACK_TIMEOUT_S, CALLBACK_TOKEN
from .logging_setup import get_logger

log = get_logger(__name__)

_tasks: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def new_task_id(prefix: str = "inf") -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"


def submit_task(fn: Callable[[str, dict], None], payload: dict) -> str:
    """登记任务并起后台线程执行，返回 taskId。

    fn 的签名固定为 (task_id, payload)，内部自己调 update_task 报进度。
    """
    task_id = new_task_id()
    with _lock:
        _tasks[task_id] = {
            "status": "PENDING", "progress": 0,
            "submittedAt": time.time(), **payload,
        }
    threading.Thread(target=fn, args=(task_id, payload), daemon=True).start()
    return task_id


def update_task(task_id: str, status: str, progress: int, **extra: Any) -> None:
    with _lock:
        t = _tasks.get(task_id)
        if t is not None:
            t["status"] = status
            t["progress"] = progress
            t.update(extra)


def get_task(task_id: str) -> dict | None:
    """返回任务快照（副本）；不存在返回 None"""
    with _lock:
        t = _tasks.get(task_id)
        return dict(t) if t is not None else None


def clear_tasks() -> None:
    """进程退出时清空（lifespan 钩子调用）"""
    with _lock:
        _tasks.clear()


def post_callback(callback_url: str, payload: dict) -> str | None:
    """POST 到 Java 回调接口。

    成功返回 None；失败返回错误描述——调用方可以决定是记进结果还是直接忽略。
    统一带 X-Inference-Token，否则 Java 侧 401。
    """
    try:
        resp = requests.post(
            callback_url, json=payload, timeout=CALLBACK_TIMEOUT_S,
            headers={"X-Inference-Token": CALLBACK_TOKEN},
        )
        resp.raise_for_status()
        return None
    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        log.warning("回调失败 %s", detail)
        return detail

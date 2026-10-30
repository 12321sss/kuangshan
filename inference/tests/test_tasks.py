"""任务注册表的单元测试（不走 HTTP）。

这层以前匿名嵌在 main.py 里，没法单独测；抽到 app/tasks.py 之后
「提交 → 更新进度 → 查快照」「回调失败要返回错误而不是抛异常」都能直接验。
"""
from __future__ import annotations

import time

from app import tasks


def _wait_status(task_id: str, want: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = tasks.get_task(task_id)
        if snap and snap.get("status") == want:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内变为 {want}：{tasks.get_task(task_id)}")


def test_submit_then_update_and_snapshot():
    def worker(task_id: str, payload: dict) -> None:
        tasks.update_task(task_id, "RUNNING", 50)
        tasks.update_task(task_id, "SUCCESS", 100, result={"area": payload["area"]})

    task_id = tasks.submit_task(worker, {"area": 1.5})
    assert task_id.startswith("inf-")

    # 提交瞬间状态是 PENDING，且 payload 被合并进任务记录
    snap = tasks.get_task(task_id)
    assert snap["status"] in ("PENDING", "RUNNING", "SUCCESS")
    assert snap["area"] == 1.5

    final = _wait_status(task_id, "SUCCESS")
    assert final["progress"] == 100
    assert final["result"] == {"area": 1.5}


def test_get_task_returns_copy():
    """对外必须给快照：否则调用方改了返回值会污染任务表"""
    def worker(task_id: str, payload: dict) -> None:
        tasks.update_task(task_id, "SUCCESS", 100)

    task_id = tasks.submit_task(worker, {})
    _wait_status(task_id, "SUCCESS")

    snap = tasks.get_task(task_id)
    snap["status"] = "TAMPERED"
    assert tasks.get_task(task_id)["status"] == "SUCCESS"


def test_unknown_task_returns_none():
    assert tasks.get_task("no-such-task") is None


def test_post_callback_returns_error_instead_of_raising():
    # 指向一个必然连不上的地址：失败应返回错误描述，由调用方决定怎么记
    err = tasks.post_callback("http://127.0.0.1:9/callback", {"taskId": "x"})
    assert isinstance(err, str) and err

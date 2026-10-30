"""pytest 共用夹具。

约定
----
- 测试只走 HTTP 接口（TestClient），不直接调算法函数——这样重构内部结构时测试不用改。
- 需要本地高分影像的用例，找不到影像就 skip，不让「没拷客户数据」变成红灯。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

INFERENCE_DIR = Path(__file__).resolve().parent.parent
# 让 `import main` 生效（pytest 的 rootdir 不一定是 inference/）
sys.path.insert(0, str(INFERENCE_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    # 用 with 触发 lifespan，顺带验证启动/关闭钩子不会抛异常
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_aoi() -> list[list[float]]:
    """宁都河源样区约 1 km² 的矩形 AOI（与线上演示同一区域）"""
    return [[116.018, 26.470], [116.026, 26.470], [116.026, 26.476], [116.018, 26.476]]


def _find_test_tif() -> Path | None:
    """找一个可用于测试的 GeoTIFF：环境变量优先，其次仓库内常见位置"""
    env = os.environ.get("RS_TEST_TIF")
    if env and Path(env).is_file():
        return Path(env)
    for folder in (INFERENCE_DIR / "data" / "imagery", INFERENCE_DIR.parent / "影像"):
        if folder.is_dir():
            hits = sorted(folder.glob("*.tif")) + sorted(folder.glob("*.tiff"))
            if hits:
                return hits[0]
    return None


@pytest.fixture(scope="session")
def test_tif() -> Path:
    path = _find_test_tif()
    if path is None:
        pytest.skip("未找到测试影像，可设 RS_TEST_TIF 指向任意 GeoTIFF")
    return path

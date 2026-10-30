"""算法层的路径常量。

为什么单独一个模块
------------------
缓存目录以前是在 sentinel.py / dem.py 里各自用 `__file__` 现算的，
模块一旦被挪动（比如从 inference/ 挪进 algorithms/），缓存路径就跟着变，
预热好的瓦片全部失效、还得重新下载。这里统一算一次，谁用谁 import。

目录约定
--------
    inference/.cache/<md5>/...      Sentinel-2 tile 缓存（按景的 href 哈希分组）
    inference/.cache/terrarium/...  DEM 瓦片缓存
可用 INFERENCE_CACHE_DIR 覆盖到磁盘更大的位置（演示机 C 盘紧张时有用）。
"""
from __future__ import annotations

import os
from pathlib import Path

# algorithms/ 的上一级 = inference/，缓存固定落在项目目录下
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

CACHE_DIR = Path(os.environ.get("INFERENCE_CACHE_DIR") or _PACKAGE_ROOT / ".cache")

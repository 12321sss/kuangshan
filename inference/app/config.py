"""集中配置：环境变量只在这里读，其它模块从这里取常量。

为什么集中
----------
以前回调密钥、版本号、demo 数据目录散落在 main.py 各处，改一个值要全文搜。
现在统一在这里定义，路由层与算法层都只 import 本模块，部署时改环境变量即可。
"""
from __future__ import annotations

import os
from pathlib import Path

SERVICE_NAME = "rs-platform-inference"
# 版本号同时用于 /health 与 OpenAPI 的 info.version，改一处即可
APP_VERSION = "0.3.0"

# inference/ 目录（app/ 的上一级），所有相对路径都以它为基准
BASE_DIR = Path(__file__).resolve().parent.parent

# 回调共享密钥：与 Java 侧 INFERENCE_CALLBACK_TOKEN 必须一致。
# 不带此头 Java 后端会返回 401（回调端点曾可被任意伪造写入假数据）
CALLBACK_TOKEN = os.environ.get(
    "INFERENCE_CALLBACK_TOKEN", "rs-demo-inference-token-2026")

# 回调超时（秒）：解译可能跑几分钟，但回调本身只是写库，30 秒足够
CALLBACK_TIMEOUT_S = float(os.environ.get("INFERENCE_CALLBACK_TIMEOUT", "30"))

# 离线演示数据包落盘目录（断网演示时从这里读）
DEMO_DATA_DIR = Path(os.environ.get("INFERENCE_DEMO_DIR", BASE_DIR / "demo_data"))

# 说明：瓦片缓存目录（inference/.cache）由 algorithms/paths.py 管理，
# 算法层要保持"不依赖 app/"的独立性，所以不在这里重复定义。

"""路由汇总。

一个 URL 前缀对应一个模块（/api/v1/risk → risk.py），新增功能时：
1. 在 routers/ 下新建 <前缀>.py，里面 `router = APIRouter(tags=[...])`
2. 在这里 import 并加进 ALL_ROUTERS

main.py 只调 create_app()，不直接挂路由。
"""
from . import (
    boundary,
    classification,
    deformation,
    ecology,
    extraction,
    fusion,
    imagery,
    monitor,
    report,
    risk,
    sentinel,
    slope,
    spatial,
    system,
    terrain,
)

ALL_ROUTERS = [
    system.router,           # /health, /api/v1/class-types, /api/v1/scenes
    extraction.router,       # /api/v1/inference/*
    deformation.router,      # /api/v1/deformation/*
    sentinel.router,         # /api/v1/sentinel/*
    terrain.router,          # /api/v1/terrain/*
    risk.router,             # /api/v1/risk/*
    slope.router,            # /api/v1/slope/*
    classification.router,   # /api/v1/classify/*
    monitor.router,          # /api/v1/monitor/*
    spatial.router,          # /api/v1/spatial/*
    boundary.router,         # /api/v1/aoi/*
    imagery.router,          # /api/v1/imagery/*
    fusion.router,           # /api/v1/fusion/*
    report.router,           # /api/v1/report/*
    ecology.router,          # /api/v1/ecology/*
]

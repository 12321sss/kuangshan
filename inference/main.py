"""解译服务入口。

    uvicorn main:app --port 8010 --host 127.0.0.1

这里刻意只留三行：装配逻辑在 app/__init__.py，路由在 app/routers/，
算法在 algorithms/。入口越薄，改动越不容易互相踩。
"""
from app import create_app

app = create_app()

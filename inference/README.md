# 解译服务（inference）

赣锋锂电遥感解译平台的算法与解译服务。FastAPI 提供 HTTP 接口，
Java 后端负责业务与落库，本服务负责"读影像 → 算 → 出矢量/图/报告"。

## 目录结构

```
inference/
├── main.py                 入口（uvicorn main:app），只有 3 行装配
├── app/                    应用层：只做 HTTP 相关的事
│   ├── __init__.py         create_app()：挂中间件、路由、生命周期
│   ├── config.py           环境变量与常量（密钥、版本、目录）
│   ├── logging_setup.py    日志格式与级别
│   ├── middleware.py       请求 ID + 耗时日志
│   ├── tasks.py            任务注册表 + 回调 Java
│   ├── geo.py              AOI 外接矩形 / 面积换算
│   ├── schemas.py          跨路由共用的请求响应模型
│   └── routers/            一个 URL 前缀一个文件（见下表）
├── algorithms/             算法层：纯计算，不依赖 FastAPI，可被脚本直接调用
│   ├── paths.py            缓存目录等路径常量
│   ├── classify.py         指数阈值法（NDVI/NDWI/NDBI）+ 矢量化
│   ├── supervised.py       在线 Sentinel-2 监督分类（12 维特征）
│   ├── supervised_local.py 本地高分影像监督分类（4 波段 7 维特征）
│   ├── sentinel.py         在线拉景/剪切/合成（AWS STAC + COG）
│   ├── sentinel_source.py  Sentinel-2 场景检索
│   ├── change.py           时序变化与影像可用性
│   ├── dem.py / slope.py / risk.py / spatial.py   地形、边坡、安全、空间关系
│   ├── fusion.py           分类结果 × 指数结果一致性
│   ├── ecology.py / report.py                     生态指数、Word 报告
│   └── aoi_import.py / imagery_probe.py           边界解析、影像元数据识别
├── tests/                  pytest 用例（契约 + 离线业务链路）
├── scripts/                一次性排查工具，不参与运行
│   ├── selftest/           需要真实服务/网络的端到端自检
│   └── probe_*.py          数据源调研脚本（可选依赖）
├── requirements.txt        运行依赖（全部锁版本）
├── requirements-dev.txt    开发依赖（pytest）
└── pyproject.toml          pytest / ruff 配置
```

分层约定（改代码前先看一眼）：

1. **routers 不写业务逻辑**——只解析请求、调算法、拼响应。
2. **algorithms 不 import fastapi**——保证能被脚本和测试直接调用。
3. 模块之间跨包引用一律用相对导入（`from . import dem`），整包可搬。
4. 新增一个 URL 前缀 = 新建 `app/routers/<前缀>.py` + 在 `app/routers/__init__.py` 登记。

## 启动

```powershell
cd inference
.venv\Scripts\python.exe -m pip install -r requirements.txt --only-binary :all:
.venv\Scripts\python.exe -m uvicorn main:app --port 8010 --host 127.0.0.1
```

**端口用 8010**：本机 8000 被 Intel IncrediBuild 占用。

装了 uvicorn 的标准安装包后也可以直接 `uvicorn main:app --port 8010`，
效果相同（`main.py` 里 `app = create_app()` 就是给 uvicorn 找的）。

## 测试

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt --only-binary :all:
.venv\Scripts\python.exe -m pytest
```

- `tests/test_api_surface.py` 是**契约护栏**：27 条路径 / 28 个方法写死在用例里，
  删路由或改错前缀会立刻红。改接口时记得同步这份清单和前端/Java。
- 需要 GeoTIFF 的用例（`test_imagery_probe` / `test_classify_local`）会按
  `$RS_TEST_TIF` → `inference/data/imagery` → 仓库根 `影像/` 的顺序找影像，找不到就 skip。
- 端到端自检（会真的打网络/调 Java）在 `scripts/selftest/`，单独跑，不进 pytest。

## 接口分组

| 前缀 | 文件 | 说明 |
|---|---|---|
| `/health`、`/api/v1/class-types`、`/api/v1/scenes` | `system.py` | 探活、七类地物、场景检索 |
| `/api/v1/inference/*` | `extraction.py` | 上传影像解译（提交 / 查进度） |
| `/api/v1/sentinel/*` | `sentinel.py` | 在线 S2 解译、检索、预览、差异、导出、演示包 |
| `/api/v1/terrain/*`、`/risk/*`、`/slope/*`、`/spatial/*` | 同名文件 | 地形、安全、边坡、空间关系 |
| `/api/v1/classify/*` | `classification.py` | 监督分类（在线 / 本地） |
| `/api/v1/monitor/*` | `monitor.py` | 影像可用性、突变事件 |
| `/api/v1/aoi/*`、`/imagery/*` | `boundary.py`、`imagery.py` | 边界导入、影像元数据识别 |
| `/api/v1/fusion/*` | `fusion.py` | 分类 × 指数一致性、融合 |
| `/api/v1/report/*`、`/ecology/*` | `report.py`、`ecology.py` | Word 报告、RSEI |

完整 schema 启动后看 `http://127.0.0.1:8010/docs`。

## 环境变量

见 `.env.example`。常用的三个：

1. `INFERENCE_CALLBACK_TOKEN`：回调 Java 的鉴权头，**必须与 Java 侧一致**，否则 401。
2. `INFERENCE_CACHE_DIR`：瓦片缓存位置，默认 `inference/.cache`（已有 150MB+ 预热瓦片）。
3. `INFERENCE_LOG_LEVEL`：日志级别，排查时设 `DEBUG`。

## 口径红线（写代码时不要越界）

1. 输出一律是**潜在风险筛查**，不是实测值：水土流失不给侵蚀量，边坡不给安全系数。
2. **IoU / 一致率不是精度**，只说明两种方法是否一致；不一致只能说"建议核查"。
3. 监督分类的 OA / Kappa **只对本次影像与 AOI 有效**，不能写成"平台精度"。
4. 10m DEM 不能算台阶坡面角、坑深、体积；精细边坡指标要亚米级 DSM。
5. 矿权边界 ≠ 实际扰动边界，两者分开存、分开算。

## 排障

- **登录/页面数据全空**：先看 Java 后端 8080 是否还活着，本服务挂了前端会一并空。
- **在线解译很慢**：首跑要下瓦片（走代理限速），之后命中 `.cache` 秒回；演示前可预跑一次预热。
- **回调失败但结果正常**：看日志里的 `回调失败`，多为 Java 未起或令牌不一致；结果仍在任务表里可查。
- **Windows 控制台卡住不输出**：控制台"快速编辑模式"会阻塞写入，按一下回车即可恢复。

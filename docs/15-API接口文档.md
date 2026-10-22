# API 接口文档

> 适用版本：2026-10-22（含边界导入、监督分类、变化监测、空间关系）
> 统一响应体：`{ "code": 0, "message": "success", "data": ... }`，`code != 0` 表示业务失败
> 认证：除 `/api/auth/*` 与 `/health` 外，全部要求 `Authorization: Bearer <accessToken>`
> 数据隔离：所有带 `projectId` 的接口都会校验「当前用户是否该项目成员」，管理员直通

---

## 一、认证 `/api/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录，返回 accessToken（短时效）+ 写入 refresh Cookie |
| POST | `/api/auth/refresh` | 用 refresh Cookie 换新 accessToken |
| POST | `/api/auth/logout` | 注销并清除 Cookie |
| GET | `/api/auth/me` | 当前用户信息与权限点 |

```json
POST /api/auth/login
{ "username": "admin", "password": "admin123" }

200 { "code": 0, "data": { "accessToken": "eyJ...", "user": { "username": "admin", "role": "ADMIN" } } }
```

**约定**：accessToken 只放内存，不进 localStorage、不进 URL 查询参数；刷新由前端拦截器在 401 时自动发起。

---

## 二、影像库 `/api/imagery`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/imagery?projectId=&source=` | page:imagery | 列表；`source=UPLOAD/SENTINEL2/LANDSAT9/GF2` |
| GET | `/api/imagery/{id}` | page:imagery | 详情 |
| GET | `/api/imagery/crs-options` | — | 上传可选坐标系 |
| POST | `/api/imagery/upload` | action:imagery-manage | 上传高分影像（multipart，上限 2GB） |
| GET | `/api/imagery/scenes/search` | page:imagery | 检索 Sentinel-2 公开场景 |
| POST | `/api/imagery/register-public` | action:imagery-manage | 检索结果登记入库 |
| PUT | `/api/imagery/{id}/metadata` | action:imagery-manage | **新增**：档案元数据 12 字段 |
| PUT | `/api/imagery/{id}/favorite` | page:imagery | 收藏/取消收藏 |
| GET | `/api/imagery/{id}/path` | action:imagery-manage | 本地影像绝对路径（供解译服务读取） |
| DELETE | `/api/imagery/{id}` | action:imagery-manage | 删除（无级联，先查关联记录数） |

### 元数据字段（方案附录 B）

| 字段 | 类型 | 取值范围 | 说明 |
|---|---|---|---|
| offNadirAngle | number | 0–65 | 离轴角（度），越大侧视越强、正射精度越差 |
| sunElevation | number | 0–90 | 太阳高度角（度），过低会拉长阴影 |
| sunAzimuth | number | 0–360 | 太阳方位角（度） |
| orthoLevel | string | RAW / L1T / L2A / ORTHO / OTHER | 正射等级 |
| licenseScope | string | INTERNAL / TRAIN / PUBLISH / CROSS_BORDER | **授权范围**，决定能否训练/发表/跨境 |
| vendor | string(128) | — | 供应商 |
| price | number | ≥0 | 采购单价 |
| priceCurrency | string | CNY / USD / EUR | 币种 |
| orderNo | string(64) | — | 采购单号 / 合同号 |
| deliveryDate | date | YYYY-MM-DD | 交付日期 |
| bandCount | int | 1–200 | 波段数 |
| sensorName | string(32) | — | 传感器型号（MSI / PMS / WFV…） |

```json
PUT /api/imagery/12/metadata
{ "offNadirAngle": 8.5, "sunElevation": 55, "orthoLevel": "L2A",
  "licenseScope": "TRAIN", "vendor": "二十一世纪空间技术", "price": 12000 }

200 { "code": 0, "data": { "id": 12, "licenseScope": "TRAIN", ... } }
400 { "code": 400, "message": "授权范围只能是：INTERNAL / TRAIN / PUBLISH / CROSS_BORDER" }
```

---

## 三、边界管理 `/api/aoi-boundaries`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/aoi-boundaries?projectId=&type=` | page:imagery | 列表（不含几何） |
| GET | `/api/aoi-boundaries/{id}` | page:imagery | 详情（含几何外环 + 内洞） |
| GET | `/api/aoi-boundaries/summary?projectId=` | page:imagery | 各类边界数量与「越界检测是否可用」 |
| POST | `/api/aoi-boundaries/import` | action:imagery-manage | 导入 SHP/GeoJSON/KML |
| DELETE | `/api/aoi-boundaries/{id}` | action:imagery-manage | 删除 |

`boundaryType`：`PERMIT` 矿权范围（越界检测唯一基准）/ `DISTURBANCE` 实际扰动边界 / `ECO` 生态缓冲区。

```json
POST /api/aoi-boundaries/import
{ "projectId": 1, "boundaryType": "PERMIT", "filename": "mine.zip",
  "contentBase64": "UEsDBBQ...", "name": "宁都河源矿权", "merge": false }

200 { "code": 0, "data": {
  "count": 1, "sourceFormat": "SHP", "sourceCrs": "EPSG:32650",
  "warnings": "EPSG:32650",
  "saved": [{ "id": 1, "name": "宁都河源矿权", "areaHa": 246.74, "vertexCount": 5 }] } }
```

**错误约定**：`.prj` 缺失且坐标值不像经纬度 → `400`，不猜测坐标系。

---

## 四、解译 `/api/extractions`、`/api/timeseries`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/extractions?projectId=` | page:extract | 业务列表（排除回收站） |
| POST | `/api/extractions/submit` | action:extract-manage | 上传影像 → 异步解译（回调落库） |
| POST | `/api/extractions/submit-online` | action:extract-manage | 在线影像 → 异步解译 |
| POST | `/api/extractions/save` | action:extract-manage | 前端已算好结果直接落库 |
| DELETE | `/api/extractions/{id}` | action:extract-manage | 软删除（进回收站） |
| GET | `/api/extractions/trash?projectId=` | page:extract | 回收站列表 |
| POST | `/api/extractions/{id}/restore` | action:extract-manage | 还原 |
| DELETE | `/api/extractions/{id}/purge` | action:extract-manage | 彻底删除 |
| GET | `/api/timeseries/groups?projectId=` | page:analysis | 按 AOI 指纹分组 |
| GET | `/api/timeseries/{signature}` | page:analysis | 某区域的期次序列（含几何） |
| POST | `/api/callback/task-complete` | X-Inference-Token | 解译服务回调（必须带令牌） |

---

## 五、分析 `/api/analysis`

### 5.1 时序与构成

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/analysis/area-timeseries?projectId=&granularity=month\|year` | 存量口径面积时序（同期同 AOI 取最新） |
| GET | `/api/analysis/change-summary?projectId=` | 当前地物构成（并集去重） |
| GET | `/api/analysis/aoi-profile?projectId=&signature=` | 单区域纵向体检 |
| GET | `/api/analysis/pit-forecast?projectId=` | 采坑外推（含 disclaimer / uncertaintyHa） |
| GET | `/api/analysis/trend-judgement?projectId=` | **新增**：扰动扩张/收缩 + 持续复绿判定 |
| POST | `/api/analysis/check-trends?projectId=&thresholdPct=` | 面积突变检测并生成告警 |

```json
GET /api/analysis/trend-judgement?projectId=1
200 { "code": 0, "data": {
  "available": true,
  "conclusion": "扰动无法比较；植被未复绿",
  "disturbTrend": { "direction": "无法比较", "overallDeltaHa": 98.3 },
  "regreening": [{ "signature": "950544574", "periodCount": 6, "upStreak": 0,
                   "growthPct": 3.4, "verdict": "未复绿", "note": "..." }],
  "hint": "" } }
```

**判定规则**：连续 ≥3 期上升且累计 ≥5% 才判「持续复绿」，且注明"不等于生态修复成功"。

### 5.2 安全评估与空间关系

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/analysis/safety-evaluate?projectId=&withGrid=&withSlope=` | 六维风险评分 + 风险图 + 热点 |
| POST | `/api/analysis/slope-units?projectId=` | 边坡单元 + 三区扰动 |
| POST | `/api/analysis/spatial-relations?projectId=&bufferKm=&slopeCutDeg=` | **新增**：坑内积水/尾矿水面/排土场汇流/道路切坡/缓冲区/采坑形态 |
| GET | `/api/analysis/safety-latest-meta?projectId=` | 可评估记录数提示 |

```json
POST /api/analysis/spatial-relations?projectId=1&bufferKm=2&slopeCutDeg=15
200 { "code": 0, "data": {
  "available": true,
  "items": [{ "key": "dump_flow", "label": "排土场汇流路径", "level": "中",
              "finding": "排土场约 15.0%（3.64 ha）位于相对低洼汇水区",
              "advice": "核查坡脚截排水沟与拦挡设施…",
              "metrics": [{ "label": "压占比例", "value": 15, "unit": "%" }] }],
  "summary": { "total": 6, "available": 2, "headline": "…" },
  "imageBase64": "iVBOR…", "pitShapes": [] } }
```

### 5.3 精细解译与周尺度监测（新增）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/analysis/aoi-options?projectId=` | 可选分析区（含外环，前端下拉用） |
| POST | `/api/analysis/classify-supervised` | 监督分类（随机森林 + 混淆矩阵） |
| POST | `/api/analysis/monitor-availability` | L1 影像可用性检查 |
| POST | `/api/analysis/change-events` | L2 两期突变检测 |

```json
POST /api/analysis/classify-supervised
{ "projectId": 1, "aoi": [[116.014,26.466], ...],
  "samples": [{ "classType": "PIT", "lng": 116.019, "lat": 26.471 }],
  "start": "2026-09-01", "end": "2026-10-01", "maxCloud": 20 }

200 { "code": 0, "data": {
  "accuracy": { "overallAccuracy": 87.5, "kappa": 0.833, "oobScore": 83.3,
                "labels": ["DUMP","BARE","VEGETATION","WATER"],
                "confusionMatrix": [[8,2,0,0],[2,8,0,0],[0,0,10,0],[0,0,1,9]],
                "split": "65/35 分层抽样" },
  "classes": [{ "classType": "VEGETATION", "areaHa": 108.96, "userAccuracy": 90.9,
                "producerAccuracy": 100.0 }],
  "featureImportance": [{ "name": "NDVI", "importance": 15.8 }],
  "features": { "VEGETATION": [ /* GeoJSON Feature */ ] },
  "warnings": ["10m 分辨率分不出采坑内部台阶…"] } }
400 { "code": 400, "message": "样本太少，每类至少 8 个：露天采坑 5 个…" }
```

```json
POST /api/analysis/monitor-availability
{ "projectId": 1, "days": 30, "maxCloud": 20 }
200 { "data": { "level": "充足", "message": "近 30 天有 5 天可用影像…",
                "scenes": [{ "date": "2026-10-17", "cloudCover": 13.9 }],
                "note": "「没有可用影像」与「没有变化」是两件事" } }

POST /api/analysis/change-events
{ "projectId": 1, "d1Start": "2026-09-20", "d1End": "2026-09-30",
  "d2Start": "2026-10-10", "d2End": "2026-10-18", "minAreaHa": 0.5 }
200 { "data": { "totalEvents": 36,
                "events": [{ "type": "NEW_BARE", "label": "新增裸地/扰动",
                             "count": 3, "totalAreaHa": 23.83,
                             "patches": [{ "lng": 116.0182, "lat": 26.4699, "areaHa": 15.71 }] }],
                "conclusion": "检出 36 处超过 0.5 ha 的可疑变化…",
                "warnings": ["两期仅相隔 15 天，小面积斑块多为阈值抖动…"] } }
```

---

## 六、监测告警 `/api/alarms`、`/api/sensors`、`/api/stations`、`/api/warning-rules`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/alarms?projectId=&status=` | 告警列表 |
| POST | `/api/alarms/{id}/ack` | 确认（进入处理中） |
| POST | `/api/alarms/{id}/resolve` | 闭环处理 |
| GET | `/api/sensors?projectId=` | 传感器列表 |
| GET | `/api/sensors/{id}/data?hours=` | 时序数据 |
| GET | `/api/sensors/{id}/displacement` | 位移曲线 |
| GET | `/api/sensors/{id}/export` | CSV 导出 |
| GET/POST/PUT/DELETE | `/api/stations` | 站点增删改查 |
| GET/PUT | `/api/warning-rules` | 预警规则 |

---

## 七、平台管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/PUT/DELETE | `/api/projects` | 项目；`PUT /{id}/members` 分配成员；`GET /{id}/boundary` 三图层边界 |
| GET/POST/PUT/DELETE | `/api/users` | 用户管理 |
| GET/POST/PUT/DELETE | `/api/roles` | 角色与权限矩阵；`GET /catalog` 权限点目录 |
| GET | `/api/audit-logs?projectId=` | 操作日志 |
| GET/PUT | `/api/dict` | 数据字典 |
| GET | `/api/health/checks` | 各子系统健康检查 |
| GET | `/health` | 存活探针（无认证） |
| GET | `/api/overview/stats` | 首页统计 |
| GET | `/api/screen/summary` | GIS 大屏汇总 |
| GET | `/api/search?kw=` | 全局搜索 |
| POST/GET/DELETE | `/api/share` | 访客分享链接 |
| GET | `/api/aoi-watch` | 关注区（哨兵） |

---

## 八、解译服务（inference，默认 `127.0.0.1:8010`）

前端经 Vite 代理 `/sentinel` 访问；Java 侧经 `INFERENCE_BASE_URL` 访问。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 服务健康 |
| GET | `/api/v1/class-types` | 七类地物中文名（统一口径） |
| POST | `/api/v1/sentinel/search` | 检索公开影像 |
| POST | `/api/v1/sentinel/preview` | 真彩/假彩预览（base64） |
| POST | `/api/v1/sentinel/extract` | 指数阈值法提取（七类） |
| POST | `/api/v1/classify/supervised` | **监督分类** |
| POST | `/api/v1/monitor/availability` | **L1 可用性** |
| POST | `/api/v1/monitor/change-events` | **L2 突变检测** |
| POST | `/api/v1/terrain/analyze` | 地形与坡度 |
| POST | `/api/v1/spatial/analyze` | **空间关系 6 项** |
| POST | `/api/v1/slope/analyze` | 边坡单元与三区扰动 |
| POST | `/api/v1/risk/evaluate` | 六维风险评分 |
| POST | `/api/v1/aoi/import` | 边界文件解析 |
| POST | `/api/v1/report/generate` | Word 报告生成 |

---

## 九、错误码

| code | 含义 | 前端处理 |
|---|---|---|
| 0 | 成功 | — |
| 400 | 参数/业务校验失败（message 可直接展示） | 原样提示，不重试 |
| 401 | 未认证或令牌过期 | 自动刷新一次，失败跳登录 |
| 403 | 无权限 / 非项目成员 | 提示无权限，不重试 |
| 404 | 资源不存在 | 提示并刷新列表 |
| 502/503 | 下游（inference）异常或未启动 | 提示检查解译服务，5xx 可重试最多 3 次 |

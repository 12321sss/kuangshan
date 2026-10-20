# 赣锋锂电遥感解译平台 · 项目长期笔记

## 项目定位
面向赣锋锂业硬岩锂矿的遥感解译 + 时序变化监测预警 + IoT + 三维 WebGIS 平台。**商业目标：先做 demo 向赣锋演示拿单**（团队在新余，与赣锋总部同城，地缘优势）。平台四大功能：①影像上传解译（七类：采坑/排土场/尾矿/裸地扰动/植被/道路设施/水体）②矿坑时序变化演示+未来预测 ③IoT 接口预留 ④矿山稳定性/安全性报告生成。

## 已确认架构决策（2026-10-16，ADR-01）
- monorepo：frontend（Vue3+TS+Cesium+Element Plus+Pinia）/ backend-java（Spring Boot 3）/ inference（FastAPI）/ deploy / docs
- Java↔Python 走 REST 提交 + 回调；JWT 认证（令牌不落 localStorage）；WebSocket 推送进度与传感器数据
- demo 期数据层：PostGIS + MinIO + Redis + EMQX 单机；Kafka/Flink/TDengine/K8s 延后生产期
- demo 算法：Sentinel-2 指数法出七类雏形，GPU 服务器就位+商业影像采购后换 Mask2Former
- 变化检测先做 GIS 叠加+转移矩阵基线；预测=面积时序拟合+边界外推（必须标注不确定性）
- 报告引擎 python-docx 模板化，结论措辞规则化

## 关键口径红线（来自实施方案报告，交付合规必须守住）
- 只能输出"潜在水土流失风险筛查"，不能报实测侵蚀量
- "持续复绿"≠"生态修复成功"
- 演示用 Sentinel-2（10m）必须向客户说清证据等级，亚米级才是正式数据源
- 矿权边界 ≠ 实际扰动边界，分开管理

## 数据现状
暂无商业影像。demo 用 Sentinel-2 公开时序（首选样区：宁都河源，江西本地）。候选矿区：Goulamina（马里）、Mount Marion、Pilgangoora（澳大利亚）、宁都河源（条件样区）；松树岗不默认纳入。

## 环境备注
## 环境备注（2026-10-16 换机后重校，以此为准）
- **本机无 D 盘、无管理员权限、无 Docker**。原记录的 D:\Dev 全系列绿色版在本机不存在。
- JDK 17：`C:\Java17\jdk-17.0.2`（PATH 默认仍是 JDK 8，Maven 必须显式指定 JAVA_HOME）
- Maven 3.9.9：`C:\dev\apache-maven-3.9.9`（settings.xml 已配华为云镜像；下载源用 repo.huaweicloud.com，archive.apache.org 极慢）
- MySQL 8.0.28：`C:\dev\mysql-8.0.28-winx64`（root/root，库 rs_platform，utf8mb4）
- Node v22；Python 用 WorkBuddy 托管 3.13.12，venv 建在 inference/.venv
- **8000 端口被 IncrediBuild 占用，解译服务跑 8010**
- 构建：JAVA_HOME="C:\Java17\jdk-17.0.2" C:/dev/apache-maven-3.9.9/bin/mvn -s C:/dev/apache-maven-3.9.9/conf/settings.xml -DskipTests package
- 后端启动显式 --server.port=8080；mvn package 前杀旧 java 进程（jar 锁）
- 平台品牌名"智慧矿山"，不出现客户字眼

## 遥感解译链路（2026-10-16 落地，全链路实测通过）
- **imagery 表**统一两条路线：source=UPLOAD（用户上传高分影像）/ SENTINEL2（公开检索）
- **坐标系上传时必选**（用户明确要求），crs 原样记录；覆盖范围统一存 WGS84 供 Cesium 定位
- 主链路：影像库 → 选影像+圈AOI → POST /api/extractions/submit → inference 真实指数法 → 回调 /api/callback/task-complete → extractions 落库
- inference 跑 **8010**（8000 被 IncrediBuild 占），INFERENCE_BASE_URL 默认已指向 8010
- 指数法：NDVI(植被>0.3)/NDWI(水体>0.1)/NDBI(裸地>-0.1)，矢量化用 rasterio.features.shapes + shapely
- **TasksView.vue 已删**，任务降级为流水追溯（/api/tasks 保留）；在线提取页改为真实提交+轮询
- 权限点：page:imagery / action:imagery-manage（page:tasks、action:task-manage 已废）
- 口径：输出为「潜在水土流失风险筛查」，非实测侵蚀量；采坑/排土场/尾矿无 DEM 与分割模型时无法细分，需标注局限
- 自检脚本（可复跑）：inference/selftest_classify.py、selftest_e2e.py、selftest_fullchain.py、selftest_upload.py、selftest_timeseries.py
- **上传限制**必须放开：application.yml 里 spring.servlet.multipart.max-file-size=2GB（默认1MB 会让高分影像传不上去）
- **上传影像（source=UPLOAD）也走解译**：白名单含 GF2/GF7/UPLOAD，前端 UPLOAD 时显式传 satellite 决定波段映射

## 在线 Sentinel-2 解译（2026-10-19 落地，AWS STAC 直连方案）
- **数据源：AWS Earth Search STAC + COG**（`sentinel.py`），本机可直连、无需账号，
  绕开被墙的 Copernicus 波段数据。之前 Copernicus 元数据可检索但波段 JP2 403、公开 WMS 被墙。
- 技术：STAC 检索 → COG Range 按 tile 精确下载 → zlib 解码 + predictor=2 水平差分还原 → 指数 → 矢量
- `_TileCache` 磁盘缓存：同一景同一 tile 只下载一次，跨 AOI 复用；演示前可"预热"目标矿区
- 三条 inference 接口：/api/v1/sentinel/search（检索景）、/preview（真彩 base64）、/extract（在线解译+回调）
- Java 对应：/api/extractions/submit-online（异步）和 /save（前端已算好直接落库）
- **两条数据来源路径并行**：上传高分影像（imageryId+filePath）与 在线S2（无 imageryId，落库 null）
- 前端「遥感提取」页 = RemoteExtractView.vue（/remote-extract），走 /sentinel 代理到 8010

## 面积单位约定（2026-10-19）
- **底层统一存公顷(ha)**，字段名 extractAreaHa/aoiAreaHa/totalAreaHa 等保持不变
- **仅展示层换算成 km²**（1 km² = 100 ha），工具函数在 `frontend/src/utils/format.ts`（haToKm2/haToKm2Num/formatArea）
- 已改：TimeSeriesPanel、AnalysisView（含图表）、ExtractView、ImageryView、RemoteExtractView、ScreenView

## 时序播放与变化分析（2026-10-16 落地）
- **aoi_signature**：识别同一 AOI 的不同期结果，时序分组依据。
  归一化三坑：浮点尾数 /闭合环首尾重复点 /顶点顺序 → 正解是「四舍五入5位 + TreeSet 去重 + 哈希」
- 接口：/api/timeseries/groups（分组）、/api/timeseries/{sig}（序列含几何）
- 前端 components/TimeSeriesPanel.vue：区域下拉+播放/步进+时间滑块+面积迷你趋势条，@frame 驱动地图切帧
- analysis 已全改真实数据：/api/analysis/area-timeseries、change-summary、pit-forecast
- 预测必带 disclaimer + uncertaintyHa；期数<2 返回 insufficient:true **不编数**

## 安全红线（两处曾经的严重漏洞，已修复并实测）
- **回调必须带 X-Inference-Token**（INFERENCE_CALLBACK_TOKEN 注入）：裸奔时任何人可写 9999ha 假数据
- **跨项目数据隔离**：imagery/extractions/timeseries/analysis 都必须经
  PermissionGuard.requireAccess(projectId, auth)，否则非成员能看他人项目数据
- 测试务必覆盖**每条入口路径**（UPLOAD 与公开源都要测），只测最顺的那条会漏致命 bug

## 数据中台（2026-10-16 落地）
- 业务库 MySQL（rs_platform）：users/roles/projects+project_members/stations/sensors/tasks/alarms/warning_rules/extractions
- 空间库 PostGIS 缓到服务器期；几何暂 JSON 存 MySQL，GeoStore 接口隔离
- 动态 RBAC：PermCatalog 权限点目录 + roles 表 JSON 权限 + PermissionGuard 实时解析
- 项目隔离：全接口 projectId 过滤，非管理员只见成员项目
- 详见 docs/02-数据中台与数据库设计.md

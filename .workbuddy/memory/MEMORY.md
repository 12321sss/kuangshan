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
- 本机无管理员权限，无 Docker
- MySQL 绿色版 8.0.28：D:\Dev\mysql-8.0.28-winx64（root/root，库 rs_platform，utf8mb4），启动命令见 README
- Maven 3.9.16 绿色版：D:\Dev\maven，构建带 -s deploy/maven-settings.xml（阿里云镜像）
- JDK17 在 D:\Dev\Java；GPU 在服务器端，本机只做开发调试
- 后端启动必须显式 --server.port=8080（环境注入 SERVER_PORT 干扰）；mvn package 前杀旧 java 进程（jar 锁）
- 平台品牌名"智慧矿山"，不出现客户字眼

## 数据中台（2026-10-16 落地）
- 业务库 MySQL（rs_platform）：users/roles/projects+project_members/stations/sensors/tasks/alarms/warning_rules/extractions
- 空间库 PostGIS 缓到服务器期；几何暂 JSON 存 MySQL，GeoStore 接口隔离
- 动态 RBAC：PermCatalog 权限点目录 + roles 表 JSON 权限 + PermissionGuard 实时解析
- 项目隔离：全接口 projectId 过滤，非管理员只见成员项目
- 详见 docs/02-数据中台与数据库设计.md

## 遥感提取（2026-10-19 真实算法跑通）
- 数据源 AWS Earth Search STAC（零 token 直连），Sentinel-2 L2A COG
- 关键技术：GDAL /vsicurl 在本机崩溃 → httpx + tifffile 解析 tile 偏移表 + zlib 手动解码；asset 键是 blue/green/red/nir/swir16；景是 UTM 需 transform_bounds 投影；矢量化用 rasterio.features.shapes
- 硬约束：本机沙箱代理限速 35KB/s，首次下载慢 → tile 级本地缓存（inference/.cache）复用后 20 秒
- 接口 /api/v1/sentinel/{search,preview,extract}；前端 /remote-extract 页
- 指数：NDVI/NDWI/NDBI/裸土/山体，阈值分割 + 矢量化

## 2026-10-20 合并服务器版（升级 0.2.0）
- 服务器新增：影像库(imagery)、上传影像解译(classify.py)、报告生成(report.py)、Copernicus 数据源(sentinel_source.py)、时序接口(TimeSeriesController)、回调入口(InferenceCallbackController 带共享密钥)
- 端口统一 8000（服务器 8010 因 IncrediBuild 占用，本机改回 8000）
- 回调安全：X-Inference-Token 共享密钥 + 数值合理性校验（防伪造假数据）
- 详见 docs/04-功能扩展清单.md 与 docs/05-客户操作功能与优化清单.md（后续需求蓝本）

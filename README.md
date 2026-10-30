# 智慧矿山 · 遥感解译与物联网三维 WebGIS 平台

面向硬岩锂矿的**遥感影像智能解译 + 时序变化监测预警 + 物联网感知 + 三维可视化**一体化平台。

## 仓库结构（monorepo）

```
├── frontend/          # Vue3 + TS + Vite + Cesium + Element Plus + Pinia
├── backend-java/      # Spring Boot 3 业务服务（认证/项目/影像/解译记录/报告）
├── inference/         # FastAPI 解译服务
│   ├── main.py        #   入口（只有 app = create_app()）
│   ├── app/           #   HTTP 层：config / routers（14 个，一个 URL 前缀一个文件）
│   ├── algorithms/    #   算法层：指数法、监督分类、融合、地形/边坡/风险、报告（不依赖 FastAPI）
│   ├── tests/         #   pytest：接口契约 + 离线业务链路
│   └── scripts/       #   一次性排查脚本；scripts/selftest 为端到端自检
├── deploy/            # docker-compose 基础设施编排、Maven 镜像配置
│   └── prod/          #   生产部署：Dockerfile×3、全栈 compose、nginx、systemd、备份/冒烟脚本
├── docs/              # 架构决策、API 约定、数据库设计、部署方案
├── .env.example       # 环境变量模板（真实 .env 不入库）
└── README.md
```

解译服务的分层约定与排障见 [`inference/README.md`](inference/README.md)，
为什么要这么分见 [`docs/24-解译服务工程结构.md`](docs/24-解译服务工程结构.md)，
上线怎么部署见 [`docs/25-部署方案.md`](docs/25-部署方案.md)。

## 快速启动（开发环境）

> 下面命令按**本机实测路径**给出（Windows + Git Bash）。换机器时对照[换机开发指南](#换机开发指南源码包迁移)调整路径即可。
> 注意本机 `JAVA_HOME` 默认指向 JDK 8，Spring Boot 3.x 必须显式指定 JDK 17，否则构建报编译错误。
>
> `.env` 说明：**当前本地开发无需复制 `.env.example`**，按下面默认配置即可跑通（后端未引入 dotenv，
> 不读 `.env` 文件；`deploy/docker-compose.yml` 用的是硬编码 environment，也未引用 env_file）。
> 根目录 `.env.example` 是数据层（PostGIS/MinIO/Redis）的模板；
> 生产部署的环境变量在 `deploy/prod/.env.example`，见[部署](#生产部署)。

### 0. 环境路径（本机）

| 组件 | 路径 |
| --- | --- |
| JDK 17 | `C:\Java17\jdk-17.0.2` |
| Maven 3.9.9 | `C:\dev\apache-maven-3.9.9\bin\mvn` |
| MySQL 8.0.28 | `C:\dev\mysql-8.0.28-winx64\bin\mysqld.exe` |
| Node | `v22.22.2` |
| Python venv | `inference/.venv`（依赖已装） |

### 1. 启动 MySQL（绿色版，已初始化）

```bash
/c/dev/mysql-8.0.28-winx64/bin/mysqld.exe --port=3306 \
  --datadir="C:\dev\mysql-8.0.28-winx64\data" --character-set-server=utf8mb4 --console
```

> 账号 root/root，库 rs_platform。首次由后端自动建表并播种演示数据
> （users/roles/projects/project_members/sensors/stations/tasks/alarms/warning_rules/extractions，共 4 用户 + 4 项目）。

### 2. 构建并启动业务服务

```bash
# 构建（必须显式指定 JDK 17）
cd backend-java
JAVA_HOME="C:\Java17\jdk-17.0.2" /c/dev/apache-maven-3.9.9/bin/mvn \
  -s ../deploy/maven-settings.xml -DskipTests package

# 启动（显式端口，本环境有 SERVER_PORT 环境变量干扰）
/c/Java17/jdk-17.0.2/bin/java -jar target/rs-platform-backend-0.0.1-SNAPSHOT.jar --server.port=8080
```

> 重新构建前先杀旧 java 进程，否则 jar 被占用导致打包失败：
> `taskkill //PID <pid> //F`

### 3. 启动解译服务

```bash
cd inference && ./.venv/Scripts/python -m uvicorn main:app --port 8010
```

> **端口是 8010**：本机 8000 被 Intel IncrediBuild 占用。后端 `INFERENCE_BASE_URL`
> 默认值与前端 `/sentinel` 代理都指向 8010。
>
> 该服务已接入真实解译链路（代码都在 `inference/algorithms/`）：
> ① 上传影像解译（`classify.py` 指数法 + 矢量化）
> ② 在线 Sentinel-2 解译（`sentinel.py`，AWS Earth Search STAC 直连，无需账号）
> ③ 监督分类（`supervised.py` 在线 12 维特征 / `supervised_local.py` 本地 4 波段 7 维特征）
> ④ 报告生成（`report.py`，python-docx）。
>
> 自检：`cd inference && .venv/Scripts/python -m pytest`（23 个用例，不需要外部服务）。

### 4. 启动前端

```bash
cd frontend && npm run dev   # → http://localhost:5173
```

### 验证

| 服务 | 地址 | 状态检查 |
| --- | --- | --- |
| 前端 | http://localhost:5173 | 浏览器打开 |
| 后端 | http://localhost:8080 | `curl http://localhost:8080/actuator/health` → `{"status":"UP"}` |
| 解译服务 | http://localhost:8010 | `curl http://localhost:8010/health` |
| MySQL | 3306 | `mysqladmin -u root -proot status` |

演示账号：admin/admin123（管理员）、manager/manager123、analyst/analyst123、viewer/viewer123。

## 换机开发指南（源码包迁移）

源码包不含依赖产物，目标机器按下面备齐环境：

1. **JDK 17**：解压绿色版 Temurin，记住路径（本机为 `C:\Java17\jdk-17.0.2`）。
   若系统 `JAVA_HOME` 仍指向旧版本，构建时需显式覆盖：`JAVA_HOME=<jdk17路径>`
2. **Maven 3.9+**：解压绿色版（本机为 `C:\dev\apache-maven-3.9.9`）。构建统一用随包分发的配置：
   `mvn -s ../deploy/maven-settings.xml -DskipTests package`（在 backend-java 目录下执行）。
   该配置已内置华为云镜像（`mirrorOf=*`）与 UTF-8 编码，无需再单独指定 settings
   - 下载 Maven 本体建议用 `https://repo.huaweicloud.com/apache/maven/`，官方 archive 源实测极慢
3. **Node 18+**：`cd frontend && npm install`（Cesium 包较大，耐心等；建议配国内镜像源）
4. **Python 3.13+**：`cd inference && python -m venv .venv && .venv/Scripts/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt`
   - 注意：numpy 需 2.x，Python 3.13 才有预编译轮子（3.11/3.12 无 1.26 轮子会源码编译失败）
   - 不要装 pyproj（Windows 无 3.13 轮子）；坐标变换用 rasterio 自带的 GDAL
5. **MySQL 8 绿色版**：解压后 `mysqld --initialize-insecure --datadir=<数据目录>` 初始化，
   再设密码并建库（后端连接需要 root 密码，且库要为 utf8mb4）：

   ```sql
   ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root';
   CREATE DATABASE rs_platform DEFAULT CHARACTER SET utf8mb4;
   ```

   然后 `mysqld --port=3306 --datadir=<数据目录> --character-set-server=utf8mb4` 启动。
   `rs_platform` 的表由后端首次启动自动建好并播种，无需导数据
6. 前端密钥已在 `frontend/.env.local`（天地图/Cesium token），随包迁移，无需重配
7. 数据库连接等非默认值：复制 `.env.example` 为 `.env` 并按需覆盖（默认 root/root + 本机 3306 即可跑）
8. **检查端口占用**：`netstat -ano | findstr :8010`。解译服务用 8010（8000 被 IncrediBuild 占用）。

> 空间库 PostGIS、MinIO、Redis 按 `docs/02-数据中台与数据库设计.md` 在服务器部署期接入（deploy/docker-compose.yml 已备好编排，本机无 Docker 暂缓）。

## 生产部署

```bash
cd deploy/prod
cp .env.example .env && vi .env      # 改密钥、填天地图 tk、定镜像 tag
docker compose --env-file .env up -d --build
./scripts/smoke.sh                   # 全绿才算部署完成
```

设计说明与坑位（三个隐性依赖、内网离线策略、容量、回滚）见
[`docs/25-部署方案.md`](docs/25-部署方案.md)，操作步骤见 [`deploy/prod/README.md`](deploy/prod/README.md)。

## 当前阶段

**Phase 0-1（demo 优先）**：以 Sentinel-2 公开数据跑通「上传 → 解译 → 时序变化 → 报告」全流程 demo，
用于向赣锋演示拿单。企业级完整架构（Kafka/Flink/TDengine/K8s）延后到生产期。

详见 `docs/01-架构决策与分期.md`。

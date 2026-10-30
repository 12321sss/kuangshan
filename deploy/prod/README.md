# 生产部署操作手册（Docker Compose 单机）

设计说明见 `docs/25-部署方案.md`；这里只写**照着敲**的步骤。

## 0. 前置

宿主机：Linux（Ubuntu 22.04 / CentOS Stream 9 均可），4 核 8G 起步（推荐 8 核 16G），
Docker 24+ 与 compose 插件：

```bash
docker --version && docker compose version
```

磁盘：系统盘 ≥100G，影像盘 ≥2T（`rs-imagery` 卷可迁到数据盘，见第 6 节）。

## 1. 取代码

```bash
git clone <仓库地址> /opt/rs-platform
cd /opt/rs-platform
```

## 2. 配环境变量

```bash
cd deploy/prod
cp .env.example .env

# 生成三个密钥，粘进 .env
openssl rand -base64 48     # JWT_SECRET
openssl rand -base64 48     # INFERENCE_CALLBACK_TOKEN
openssl rand -hex 16        # DB_PASSWORD（DB_ROOT_PASSWORD 同理）

vi .env
chmod 600 .env
```

必须改的项：

| 变量 | 不改的后果 |
|---|---|
| `JWT_SECRET` | 默认值公开，任何人都能签管理员令牌 |
| `INFERENCE_CALLBACK_TOKEN` | 默认值公开，回调端点可被伪造写假数据 |
| `DB_ROOT_PASSWORD` / `DB_PASSWORD` | 弱口令，且容器内 3306 一旦误暴露就是全库泄露 |
| `VITE_TIANDITU_TOKEN` | **不填三维大屏底图是空白**（构建期写死，事后改要重新构建） |
| `TAG` | 用版本号，别用 latest，否则没法回滚 |

## 3. 构建并启动

```bash
docker compose --env-file .env up -d --build
```

首次 10–20 分钟（maven 拉依赖 + pip 装遥感栈）。之后看状态：

```bash
docker compose ps          # 四个服务都应是 healthy
docker compose logs -f backend
```

## 4. 验收

```bash
./scripts/smoke.sh
```

全绿后浏览器打开 `http://<服务器IP>/`，用 `admin / admin123` 登录，**立刻改密码**。

## 5. 日常运维

```bash
docker compose --env-file .env ps
docker compose --env-file .env logs -f --tail=100 inference
docker compose --env-file .env restart inference
docker compose --env-file .env down          # 数据在命名卷里，不会丢
```

备份（建议加进 crontab，每天 2:10）：

```bash
./scripts/backup.sh
crontab -e
# 10 2 * * * /opt/rs-platform/deploy/prod/scripts/backup.sh >> /var/log/rs-backup.log 2>&1
```

## 6. 把影像目录挪到数据盘（可选）

影像比数据库大得多，通常单独挂盘：

```bash
# 停服务 → 建目录 → 迁移 → 改 compose 挂载 → 起服务
docker compose --env-file .env stop backend
mkdir -p /data/rs/imagery
docker run --rm -v rs-platform_rs-imagery:/from -v /data/rs/imagery:/to alpine \
    sh -c "cp -a /from/. /to/"
```

然后把 `docker-compose.yml` 里 backend 的
`- rs-imagery:/data/imagery` 改成 `- /data/rs/imagery:/data/imagery`，
并在 `volumes:` 段保留 `rs-imagery:` 以免 compose 报「卷不存在」。

## 7. 升级与回滚

```bash
# 升级：先备份
./scripts/backup.sh
cd /opt/rs-platform && git pull
cd deploy/prod
sed -i 's/^TAG=.*/TAG=1.1.0/' .env          # 打新版本号
docker compose --env-file .env up -d --build
./scripts/smoke.sh

# 回滚：镜像 tag 换回上一版
sed -i 's/^TAG=.*/TAG=1.0.0/' .env
docker compose --env-file .env up -d
```

**升级窗口注意**：正在跑的解译任务存在进程内存里，重启即丢，需重提。挑没人用的时候升。

## 8. 离线（内网）部署

外网不可达时，inference 的在线 Sentinel-2 能力用不了，走这两条：

1. **本地高分影像**（主路径）：客户自己的 GF-2 / GF-7 / 无人机影像走「本地解译 + 本地监督分类」，全程不出网。
2. **预置离线演示包**：在能出网的机器上跑一次在线解译生成 bundle，把 `demo_data/*.json`
   拷进 `rs-demo` 卷：

```bash
# 联网机器：生成后从容器里拷出来
docker cp rs-inference:/data/demo ./demo_data

# 内网机器：灌进去
docker cp ./demo_data/. rs-inference:/data/demo/
docker compose restart inference
```

3. **预热瓦片**（救急）：把联网机器的 `inference/.cache` 拷进 `rs-cache` 卷，同景同 tile 不再下载。

镜像本身也要能带进内网：在联网机器 `docker compose build` 后
`docker save rs-platform/backend:TAG rs-platform/inference:TAG rs-platform/frontend:TAG mysql:8.0 | gzip > rs-images.tar.gz`，
内网 `docker load -i` 再 `up -d`（去掉 `--build`）。

## 9. 排障对照

| 现象 | 先查 |
|---|---|
| 页面能开、所有数据空 | backend 是否 healthy；`docker compose logs backend` 里 DB 连接 |
| 登录 500 | 后端挂了或 MySQL 未就绪；`docker compose ps` |
| 解译一直"进行中"、结果不落库 | **`JAVA_CALLBACK_URL` 是否写成 `http://backend:8080/...`**（写成 localhost 必错） |
| 解译返回 401/回调鉴权失败 | 两侧 `INFERENCE_CALLBACK_TOKEN` 不一致 |
| 上传 413 | nginx `client_max_body_size` 未生效（改完要 `docker compose restart frontend`） |
| 三维地图底图空白 | 构建时缺 `VITE_TIANDITU_TOKEN`，需重新 build 前端 |
| 在线解译超时 | 服务器出不了网（AWS STAC），属预期；改走本地影像 |
| 任务"不存在" | inference 被起了多副本/多 worker，任务表分裂，恢复单实例 |

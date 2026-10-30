#!/usr/bin/env bash
# 备份：业务库 + 上传影像。
#
#   ./scripts/backup.sh                 # 默认备份到 /backup/rs-platform
#   BACKUP_ROOT=/data/backup ./scripts/backup.sh
#
# 必须做的两件事：
#   1. 备份完 `mysql` 那份要**试恢复一次**（没演练过的备份等于没有）
#   2. 加进 crontab，例如每天 2:10：
#      10 2 * * * /opt/rs-platform/deploy/prod/scripts/backup.sh >> /var/log/rs-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."                     # 切到 deploy/prod（compose 文件所在目录）

BACKUP_ROOT="${BACKUP_ROOT:-/backup/rs-platform}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M)"
DEST="$BACKUP_ROOT/$STAMP"

# .env 里有数据库密码
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
: "${DB_ROOT_PASSWORD:?缺少 DB_ROOT_PASSWORD（检查 .env）}"
DB_NAME="${DB_NAME:-rs_platform}"

mkdir -p "$DEST"

echo "[$(date '+%F %T')] 开始备份 → $DEST"

# ---- 1. 业务库（--single-transaction：不锁表，业务可继续用） ----
echo "  → MySQL ($DB_NAME)"
docker compose exec -T mysql \
    mysqldump -uroot -p"$DB_ROOT_PASSWORD" \
    --single-transaction --quick --routines --events \
    --databases "$DB_NAME" 2>/dev/null | gzip > "$DEST/db-$DB_NAME.sql.gz"

# ---- 2. 上传影像（直接从 backend 容器的挂载卷打包，不落临时副本） ----
echo "  → 影像目录 /data/imagery"
docker compose exec -T backend tar czf - -C /data/imagery . > "$DEST/imagery.tar.gz"

# ---- 3. 校验：gzip 能否完整解开、文件大小是否合理 ----
for f in "$DEST/db-$DB_NAME.sql.gz" "$DEST/imagery.tar.gz"; do
    gzip -t "$f" || { echo "  [错误] 备份损坏：$f"; exit 1; }
done
echo "  大小：$(du -h "$DEST"/*.gz | awk '{printf "%s ", $1}')"

# ---- 4. 过期清理 ----
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true

echo "[$(date '+%F %T')] 完成"
echo
echo "恢复方法（先停业务，避免写入覆盖）："
echo "  gunzip -c $DEST/db-$DB_NAME.sql.gz | docker compose exec -T mysql mysql -uroot -p\$DB_ROOT_PASSWORD"
echo "  docker compose exec -T backend tar xzf - -C /data/imagery < $DEST/imagery.tar.gz"
echo
echo "建议每季度演练一次恢复：恢复到临时库 rs_platform_restore，抽查 extractions / users 行数。"

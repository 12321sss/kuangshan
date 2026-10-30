#!/usr/bin/env bash
# 茜坑矿区 NISAR 形变趋势分析 —— 一条龙编排（下载 → 分析 → HTML 报告）
#
# 用法：bash scripts/run_xicheng_pipeline.sh
# 产出：docs/茜坑形变趋势.html（双击即可看）
#
# 说明：
#   - fetch_nisar.py 有断点续传 + manifest，重复跑会自动跳过已下载的景；
#   - 分析在下载全部完成后执行，产出自包含 HTML（无外部依赖）。
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
PY=".venv/Scripts/python.exe"

echo "=================================================="
echo "茜坑矿区形变趋势分析管道（下载 → 分析 → 报告）"
echo "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

# 1. 下载 track 18（降轨，覆盖居中，质量最好）全部 8 景
echo "[1/3] 下载 track 18 GUNW 数据 ..."
"$PY" -u scripts/fetch_nisar.py download --track 18 || {
  echo "下载中断（可能是网络），已下载部分保留，可重跑续传"; }

# 2. 确认景数
N=$(ls .cache/nisar/*_018_*.h5 2>/dev/null | wc -l)
echo "[2/3] 已就绪 track 18 景数: $N"

# 3. 分析 + 生成报告
echo "[3/3] 形变趋势分析 + 生成 HTML ..."
"$PY" -u scripts/analyze_xicheng_trend.py --track 18 \
    --out "docs/茜坑形变趋势.html"

echo "=================================================="
echo "完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "报告: docs/茜坑形变趋势.html"
echo "=================================================="

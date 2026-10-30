#!/usr/bin/env bash
# 上线冒烟：逐项验活，全绿才算部署完成。
#
#   ./scripts/smoke.sh                      # 默认 http://127.0.0.1
#   BASE_URL=http://10.0.0.8 ./scripts/smoke.sh
#   USER_NAME=admin USER_PASS=xxx ./scripts/smoke.sh
#
# 只依赖 curl / grep / sed，不要求装 jq（客户服务器常常没有）。
set -uo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1}"
USER_NAME="${USER_NAME:-admin}"
USER_PASS="${USER_PASS:-admin123}"

# 本机若配了 http_proxy，访问 127.0.0.1 会被代理拦（返回 502 upstream），必须绕开
CURL="curl -sS --noproxy * --max-time 30"

pass=0
fail=0

ok()   { pass=$((pass + 1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }

check_http() {   # 名称 URL 期望子串
    local name="$1" url="$2" expect="${3:-}"
    local body
    body=$($CURL "$url" 2>/dev/null) || { bad "$name（连不上 $url）"; return; }
    if [ -n "$expect" ] && ! printf '%s' "$body" | grep -q "$expect"; then
        bad "$name（响应里没有「$expect」）"
        return
    fi
    ok "$name"
}

echo "== 1. 服务健康 =="
check_http "nginx 存活"        "$BASE_URL/healthz"            "ok"
check_http "解译服务（经 nginx）" "$BASE_URL/sentinel/health"   '"status"'
check_http "业务后端"           "$BASE_URL/api/health"          '"status"'

echo
echo "== 2. 登录与鉴权 =="
LOGIN=$($CURL -X POST "$BASE_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$USER_NAME\",\"password\":\"$USER_PASS\"}" 2>/dev/null)

TOKEN=$(printf '%s' "$LOGIN" | sed -n 's/.*"accessToken":"\([^"]*\)".*/\1/p')
if [ -z "$TOKEN" ]; then
    bad "登录失败（检查账号密码，或后端是否起来）"
    printf '%s\n' "$LOGIN" | head -3
    echo
    echo "结果：$pass 通过 / $fail 失败"
    exit 1
fi
ok "登录成功（$USER_NAME）"

AUTH="Authorization: Bearer $TOKEN"

echo
echo "== 3. 业务接口（带令牌） =="
for pair in "影像库:/api/imagery?projectId=1" "边界库:/api/aoi-boundaries?projectId=1" "解译记录:/api/extractions?projectId=1"; do
    name="${pair%%:*}"; path="${pair#*:}"
    body=$($CURL "$BASE_URL$path" -H "$AUTH" 2>/dev/null) || { bad "$name（请求失败）"; continue; }
    if printf '%s' "$body" | grep -q '"code":0'; then
        ok "$name"
    else
        bad "$name（返回非 0）"
        printf '%s\n' "$body" | head -2
    fi
done

echo
echo "== 4. 大文件上传通道（不带 body，只看是否被 nginx 拦 413） =="
code=$($CURL -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/imagery/probe" -H "$AUTH" 2>/dev/null)
if [ "$code" = "400" ] || [ "$code" = "200" ]; then
    ok "上传接口可达（HTTP $code，说明 2GB 限制已放开、请求能进后端）"
elif [ "$code" = "413" ]; then
    bad "上传被 nginx 拦下（413）—— 检查 client_max_body_size"
else
    bad "上传接口异常（HTTP $code）"
fi

echo
if [ "$fail" -eq 0 ]; then
    printf '\033[32m全部通过：%d 项\033[0m\n' "$pass"
    exit 0
fi
printf '\033[31m有 %d 项失败（通过 %d）\033[0m\n' "$fail" "$pass"
exit 1

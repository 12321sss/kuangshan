#!/usr/bin/env bash
# WSL/Ubuntu 侧一键初始化：装 snaphu 解缠环境并自检
#
# 用法（在 WSL 的 Ubuntu 终端里）：
#     bash /mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/inference/scripts/setup_snaphu_linux.sh
#
# 或者先进项目目录再跑：
#     cd ~/kuangshan/inference && bash scripts/setup_snaphu_linux.sh
#
# 做完什么：
#   1. 换阿里云 apt 源（不换源 apt 慢到不可用）
#   2. 装 python3-venv + build-essential（snaphu 是纯 C，必须有编译器）
#   3. 在 ~/rs-venv 建虚拟环境
#   4. 装 snaphu / h5py / rasterio / scipy / scikit-image
#   5. 验证 snaphu 能 import
#   6. 跑一次合成数据解缠，确认整条链路通
#
# 幂等：重复跑不会出问题（已装的东西会跳过）

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; }
step() { echo; echo "──────────────────────────────────────────"; echo "▶ $*"; }

# ---------- 0. 环境自检 ----------
step "0/6 环境自检"

if ! grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    err "这不像 WSL 环境（/proc/version 未含 Microsoft/WSL）"
    warn "如果你在真机 Linux 上跑，脚本也能继续，但注意路径假设"
fi

if [ "$(id -u)" = "0" ]; then
    err "请不要用 root 直接跑，用普通用户 + sudo"
    exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
    err "找不到 sudo，无法安装系统包"
    exit 1
fi

UBUNTU_VER="$(lsb_release -rs 2>/dev/null || echo unknown)"
ok "Ubuntu ${UBUNTU_VER} / 用户 $(whoami)"
ok "内核 $(uname -r)"

# ---------- 1. 换 apt 源 ----------
step "1/6 换国内 apt 源"

if grep -q "mirrors.aliyun.com" /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null; then
    ok "已是阿里云源，跳过"
else
    warn "切换到阿里云源（失败也不影响后续，只是慢）"
    # Ubuntu 24.04+ 用 deb822 格式的 ubuntu.sources；22.04 用 sources.list
    if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
        sudo cp -n /etc/apt/sources.list.d/ubuntu.sources \
                   /etc/apt/sources.list.d/ubuntu.sources.bak 2>/dev/null || true
        sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g;
                     s|http://security.ubuntu.com|https://mirrors.aliyun.com|g;
                     s|http://ports.ubuntu.com|https://mirrors.aliyun.com|g' \
                 /etc/apt/sources.list.d/ubuntu.sources
    fi
    if [ -f /etc/apt/sources.list ]; then
        sudo cp -n /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || true
        sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g;
                     s|http://security.ubuntu.com|https://mirrors.aliyun.com|g' \
                 /etc/apt/sources.list
    fi
    ok "源已切换（备份在 *.bak）"
fi

# ---------- 2. 系统包 ----------
step "2/6 安装编译工具与 python3-venv"

export DEBIAN_FRONTEND=noninteractive
if ! sudo apt-get update -qq; then
    err "apt update 失败，检查网络或源配置"
    exit 1
fi

# build-essential：snaphu 纯 C 项目，没 gcc/make 装不上
PKGS="python3 python3-pip python3-venv build-essential"
MISSING=""
for p in $PKGS; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then
    warn "需要安装:$MISSING"
    sudo apt-get install -y -qq $MISSING || { err "系统包安装失败"; exit 1; }
    ok "系统包已安装"
else
    ok "系统包已齐全"
fi

gcc --version | head -1 | sed 's/^/  /'

# ---------- 3. Python 虚拟环境 ----------
step "3/6 准备 Python 虚拟环境"

VENV="${HOME}/rs-venv"
if [ -x "${VENV}/bin/python" ]; then
    ok "已存在 ${VENV}"
else
    python3 -m venv "${VENV}" || { err "venv 创建失败"; exit 1; }
    ok "已创建 ${VENV}"
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
ok "已激活：$(python --version)"

# ---------- 4. pip 装遥感栈 ----------
step "4/6 安装 snaphu 与遥感依赖（可能要几分钟）"

PIP_MIRROR="-i https://mirrors.aliyun.com/pypi/simple/"
python -m pip install --upgrade pip -q ${PIP_MIRROR} || warn "pip 升级失败，继续"

# 逐个装，失败时能定位到具体包
for pkg in numpy scipy scikit-image h5py rasterio snaphu; do
    if python -c "import ${pkg}" 2>/dev/null; then
        ok "${pkg} 已装（$(python -c "import ${pkg}; print(getattr(${pkg},'__version__','?'))" 2>/dev/null)）"
        continue
    fi
    echo "  安装 ${pkg} ..."
    if ! python -m pip install -q ${PIP_MIRROR} "${pkg}"; then
        err "${pkg} 安装失败"
        # rasterio 有时需要系统 GDAL，给出提示
        if [ "$pkg" = "rasterio" ]; then
            warn "rasterio 失败时可试：sudo apt install -y libgdal-dev gdal-bin"
        fi
        exit 1
    fi
    ok "${pkg} 安装完成"
done

# ---------- 5. 验证 snaphu ----------
step "5/6 验证 snaphu"

if python -c "import snaphu, sys; print('  snaphu', getattr(snaphu,'__version__','?'))" 2>/dev/null; then
    ok "snaphu 可 import"
else
    err "snaphu 装上了但 import 失败，看上面的报错"
    exit 1
fi

# ---------- 6. 端到端自检 ----------
step "6/6 端到端自检（合成数据跑一次解缠）"

# 定位项目目录：优先当前目录（假设在 inference/ 下执行），否则试常见挂载路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${PROJ_DIR}/scripts/unwrap.py" ]; then
    cd "${PROJ_DIR}" || exit 1
    ok "项目目录：${PROJ_DIR}"
    echo
    if python scripts/unwrap.py --synthetic --backend snaphu --out "${HOME}/out_snaphu_test"; then
        echo
        ok "合成数据解缠成功，产物在 ${HOME}/out_snaphu_test"
    else
        err "解缠脚本执行失败，见上面输出"
        exit 1
    fi
else
    warn "没找到 ${PROJ_DIR}/scripts/unwrap.py，跳过端到端自检"
    warn "请 cd 到 inference/ 目录后手动执行："
    warn "  python scripts/unwrap.py --synthetic --backend snaphu --out ~/out_test"
fi

# ---------- 完成 ----------
step "全部完成"
cat <<EOF

后续用法：

  1. 每次进 WSL 先激活环境：
       source ~/rs-venv/bin/activate

  2. 真实数据解缠：
       cd <项目>/inference
       python scripts/unwrap.py --input /path/GUNW.h5 \\
           --aoi 114.87,28.57,114.93,28.62 --backend snaphu --out ~/out_real

  3. 产物拷回 Windows（平台直接可用）：
       cp ~/out_real/*.tif /mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/inference/.cache/nisar/

  4. 与纯 Python 后端对比精度：
       python scripts/unwrap.py --synthetic --backend python --out ~/out_py
       # 比较两个目录里 [自检] 打印的 RMS 残差

EOF

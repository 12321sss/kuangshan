# WSL + snaphu 部署指南（启用 20m 解缠的 Linux 后端）

> 编写：2026-10-30
> 目的：让本机具备 snaphu 解缠能力（工业级 network-flow），补齐纯 Python 后端在整景/长时序上的精度短板
> 关联：`docs/26-形变监测落地瓶颈与约束.md`（为什么需要 Linux）、`inference/scripts/unwrap.py`（跨平台解缠脚本）

---

## 一、本机现状诊断（实测，2026-10-30）

| 项目 | 结果 | 影响 |
|---|---|---|
| 系统 | Windows 11 家庭版 中文版 Build 26200 | 支持 WSL2（家庭版没有 Hyper-V，但 WSL2 不需要） |
| 内存 | **31.3 GB** | 够用，WSL2 默认最多吃 50%（约 15 GB） |
| 磁盘可用 | **415 GB** | 充足（Ubuntu 约 1~2 GB，加上数据建议留 50 GB） |
| CPU 虚拟化 | **已开启**（VirtualizationFirmwareEnabled=True） | WSL2 的前提已满足 |
| VirtualMachinePlatform | **Enabled** | 虚拟机平台已启用，省一步 |
| **Microsoft-Windows-Subsystem-Linux** | **Disabled** | ← **必须启用，是卡点** |
| 已装 Linux 发行版 | 无 | 需要装 Ubuntu |
| 当前用户权限 | **管理员** | 可以自己启用功能，不用找人 |
| **`wsl.exe` 可执行性** | **被 WorkBuddy 安全策略拦（程序黑名单）** | ← **第一道关卡** |

**结论**：硬件和权限都够，只差两件事——放行 `wsl.exe`、启用 WSL 功能。

---

## 二、三道关卡（必须按顺序）

```
第 1 关：WorkBuddy 安全中心放行 wsl.exe       ← 不做这步，后面所有命令都 Permission denied
   ↓
第 2 关：启用 WSL 功能 + 重启                   ← 需要管理员，DISM 一条命令
   ↓
第 3 关：安装 Ubuntu + 在里面装 snaphu          ← 装完就能跑 20m 解缠
```

---

## 三、第 1 关：放行 `wsl.exe`（界面操作，约 1 分钟）

这是 WorkBuddy 客户端的安全策略，**不是 Windows 系统功能**，只能用界面改：

1. 打开 WorkBuddy → **设置 / 安全中心**
2. 找到 **命令安全**（Command Security）→ **程序黑名单**（Program Blacklist）
3. 在列表里找到 `wsl.exe`（路径通常是 `C:\Windows\system32\wsl.exe`）
4. **移除 / 放行** 这一项
5. 保存

**验证方法**：在 WorkBuddy 里说一句「跑一下 wsl --status」，或者直接在终端执行：

```bash
wsl.exe --status
```

看到版本信息（而不是 `PROGRAM BLOCKED BY SECURITY POLICY`）就表示放行成功。

> ⚠️ 如果列表里没有 `wsl.exe` 但有通配规则（比如 `*.exe`、系统目录整目录禁用），需要调整那条规则，
> 别把整个 `C:\Windows\system32` 都放开——只放行 `wsl.exe` 及其配套（`wslhost.exe`、`wslservice.exe`）。

---

## 四、第 2 关：启用 WSL 功能（管理员 PowerShell，约 2 分钟 + 重启）

**方式 A：一条命令搞定（推荐，Windows 11 支持）**

管理员 PowerShell 里执行：

```powershell
wsl --install
```

它会自动完成：启用 `Microsoft-Windows-Subsystem-Linux`、下载 WSL2 内核、装默认 Ubuntu。
**然后重启电脑**。

**方式 B：不想自动装发行版，只启用功能**

```powershell
# 启用 WSL 功能（VirtualMachinePlatform 本机已启用，可在同一条里带上也无害）
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

# 重启
Restart-Computer
```

重启后用管理员 PowerShell 把 WSL2 设为默认版本：

```powershell
wsl --set-default-version 2
wsl --update
```

> **为什么必须重启**：WSL 是内核级功能（`lxss` 驱动），DISM 改的是系统组件，不重启不生效。
> 这是我唯一建议用 PowerShell 管理员的场景，其余命令都在 WSL 里跑。

**验证**：

```powershell
wsl --status
# 期望看到：默认版本: 2 / 内核版本: x.x.x
```

---

## 五、第 3 关：安装 Ubuntu + snaphu（约 10 分钟，取决于网速）

### 5.1 装 Ubuntu

```powershell
# 列出可装发行版
wsl --list --online

# 装 Ubuntu 24.04（或 22.04，都行；22.04 生态更稳）
wsl --install -d Ubuntu-24.04
```

首次启动会要求设置 **Linux 用户名和密码**（跟 Windows 无关，自己记好）。

验证：

```powershell
wsl -l -v
# NAME            STATE           VERSION
# Ubuntu-24.04    Running         2
```

### 5.2 首次进入先换源 + 装编译工具（国内必做）

进入 WSL：

```powershell
wsl
```

在 Ubuntu 里执行：

```bash
# 换阿里云源（不换源 apt 会很慢，甚至超时）
sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g; s|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null \
  || sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g; s|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list

sudo apt update
sudo apt install -y python3 python3-pip python3-venv build-essential
```

> snaphu 是纯 C 项目，`build-essential`（gcc、make）必须有，否则 pip 装不上。

### 5.3 装 snaphu 和遥感栈

```bash
# 建议用 venv，别污染系统 python
python3 -m venv ~/rs-venv
source ~/rs-venv/bin/activate

pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    snaphu h5py rasterio numpy scipy scikit-image
```

> `rasterio` 在 Linux 上有预编译轮子（manylinux），不用编译 GDAL，比 Windows 省事。

验证 snaphu 能跑：

```bash
python -c "import snaphu; print('snaphu', snaphu.__version__)"
```

### 5.4 关键一步：让 WSL 能访问 Windows 的项目目录

WSL 里 Windows 的 C 盘挂在 `/mnt/c/`。项目路径含中文，建议先软链到英文路径避免各种坑：

```bash
ln -s "/mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016" ~/kuangshan
cd ~/kuangshan/inference
```

如果软链因中文路径失败，改用 `wsl.conf` 挂载或直接把 `inference/` 复制进 WSL 家目录（数据量大时再考虑）。

---

## 六、验证：跑通 20m 解缠（snaphu 后端）

### 6.1 先跑合成数据（不需要真实 GUNW）

```bash
cd ~/kuangshan/inference
source ~/rs-venv/bin/activate

python scripts/unwrap.py --synthetic --backend snaphu --out ~/out_snaphu
```

**期望输出**：

```
[合成模式] 生成 (114.87, 28.57, 114.93, 28.62) 内的模拟 20m 干涉图
  窗口 (240, 320)，有效像元 69966/76800
解缠完成（后端 snaphu，耗时 x.xx s）
产物已写入 ...
[自检] 与合成真值对比：
  常数偏置 ... mm
  去偏置后残差：RMS x.xx mm
  低相干区被正确屏蔽：True
```

**和纯 Python 后端对比**：把同一份合成数据分别用 `--backend python` 和 `--backend snaphu` 跑，
比较自检的 RMS 残差。snaphu 在低相干边界处通常更稳（残差更小、条纹断裂更少）。

### 6.2 再跑真实数据（有 GUNW 时）

```bash
python scripts/unwrap.py \
    --input /path/to/NISAR_GUNW.h5 \
    --aoi 114.87,28.57,114.93,28.62 \
    --backend snaphu \
    --out ~/out_real
```

产物（与 Windows 后端完全同格式，可直接拷回 Windows 给平台用）：

```
unwrapped_phase.tif   解缠相位（弧度）
los_disp_mm.tif       LOS 位移（mm）
coherence.tif         相干性
unwrap_meta.json      后端名 = "snaphu"，便于事后追溯
```

### 6.3 拷回 Windows

```bash
cp ~/out_real/*.tif "/mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/inference/.cache/nisar/"
```

平台侧读取逻辑不用改——产物格式、CRS、nodata 与纯 Python 后端一致。

---

## 七、本机跑得动什么、跑不动什么

有 31 GB 内存和 WSL2 之后，能力边界变化如下：

| 任务 | 之前（纯 Windows） | 现在（WSL2 + snaphu） | 说明 |
|---|---|---|---|
| 单 AOI 20m 解缠（几十 km²） | ✅ 纯 Python 可跑 | ✅ 更稳 | snaphu 在低相干区抗噪更好 |
| **整景 20m 解缠** | ❌ | ✅ **可以跑了** | 内存够（31 GB），snaphu 处理整景不再是问题 |
| 几十景 SBAS 时序反演 | ❌ | ⚠️ 勉强 | 依赖数据量与算法；建议先在 WSL 里试 5~10 景 |
| Sentinel-1 SLC 干涉（isce2） | ❌ | ⚠️ 仍吃力 | isce2 安装复杂、单景处理吃内存，31 GB 可试但慢 |
| MintPy 长时序 | ❌ | ⚠️ 需评估 | 依赖 isce2 产品，栈很重 |

**建议**：先只用 WSL 做**解缠**（snaphu 单步），干涉和时间序列仍在 Windows 侧用现有链路。
这是投入产出比最高的用法，不要一上来就搭 isce2 + MintPy 全家桶。

---

## 八、WSL2 内存与磁盘调优（可选，但建议做）

WSL2 默认最多吃宿主一半内存，且磁盘虚拟盘会一直涨。在 **Windows** 侧建 `C:\Users\asus\.wslconfig`：

```ini
[wsl2]
# 限制内存上限，避免 WSL 抢满导致 Windows 卡顿（31GB 机器给 16GB 足够跑整景解缠）
memory=16GB
# 处理器核数（i7-4790 是 4 核 8 线程，留 2 核给 Windows）
processors=6
# 交换分区
swap=8GB

[experimental]
# 释放未使用的磁盘空间（默认只增不减）
autoMemoryReclaim=gradual
```

改完执行 `wsl --shutdown` 再重启 WSL 生效。

> 注意：`processors=6` 是按 4C8T 估的；实际以 `Get-CimInstance Win32_Processor` 的
> `NumberOfLogicalProcessors` 为准，别超过物理线程数。

---

## 九、常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `wsl.exe: Permission denied` / `PROGRAM BLOCKED BY SECURITY POLICY` | 安全中心程序黑名单 | 回第 1 关放行，**不要试图绕过** |
| `wsl --install` 报 `WSL 2 requires an update to its kernel component` | 内核包没装 | `wsl --update`，或手动装 [WSL2 内核更新包](https://aka.ms/wsl2kernel) |
| `wsl --install` 卡在下载 | 网络 | 换成 `wsl --install --web-download`，或手动下 appx 离线装 |
| Ubuntu 里 `pip install snaphu` 报 `gcc: not found` | 缺编译工具 | `sudo apt install -y build-essential` |
| `pip install rasterio` 尝试编译 GDAL（很久） | 用了国内镜像的旧版 | 加 `--only-binary :all:`，或升级 pip |
| 访问 `/mnt/c/...` 中文路径报错 | 编码/字符集 | 软链到英文路径，或把数据复制进 `~` |
| 解缠脚本报 `ModuleNotFoundError: algorithms` | cwd 不对 | 必须在 `inference/` 目录下执行（脚本靠相对路径 import） |
| WSL 里 `python` 指向系统 python 而非 venv | 没 activate | `source ~/rs-venv/bin/activate`，或直接用 `~/rs-venv/bin/python` |
| 磁盘越来越小 | WSL 虚拟盘只增不减 | `wsl --shutdown` 后 `Optimize-VHD`，或配 `autoMemoryReclaim` |

---

## 十、如果不想折腾 WSL 的备选方案

按推荐度排序：

1. **继续用纯 Python 后端**（`--backend python`）
   已经跑通、已测精度（RMS 2.92 mm / 峰值 40 mm）。AOI 几十 km² 的日常解译够用，
   零额外环境成本。**这是我建议的默认选择**。

2. **租一台按量计费的 Linux 云服务器**
   按小时计费，跑完解缠就释放。优势：不用改本机环境、内存可临时拉高到 64 GB、
   装 snaphu 一条 `pip install`。适合「偶尔要处理整景/长时序」的场景。
   注意：NISAR/Sentinel 数据要先传上去，带宽可能是瓶颈。

3. **本机 WSL2**（本文档）
   适合「长期要在本机做 InSAR 处理」的情况。一次性投入约 20 分钟，之后随时可用。

4. **暂时不追求 20m**，用 NISAR 官方 80m 已解缠产品
   A 阶段已跑通，完全不依赖 snaphu。精度牺牲但零成本，演示够用。

---

## 十一、一句话总结

> 本机硬件和权限都满足，卡点只有两个：**安全中心放行 `wsl.exe`**（界面操作）、
> **启用 WSL 功能**（`wsl --install` + 重启）。
> 之后在 Ubuntu 里 `pip install snaphu` 就能跑整景解缠，产物格式与现有 Python 后端完全一致，
> 平台侧一行代码都不用改。
>
> 但如果你只是做矿区 AOI 级别的日常解译，**现有的纯 Python 后端已经够用**，
> 不必为了 snaphu 折腾环境。

---

## 十二、装完之后：三条命令搞定剩余步骤

前提：`wsl --install` 已跑完并**重启过电脑**，`wsl -l -v` 能看到 Ubuntu。

### 第 1 条：确认 WSL2 与发行版（Windows 终端）

```bash
wsl --status
wsl -l -v
```

期望 `VERSION` 列是 **2**。如果是 1：

```bash
wsl --set-version Ubuntu-24.04 2
wsl --set-default-version 2
```

### 第 2 条：进 WSL 建项目快捷路径

```bash
wsl
```

进 Ubuntu 后：

```bash
# 中文路径在 /mnt/c 下容易出坑，软链成英文路径
ln -sfn "/mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016" ~/kuangshan
ls ~/kuangshan/inference/scripts/
```

### 第 3 条：跑一键初始化脚本（换源 + 装 snaphu + 自检）

```bash
bash ~/kuangshan/inference/scripts/setup_snaphu_linux.sh
```

脚本会依次做（幂等，可重复跑）：

| 步骤 | 动作 | 失败会怎样 |
|---|---|---|
| 0 | 检查是否 WSL、是否 root、有无 sudo | 非 WSL 只警告；以 root 跑直接退出 |
| 1 | 换阿里云 apt 源（24.04 的 deb822 与 22.04 的 sources.list 都兼容，自动备份 `.bak`） | 换失败只警告，继续（只是慢） |
| 2 | 装 `python3-venv` + **`build-essential`**（snaphu 纯 C，没编译器必失败） | 失败即退出 |
| 3 | 在 `~/rs-venv` 建虚拟环境 | 失败即退出 |
| 4 | 逐个 pip 装 numpy / scipy / scikit-image / h5py / rasterio / **snaphu** | 哪个失败报哪个；rasterio 失败会给 `libgdal-dev` 提示 |
| 5 | `import snaphu` 验证 | 失败即退出 |
| 6 | 跑 `scripts/unwrap.py --synthetic --backend snaphu` 端到端自检 | 失败即退出 |

**成功的样子**（末尾会打印）：

```
✓ snaphu 可 import
解缠完成（后端 snaphu，耗时 x.xx s）
[自检] 与合成真值对比：
  常数偏置 ... mm
  去偏置后残差：RMS x.xx mm
  低相干区被正确屏蔽：True
✓ 合成数据解缠成功，产物在 /home/xxx/out_snaphu_test
```

### 之后每次用（三步）

```bash
# 1. 激活环境
source ~/rs-venv/bin/activate

# 2. 跑真实数据
cd ~/kuangshan/inference
python scripts/unwrap.py --input /path/GUNW.h5 \
    --aoi 114.87,28.57,114.93,28.62 --backend snaphu --out ~/out_real

# 3. 产物拷回 Windows（平台直接可读，格式与纯 Python 后端一致）
cp ~/out_real/*.tif \
   "/mnt/c/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/inference/.cache/nisar/"
```

### 对比两种后端精度（建议做一次）

```bash
cd ~/kuangshan/inference && source ~/rs-venv/bin/activate
python scripts/unwrap.py --synthetic --backend python --out ~/out_py
python scripts/unwrap.py --synthetic --backend snaphu --out ~/out_snaphu
# 比较两次 [自检] 的 RMS 残差，snaphu 通常更小（低相干边界附近尤其明显）
```

---

## 十三、为什么 AI 不能直接代跑 `wsl.exe`

WorkBuddy 的命令执行环境受**安全策略 → 命令安全 → 程序黑名单**约束，
`wsl.exe` 在黑名单里时长这样：

```
PROGRAM BLOCKED BY SECURITY POLICY - The sandbox prevented a program on the
configured Program Blacklist from starting:
  - wsl.exe (C:\Windows\system32\wsl.exe)
```

这条**不是沙箱权限问题，无法通过提权或换 shell 绕过**（系统会拦截任何等价调用）。
两条路：

1. **你在自己的终端里跑**（本文档所有命令都适用，你本来就是这么装的）——
   装完后按第十二节走，脚本已封装好；
2. **在 WorkBuddy 安全中心把 `wsl.exe` 移出黑名单**，之后 AI 就能直接代跑：
   自动装 Ubuntu、装 snaphu、跑解缠、把产物拷回项目目录，全程不用你敲命令。

> 推荐第 2 条：放行一次，以后所有 WSL 操作（排查、重装、跑数据）都能自动化。
> 放行范围只给 `wsl.exe`（必要时加 `wslhost.exe`、`wslservice.exe`），
> 不要把整个 `C:\Windows\system32` 放开。

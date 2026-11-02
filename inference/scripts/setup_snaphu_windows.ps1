# SNAPHU 一键安装（Windows）
#
# 为什么需要这个脚本
# ------------------
# 20m 相位解缠要用 SNAPHU（工业级 network-flow 算法）。snaphu-py 是 Python 绑定，
# 安装时要编译 C 源码，Windows 没编译器就装不上。ESA 官方提供 **Windows 预编译包**
# （MSYS2 构建，v1.4.2），算法与 snaphu-py 完全一致，且不需要任何编译环境。
#
# 用法（在仓库根目录或任意位置执行）：
#     powershell -ExecutionPolicy Bypass -File inference/scripts/setup_snaphu_windows.ps1
#
# 装完后 inference 会自动发现它（`algorithms/unwrap.py` 的候选路径里含本脚本的安装位置），
# 也可用环境变量 SNAPHU_EXE 指定别的位置。
#
# 验证：
#     inference\.venv\Scripts\python.exe -c "from algorithms.unwrap import find_snaphu_exe; print(find_snaphu_exe())"

$ErrorActionPreference = "Stop"

$InstallDir = "D:\Dev\snaphu"
$ZipUrl = "https://step.esa.int/thirdparties/snaphu/1.4.2-2/snaphu-v1.4.2_win64.zip"
$ZipPath = Join-Path $env:TEMP "snaphu-v1.4.2_win64.zip"

Write-Host "=== SNAPHU Windows 安装 ===" -ForegroundColor Cyan
Write-Host "目标目录: $InstallDir"

if (Test-Path (Join-Path $InstallDir "snaphu-v1.4.2_win64\bin\snaphu.exe")) {
    Write-Host "已安装，跳过下载。" -ForegroundColor Green
} else {
    Write-Host "下载 $ZipUrl"
    # ESA 站点在国内偶有超时，失败重试 3 次
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing -TimeoutSec 180
            break
        } catch {
            if ($i -eq 3) { throw "下载失败（已重试 3 次）: $_" }
            Write-Host "  第 $i 次失败，5 秒后重试..." -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force
    Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
}

$Exe = Join-Path $InstallDir "snaphu-v1.4.2_win64\bin\snaphu.exe"
if (-not (Test-Path $Exe)) { throw "解压后未找到 snaphu.exe" }

Write-Host "验证 snaphu.exe ..."
& $Exe 2>&1 | Select-Object -First 3

Write-Host ""
Write-Host "安装完成：$Exe" -ForegroundColor Green
Write-Host "inference 会自动在候选路径里找到它；如需自定义位置，设置环境变量："
Write-Host "  setx SNAPHU_EXE `"$Exe`""

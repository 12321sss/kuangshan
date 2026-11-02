"""20m 高分辨率相位解缠（C 阶段）。

把 GUNW 的 20m wrappedInterferogram（复数）解缠成连续相位，再把分辨率
从 80m（官方 unwrapped 产品）提到 20m，用于识别单个边坡的形变。

方案
----
用 SNAPHU（Statistical-Cost Network-Flow Algorithm for Phase Unwrapping）做解缠。
它是工业级解缠器，与 NISAR 同属 NASA/isce 生态。

**三个后端**（按优先级自动选择，见 `unwrap_auto`）：

  | 后端 | 依赖 | 平台 | 质量 |
  |---|---|---|---|
  | `snaphu` | snaphu-py（Python 绑定，纯 C 需编译器） | 仅 Linux/macOS | 工业级 network-flow |
  | `snaphu-exe` | **snaphu.exe 预编译二进制**（ESA 官方，无需编译器） | **Windows 也可** | **与上者同一算法**，工业级 |
  | `python` | scikit-image（有 cp313 预编译轮子） | 全平台 | 2D Herráez，AOI 小时可用 |

演进过程（为什么有三个）：
  1. 最初只有 snaphu-py → Windows 装不上（纯 C 需编译器），C 阶段卡死；
  2. 加了纯 Python 降级（scikit-image）→ Windows 能跑，但实测与官方产品
     空间相关仅 r≈0.65、残差 RMS 11mm（信号本身 std 13mm），精度不够硬；
  3. 发现 ESA 官方提供 **Windows 预编译 snaphu.exe**（1.4.2，MSYS2 构建），
     于是加 `unwrap_snaphu_exe` 后端：**无需编译器、无需 Linux，直接拿到工业级算法**。

三个后端产物格式完全一致（unwrapped_phase.tif / los_disp_mm.tif / coherence.tif），
平台侧不用改。元数据里记录实际用的是哪个后端，便于事后追溯。

本模块职责（纯 Python，可单测）：
  1. read_wrapped：从 GUNW 读 20m 复数干涉图 + 相干性 + mask
  2. to_phase_corr：转成相位 + 相关性（各后端共用输入）
  3. unwrap_auto：按环境选后端
  4. phase_to_los_mm：解缠相位 → LOS 位移（与 sbas 同口径）

约定
----
- 相位无效处（NaN 复数 / mask 无效）→ 解缠后仍是 NaN
- 输出 LOS 位移单位毫米，正值 = 地面向卫星靠近
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

L_BAND_WAVELENGTH_M = 299792458.0 / 1.229e9  # ≈ 0.2439 m

# snaphu 可执行文件的查找顺序：环境变量 → 本机常见安装位置 → PATH。
# 允许用 SNAPHU_EXE 指定别的版本/位置，不用改代码。
_SNAPHU_EXE_ENV = "SNAPHU_EXE"
_SNAPHU_EXE_CANDIDATES = [
    r"D:\Dev\snaphu\snaphu-v1.4.2_win64\bin\snaphu.exe",
    r"C:\Program Files\snaphu\bin\snaphu.exe",
    "/usr/local/bin/snaphu",
    "/usr/bin/snaphu",
]


def _resample_iono(h, base_unwrapped: str, polar: str,
                   x20: np.ndarray, y20: np.ndarray,
                   epsg: int) -> np.ndarray | None:
    """把 80m 网格上的电离层相位屏插值到给定的 20m 网格。

    参数
    ----
    h：已打开的 h5py 文件句柄
    base_unwrapped：unwrappedInterferogram 的组路径
    x20 / y20：目标 20m 网格的 UTM 坐标（x 递增、y 递减）
    epsg：投影 EPSG（仅用于校验，实际按坐标插值）

    返回
    ----
    与 (len(y20), len(x20)) 同形状的相位屏（弧度）；无该数据集时返回 None。

    实现说明
    --------
    两套网格同为 UTM、轴对齐、只是间距不同（80m vs 20m），因此不需要通用的
    坐标变换库：按坐标算出 20m 像元在 80m 数组中的**分数索引**，再做双线性插值即可。
    窗口按 20m 网格的外接范围裁一小块 80m 数据，避免读整景（整景 4257×4329）。
    """
    try:
        ds = h[f"{base_unwrapped}/{polar}/ionospherePhaseScreen"]
    except KeyError:
        return None

    x80 = h[f"{base_unwrapped}/xCoordinates"][:]
    y80 = h[f"{base_unwrapped}/yCoordinates"][:]

    # 80m 网格上的外接窗口（多留 2 像素给插值边界）
    c0 = max(0, int(np.searchsorted(x80, x20.min())) - 2)
    c1 = min(len(x80), int(np.searchsorted(x80, x20.max())) + 3)
    # y80 递减：用反转后的搜索
    r0 = max(0, len(y80) - int(np.searchsorted(y80[::-1], y20.max())) - 3)
    r1 = min(len(y80), len(y80) - int(np.searchsorted(y80[::-1], y20.min())) + 2)
    if r1 <= r0 or c1 <= c0:
        return None

    blk = ds[r0:r1, c0:c1].astype(np.float64)
    if not np.isfinite(blk).any():
        return None

    # 分数索引：把 20m 坐标映射到裁剪后的 80m 子数组
    dx = x80[min(c0 + 1, len(x80) - 1)] - x80[c0]
    fx = (x20 - x80[c0]) / dx if abs(dx) > 1e-9 else np.zeros_like(x20)
    # y80 递减 → 行索引随 y 增大而减小，故 dy 为负，fy 自然为负增量，符合预期
    dy = y80[min(r0 + 1, len(y80) - 1)] - y80[r0]
    fy = (y20 - y80[r0]) / dy if abs(dy) > 1e-9 else np.zeros_like(y20)

    FY, FX = np.meshgrid(fy, fx, indexing="ij")
    # 屏里 NaN（滤波插值区）用 0 填充，避免把 NaN 带到解缠输入
    filled = np.where(np.isfinite(blk), blk, 0.0)
    from scipy.ndimage import map_coordinates
    out = map_coordinates(filled, [FY, FX], order=1, mode="nearest")
    return out.astype(np.float32)


def read_wrapped(path: Path,
                 aoi_wsen: tuple[float, float, float, float] | None = None,
                 polar: str = "HH",
                 apply_iono: bool = True) -> dict:
    """读 GUNW 的 20m wrapped 干涉图。

    返回 {wrapped(复数), coherence, mask, epsg, x, y, spacing}

    wrapped 的无效处是 nan+nanj（产品 _FillValue）。

    apply_iono：是否减电离层相位屏（默认 True）。
    为什么需要：L 波段电离层延迟在**大范围**上可达几个 rad（实测某景
    半幅内 std 从 4.82 rad 降到 0.96 rad），不减会严重污染大 AOI 的解缠；
    小窗口（几 km）内电离层近似常数，减不减对相对形变几乎无影响。
    电离层屏在 80m 网格上，这里按坐标插值上采样到 20m 网格。
    """
    import h5py
    from rasterio.warp import transform as wtrans

    B = "science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram"
    BU = "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram"
    with h5py.File(path, "r") as h:
        epsg = int(h[f"{B}/projection"][()])
        xc = h[f"{B}/xCoordinates"][:]
        yc = h[f"{B}/yCoordinates"][:]

        if aoi_wsen is not None:
            W, S, E, N = aoi_wsen
            xs, ys = wtrans("EPSG:4326", f"EPSG:{epsg}", [W, E], [S, N])
            c0, c1 = np.searchsorted(xc, [xs[0], xs[1]])
            r0, r1 = np.searchsorted(yc[::-1], [ys[0], ys[1]])
            r0, r1 = len(yc) - r1, len(yc) - r0
            r0, r1 = max(0, r0), min(len(yc), r1)
            c0, c1 = max(0, c0), min(len(xc), c1)
            if r1 <= r0 or c1 <= c0:
                raise ValueError(f"AOI 与影像不相交：{aoi_wsen}")
        else:
            r0, r1, c0, c1 = 0, len(yc), 0, len(xc)

        wrapped = h[f"{B}/{polar}/wrappedInterferogram"][r0:r1, c0:c1]
        coh = h[f"{B}/{polar}/coherenceMagnitude"][r0:r1, c0:c1]
        mask = h[f"{B}/mask"][r0:r1, c0:c1]
        x = xc[c0:c1]
        y = yc[r0:r1]

        # 电离层相位屏（80m 网格）→ 插值到 20m 网格
        iono_20m = None
        if apply_iono:
            iono_20m = _resample_iono(h, BU, polar, x, y, epsg)

    if iono_20m is not None:
        # 复数域去相位：乘 exp(-i*iono)，等效于相位减去屏
        wrapped = wrapped * np.exp(-1j * iono_20m).astype(wrapped.dtype)

    return {
        "wrapped": wrapped, "coherence": coh, "mask": mask,
        "epsg": epsg, "x": x, "y": y, "spacing": 20.0,
    }


def to_phase_corr(wrapped: np.ndarray, coherence: np.ndarray,
                  mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """转成 snaphu 输入：缠绕相位（弧度，[-π,π]）与相关性（0~1）。

    相位 = angle(wrapped)；无效像元置 NaN。
    snaphu 用「相关性」作为解缠的置信度（越高越可信）。
    """
    phase = np.angle(wrapped).astype(np.float32)
    corr = coherence.astype(np.float32)
    # 无效：mask=0 或相位/相关性非有限
    invalid = (mask == 0) | ~np.isfinite(phase) | ~np.isfinite(corr)
    phase[invalid] = np.nan
    corr[invalid] = np.nan
    return phase, corr


def phase_to_los_mm(unwrapped_phase: np.ndarray,
                    wavelength_m: float = L_BAND_WAVELENGTH_M) -> np.ndarray:
    """解缠相位（弧度）→ LOS 位移（毫米），与 sbas.phase_to_los_mm 同口径。

    正值 = 地面向卫星靠近（LOS 缩短）。
    """
    return unwrapped_phase * (wavelength_m / (4 * math.pi)) * 1000.0


def read_unwrapped_phase(path: Path) -> np.ndarray:
    """读 snaphu 输出的解缠相位（.unw 二进制文件，float32 行优先）。

    snaphu-py 的 unwrap 函数默认输出 float32 的二维数组，逐行存储。
    若后续用其它格式，在这里加分支，上层不用改。
    """
    data = np.fromfile(path, dtype="<f4")
    # 需要形状：由调用方已知，这里只返回一维，由调用方 reshape
    # 实际 snaphu-py 返回 numpy 数组，不经文件；此函数为「独立 snaphu 可执行
    # 文件输出」场景预留。当前主路径用 snaphu-py 的 Python API 直接拿数组。
    return data

# ---------------------------------------------------------------------------
# 解缠后端
# ---------------------------------------------------------------------------

def unwrap_python(phase: np.ndarray, corr: np.ndarray,
                  coh_min: float = 0.05) -> np.ndarray:
    """纯 Python 解缠（Windows 可用），不依赖 snaphu 二进制。

    用 `skimage.restoration.unwrap_phase`（Herráez 2D 方法）。它的 masked array
    语义正好符合需求：被 mask 的像元**不参与解缠、也不影响邻域**，
    因此低相干区（水体、植被遮挡、叠掩）不会把噪声扩散到整个 AOI。

    参数
    ----
    phase  : 缠绕相位（弧度，[-π,π)，NaN 表示无效）
    corr   : 相关性 0~1（越低越不可信）
    coh_min: 相干性阈值，低于此值视为无效（默认 0.05，仅剔除近乎全噪的像元）

    返回
    ----
    解缠相位（弧度，float32），无效处为 NaN

    局限
    ----
    Herráez 是全局最小二乘类方法，对**大范围强噪声**不如 snaphu 的
    network-flow 稳健。AOI 在几十 km² 内、相干性尚可时误差可接受；
    若做整景或长时序，仍应上 Linux 用 snaphu。
    """
    from skimage.restoration import unwrap_phase

    if phase.size == 0:
        return phase.astype(np.float32)

    invalid = (~np.isfinite(phase)) | (~np.isfinite(corr)) | (corr < coh_min)
    if invalid.all():
        # 全无效：没有什么可解缠的
        return np.full(phase.shape, np.nan, dtype=np.float32)

    data = np.where(invalid, 0.0, phase)
    masked = np.ma.array(data, mask=invalid)
    out = unwrap_phase(masked)
    arr = np.asarray(np.ma.filled(out, np.nan), dtype=np.float32)
    arr[invalid] = np.nan
    return arr


def find_snaphu_exe() -> str | None:
    """查找 snaphu 可执行文件，找不到返回 None。

    顺序：环境变量 SNAPHU_EXE → 本机常见安装位置 → PATH。
    找到即返回绝对路径，供 `unwrap_snaphu_exe` 调用。
    """
    env = os.environ.get(_SNAPHU_EXE_ENV)
    if env and Path(env).is_file():
        return env
    for cand in _SNAPHU_EXE_CANDIDATES:
        if Path(cand).is_file():
            return cand
    # PATH 里找（Linux 上 apt/编译安装后通常在这里）
    for name in ("snaphu", "snaphu.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def unwrap_snaphu_exe(phase: np.ndarray, corr: np.ndarray,
                      coh_min: float = 0.05,
                      exe: str | None = None,
                      mode: str = "deformation",
                      timeout: int = 1800) -> np.ndarray:
    """调用 snaphu 可执行文件解缠（工业级 network-flow，Windows 可用）。

    为什么用它而不是 snaphu-py：snaphu-py 是 Python 绑定，安装时要编译 C 源码，
    Windows 没编译器就装不上。ESA 官方提供 Windows 预编译的 snaphu.exe
    （MSYS2 构建），算法完全一样，而且不需要任何编译环境。

    参数
    ----
    phase：缠绕相位（弧度，[-π,π)，NaN=无效）
    corr：相关性 0~1（NaN=无效）
    mode：'deformation'（-d，形变场景，默认）/ 'topography'（-t）/ 'smooth'（-s）
    timeout：子进程超时（秒）。整景大 AOI 可能跑几分钟。

    返回
    ----
    解缠相位（弧度，float32），无效处 NaN

    实现要点
    --------
    - **必须用配置文件显式声明三个文件的格式**：snaphu 1.4.2 的默认值是
      输入 `COMPLEX_DATA`（复数）、输出与相关性 `ALT_LINE_DATA`（双通道：
      幅度+相位）。若按单通道 float32 读写，snaphu 会把数据当复数对/双通道解读，
      结果完全错乱（实测：合成数据 RMS 从 2.9mm 恶化到 40.6mm）。
      这里统一声明为 `FLOAT_DATA`（单通道 float32），读写都简单。
    - snaphu 只吃无 NaN 的输入：无效像元填 0 相位 + 0 相关性，解缠后还原 NaN。
    - 输入/输出都是行优先（row-major）float32，linelength = 列数。
    """
    exe = exe or find_snaphu_exe()
    if not exe:
        raise FileNotFoundError(
            "未找到 snaphu 可执行文件。\n"
            "  Windows：下载 ESA 官方预编译包 snaphu-v1.4.2_win64.zip 解压后，\n"
            "           设置环境变量 SNAPHU_EXE 指向 bin/snaphu.exe；\n"
            "  Linux/macOS：apt install snaphu 或自行编译。"
        )

    if phase.size == 0:
        return phase.astype(np.float32)

    invalid = (~np.isfinite(phase)) | (~np.isfinite(corr)) | (corr < coh_min)
    if invalid.all():
        return np.full(phase.shape, np.nan, dtype=np.float32)

    h, w = phase.shape
    # snaphu 不接受 NaN：无效像元填 0 相位、0 相关性（低可信，不参与代价优化）
    ph_in = np.where(invalid, 0.0, phase).astype("<f4")
    co_in = np.where(invalid, 0.0, np.clip(corr, 0.0, 1.0)).astype("<f4")

    mode_flag = {"deformation": "-d", "topography": "-t", "smooth": "-s"}.get(mode, "-d")

    with tempfile.TemporaryDirectory(prefix="snaphu_") as td:
        ph_path = Path(td) / "phase.bin"
        co_path = Path(td) / "corr.bin"
        out_path = Path(td) / "unw.bin"
        cfg_path = Path(td) / "snaphu.conf"
        ph_in.tofile(ph_path)
        co_in.tofile(co_path)
        # 关键：三个文件统一声明成单通道 FLOAT_DATA，否则会按默认的
        # COMPLEX_DATA / ALT_LINE_DATA 解读而得到完全错误的结果
        cfg_path.write_text(
            "INFILEFORMAT\tFLOAT_DATA\n"
            "CORRFILEFORMAT\tFLOAT_DATA\n"
            "OUTFILEFORMAT\tFLOAT_DATA\n",
            encoding="utf-8")

        cmd = [exe, mode_flag, "-f", str(cfg_path),
               "-o", str(out_path), "-c", str(co_path),
               str(ph_path), str(w)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                  text=True, errors="replace")
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"snaphu 解缠超时（>{timeout}s）: {w}x{h} 像元") from e

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-600:]
            raise RuntimeError(f"snaphu 解缠失败（exit={proc.returncode}）：{tail}")

        if not out_path.is_file():
            raise RuntimeError("snaphu 未产出结果文件")

        unw = np.fromfile(out_path, dtype="<f4")
        if unw.size != h * w:
            raise RuntimeError(
                f"snaphu 输出尺寸不符：期望 {h*w}，实得 {unw.size}")

    arr = unw.reshape(h, w).astype(np.float32)
    arr[invalid] = np.nan
    return arr


def unwrap_auto(phase: np.ndarray, corr: np.ndarray,
                coh_min: float = 0.05) -> tuple[np.ndarray, str]:
    """按环境自动选后端，返回 (解缠相位, 实际使用的后端名)。

    优先级：snaphu-py（Linux）→ snaphu.exe（Windows/Linux 均可，工业级）
            → 纯 Python（兜底）。
    后端名写进产物元数据，方便事后追溯这批 20m 结果是谁出的。
    """
    # 1) snaphu-py（Python 绑定）：能 import 说明 Linux 上装好了
    try:
        import snaphu  # noqa: F401
    except ImportError:
        pass
    else:
        # 导入成功就一定要用 snaphu-py。调用失败必须显式抛出，不能静默降级——
        # 曾经的坑：把 snaphu.unwrap() 也包进 try，底层二进制缺失时异常被吞，
        # 上层误报「环境没有 snaphu」，把「包装好了但二进制没装」误诊成「没装包」。
        # snaphu-py 0.4.1 真实接口（实测，与旧文档不符）：
        #   1) igram 必须是【复数】干涉图，传实相位会 TypeError
        #   2) 没有 verbose 参数（nlooks 是第 3 个位置参数）
        #   3) 返回 (unw, conncomp) 元组
        nan_mask = ~np.isfinite(phase) | ~np.isfinite(corr)
        ph = np.where(nan_mask, 0.0, phase)
        co = np.where(nan_mask, 1e-6, np.clip(corr, 0, 1))
        igram = np.exp(1j * ph).astype(np.complex64)
        res = snaphu.unwrap(igram, co, 1.0)          # 1.0 = nlooks
        unw_ds = res[0] if isinstance(res, tuple) else res
        unw = np.asarray(unw_ds[...]).astype(np.float64)
        unw[nan_mask] = np.nan
        return unw, "snaphu"

    # 2) snaphu 可执行文件（ESA 官方 Windows 预编译包 / Linux apt 安装）
    if find_snaphu_exe():
        return unwrap_snaphu_exe(phase, corr, coh_min=coh_min), "snaphu-exe"

    # 3) 纯 Python 兜底（scikit-image，任意平台，精度略逊）
    return unwrap_python(phase, corr, coh_min=coh_min), "python"

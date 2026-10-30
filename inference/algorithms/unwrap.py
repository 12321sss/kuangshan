"""20m 高分辨率相位解缠（C 阶段）。

把 GUNW 的 20m wrappedInterferogram（复数）解缠成连续相位，再把分辨率
从 80m（官方 unwrapped 产品）提到 20m，用于识别单个边坡的形变。

方案
----
用 SNAPHU（Statistical-Cost Network-Flow Algorithm for Phase Unwrapping，
isce-framework/snaphu-py）做解缠。它是工业级解缠器，与 NISAR 同属
NASA/isce 生态。

**平台约束与两条后端**（2026-10-30 补充）：

  | 后端 | 依赖 | 平台 | 质量 |
  |---|---|---|---|
  | `snaphu` | snaphu-py（纯 C，需编译器） | **仅 Linux/macOS** | 工业级，statistical-cost network-flow |
  | `python` | scikit-image（有 cp313 预编译轮子） | **Windows / Linux / macOS** | 2D Herráez 方法，AOI 小时可用 |

原先只有 snaphu 一条路，Windows 完全跑不了 20m 解缠（C 阶段卡死）。
现新增 `unwrap_python`：用 `skimage.restoration.unwrap_phase` 的 **masked array** 能力，
无效像元（低相干 / mask=0）既不参与解缠也不污染邻域，产出与 snaphu 同口径的
`unwrapped_phase.tif` / `los_disp_mm.tif`，平台侧完全不用改。

选中逻辑见 `unwrap_auto`：有 snaphu 用 snaphu，否则自动退回 python，两条路产物格式一致。

本模块职责（纯 Python，可单测）：
  1. read_wrapped：从 GUNW 读 20m 复数干涉图 + 相干性 + mask
  2. prepare：转成 snaphu 需要的相位 + 相关性输入（实部浮点数组）
  3. phase_to_los_mm：解缠相位 → LOS 位移（与 sbas 同口径）

约定
----
- 相位无效处（NaN 复数 / mask 无效）→ 解缠后仍是 NaN
- 输出 LOS 位移单位毫米，正值 = 地面向卫星靠近
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

L_BAND_WAVELENGTH_M = 299792458.0 / 1.229e9  # ≈ 0.2439 m


def read_wrapped(path: Path,
                 aoi_wsen: tuple[float, float, float, float] | None = None,
                 polar: str = "HH") -> dict:
    """读 GUNW 的 20m wrapped 干涉图。

    返回 {wrapped(复数), coherence, mask, epsg, x, y, spacing}
    wrapped 的无效处是 nan+nanj（产品 _FillValue）。
    """
    import h5py
    from rasterio.warp import transform as wtrans

    B = "science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram"
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


def unwrap_auto(phase: np.ndarray, corr: np.ndarray,
                coh_min: float = 0.05) -> tuple[np.ndarray, str]:
    """按环境自动选后端：有 snaphu 用 snaphu，否则用纯 Python。

    返回 (解缠相位, 实际使用的后端名)，后端名用于日志与产物元数据，
    方便事后追溯这批 20m 结果是哪个解缠器出的。
    """
    try:
        import snaphu  # 仅在 Linux/macOS 装得上

        nan_mask = ~np.isfinite(phase) | ~np.isfinite(corr)
        ph = np.where(nan_mask, 0.0, phase)
        co = np.where(nan_mask, 1e-6, np.clip(corr, 0, 1))
        unw = snaphu.unwrap(ph, co, nlooks=1.0, verbose=False).astype(np.float64)
        unw[nan_mask] = np.nan
        return unw, "snaphu"
    except Exception:
        return unwrap_python(phase, corr, coh_min=coh_min), "python"

"""NISAR GUNW HDF5 读取层。

把 GUNW 产品读成 sbas.Pair 列表，屏蔽 HDF5 内部路径的细节，
让 SBAS 解算只关心「时间 + 相位 + 相干性」三样东西。

约定
----
- 只读 80m 的 unwrappedInterferogram（已解缠，直接可做 SBAS）
- 相位无效处（mask=0、NaN）→ NaN
- 支持按经纬度 AOI 裁剪，避免把整景 4257×4329 读进内存再裁
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .sbas import Pair

# GUNW 内部路径（NISAR 产品规范固定，见 NISAR Data User Guide）
_BASE = "science/LSAR/GUNW/grids/frequencyA"
_UNW = f"{_BASE}/unwrappedInterferogram"
_HH = f"{_UNW}/HH"

L_BAND_CENTER_FREQ_HZ = 1.229e9
L_BAND_WAVELENGTH_M = 299792458.0 / L_BAND_CENTER_FREQ_HZ  # ≈ 0.2439 m


def _decode(b: bytes | np.bytes_) -> str:
    if isinstance(b, np.bytes_):
        b = b.tobytes()
    return b.decode("utf-8", errors="replace")


def _iso_to_decimal_year(iso: bytes) -> float:
    """ISO 时间串 → 小数年（SBAS 时间轴用年，速率才直接是 mm/yr）"""
    s = _decode(iso)
    # 形如 2026-10-01T11:01:40.000000000
    year = int(s[:4])
    month = int(s[5:7])
    day = int(s[8:10])
    doy = (int(s[:4]), month, day)
    import datetime
    d = datetime.date(year, month, day)
    frac = d.timetuple().tm_yday / 366.0 if _is_leap(year) else d.timetuple().tm_yday / 365.0
    return year + frac


def _is_leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def read_pair(path: Path, aoi_wsen: tuple[float, float, float, float] | None = None,
              polar: str = "HH") -> Pair:
    """读单景 GUNW → 一个 Pair。

    aoi_wsen：可选 (west, south, east, north) 经纬度裁剪；None 读整景。
    polar：极化，默认 HH（NISAR L 波段主极化）。
    """
    import h5py
    from rasterio.warp import transform as wtrans

    with h5py.File(path, "r") as h:
        freq = float(h[f"{_BASE}/centerFrequency"][()])
        wavelength = 299792458.0 / freq

        idg = h["science/LSAR/identification"]
        t_ref = _iso_to_decimal_year(idg["referenceZeroDopplerStartTime"][()])
        t_sec = _iso_to_decimal_year(idg["secondaryZeroDopplerStartTime"][()])

        epsg = int(h[f"{_UNW}/projection"][()])
        xc = h[f"{_UNW}/xCoordinates"][:]
        yc = h[f"{_UNW}/yCoordinates"][:]   # 递减（行号朝北）

        # 裁剪
        if aoi_wsen is not None:
            W, S, E, N = aoi_wsen
            xs, ys = wtrans("EPSG:4326", f"EPSG:{epsg}", [W, E], [S, N])
            c0, c1 = np.searchsorted(xc, [xs[0], xs[1]])
            # yc 递减：行号 = len(yc) - (索引)
            r0, r1 = np.searchsorted(yc[::-1], [ys[0], ys[1]])
            r0, r1 = len(yc) - r1, len(yc) - r0
            r0, r1 = max(0, r0), min(len(yc), r1)
            c0, c1 = max(0, c0), min(len(xc), c1)
            if r1 <= r0 or c1 <= c0:
                raise ValueError(f"AOI 与影像不相交：{aoi_wsen}")
        else:
            r0, r1, c0, c1 = 0, len(yc), 0, len(xc)

        phase = h[f"{_HH}/unwrappedPhase"][r0:r1, c0:c1]
        coh = h[f"{_HH}/coherenceMagnitude"][r0:r1, c0:c1]
        mask = h[f"{_UNW}/mask"][r0:r1, c0:c1]
        # 电离层相位屏：L 波段电离层延迟可达几十 rad，远大于形变信号，
        # 是速率场噪声的主源。产品自带该校正，直接减。
        try:
            iono = h[f"{_HH}/ionospherePhaseScreen"][r0:r1, c0:c1]
        except KeyError:
            iono = None

    # 无效像元：mask=0（subswath/水体无效）或相位非有限
    invalid = (mask == 0) | ~np.isfinite(phase)
    phase = phase.astype(np.float64)
    phase[invalid] = np.nan
    coh = coh.astype(np.float32)
    coh[invalid] = np.nan
    # 电离层校正：相位减去电离层屏（有限值才减）
    if iono is not None:
        iono = iono.astype(np.float64)
        iono[invalid] = np.nan
        valid = np.isfinite(iono)
        phase[valid] = phase[valid] - iono[valid]

    return Pair(t_ref, t_sec, phase, coh)


def read_track(paths: list[Path],
               aoi_wsen: tuple[float, float, float, float] | None = None,
               polar: str = "HH") -> list[Pair]:
    """读同一轨道的多景 → Pair 列表（按时间排序）"""
    pairs = [read_pair(p, aoi_wsen, polar) for p in paths]
    pairs.sort(key=lambda p: p.t_ref)
    return pairs


def auto_reference_mask(pairs: list[Pair],
                        buffer_cols: int = 10) -> np.ndarray:
    """自动选参考区：取图像边缘一圈（通常远离矿区扰动）。

    简单但够用：矿区一般位于影像中部，四周是稳定地表。更精细的做法
    是按相干性 + 坡度选稳定区，但 demo 期用边缘环 + 高相干即可。
    返回与 phase 同 shape 的布尔掩膜。
    """
    h, w = pairs[0].phase.shape
    mask = np.zeros((h, w), dtype=bool)
    b = buffer_cols
    mask[:b, :] = True
    mask[-b:, :] = True
    mask[:, :b] = True
    mask[:, -b:] = True
    return mask


def read_los_vector(path: Path) -> tuple[float, float, float]:
    """读 GUNW 的代表 LOS 单位向量 (E, N, U)，用于升降轨联合分解。

    为什么取中位值而不是逐像元：
      NISAR GUNW 的 LOS 向量只在 `metadata/radarGrid/losUnitVectorX/Y`
      （雷达网格 20×699×710）上提供，**不在 80m 输出网格上**。
      要逐像元映射得做雷达坐标 → 地理坐标的重采样，代价大且引入插值误差。
      而 5km 级 AOI 内入射角只变化几度，LOS 向量几乎恒定，
      取全图中位值的分解误差远小于形变本身的测量不确定度。
      AOI 跨几十公里时再考虑逐像元映射。

    返回 (east, north, up)，已归一化的单位向量。
    符号约定：从地面指向卫星，up > 0；与「位移正值 = 向卫星靠近」一致。
    """
    import h5py

    base = "science/LSAR/GUNW/metadata/radarGrid"
    with h5py.File(path, "r") as h:
        lx = h[f"{base}/losUnitVectorX"][:]
        ly = h[f"{base}/losUnitVectorY"][:]
        e = float(np.nanmedian(lx))
        n = float(np.nanmedian(ly))

    # 单位化约束给 U：X/Y 已知，Z = sqrt(1 - X² - Y²)，取正（指向天空）
    u = float(np.sqrt(max(1.0 - e * e - n * n, 0.0)))
    norm = float(np.sqrt(e * e + n * n + u * u)) or 1.0
    return (e / norm, n / norm, u / norm)


def read_pass_direction(path: Path) -> str:
    """读轨道方向：'Ascending' / 'Descending'（用于标识升/降轨）。"""
    import h5py

    with h5py.File(path, "r") as h:
        v = h["science/LSAR/identification/orbitPassDirection"][()]
    return v.decode() if isinstance(v, bytes) else str(v)

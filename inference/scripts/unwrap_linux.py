"""20m 高分辨率解缠（C 阶段）—— Linux 执行脚本。

调用 snaphu-py 对 GUNW 的 20m wrapped 干涉图解缠，输出 20m LOS 位移场。

为什么在 Linux：snaphu 是纯 C 项目，官方只支持 linux|macos（需编译器），
Windows 无法安装。本脚本部署到 Linux 服务器后运行，产物（解缠相位 GeoTIFF）
拷回平台，由 B 阶段的形变判定层消费。

用法（Linux 上）：
    pip install snaphu h5py rasterio
    python scripts/unwrap_linux.py --input <GUNW.h5> --aoi w,s,e,n --out <dir>

输出：
    <dir>/unwrapped_phase.tif   20m 解缠相位（弧度，WGS84）
    <dir>/los_disp_mm.tif       20m LOS 位移（毫米）
    <dir>/coherence.tif         20m 相干性
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from algorithms.unwrap import phase_to_los_mm, read_wrapped, to_phase_corr


def unwrap_snaphu(phase: np.ndarray, corr: np.ndarray) -> np.ndarray:
    """用 snaphu-py 解缠。

    phase：缠绕相位（弧度，[-π,π]，NaN 表示无效）
    corr：相关性 0~1（解缠置信度）
    返回解缠相位（弧度），与输入同 shape。
    """
    import snaphu

    # 用极小相关值填充 NaN 像元，解缠后再还原成 NaN
    nan_mask = ~np.isfinite(phase) | ~np.isfinite(corr)
    ph = np.where(nan_mask, 0.0, phase)
    co = np.where(nan_mask, 1e-6, np.clip(corr, 0, 1))

    # snaphu 解缠（默认 statistical-cost network-flow）
    unw = snaphu.unwrap(ph, co, nlooks=1.0, verbose=False)

    out = unw.astype(np.float64)
    out[nan_mask] = np.nan
    return out


def _write_tif(path: Path, arr: np.ndarray, bbox, epsg: int) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    h, w = arr.shape
    west, south, east, north = bbox
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=f"EPSG:{epsg}",
                       transform=from_bounds(west, south, east, north, w, h),
                       nodata=np.nan) as dst:
        dst.write(arr.astype(np.float32), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="20m 解缠（Linux + snaphu）")
    ap.add_argument("--input", required=True, help="GUNW .h5 路径")
    ap.add_argument("--aoi", default="114.87,28.57,114.93,28.62", help="w,s,e,n")
    ap.add_argument("--out", default=".cache/nisar/unwrapped")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.aoi.split(","))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"读 {args.input}")
    d = read_wrapped(Path(args.input), aoi_wsen=bbox)
    phase, corr = to_phase_corr(d["wrapped"], d["coherence"], d["mask"])
    print(f"  窗口 {phase.shape}，有效像元 {int(np.isfinite(phase).sum())}")

    print("解缠中（snaphu）...")
    unw = unwrap_snaphu(phase, corr)
    disp = phase_to_los_mm(unw)

    # 输出 GeoTIFF（用 WGS84 bbox，便于平台直接上图）
    from rasterio.warp import transform_bounds
    # 保持输入 EPSG，但输出用 WGS84 bbox 更通用；这里直接用经纬度 bbox
    _write_tif(out_dir / "unwrapped_phase.tif", unw, bbox, 4326)
    _write_tif(out_dir / "los_disp_mm.tif", disp, bbox, 4326)
    _write_tif(out_dir / "coherence.tif", corr, bbox, 4326)

    v = disp[np.isfinite(disp)]
    print(f"\n解缠完成 → {out_dir}")
    if v.size:
        print(f"  LOS 位移(mm)：中位 {np.median(v):+.1f} | "
              f"5~95% {np.percentile(v, 5):+.1f} ~ {np.percentile(v, 95):+.1f} | "
              f"极值 {v.min():+.1f} ~ {v.max():+.1f}")


if __name__ == "__main__":
    main()

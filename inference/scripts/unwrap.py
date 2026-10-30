"""20m 高分辨率解缠（C 阶段）—— 跨平台执行脚本。

与 `unwrap_linux.py` 的区别：那个只能在 Linux + snaphu 上跑；
这个支持两种后端，Windows 也能出 20m 解缠产物。

用法
----
真实数据（GUNW）：
    python scripts/unwrap.py --input path/GUNW.h5 --aoi 114.87,28.57,114.93,28.62 --out out/

没有 GUNW 时验证链路（合成一个已知形变场，用于自检/演示）：
    python scripts/unwrap.py --synthetic --out out/

指定后端：
    --backend auto   默认。有 snaphu 用 snaphu，否则退回纯 Python
    --backend snaphu 强制 snaphu（Linux/macOS）
    --backend python 强制纯 Python（任意平台）

输出（三份 GeoTIFF + 一份元数据 JSON，两条后端产物格式完全一致）
    unwrapped_phase.tif   解缠相位（弧度）
    los_disp_mm.tif       LOS 位移（毫米，正 = 向卫星靠近）
    coherence.tif         相干性 0~1
    unwrap_meta.json      后端名、AOI、像元数、位移统计、参数

为什么要有纯 Python 后端
------------------------
snaphu 是纯 C 项目，官方只发 linux/macos 轮子，Windows 装不上（需要 CMake + C 编译器）。
这导致 C 阶段在 Windows 上完全卡死。改用 scikit-image 的 Herráez 2D 解缠后，
Windows 也能产出同口径结果；精度略逊于 snaphu 的 network-flow，但 AOI 小、相干性好时够用。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from algorithms.unwrap import (
    L_BAND_WAVELENGTH_M,
    phase_to_los_mm,
    read_wrapped,
    to_phase_corr,
    unwrap_auto,
    unwrap_python,
)


def _write_tif(path: Path, arr: np.ndarray, bbox, epsg: int) -> None:
    """按经纬度 bbox 写单波段 float32 GeoTIFF（平台直接可上图）"""
    import rasterio
    from rasterio.transform import from_bounds

    h, w = arr.shape
    west, south, east, north = bbox
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=f"EPSG:{epsg}",
                       transform=from_bounds(west, south, east, north, w, h),
                       nodata=np.nan) as dst:
        dst.write(arr.astype(np.float32), 1)


def _synthetic(aoi_wsen: tuple[float, float, float, float],
               ny: int = 240, nx: int = 320,
               spacing_m: float = 20.0) -> dict:
    """合成一份"看似真实"的 20m 干涉图，用于在没有 GUNW 时验证全链路。

    构造一个中心隆起的形变场（模拟采空区/边坡沉降），峰值位移约 40 mm，
    叠加一点噪声和一块低相干区（模拟水体），并缠绕到 [-π, π)。
    这样解缠结果的量级、形态、掩膜行为都能被检验。
    """
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)

    # 高斯隆起：中心沉降 40 mm（负值 = 远离卫星）
    cy, cx, sigma = ny * 0.55, nx * 0.45, min(ny, nx) * 0.22
    gauss = np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))

    peak_disp_mm = -40.0
    truth_mm = peak_disp_mm * gauss
    truth_phase = truth_mm / 1000.0 * (4 * np.pi / L_BAND_WAVELENGTH_M)

    # 缠绕
    wrapped_complex = np.exp(1j * truth_phase).astype(np.complex64)

    # 相干性：整体 0.75，右下一块低相干（水体/植被），再叠一点起伏
    corr = 0.75 + 0.1 * np.sin(xx / 18.0) * np.cos(yy / 22.0)
    lake = (yy > ny * 0.72) & (xx > nx * 0.68)
    corr[lake] = 0.02
    corr = np.clip(corr, 0.0, 1.0).astype(np.float32)

    mask = np.ones((ny, nx), dtype=np.uint8)
    mask[lake] = 0

    # 加入轻微相位噪声（±0.15 弧度），模拟真实干涉图
    rng = np.random.default_rng(42)
    phase = np.angle(wrapped_complex) + rng.normal(0, 0.15, (ny, nx))
    wrapped = np.exp(1j * phase).astype(np.complex64)

    w, s, e, n = aoi_wsen
    return {
        "wrapped": wrapped,
        "coherence": corr,
        "mask": mask,
        "epsg": 4326,
        "x": np.linspace(w, e, nx),
        "y": np.linspace(s, n, ny),
        "spacing": spacing_m,
        "_truth_mm": truth_mm,
        "_lake": lake,
        "_bbox": (w, s, e, n),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="20m 解缠（跨平台：snaphu / 纯 Python）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="GUNW .h5 路径")
    src.add_argument("--synthetic", action="store_true", help="用合成形变场自检（无需数据）")
    ap.add_argument("--aoi", default="114.87,28.57,114.93,28.62", help="AOI: w,s,e,n")
    ap.add_argument("--out", default=".cache/nisar/unwrapped", help="输出目录")
    ap.add_argument("--backend", default="auto", choices=["auto", "snaphu", "python"])
    ap.add_argument("--polar", default="HH", help="极化（GUNW 常用 HH）")
    ap.add_argument("--coh-min", type=float, default=0.05, help="纯 Python 后端的相干性阈值")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.aoi.split(","))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 读数据 ----------
    truth_mm = None
    if args.synthetic:
        print(f"[合成模式] 生成 {bbox} 内的模拟 20m 干涉图")
        d = _synthetic(bbox)
        truth_mm = d.pop("_truth_mm")
        lake = d.pop("_lake")
        d.pop("_bbox", None)
        bbox = tuple(d["x"][[0, -1]]) + tuple(d["y"][[0, -1]])
        bbox = (d["x"][0], d["y"][0], d["x"][-1], d["y"][-1])
    else:
        print(f"读 {args.input}")
        d = read_wrapped(Path(args.input), aoi_wsen=bbox, polar=args.polar)

    phase, corr = to_phase_corr(d["wrapped"], d["coherence"], d["mask"])
    n_valid = int(np.isfinite(phase).sum())
    print(f"  窗口 {phase.shape}，有效像元 {n_valid}/{phase.size}")

    # ---------- 解缠 ----------
    t0 = time.time()
    if args.backend == "python":
        unw = unwrap_python(phase, corr, coh_min=args.coh_min)
        backend = "python"
    elif args.backend == "snaphu":
        unw, backend = unwrap_auto(phase, corr, coh_min=args.coh_min)
        if backend != "snaphu":
            print("  ✗ 指定 snaphu 但当前环境没有 snaphu（仅 Linux/macOS 可装）")
            return 2
    else:
        unw, backend = unwrap_auto(phase, corr, coh_min=args.coh_min)
    elapsed = time.time() - t0
    print(f"解缠完成（后端 {backend}，耗时 {elapsed:.2f}s）")

    disp = phase_to_los_mm(unw)

    # ---------- 写产物 ----------
    _write_tif(out_dir / "unwrapped_phase.tif", unw, bbox, 4326)
    _write_tif(out_dir / "los_disp_mm.tif", disp, bbox, 4326)
    _write_tif(out_dir / "coherence.tif", corr, bbox, 4326)

    v = disp[np.isfinite(disp)]
    stats = {}
    if v.size:
        stats = {
            "medianMm": round(float(np.median(v)), 2),
            "p5Mm": round(float(np.percentile(v, 5)), 2),
            "p95Mm": round(float(np.percentile(v, 95)), 2),
            "minMm": round(float(v.min()), 2),
            "maxMm": round(float(v.max()), 2),
        }

    meta = {
        "backend": backend,
        "source": "synthetic" if args.synthetic else str(args.input),
        "polar": args.polar,
        "aoiWsen": list(bbox),
        "shape": list(phase.shape),
        "validPixels": n_valid,
        "coherenceMin": args.coh_min,
        "wavelengthM": L_BAND_WAVELENGTH_M,
        "elapsedSec": round(elapsed, 3),
        "dispStats": stats,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "unwrap_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 报告 ----------
    print(f"\n产物已写入 {out_dir}")
    for name in ("unwrapped_phase.tif", "los_disp_mm.tif", "coherence.tif", "unwrap_meta.json"):
        f = out_dir / name
        if f.exists():
            print(f"  {name:22s} {f.stat().st_size / 1024:8.1f} KB")

    if stats:
        print(f"\nLOS 位移(mm)：中位 {stats['medianMm']:+.1f} | "
              f"5~95% {stats['p5Mm']:+.1f} ~ {stats['p95Mm']:+.1f} | "
              f"极值 {stats['minMm']:+.1f} ~ {stats['maxMm']:+.1f}")

    # 合成模式下与真值对比，验证解缠可信度
    if truth_mm is not None:
        valid = np.isfinite(disp)
        diff = disp[valid] - truth_mm[valid]
        offset = np.median(diff)          # 解缠有 2π 整数倍不确定，去掉常数偏置
        resid = diff - offset
        print(f"\n[自检] 与合成真值对比：")
        print(f"  常数偏置 {offset:+.1f} mm（解缠固有的 2π 模糊，可接受）")
        print(f"  去偏置后残差：RMS {np.sqrt((resid**2).mean()):.2f} mm，"
              f"最大 {np.abs(resid).max():.2f} mm")
        print(f"  低相干区被正确屏蔽：{bool(np.isnan(disp[lake]).all())}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

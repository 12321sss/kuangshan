"""NISAR GUNW 时序 SBAS 处理入口（A 阶段）。

把同一轨道的多期 GUNW 读进来 → 参考区归零 → SBAS 反演 → 落产物。

产物（写到一个 JSON + 一个 GeoTIFF，供 B 阶段平台集成消费）：
    .cache/nisar/result/<track>/sbas_result.json   速率场统计 + 时序摘要
    .cache/nisar/result/<track>/velocity.tif       速率场 GeoTIFF（WGS84）

用法：
    python scripts/run_sbas.py --track 18 --bbox 114.87,28.57,114.93,28.62

只调用 algorithms/ 里的模块，不内联算法逻辑（保证可维护）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from algorithms.nisar_io import read_track, auto_reference_mask
from algorithms.sbas import reference_correction, solve

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "nisar"
RESULT = CACHE / "result"


def main() -> None:
    ap = argparse.ArgumentParser(description="NISAR GUNW 时序 SBAS 处理")
    ap.add_argument("--track", type=int, required=True)
    ap.add_argument("--bbox", default="114.87,28.57,114.93,28.62")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))

    # 1. 找该轨道已下载的完整文件（>1GB 才认为是完整的）
    files = [f for f in glob.glob(str(CACHE / "*.h5"))
             if os.path.getsize(f) > 1_000_000_000
             and f"_{args.track:03d}_" in f]
    if len(files) < 2:
        raise SystemExit(f"track {args.track} 只找到 {len(files)} 景完整文件，至少 2 景才能 SBAS")

    print(f"track {args.track}：{len(files)} 景")
    pairs = read_track([Path(f) for f in files], aoi_wsen=bbox)
    print(f"  每景窗口 {pairs[0].phase.shape}，时间跨度 "
          f"{min(p.t_ref for p in pairs):.3f} ~ {max(p.t_sec for p in pairs):.3f} 年")

    # 2. 参考区归零（边缘环）
    ref_mask = auto_reference_mask(pairs, buffer_cols=10)
    pairs = reference_correction(pairs, ref_mask)

    # 3. SBAS 反演
    res = solve(pairs)
    v = res["velocity_mmyr"]
    valid = res["valid_mask"]
    vv = v[valid]

    print(f"\n=== SBAS 结果 ===")
    print(f"  有效像元 {res['quality']['n_valid_pixels']} / {v.size}")
    print(f"  速率：中位 {np.nanmedian(vv):+.1f} mm/yr | "
          f"5~95% {np.nanpercentile(vv, 5):+.1f} ~ {np.nanpercentile(vv, 95):+.1f} | "
          f"极值 {np.nanmin(vv):+.1f} ~ {np.nanmax(vv):+.1f}")
    print(f"  时序残差 RMS {res['quality']['rms_mm']} mm")
    print(f"  时间轴：{[f'{t:.3f}' for t in res['times']]}")

    # 4. 落产物
    out_dir = RESULT / f"track{args.track}"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "track": args.track,
        "bbox": list(bbox),
        "n_pairs": res["quality"]["n_pairs"],
        "n_times": res["quality"]["n_times"],
        "times": res["times"],
        "reference_time": res["reference_time"],
        "velocity": {
            "median_mmyr": float(np.nanmedian(vv)),
            "p5": float(np.nanpercentile(vv, 5)),
            "p95": float(np.nanpercentile(vv, 95)),
            "min": float(np.nanmin(vv)),
            "max": float(np.nanmax(vv)),
        },
        "rms_mm": res["quality"]["rms_mm"],
        "note": res["quality"]["note"],
    }
    (out_dir / "sbas_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # 速率场 → GeoTIFF（用 rasterio 写，带 WGS84 范围，B 阶段可直接上图）
    write_velocity_tif(out_dir / "velocity.tif", v, valid, bbox)

    print(f"\n产物已写：{out_dir}")


def write_velocity_tif(path: Path, velocity: np.ndarray, valid: np.ndarray,
                       bbox: tuple[float, float, float, float]) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    h, w = velocity.shape
    west, south, east, north = bbox
    arr = np.where(valid, velocity, np.nan).astype(np.float32)
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_bounds(west, south, east, north, w, h),
                       nodata=np.nan) as dst:
        dst.write(arr, 1)


if __name__ == "__main__":
    main()

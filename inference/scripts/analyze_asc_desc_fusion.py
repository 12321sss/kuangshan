"""茜坑矿区升降轨联合解算：LOS → 垂直 + 东西向二维位移。

单轨 InSAR 只能测「视线向(LOS)」位移，不能直接说「沉降多少」。升降轨联合可以解出
垂直(V)与东西(E)两个分量——这才是客户真正关心的「沉降量」。南北向因轨道近极地不可解。

链路：
    降轨 track 18 (8景) ─ SBAS ─→ 降轨速率场 ┐
                                            ├─ 网格对齐 ─→ 2D 分解 ─→ 垂直/东西向场
    升轨 track 68  (8景) ─ SBAS ─→ 升轨速率场 ┘

关键工程点
----------
两个轨道的地面网格不同（即使都是 80m，网格起点也不同），AOI 裁剪后 shape 不一致，
必须先重采样到同一网格才能逐像元解方程。本脚本用「把升轨双线性重采样到降轨网格」，
因为两者覆盖同一 bbox，插值误差远小于形变不确定度。

用法：
    python scripts/analyze_asc_desc_fusion.py --desc-track 18 --asc-track 68 \
        --out ../docs/茜坑升降轨联合.html
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from scipy.ndimage import zoom

from algorithms.deformation_fusion import decompose_los_to_2d
from algorithms.nisar_io import auto_reference_mask, read_los_vector, read_pass_direction, read_track
from algorithms.sbas import reference_correction, solve

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "nisar"
XICHENG_BBOX = (114.87, 28.57, 114.93, 28.62)


def _track_files(track: int) -> list[str]:
    """找某轨道的完整景（>2GB 才算完整下载）。"""
    return sorted(f for f in glob.glob(str(CACHE / "*.h5"))
                  if os.path.getsize(f) > 2_000_000_000
                  and f"_{track:03d}_" in f)


def _velocity(track: int, bbox: tuple) -> tuple[np.ndarray, np.ndarray, list]:
    """跑单轨道 SBAS → 速率场。返回 (速度场, 有效掩膜, times)。"""
    files = _track_files(track)
    if len(files) < 2:
        raise SystemExit(f"track {track} 完整景不足（{len(files)} 景），请先下载")
    pairs = read_track([Path(f) for f in files], aoi_wsen=bbox)
    pairs = reference_correction(pairs, auto_reference_mask(pairs))
    res = solve(pairs)
    return res["velocity_mmyr"], res["valid_mask"], files


def main() -> int:
    ap = argparse.ArgumentParser(description="升降轨联合 → 垂直+东西向二维位移")
    ap.add_argument("--desc-track", type=int, default=18, help="降轨轨道号")
    ap.add_argument("--asc-track", type=int, default=68, help="升轨轨道号")
    ap.add_argument("--bbox", default=",".join(map(str, XICHENG_BBOX)))
    ap.add_argument("--out", default="../docs/茜坑升降轨联合.html")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))

    print(f"1/4 降轨 track {args.desc_track} 速率场 ...")
    vel_desc, mask_desc, files_desc = _velocity(args.desc_track, bbox)
    print(f"     shape={vel_desc.shape}, 有效像元 {int(np.isfinite(vel_desc).sum())}")

    print(f"2/4 升轨 track {args.asc_track} 速率场 ...")
    vel_asc, mask_asc, files_asc = _velocity(args.asc_track, bbox)
    print(f"     shape={vel_asc.shape}, 有效像元 {int(np.isfinite(vel_asc).sum())}")

    # ---- 网格对齐：升轨重采样到降轨网格 ----
    print(f"3/4 网格对齐（升轨 {vel_asc.shape} → 降轨 {vel_desc.shape}）...")
    if vel_asc.shape != vel_desc.shape:
        fy = vel_desc.shape[0] / vel_asc.shape[0]
        fx = vel_desc.shape[1] / vel_asc.shape[1]
        # NaN 先填 0 再缩放，缩放后把原 NaN 区域恢复成 NaN，避免把无效值当 0 参与解算
        filled = np.where(np.isfinite(vel_asc), vel_asc, 0.0)
        scaled = zoom(filled, (fy, fx), order=1)
        nanmask = zoom(np.isfinite(vel_asc).astype(float), (fy, fx), order=0) < 0.5
        vel_asc_r = np.where(nanmask, np.nan, scaled)
    else:
        vel_asc_r = vel_asc

    # ---- LOS 向量 ----
    los_desc = read_los_vector(Path(files_desc[0]))
    los_asc = read_los_vector(Path(files_asc[0]))
    print(f"4/4 二维分解 ...")
    print(f"     降轨 LOS: E={los_desc[0]:+.3f} N={los_desc[1]:+.3f} U={los_desc[2]:+.3f}"
          f" ({read_pass_direction(Path(files_desc[0]))})")
    print(f"     升轨 LOS: E={los_asc[0]:+.3f} N={los_asc[1]:+.3f} U={los_asc[2]:+.3f}"
          f" ({read_pass_direction(Path(files_asc[0]))})")

    fused = decompose_los_to_2d(vel_asc_r, los_asc, vel_desc, los_desc)
    vert = fused["vertical"]
    east = fused["east_west"]
    solved = fused["solved_mask"]

    n_solved = int(solved.sum())
    print(f"     可解像元: {n_solved} / {solved.size}")

    def stat(a, name, unit="mm/yr"):
        v = a[np.isfinite(a)]
        if v.size == 0:
            print(f"     {name}: 无有效像元")
            return None
        print(f"     {name}: 中位 {np.median(v):+.1f} | P5~P95 "
              f"{np.percentile(v,5):+.1f} ~ {np.percentile(v,95):+.1f} | "
              f"极值 {v.min():+.1f} ~ {v.max():+.1f} {unit}")
        return v

    print("\n" + "=" * 60)
    print("二维分解结果（正值 = 向上 / 向东）")
    print("=" * 60)
    stat(vert, "垂直分量 V")
    stat(east, "东西分量 E")
    print("南北分量 N：不可解（轨道近极地），标记为 NaN")

    # ---- 落 JSON ----
    out_json = CACHE / "result" / f"fusion_{args.desc_track}_{args.asc_track}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    import json
    meta = {
        "descTrack": args.desc_track, "ascTrack": args.asc_track,
        "losDesc": [round(x, 4) for x in los_desc],
        "losAsc": [round(x, 4) for x in los_asc],
        "shape": list(vel_desc.shape),
        "solvedPixels": n_solved,
        "vertical": _stats(vert), "eastWest": _stats(east),
        "note": "单轨/双轨均为 LOS 或 2D 近似；南北分量不可解；"
                "时序仅 3 个月，速率可用、加速度不可信",
    }
    out_json.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写 {out_json}")
    return 0


def _stats(a: np.ndarray) -> dict | None:
    v = a[np.isfinite(a)]
    if v.size == 0:
        return None
    return {
        "median": round(float(np.median(v)), 2),
        "p5": round(float(np.percentile(v, 5)), 2),
        "p95": round(float(np.percentile(v, 95)), 2),
        "min": round(float(v.min()), 2),
        "max": round(float(v.max()), 2),
    }


if __name__ == "__main__":
    raise SystemExit(main())

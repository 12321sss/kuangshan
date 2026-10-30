"""形变时序分析端到端（A 阶段成果 → 判定指标）。

消费 sbas 的累积位移时序，逐像元算速度/加速度/失稳外推，
并做「信号/噪声比」的自检——信噪比太低时明确提示数据不足，
而不是把噪声当形变输出。

用法：
    python scripts/run_deformation.py --track 18 --bbox 114.87,28.57,114.93,28.62

产出：
    .cache/nisar/result/track18/deformation.json   统计 + 信噪比自检
    .cache/nisar/result/track18/acceleration.tif   加速度场
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

from algorithms.deformation import analyze_timeseries
from algorithms.nisar_io import auto_reference_mask, read_track
from algorithms.sbas import reference_correction, solve

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "nisar"
RESULT = CACHE / "result"


def main() -> None:
    ap = argparse.ArgumentParser(description="形变时序分析")
    ap.add_argument("--track", type=int, required=True)
    ap.add_argument("--bbox", default="114.87,28.57,114.93,28.62")
    args = ap.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))

    files = sorted(f for f in glob.glob(str(CACHE / "*.h5"))
                   if os.path.getsize(f) > 2_000_000_000
                   and f"_{args.track:03d}_" in f)
    if len(files) < 2:
        raise SystemExit(f"track {args.track} 完整景不足")

    pairs = read_track([Path(f) for f in files], aoi_wsen=bbox)
    pairs = reference_correction(pairs, auto_reference_mask(pairs))
    res = solve(pairs)
    times, disp, valid = res["times"], res["displacement_mm"], res["valid_mask"]

    H, W = disp.shape[1], disp.shape[2]
    acc = np.full((H, W), np.nan)
    tf = np.full((H, W), np.nan)
    n_acc = n_tf = 0
    for r in range(H):
        for c in range(W):
            if not valid[r, c]:
                continue
            d = disp[:, r, c]
            tv = np.isfinite(d)
            if tv.sum() < 6:
                continue
            tr = analyze_timeseries([times[i] for i in range(len(times)) if tv[i]], d[tv])
            acc[r, c] = tr.acceleration_mmyr2
            if tr.tf_days:
                tf[r, c] = tr.tf_days
                n_tf += 1
            if tr.accelerating:
                n_acc += 1

    av = acc[np.isfinite(acc)]
    snr = abs(float(np.median(av))) / float(av.std()) if av.size and av.std() > 0 else 0.0

    out = {
        "track": args.track,
        "bbox": list(bbox),
        "n_pixels": int(valid.sum()),
        "n_accelerating": n_acc,
        "n_forecastable": n_tf,
        "acceleration_median_mmyr2": float(np.median(av)) if av.size else None,
        "acceleration_std_mmyr2": float(av.std()) if av.size else None,
        "snr": round(snr, 3),
        "reliable": bool(snr >= 0.3),
        "note": "信噪比 < 0.3 表示加速度淹没在噪声中（时序过短或未充分大气校正），"
                "此时不应输出加速度与失稳时刻判定。",
    }
    out_dir = RESULT / f"track{args.track}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "deformation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n产物已写 {out_dir / 'deformation.json'}")


if __name__ == "__main__":
    main()

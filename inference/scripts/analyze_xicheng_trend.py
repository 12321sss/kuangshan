"""茜坑矿区真实 NISAR 数据 → 形变趋势分析 → 可视化 HTML 报告。

下载完成后执行，一条龙产出可双击查看的趋势分析报告。

链路：
    GUNW(真实) → 参考区归零 → SBAS 反演 → 逐像元速度/加速度/失稳外推
              → 空间化趋势研判 → 形变证据 → 风险提级 → HTML

用法：
    python scripts/analyze_xicheng_trend.py --track 18 [--out docs/茜坑形变趋势.html]

数据源：.cache/nisar/*.h5（先跑 fetch_nisar.py download 下好）
口径：输出为「潜在形变风险筛查」，单轨 LOS 视线向，非垂直沉降；
      时序过短时加速度与失稳外推自动标注「不可信」，不编数。
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from algorithms.deformation import analyze_timeseries, build_evidence
from algorithms.nisar_io import auto_reference_mask, read_track
from algorithms.sbas import reference_correction, solve

# 复用演示脚本的 HTML 生成（同一份可视化逻辑）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_deformation_trend import _build_html, XICHENG_BBOX  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "nisar"
RESULT = CACHE / "result"


def main() -> int:
    ap = argparse.ArgumentParser(description="茜坑真实 NISAR 趋势分析 + HTML 报告")
    ap.add_argument("--track", type=int, default=18)
    ap.add_argument("--bbox", default=",".join(map(str, XICHENG_BBOX)))
    ap.add_argument("--out", default="docs/茜坑形变趋势.html")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))

    # 找该轨道的完整 GUNW（>2GB 才算完整景）
    files = sorted(f for f in glob.glob(str(CACHE / "*.h5"))
                   if os.path.getsize(f) > 2_000_000_000
                   and f"_{args.track:03d}_" in f)
    if len(files) < 2:
        raise SystemExit(f"track {args.track} 完整景不足（当前 {len(files)} 景），"
                         f"请先跑 fetch_nisar.py download --track {args.track}")

    print(f"读取 track {args.track} 的 {len(files)} 景 GUNW ...")
    pairs = read_track([Path(f) for f in files], aoi_wsen=bbox)
    print(f"  参考区归零 + SBAS 反演（{len(pairs)} 个干涉对）...")
    pairs = reference_correction(pairs, auto_reference_mask(pairs))
    res = solve(pairs)

    times = res["times"]
    disp = res["displacement_mm"]
    valid = res["valid_mask"]
    H, W = disp.shape[1], disp.shape[2]

    print(f"  逐像元趋势分析（{H}×{W}）...")
    v_field = np.full((H, W), np.nan)
    a_field = np.full((H, W), np.nan)
    tf_field = np.full((H, W), np.nan)
    n_pts = 0
    for r in range(H):
        for c in range(W):
            if not valid[r, c]:
                continue
            d = disp[:, r, c]
            tv = np.isfinite(d)
            if tv.sum() < 6:
                continue
            tr = analyze_timeseries([times[i] for i in range(len(times)) if tv[i]], d[tv])
            v_field[r, c] = tr.velocity_mmyr
            a_field[r, c] = tr.acceleration_mmyr2
            if tr.tf_days:
                tf_field[r, c] = tr.tf_days
            n_pts += 1

    # 信噪比（加速度中位 / 标准差）
    av = a_field[np.isfinite(a_field)]
    snr = abs(float(np.median(av))) / float(av.std()) if av.size and av.std() > 0 else 0.0

    # 经纬度坐标轴（读真实 GUNW 的网格，简化用 bbox 均匀网格）
    xs = np.linspace(bbox[0], bbox[2], W)
    ys = np.linspace(bbox[1], bbox[3], H)
    evidence = build_evidence(v_field, a_field, tf_field, snr, xs, ys, top_n=10)

    from algorithms.deformation_risk import deformation_overlay
    overlay = deformation_overlay(55.0, evidence["velocityMmyr"],
                                  evidence["accelerationMmyr2"],
                                  reliable=evidence["reliable"])

    # 代表测点时序：取最危险测点 + 参考区
    picks = {}
    if evidence["hotspots"]:
        h0 = evidence["hotspots"][0]
        # 由经纬度反推行列
        c_ = int(round((h0["x"] - bbox[0]) / (bbox[2] - bbox[0]) * (W - 1)))
        r_ = int(round((h0["y"] - bbox[1]) / (bbox[3] - bbox[1]) * (H - 1)))
        picks["最危险测点"] = (r_, c_)
    picks["参考区"] = (1, 1)

    disp_series = {}
    for name, (r, c) in picks.items():
        d = disp[:, r, c]
        tv = np.isfinite(d)
        disp_series[name] = [float(d[i]) if tv[i] else 0.0 for i in range(len(d))]

    out = {"evidence": evidence, "overlay": overlay, "snr": snr}

    print("  生成 HTML 报告 ...")
    html = _build_html(out, v_field, a_field, tf_field, times, disp_series,
                       bbox, (H, W))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    # 落一份 JSON 供平台后续接入
    (RESULT / f"track{args.track}").mkdir(parents=True, exist_ok=True)
    import json
    (RESULT / f"track{args.track}" / "deformation_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n" + "=" * 56)
    print("趋势研判:", evidence["verdict"]["type"],
          f"（置信度 {evidence['verdict']['confidence']}）")
    print(f"速率: 中位 {evidence['summary']['velocity']['median']} mm/yr, "
          f"最大 |v| {evidence['summary']['velocity']['maxAbs']} mm/yr")
    print(f"信噪比: {snr:.3f} ({'可靠' if evidence['reliable'] else '不足，加速度仅供参考'})")
    print(f"危险测点: {len(evidence['hotspots'])} 个, "
          f"可外推失稳 {evidence['summary']['n_forecastable']} 像元")
    print(f"风险提级: +{overlay['uplift']} 级")
    print("=" * 56)
    print(f"\n报告: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

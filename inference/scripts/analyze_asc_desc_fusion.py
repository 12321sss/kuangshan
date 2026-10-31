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
    vert = fused["vertical_mmyr"]
    east = fused["east_west_mmyr"]
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
        # 场数组（前端热力图直接消费；round 到 1 位，NaN 保留）
        "verticalField": _field(vert),
        "eastWestField": _field(east),
        "bbox": list(bbox),
        "note": "单轨/双轨均为 LOS 或 2D 近似；南北分量不可解；"
                "时序仅 3 个月，速率可用、加速度不可信",
    }
    out_json.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写 {out_json}")

    # ---- 生成自包含 HTML（垂直/东西向双热力图 + 统计）----
    html = _build_fusion_html(vert, east, los_desc, los_asc, meta)
    html_path = Path(args.out)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    print(f"报告: {html_path.resolve()}")
    return 0




def _field(a: np.ndarray) -> list:
    """把二维场转成 list[list]（round 1 位，NaN 保留），供前端热力图。"""
    arr = np.round(a, 1)
    return [[None if not np.isfinite(v) else float(v) for v in row] for row in arr]


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


def _cmap(t: float) -> str:
    """蓝(负) → 白(0) → 红(正)，与国内涨红跌绿习惯一致的方向感。"""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        x = t * 2
        r, g, b = 0.2 + x * 0.4, 0.3 + x * 0.5, 1.0 - x * 0.2
    else:
        x = (t - 0.5) * 2
        r, g, b = 1.0, 1.0 - x * 0.85, 1.0 - x * 0.8
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _heat_svg(field, title: str, unit: str) -> str:
    """单场热力图（P5~P95 自适应上色，避免极值噪声主导）。"""
    f = np.asarray(field, dtype=np.float64)
    H, W = f.shape
    valid = f[np.isfinite(f)]
    vmin = float(np.percentile(valid, 5)) if valid.size else -1
    vmax = float(np.percentile(valid, 95)) if valid.size else 1
    span = (vmax - vmin) or 1.0
    rects = []
    for r in range(H):
        for c in range(W):
            v = f[r, c]
            if not np.isfinite(v):
                color = "#1f2937"
            else:
                color = _cmap((np.clip(v, vmin, vmax) - vmin) / span)
            rects.append(f'<rect x="{c*7}" y="{r*7}" width="7" height="7" fill="{color}"/>')
    return (f'<div class="chart"><div class="chart-title">{title}</div>'
            f'<svg viewBox="0 0 {W*7} {H*7}" width="{min(W*7, 540)}" height="{min(H*7, 500)}">'
            f'{"".join(rects)}</svg>'
            f'<div class="legend">颜色范围取 P5~P95：{vmin:+.1f} ~ {vmax:+.1f} {unit}'
            f'（超出部分饱和显示，避免极值噪声主导视觉）</div></div>')


def _build_fusion_html(vert, east, los_desc, los_asc, meta: dict) -> str:
    """升降轨联合结果的 HTML 报告。"""
    v = vert[np.isfinite(vert)]
    e = east[np.isfinite(east)]

    def stat_row(name, arr, unit="mm/yr"):
        if arr.size == 0:
            return f"<tr><td>{name}</td><td colspan=\"5\">无有效像元</td></tr>"
        return (f"<tr><td>{name}</td>"
                f"<td>{np.median(arr):+.1f}</td>"
                f"<td>{np.percentile(arr,5):+.1f}</td>"
                f"<td>{np.percentile(arr,95):+.1f}</td>"
                f"<td>{arr.min():+.1f} ~ {arr.max():+.1f}</td>"
                f"<td>{arr.size}</td></tr>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>茜坑升降轨联合解算（垂直+东西向）</title>
<style>
 body {{ font-family: "Microsoft YaHei", sans-serif; margin:0; background:#f5f7fa; color:#1f2937; }}
 .wrap {{ max-width:900px; margin:0 auto; padding:24px; }}
 h1 {{ font-size:22px; border-left:4px solid #2563eb; padding-left:12px; }}
 h2 {{ font-size:17px; margin-top:26px; color:#1e3a8a; }}
 .banner {{ background:#dbeafe; border:1px solid #60a5fa; border-radius:8px;
            padding:12px 14px; font-size:13px; color:#1e40af; margin:14px 0; }}
 table {{ width:100%; border-collapse:collapse; background:#fff; font-size:13px; margin:10px 0; }}
 th,td {{ padding:8px 10px; border-bottom:1px solid #e5e7eb; text-align:left; }}
 th {{ background:#f0f4ff; color:#1e3a8a; }}
 .chart {{ background:#fff; border-radius:8px; padding:14px; margin:12px 0;
           box-shadow:0 1px 3px rgba(0,0,0,.08); }}
 .chart-title {{ font-size:14px; font-weight:600; margin-bottom:8px; }}
 .legend {{ font-size:12px; color:#6b7280; margin-top:6px; }}
 .geo {{ background:#f0fdf4; border-radius:8px; padding:12px; font-size:13px; }}
 .disclaimer {{ background:#fee2e2; border:1px solid #fca5a5; border-radius:8px;
                padding:12px; font-size:13px; color:#991b1b; margin-top:22px; }}
</style></head><body><div class="wrap">
<h1>茜坑矿区升降轨联合解算</h1>
<div class="banner">单轨 InSAR 只能测视线向(LOS)位移；联合升轨+降轨可解出<b>垂直(V)与东西(E)</b>
两个分量——这才是「沉降量」的物理含义。南北向因轨道近极地不可解。</div>

<h2>一、几何条件（解算成立的前提）</h2>
<div class="geo">
 降轨 LOS 单位向量：(E={los_desc[0]:+.3f}, N={los_desc[1]:+.3f}, U={los_desc[2]:+.3f})<br>
 升轨 LOS 单位向量：(E={los_asc[0]:+.3f}, N={los_asc[1]:+.3f}, U={los_asc[2]:+.3f})<br>
 <span style="color:#059669">✓ 两轨东西向符号相反、垂直向同号，几何正交性良好，可解像元
 {meta['solvedPixels']} / {meta['shape'][0]*meta['shape'][1]}</span>
</div>

<h2>二、统计</h2>
<table><thead><tr><th>分量</th><th>中位</th><th>P5</th><th>P95</th><th>极值</th><th>像元数</th></tr></thead>
<tbody>
{stat_row("垂直分量 V", v)}
{stat_row("东西分量 E", e)}
</tbody></table>

<h2>三、空间分布</h2>
{_heat_svg(vert, "垂直形变速率（正值=抬升，负值=沉降）", "mm/yr")}
{_heat_svg(east, "东西向形变速率（正值=向东）", "mm/yr")}

<div class="disclaimer">
<b>口径与局限：</b>本结果为「潜在形变风险筛查」，非边坡稳定性评价，不给安全系数。<br>
① 观测期仅 3 个月（NISAR 8 期 / 6 期），速率可用但<b>加速度不可信</b>，且空间噪声较大
（P5~P95 跨度远大于中位值）；<br>
② 已按参考区归零消除大气/轨道长波残差，但短时序无法完全压制；<br>
③ 东西向分量对 LOS 几何敏感，斜距向误差会放大到东西向，需谨慎解读；<br>
④ 判定须结合边坡单元、现场勘察与多源数据复核。
</div>
</div></body></html>"""

if __name__ == "__main__":
    raise SystemExit(main())

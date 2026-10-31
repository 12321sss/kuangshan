"""茜坑矿区形变趋势分析演示（合成数据版，跑通真实算法链路）。

背景
----
真实 InSAR 数据（NISAR GUNW / Sentinel-1 SLC）当前不在本机、且无 Earthdata 凭据，
无法对真实数据跑趋势分析。本脚本用「符合实测量级的合成时序」跑通完整链路：

    SBAS 反演 → 速度/加速度/失稳外推 → 趋势研判 → 形变证据 → 风险提级

目的：展示「趋势分析 + 安全分析」的完整输出形态，等真实数据到位后，
把数据源换成 read_track() 即可出真实结论。

口径红线
--------
本脚本产出的是**合成演示数据**，仅展示链路与输出形态，不构成任何真实安全结论。
报告标题、正文、免责声明三处均明确标注「合成演示数据」。

用法
----
    python scripts/demo_deformation_trend.py --out docs/茜坑形变趋势演示.html
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from algorithms.deformation import analyze_timeseries, build_evidence, summarize_field
from algorithms.unwrap import L_BAND_WAVELENGTH_M
from algorithms.deformation_risk import deformation_overlay
from algorithms.sbas import Pair, reference_correction, solve

# 茜坑矿区（track 18，参考 docs/26）：约 114.87~114.93E, 28.57~28.62N
XICHENG_BBOX = (114.87, 28.57, 114.93, 28.62)
GRID = (48, 60)          # 行(纬度) × 列(经度)，80m 网格约 3.84km × 4.8km
N_EPOCHS = 12            # 12 期，约每月一景，跨 1 年（满足「≥1 年出可信趋势」）


# ---------------------------------------------------------------------------
# 合成形变场：符合 docs/26 实测量级（速率中位 -10.5mm/yr、峰值可达 -40mm/yr）
# ---------------------------------------------------------------------------

def _make_velocity_acceleration(grid: tuple[int, int]):
    """构造速度场（mm/yr）与加速度场（mm/yr²）。

    三类区域：
      1. 背景稳定区：±5 mm/yr 的缓变噪声
      2. 采空区沉降中心：高斯峰值 -40 mm/yr（模拟地下开采引起的缓慢沉降）
      3. 局部加速边坡：速度 -22 mm/yr 且加速度 +25 mm/yr²（模拟失稳前兆，
         会触发形变提级）
    """
    H, W = grid
    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)

    # 背景：缓慢沉降 + 空间缓变噪声
    vel = -8.0 + rng.normal(0, 4.0, (H, W))
    vel += 6.0 * np.sin(xx / 18.0) * np.cos(yy / 15.0)

    # 采空区沉降中心（高斯，峰值额外 -32 → 合计约 -40）
    cy, cx, sigma = 20.0, 34.0, 9.0
    gauss = np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))
    vel += -32.0 * gauss

    # 加速度场：全局近 0，仅局部边坡加速
    acc = np.zeros((H, W))
    ay, ax, asig = 30.0, 46.0, 4.0
    acc_gauss = np.exp(-(((yy - ay) ** 2 + (xx - ax) ** 2) / (2 * asig ** 2)))
    acc += 25.0 * acc_gauss
    # 加速区的速度也略偏高（临滑前兆）
    vel += -6.0 * acc_gauss

    # 参考区（左上角）保持绝对稳定
    vel[:4, :4] = 0.0
    acc[:4, :4] = 0.0
    return vel, acc


def _synthesize_pairs(times, vel, acc):
    """由速度/加速度场合成 11 个相邻干涉对（含大气残差噪声）。

    每像元位移 d(t) = v*(t-t0) + 0.5*a*(t-t0)^2，
    干涉相位 = (d(t_{k+1}) - d(t_k)) * 4π/λ + 噪声。
    """
    rng = np.random.default_rng(7)
    t0 = times[0]
    # 每个时刻的累积位移（H,W,T 之前先算 per-time）
    H, W = vel.shape
    disp_true = np.zeros((len(times), H, W))
    for i, t in enumerate(times):
        dt = t - t0
        disp_true[i] = vel * dt + 0.5 * acc * dt * dt

    pairs = []
    for k in range(len(times) - 1):
        dphi = disp_true[k + 1] - disp_true[k]       # 位移增量 mm
        phase = dphi / 1000.0 * (4 * math.pi / L_BAND_WAVELENGTH_M)
        # 大气/轨道残差：每景加一个空间平滑的整体偏移（几十 mm 量级）+ 白噪声
        r, c = np.mgrid[0:H, 0:W].astype(np.float64)
        atm = 3.0 * np.sin(r / 8.0 + k) * np.cos(c / 10.0 - k)   # 平滑残差
        phase = phase + atm * (4 * math.pi / L_BAND_WAVELENGTH_M) * 0.5 / 1000.0
        phase = phase + rng.normal(0, 0.3, (H, W))                # 白噪声 ±0.3 rad
        coh = 0.7 + 0.2 * rng.random((H, W))
        pairs.append(Pair(t_ref=float(times[k]), t_sec=float(times[k + 1]),
                          phase=phase.astype(np.float32),
                          coherence=coh.astype(np.float32)))
    return pairs


def _build_html(out: dict, vel, acc, tf, times, disp_series, bbox, grid) -> str:
    """生成自包含 HTML（内嵌 SVG，无外部依赖，双击即可看）。"""
    H, W = grid
    xs = np.linspace(bbox[0], bbox[2], W)
    ys = np.linspace(bbox[1], bbox[3], H)

    # ---- SVG 热力图（速度 / 加速度）----
    def heat_svg(field, title, unit, cmap="seismic", vmin=None, vmax=None):
        w, h = W * 7, H * 7
        rects = []
        f = np.asarray(field, dtype=np.float64)
        fv = f[np.isfinite(f)]
        # 颜色范围自适应到 P5~P95：真实数据的极值（边缘大气残差）可达 ±400mm/yr，
        # 若按全范围上色，热力图会被 23 个极端像元主导，真实的形变结构反而看不清。
        if vmin is None and fv.size:
            vmin = float(np.percentile(fv, 5))
        if vmax is None and fv.size:
            vmax = float(np.percentile(fv, 95))
        span = (vmax - vmin) or 1.0
        for r in range(H):
            for c in range(W):
                v = f[r, c]
                if not np.isfinite(v):
                    color = "#222"
                else:
                    t = (np.clip(v, vmin, vmax) - vmin) / span
                    color = _cmap(t, cmap)
                rects.append(f'<rect x="{c*7}" y="{r*7}" width="7" height="7" '
                             f'fill="{color}"/>')
        return (f'<div class="chart"><div class="chart-title">{title}</div>'
                f'<svg viewBox="0 0 {w} {h}" width="{min(w,520)}" height="{min(h,416)}">'
                f'{"".join(rects)}</svg></div>')

    # ---- SVG 时序曲线（3 个代表测点）----
    def ts_svg(series, t):
        w, h = 460, 220
        ymin = min(min(s) for s in series.values())
        ymax = max(max(s) for s in series.values())
        pad = (ymax - ymin) * 0.1 or 1.0
        ymin, ymax = ymin - pad, ymax + pad
        # 动态调色板：按系列出现顺序分配颜色（真实/合成数据的关键名不同）
        palette = ["#e74c3c", "#e67e22", "#2ecc71", "#3498db", "#9b59b6", "#16a085"]
        colors = {name: palette[i % len(palette)]
                  for i, name in enumerate(series.keys())}
        polys = []
        for name, s in series.items():
            pts = []
            for i, (ti, vi) in enumerate(zip(t, s)):
                x = 40 + i / (len(t) - 1) * (w - 70)
                y = 20 + (1 - (vi - ymin) / (ymax - ymin)) * (h - 50)
                pts.append(f"{x:.1f},{y:.1f}")
            polys.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                         f'stroke="{colors[name]}" stroke-width="2"/>')
        # 零线
        if ymin < 0 < ymax:
            y0 = 20 + (1 - (0 - ymin) / (ymax - ymin)) * (h - 50)
            polys.append(f'<line x1="40" y1="{y0:.1f}" x2="{w-30}" y2="{y0:.1f}" '
                         f'stroke="#555" stroke-dasharray="4 3"/>')
        legend = "".join(f'<span style="color:{c}">■ {n}</span> ' for n, c in colors.items())
        return (f'<div class="chart"><div class="chart-title">代表测点累积位移时序（LOS）</div>'
                f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
                f'{"".join(polys)}</svg><div class="legend">{legend}</div></div>')

    vel_svg = heat_svg(vel, "形变速率场（mm/yr，负=远离卫星/沉降，颜色取 P5~P95）", "mm/yr")
    acc_svg = heat_svg(acc, "形变加速度场（mm/yr²，正值=加速，颜色取 P5~P95）", "mm/yr²", cmap="hot")

    # ---- 危险测点表 ----
    rows = ""
    for i, h_ in enumerate(out["evidence"]["hotspots"][:10], 1):
        rows += (f'<tr><td>{i}</td><td>{h_["x"]:.4f}, {h_["y"]:.4f}</td>'
                 f'<td>{h_["velocity"]:+.1f}</td><td>{h_["acceleration"]:+.1f}</td>'
                 f'<td>{h_.get("tfDays") if h_.get("tfDays") is not None else "—"}</td>'
                 f'<td>{h_["severityLabel"]}</td></tr>')

    v = out["evidence"]
    ver = v["verdict"]
    uplift_txt = "未触发" if out["overlay"]["uplift"] == 0 else f"+{out['overlay']['uplift']} 级"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>茜坑矿区形变趋势分析（合成演示）</title>
<style>
 body {{ font-family: "Microsoft YaHei", sans-serif; margin: 0; background: #f5f7fa; color: #1f2937; }}
 .wrap {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
 h1 {{ font-size: 22px; border-left: 4px solid #2563eb; padding-left: 12px; }}
 h2 {{ font-size: 17px; margin-top: 28px; color: #1e3a8a; }}
 .banner {{ background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px;
            padding: 10px 14px; font-size: 13px; color: #92400e; margin: 14px 0; }}
 .kv {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }}
 .card {{ background: #fff; border-radius: 8px; padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          flex: 1 1 180px; }}
 .card .num {{ font-size: 22px; font-weight: 700; color: #2563eb; }}
 .card .lab {{ font-size: 12px; color: #6b7280; }}
 .chart {{ background: #fff; border-radius: 8px; padding: 14px; margin: 12px 0;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
 .chart-title {{ font-size: 14px; font-weight: 600; margin-bottom: 8px; }}
 .legend {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
 table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; }}
 th, td {{ padding: 7px 9px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
 th {{ background: #f0f4ff; color: #1e3a8a; }}
 .verdict {{ background: #eff6ff; border-radius: 8px; padding: 14px; margin: 10px 0; }}
 .verdict .type {{ font-size: 18px; font-weight: 700; color: #1d4ed8; }}
 .note {{ font-size: 12px; color: #6b7280; line-height: 1.6; }}
 .disclaimer {{ background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px;
                padding: 12px 14px; font-size: 13px; color: #991b1b; margin-top: 24px; }}
</style></head><body><div class="wrap">
<h1>茜坑矿区形变趋势分析（合成演示数据）</h1>
<div class="banner">⚠️ 本报告基于<b>合成时序数据</b>跑通真实算法链路，仅展示输出形态，不构成真实安全结论。
真实 InSAR 数据（NISAR/Sentinel-1）到位后，替换数据源即可出真实结果。</div>

<div class="kv">
 <div class="card"><div class="num">{v['summary']['n_valid']}</div><div class="lab">有效像元</div></div>
 <div class="card"><div class="num">{v['summary']['velocity']['median']}</div><div class="lab">中位速率(mm/yr)</div></div>
 <div class="card"><div class="num">{v['summary']['velocity']['maxAbs']}</div><div class="lab">最大|速率|(mm/yr)</div></div>
 <div class="card"><div class="num">{v['nForecastable'] if v['nForecastable'] is not None else '数据不足'}</div><div class="lab">可外推失稳像元</div></div>
 <div class="card"><div class="num">{v['snr']}</div><div class="lab">信噪比(≥0.3可靠)</div></div>
</div>

<h2>一、趋势研判</h2>
<div class="verdict"><span class="type">{ver['type']}</span>
 <span style="font-size:12px;color:#6b7280">（置信度 {ver['confidence']}）</span>
 <div class="note">{ver['basis']}</div></div>
<div class="note">趋势分布：加速 {v['summary']['trend']['accelerating']} 像元 /
 稳定 {v['summary']['trend']['stable']} 像元 /
 减速 {v['summary']['trend']['decelerating']} 像元
 （加速占比 {v['summary']['trend']['pctAccelerating']}%）。</div>

<h2>二、空间分布</h2>
{vel_svg}
{acc_svg}

<h2>三、危险测点清单（按风险排序）</h2>
<table><thead><tr><th>#</th><th>位置(lng,lat)</th><th>速率(mm/yr)</th><th>加速度(mm/yr²)</th><th>外推失稳(天)</th><th>速度分级</th></tr></thead>
<tbody>{rows}</tbody></table>

<h2>四、风险提级</h2>
<div class="kv">
 <div class="card"><div class="num">{out['overlay']['uplift']}</div><div class="lab">提级数</div></div>
 <div class="card"><div class="num">{out['overlay']['adjusted_score']}</div><div class="lab">提级后风险分</div></div>
 <div class="card"><div class="num">{uplift_txt}</div><div class="lab">提级结论</div></div>
</div>
<div class="note">{'; '.join(out['overlay']['evidence'])}</div>

<h2>五、代表测点时序</h2>
{ts_svg(disp_series, times)}

<div class="disclaimer">免责声明：本报告为合成演示数据，仅用于展示「形变趋势 → 安全分析」链路输出形态。
真实结论需以实际 InSAR 数据、结合边坡单元与现场勘察复核为准；单轨结果为 LOS 视线向，非垂直沉降。</div>
</div></body></html>"""


def _cmap(t: float, name: str) -> str:
    """简单颜色映射：seismic（蓝→白→红）或 hot（黑→红→黄）。"""
    if name == "hot":
        r = min(1.0, t * 1.8)
        g = min(1.0, max(0.0, (t - 0.4) * 1.5))
        b = min(1.0, max(0.0, (t - 0.75) * 3.0))
    else:  # seismic
        if t < 0.5:
            x = t * 2
            r, g, b = x * 0.4 + 0.2, x * 0.5, 1.0 - x * 0.2
        else:
            x = (t - 0.5) * 2
            r, g, b = 1.0, 1.0 - x * 0.85, 1.0 - x * 0.8
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def main() -> int:
    ap = argparse.ArgumentParser(description="茜坑形变趋势分析演示（合成数据）")
    ap.add_argument("--out", default="docs/茜坑形变趋势演示.html")
    args = ap.parse_args()

    H, W = GRID
    times = [2026.0 + i * (30.0 / 365.25) for i in range(N_EPOCHS)]

    print("构造合成形变场（符合实测量级）...")
    vel, acc = _make_velocity_acceleration(GRID)

    print("合成干涉对 + SBAS 反演...")
    pairs = _synthesize_pairs(times, vel, acc)
    ref_mask = np.zeros((H, W), dtype=bool)
    ref_mask[:4, :4] = True
    pairs = reference_correction(pairs, ref_mask)
    res = solve(pairs)

    print("逐像元趋势分析（速度/加速度/失稳外推）...")
    disp = res["displacement_mm"]
    times_arr = res["times"]
    v_field = np.full((H, W), np.nan)
    a_field = np.full((H, W), np.nan)
    tf_field = np.full((H, W), np.nan)
    for r in range(H):
        for c in range(W):
            d = disp[:, r, c]
            tv = np.isfinite(d)
            if tv.sum() < 6:
                continue
            tr = analyze_timeseries([times_arr[i] for i in range(len(times_arr)) if tv[i]],
                                    d[tv])
            v_field[r, c] = tr.velocity_mmyr
            a_field[r, c] = tr.acceleration_mmyr2
            if tr.tf_days:
                tf_field[r, c] = tr.tf_days

    # 信噪比：加速度中位 / 标准差
    av = a_field[np.isfinite(a_field)]
    snr = abs(float(np.median(av))) / float(av.std()) if av.size and av.std() > 0 else 0.0

    xs = np.linspace(XICHENG_BBOX[0], XICHENG_BBOX[2], W)
    ys = np.linspace(XICHENG_BBOX[1], XICHENG_BBOX[3], H)
    evidence = build_evidence(v_field, a_field, tf_field, snr, xs, ys, top_n=10)

    overlay = deformation_overlay(
        55.0, evidence["velocityMmyr"], evidence["accelerationMmyr2"],
        reliable=evidence["reliable"])

    # 代表测点时序（沉降中心 / 加速边坡 / 参考区）
    picks = {"沉降中心": (20, 34), "加速边坡": (30, 46), "稳定参考区": (1, 1)}
    disp_series = {}
    for name, (r, c) in picks.items():
        d = disp[:, r, c]
        tv = np.isfinite(d)
        disp_series[name] = [float(d[i]) if tv[i] else None for i in range(len(d))]
    # 去掉 None（绘图时跳过）
    for name in list(disp_series.keys()):
        disp_series[name] = [x if x is not None else 0.0 for x in disp_series[name]]

    out = {
        "evidence": evidence,
        "overlay": overlay,
        "snr": snr,
    }

    print("生成 HTML 报告...")
    html = _build_html(out, v_field, a_field, tf_field, times_arr, disp_series,
                       XICHENG_BBOX, GRID)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print("\n" + "=" * 56)
    print("趋势研判:", evidence["verdict"]["type"],
          f"（置信度 {evidence['verdict']['confidence']}）")
    print(f"速率: 中位 {evidence['summary']['velocity']['median']} mm/yr, "
          f"最大 |v| {evidence['summary']['velocity']['maxAbs']} mm/yr")
    print(f"信噪比: {snr:.3f} ({'可靠' if evidence['reliable'] else '不足'})")
    print(f"危险测点: {len(evidence['hotspots'])} 个, "
          f"可外推失稳 {evidence['summary']['n_forecastable']} 像元")
    print(f"风险提级: +{overlay['uplift']} 级 → 提级后 {overlay['adjusted_score']} 分")
    print("=" * 56)
    print(f"\n报告已生成: {out_path.resolve()}")
    print("双击该 HTML 即可在浏览器查看（自包含，无需联网）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

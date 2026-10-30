"""验证：能否用 QUICKLOOK（整景缩略图）按 AOI 裁剪出可显示的影像片段。

背景：Copernicus 新版 Assets 只暴露 QUICKLOOK（343x343 JPEG，无地理参考 crs=None），
波段 JP2 需鉴权（s3 直连 403），公开 WMS（CNES/GEE）在当前网络不通。
因此「显示真实影像」的可行路径是：下载 QUICKLOOK → 按场景 footprint 做线性映射
→ 裁出 AOI 那块 → 存 PNG 供前端叠加显示。

精度限制：QUICKLOOK 是 343px 覆盖约 100km，单像素约 300m，
只能做**位置与范围确认**，不能当解译数据源（解译仍需上传的高分影像）。
"""
import io
import os
import tempfile

import requests
from PIL import Image

import sys
from pathlib import Path

# 直接运行脚本时，把 inference 根目录加进 sys.path，才能 import algorithms
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algorithms import sentinel_source as s

OUT = os.path.join(tempfile.gettempdir(), "aoi_crop.png")

AOI = (115.20, 26.30, 115.40, 26.40)   # (west, south, east, north)


def main():
    scenes = s.search(115.2, 26.3, "2023-12-01", "2023-12-31", max_cloud=5, limit=1)
    if not scenes:
        print("未检索到场景")
        return
    sc = scenes[0]
    print(f"场景: {sc.acquisition_date}  云量 {sc.cloud_cover:.1f}%  tile {sc.tile_id}")
    print(f"footprint: lng[{sc.west:.4f},{sc.east:.4f}] lat[{sc.south:.4f},{sc.north:.4f}]")

    r = requests.get(sc.quicklook_url, verify=s.CA_BUNDLE, timeout=60)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    W, H = im.size
    print(f"QUICKLOOK: {W}x{H}  ({len(r.content) / 1024:.1f} KB)")

    # 关键：QUICKLOOK 无地理参考，用场景 footprint 做线性映射
    gW, gS, gE, gN = sc.bounds

    def to_px(lng: float, lat: float) -> tuple[int, int]:
        x = (lng - gW) / (gE - gW) * W
        y = (gN - lat) / (gN - gS) * H
        return int(x), int(y)

    x0, y0 = to_px(AOI[0], AOI[3])   # 左上
    x1, y1 = to_px(AOI[2], AOI[1])   # 右下
    # 夹到图内
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, max(x1, x0 + 1)), min(H, max(y1, y0 + 1))
    crop = im.crop((x0, y0, x1, y1))
    print(f"AOI 像素窗口: ({x0},{y0})-({x1},{y1})  裁剪尺寸 {crop.size}")

    crop.save(OUT)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"已保存: {OUT}  ({size_kb:.1f} KB)")

    # 校验：裁剪区域应不是纯色（纯色说明映射错了）
    colors = crop.convert("RGB").getcolors(maxcolors=100000)
    if colors and len(colors) < 3:
        print(f"[FAIL] 裁剪区域颜色种类仅 {len(colors)}，疑似映射错误")
        return
    print(f"[PASS] 裁剪区域颜色种类 {len(colors) if colors else '>10 万'}，是真实影像内容")

    # 推算地面分辨率（供前端告知用户）
    m_lng = (gE - gW) * 111320 * 0.9
    m_lat = (gN - gS) * 110540
    print(f"\nQUICKLOOK 地面分辨率约: {m_lng / W:.0f} m/px（{W}px 覆盖 {m_lng / 1000:.0f} km）")
    print("结论：可用于**位置与范围确认**，不可用于解译（解译请上传高分影像）")


if __name__ == "__main__":
    main()
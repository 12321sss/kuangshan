"""
classify.py 的自检脚本：造一景合成 GeoTIFF，验证指数法能否真的分出三类地物。

合成原理（模拟 Sentinel-2 L1C 的反射率量纲 uint16）：
- 植被区：近红外高、红外低 → NDVI 高
- 水体区：绿光高于近红外 → NDWI 高
- 裸地区：SWIR 高、近红外中等 → NDVI 低且 NDBI 高

本轮自检实际踩到并修正的坑（按发现顺序）：
1. EPSG:4326 下 from_origin 的 dx/dy 单位是「度」不是米 —— 见下方换算
2. 合成影像必须按**真实 Sentinel-2 波段号**摆放（B02=2 B03=3 B04=4 B08=8 B11=11），
   不能图省事挤在前4 个波段：classify 的 BANDS 表用真实波段号索引
3. 背景值不能用均匀灰岩（800）：它会同时满足「NDVI 低」与「NDBI 低」而落进
   裸地判据，使裸地面积虚高一倍。矿区背景多为林地覆盖，背景应给成植被光谱
4. np.s_ 生成的是元组，不能直接 bands[0, sl] 索引，须用 bands[0, rows, cols]

关键坑（自检时踩到并修正）：
- EPSG:4326 下 from_origin 的 dx/dy 是「度」，不是米！
  10m 分辨率必须先换算：dlon = 10/ (111320*cos(lat))，dlat = 10/110540
  否则影像 y 范围会变成负数（如 -2533），面积算出来差 4 个数量级。

跑法：python selftest_classify.py
"""
import math
import os
import tempfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

from classify import classify

# 样区（宁都河源附近）
WEST, SOUTH = 115.20, 26.30
SIZE = 256
RES_M = 10.0                      # 目标地面分辨率（米）
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(SOUTH))
D_LAT = RES_M / M_PER_DEG_LAT
D_LON = RES_M / M_PER_DEG_LON
NORTH = SOUTH + SIZE * D_LAT


def build_synthetic(path: str) -> None:
    """造 11 波段 S2 样式影像，按真实 S2 波段号摆放：B02=2 B03=3 B04=4 B08=8 B11=11"""
    h = w = SIZE
    transform = from_origin(WEST, NORTH, D_LON, D_LAT)
    hh, hw = h // 2, w // 2

    # 背景 = 典型亚热带林地（红低、近红高 → NDVI 约 0.6），
    # 故意给成植被而不是灰岩：灰岩值(800 均匀)会同时满足 NDVI低 且 NDBI低，
    # 落进裸地判据，导致裸地面积虚高一倍（真实矿区背景多为林地覆盖）
    bands = np.full((11, h, w), 800, dtype=np.uint16)
    bands[3, :, :] = 3100   # B04 红（低）
    bands[7, :, :] = 3300   # B08 近红外（高）→ NDVI=(3300-800)/(4100)=0.61
    bands[10, :, :] = 2400  # B11短红

    def fill(rows, cols, blue, green, red, nir, swir):
        """按**真实 Sentinel-2 波段号**填充：B02=第2波段 B03=第3 B04=第4
        B08=第8(近红外) B11=第11(短波红外)。1-based 索引减1 用 0-based。"""
        bands[1, rows, cols] = blue
        bands[2, rows, cols] = green
        bands[3, rows, cols] = red
        bands[7, rows, cols] = nir
        bands[10, rows, cols] = swir

    # 左上 = 植被：NDVI=(3200-700)/(3200+700)=0.64 高
    fill(slice(0, hh), slice(0, hw), 900, 1100, 700, 3200, 2800)
    # 右上 = 裸地：NDVI=(1900-1800)/3700~0.03 低，NDBI=(3200-1900)/5100=0.25 高
    fill(slice(0, hh), slice(hw, w), 1300, 1500, 1800, 1900, 3200)
    # 右下 = 水体：NDWI=(1600-500)/2100=0.52 高
    fill(slice(hh, h), slice(hw, w), 800, 1600, 600, 500, 400)
    # 左下保持背景 800

    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": 11,
        "dtype": "uint16",
        "crs": "EPSG:4326",
        "transform": transform,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(bands)


def main() -> None:
    tmp = os.path.join(tempfile.gettempdir(), "s2_synth_test.tif")
    build_synthetic(tmp)
    print(f"合成影像: {tmp}")
    print(f"  {SIZE}x{SIZE}  11 波段  {RES_M}m  EPSG:4326")
    print(f"  实际像元: dlon={D_LON:.8f}度 dlat={D_LAT:.8f}度")
    print()

    aoi = (WEST, SOUTH, WEST + SIZE * D_LON, NORTH)
    ok = True
    results = {}

    for cls in ("VEGETATION", "WATER", "BARE"):
        r = classify(tmp, "SENTINEL2", cls, aoi_bounds=aoi, min_polygon_ha=0.0)
        results[cls] = r
        got = r.pixel_count > 0
        status = "PASS" if got else "FAIL"
        if not got:
            ok = False
        print(f"[{status}] {r.label:8s} 多边形 {len(r.polygons):3d} 个  "
              f"像元 {r.pixel_count:7d}  面积 {r.extract_area_ha:8.2f} ha")
        print(f"         NDVI={r.stats['ndvi_mean']:.3f}  NDWI={r.stats['ndwi_mean']:.3f}  "
              f"NDBI={r.stats['ndbi_mean']:.3f}  有效像元比={r.stats['valid_pixel_ratio']:.3f}")

    print()
    expected_ha = (SIZE / 2) ** 2 * RES_M * RES_M / 10000
    print(f"参考：每象限理论面积 {expected_ha:.2f} ha")

    # 面积量级校验：三个象限各应接近理论值
    for cls in ("VEGETATION", "WATER", "BARE"):
        got_ha = results[cls].extract_area_ha
        ratio = got_ha / expected_ha if expected_ha else 0
        passed = 0.85 <= ratio <= 1.15
        if not passed:
            ok = False
        print(f"  [{'PASS' if passed else 'FAIL'}] {cls:10s} 实测 {got_ha:8.2f} ha "
              f"(理论 {expected_ha:.2f}，偏差 {abs(ratio - 1) * 100:.1f}%)")

    # 坐标与闭合性抽查
    r = results["VEGETATION"]
    if r.polygons:
        ring = r.polygons[0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        closed = ring[0] == ring[-1]
        in_range = (min(lons) >= WEST - 1e-6 and max(lons) <= WEST + SIZE * D_LON + 1e-6
                    and min(lats) >= SOUTH - 1e-6 and max(lats) <= NORTH + 1e-6)
        print()
        print(f"  首个多边形: lng[{min(lons):.5f},{max(lons):.5f}] "
              f"lat[{min(lats):.5f},{max(lats):.5f}]")
        print(f"  [{'PASS' if closed else 'FAIL'}] 环闭合")
        print(f"  [{'PASS' if in_range else 'FAIL'}] 坐标落在样区范围内")
        if not (closed and in_range):
            ok = False

    print()
    print("=== 自检结果:", "全部通过" if ok else "存在失败项", "===")


if __name__ == "__main__":
    main()
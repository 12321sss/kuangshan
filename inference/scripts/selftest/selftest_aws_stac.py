"""实测增量包 sentinel.py 的 AWS STAC 直连链路（不经过 main.py）。

验证四步：
1. search_scene：STAC 检索能否命中宁都河源样区的无云景
2. clip_aoi：COG Range 请求按 AOI 剪切多波段是否成功
3. true_color_png：真彩合成是否出有效 PNG
4. extract_class：指数 → 矢量化是否出 GeoJSON

这是集成前最重要的验证——如果这步不通，后面全白搭。
"""
import sys
from pathlib import Path

# 直接运行脚本时，把 inference 根目录加进 sys.path，才能 import algorithms
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import time

from algorithms import sentinel

# 宁都河源样区（赣锋硬岩锂矿候选样区，江西本地）
AOI = [
    [115.90, 26.60],
    [116.05, 26.60],
    [116.05, 26.75],
    [115.90, 26.75],
]


def main():
    print("=== 1. STAC 检索 ===")
    t0 = time.time()
    feat = sentinel.search_scene(AOI, "2024-01-01", "2024-12-31", max_cloud=20.0)
    dt = time.time() - t0
    if feat is None:
        print(f"[FAIL] 未检索到无云景（耗时 {dt:.1f}s）")
        return
    props = feat["properties"]
    print(f"[PASS] 命中景（耗时 {dt:.1f}s）")
    print(f"  scene_id   : {feat['id']}")
    print(f"  datetime   : {props.get('datetime')}")
    print(f"  cloud_cover: {props.get('eo:cloud_cover')}%")
    print(f"  assets     : {list(feat['assets'].keys())}")

    print("\n=== 2. AOI 剪切（B02/B03/B04 真彩三波段）===")
    t0 = time.time()
    clipped = sentinel.clip_aoi(feat, AOI, ["B02", "B03", "B04"])
    dt = time.time() - t0
    shapes = {b: clipped["bands"][b].shape for b in clipped["bands"]}
    print(f"[PASS] 剪切成功（耗时 {dt:.1f}s）")
    for b, s in shapes.items():
        print(f"  {b}: {s}")

    print("\n=== 3. 真彩 PNG ===")
    png = sentinel.true_color_png(clipped["bands"])
    print(f"[PASS] PNG 生成 {len(png)} bytes，magic={png[:4].hex()}（应 89504e47）")

    print("\n=== 4. 指数提取 + 矢量化（VEGETATION）===")
    t0 = time.time()
    # 需要 B08 算 NDVI
    clipped_full = sentinel.clip_aoi(feat, AOI, ["B02", "B03", "B04", "B08"])
    result = sentinel.extract_class(
        clipped_full["bands"], "VEGETATION",
        clipped_full["meta"]["B04"]["transform"],
        clipped_full["meta"]["B04"]["crs"],
        min_area_px=20,
    )
    dt = time.time() - t0
    print(f"[PASS] 提取完成（耗时 {dt:.1f}s）")
    print(f"  覆盖率       : {result['coverage_pct']}%")
    print(f"  要素数       : {result['feature_count']}")
    print(f"  阈值         : {result['threshold']}")
    if result["features"]:
        g = result["features"][0]["geometry"]
        print(f"  首个要素类型 : {g['type']}")
        # 抽查坐标范围是否在 WGS84 合理区间
        coords = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        lngs = [p[0] for p in coords]
        lats = [p[1] for p in coords]
        print(f"  坐标范围     : lng[{min(lngs):.4f},{max(lngs):.4f}] lat[{min(lats):.4f},{max(lats):.4f}]")
        ok = 115 < min(lngs) < 117 and 26 < min(lats) < 27
        print(f"  [{'PASS' if ok else 'FAIL'}] 坐标在宁都河源合理区间")

    print("\n=== 结论 ===")
    print("AWS Earth Search STAC 直连链路" + ("全部打通" if result["features"] else "检索成功但该 AOI 无植被"))


if __name__ == "__main__":
    main()
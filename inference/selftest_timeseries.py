"""时序播放验证：同一 AOI 用两个日期的影像各提取一次，看能否串成时序组。

流程：
1. 造两景测试影像（日期不同，植被区面积不同 —— 模拟矿山扩张）
2. 都上传入库（source=UPLOAD，走真实上传接口）
3. 用**完全相同**的 AOI 圈选，分别提交解译
4. 查 /api/timeseries/groups 看是否聚合成一个 2 期组
5. 查 /api/timeseries/{sig} 看序列是否按日期升序、面积有变化
"""
import math
import os
import time

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin

BASE = "http://localhost:8080"
TOKEN_HEAD = "rs-demo-inference-token-2026"
INF = "http://127.0.0.1:8010"

W, S = 115.20, 26.30
RES = 8.0
DLAT = RES / 110540
DLON = RES / (111320 * math.cos(math.radians(S)))
SIZE = 1024
NORTH = S + SIZE * DLAT


def build_scene(path: str, veg_side: int) -> None:
    """造一景影像：veg_side 决定植被区边长（模拟扩张）

    背景必须是**裸地**（NDVI 低、NDBI 高），不能给成植被光谱：
    若背景本身就是植被，整个 AOI 都会被判成植被，两期面积恒等于 AOI 全域，
    时序就看不出变化（实测踩过）。
    """
    tr = from_origin(W, NORTH, DLON, DLAT)
    # **四波段商业高分布局**：第1=B02蓝 第2=B03绿 第3=B04红 第4=B08近红
    # 必须与 classify.BANDS 的 GF2 映射一致；之前误按S2 十一波段布局写数据，
    # 导致按 GF2 读时波段错位、提取恒为 0。
    b = np.full((4, SIZE, SIZE), 800, dtype=np.uint16)
    # 背景 = 裸地：红较高、近红中等 → NDVI 低
    b[2] = 1800      # B04 红
    b[3] = 1900      # B08 近红 → NDVI ≈ 0.03 低
    # 植被区（面积随 veg_side 变化）：红低、近红高 → NDVI 高
    b[2, :veg_side, :veg_side] = 700
    b[3, :veg_side, :veg_side] = 3200
    rng = np.random.default_rng(veg_side)
    b = (b.astype(np.int32) + rng.integers(-15, 15, size=b.shape)).clip(1, 10000).astype(np.uint16)
    with rasterio.open(path, "w", driver="GTiff", height=SIZE, width=SIZE, count=4,
                       dtype="uint16", crs="EPSG:4326", transform=tr, compress="deflate") as d:
        d.write(b)


def login():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}


def upload(H, path, name, date):
    bounds = [W, S, W + SIZE * DLON, NORTH]
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, "image/tiff")}
        data = [("projectId", "1"), ("name", name), ("crs", "EPSG:4326"),
                ("acquisitionDate", date), ("resolutionM", "8")] + \
               [("bounds", str(b)) for b in bounds]
        r = requests.post(f"{BASE}/api/imagery/upload", headers=H,
                          files=files, data=data, timeout=300)
    r.raise_for_status()
    return r.json()["data"]


def main():
    H = login()
    print("登录成功\n")

    tmp = os.environ.get("TEMP", "C:/Users/asus/AppData/Local/Temp")
    p1 = os.path.join(tmp, "ts_scene_2021.tif")
    p2 = os.path.join(tmp, "ts_scene_2024.tif")
    # 两期面积不同：2021 植被区 400，2024 扩到 600（模拟变化）
    build_scene(p1, 420)
    build_scene(p2, 660)
    print("测试影像已生成")

    img1 = upload(H, p1, "时序测试 2021", "2021-06-15")
    img2 = upload(H, p2, "时序测试 2024", "2024-09-20")
    print(f"影像1 id={img1['id']} (2021-06-15)")
    print(f"影像2 id={img2['id']} (2024-09-20)\n")

    # 同一 AOI（顶点完全一致，仅起点不同 —— 验证指纹归一化）
    aoi = [
        [W + 0.005, S + 0.010],
        [W + 0.040, S + 0.010],
        [W + 0.040, S + 0.045],
        [W + 0.005, S + 0.045],
        [W + 0.005, S + 0.010],
    ]
    # 第二期换个起点（从第2 个顶点开始），验证指纹能否识别为同一 AOI
    aoi2 = [aoi[1], aoi[2], aoi[3], aoi[0], aoi[1]]

    for img, aoi_x, label in ((img1, aoi, "2021"), (img2, aoi2, "2024")):
        r = requests.post(f"{BASE}/api/extractions/submit", headers=H, json={
            "projectId": 1, "imageryId": img["id"], "classType": "VEGETATION",
            "aoi": aoi_x, "satellite": "GF2",
        }, timeout=30)
        r.raise_for_status()
        print(f"{label} 解译已提交: {r.json()['data']['taskId']}")

    print("\n等待回调落库...")
    for _ in range(50):
        time.sleep(1)
        items = requests.get(f"{BASE}/api/extractions", headers=H,
                             params={"projectId": 1}, timeout=15).json()["data"]
        if len([x for x in items if x.get("imageryId") in (img1["id"], img2["id"])]) >= 2:
            break

    # ---- 验证时序分组 ----
    groups = requests.get(f"{BASE}/api/timeseries/groups", headers=H,
                          params={"projectId": 1}, timeout=15).json()["data"]
    print(f"\n=== 时序分组（共 {len(groups)} 组）===")
    for g in groups:
        print(f"  {g['label']}: {g['periodCount']} 期 "
              f"{g['startDate']} → {g['endDate']}  "
              f"{g['startAreaHa']} → {g['endAreaHa']} ha "
              f"(变化 {g['areaChangeHa']:+.2f} ha, {g['changePct']:+.1f}%)")

    target = next((g for g in groups if g["periodCount"] >= 2), None)
    if not target:
        print("\n[FAIL] 没有聚合出 2 期以上的时序组")
        print("       （检查 AOI 指纹是否一致、acquisitionDate 是否落库）")
        return

    # ---- 验证序列内容 ----
    seq = requests.get(f"{BASE}/api/timeseries/{target['signature']}", headers=H,
                       timeout=15).json()["data"]
    print(f"\n=== 时序序列（{len(seq)} 帧，按日期升序）===")
    for f in seq:
        import json
        poly = json.loads(f["featuresJson"]) if f.get("featuresJson") else []
        print(f"  {f['date']}  {f['extractAreaHa']:>8} ha  "
              f"覆盖 {f['coveragePct']}%  多边形 {len(poly)} 个  影像 {f['imageryId']}")

    dates = [f["date"] for f in seq]
    sorted_ok = dates == sorted(dates)
    area_changed = len({f["extractAreaHa"] for f in seq}) > 1
    print(f"\n  [{'PASS' if sorted_ok else 'FAIL'}] 按日期升序")
    print(f"  [{'PASS' if area_changed else 'FAIL'}] 各期面积有差异（真实变化）")
    print(f"\n=== 时序链路: {'打通' if sorted_ok and area_changed else '有问题'} ===")


if __name__ == "__main__":
    main()
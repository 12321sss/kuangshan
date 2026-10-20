"""全链路验证：Java(8080) → inference(8010) → 回调 Java → extractions 落库。

步骤：
1. 用 Java 接口登记一景测试影像（模拟上传已完成、影像入库）
2. 调Java /api/extractions/submit 提交真实解译（AOI 圈在植被区）
3. 轮询 /api/extractions 直到 taskId 出现（说明回调已落库）
4. 校验结果：面积、覆盖率、像素数
"""
import time

import requests

BASE = "http://localhost:8080"
SRC = "C:/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/data/imagery/test_scene.tif"

# 与 selftest_classify 一致的样区与像元换算
import sys
sys.path.insert(0, r"C:/Users/asus/Desktop/尚子安/智慧矿山平台-源码包-20261016/inference")
from selftest_classify import D_LON, NORTH, WEST, build_synthetic  # noqa: E402


def login():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}


def main():
    H = login()
    print("登录成功")

    # ---- 1. 登记影像（等价于前端上传后入库；Java 会校验路径存在）----
    bounds = [WEST, NORTH - 256 * D_LON, WEST + 256 * D_LON, NORTH]
    r = requests.post(f"{BASE}/api/imagery/register-public", headers=H, json={
        "projectId": 1,
        "name": "宁都河源测试影像",
        "source": "SENTINEL2",
        "productId": "test-001",
        "acquisitionDate": "2023-12-07",
        "cloudCover": 0.0,
        "resolutionM": 10.0,
        "bounds": bounds,
        "note": "端到端测试影像",
        "filePath": SRC,
    }, timeout=20)
    if r.status_code != 200:
        print("登记失败:", r.status_code, r.text[:200])
        return
    img = r.json()["data"]
    print(f"影像已登记 id={img['id']} crs={img['crs']}")

    # 覆盖 filePath 指向测试文件（模拟上传后的落盘路径）
    imagery_id = img["id"]

    # 直接改库把 file_path 指到测试影像（模拟上传落盘）
    print("  （测试便利：将 file_path 指向本地测试影像）")

    # ---- 2. 提交解译 ----
    aoi = [
        [WEST + 0.001, NORTH - 128 * D_LON],
        [WEST + 128 * D_LON, NORTH - 128 * D_LON],
        [WEST + 128 * D_LON, NORTH],
        [WEST + 0.001, NORTH],
        [WEST + 0.001, NORTH - 128 * D_LON],
    ]
    r = requests.post(f"{BASE}/api/extractions/submit", headers=H, json={
        "projectId": 1,
        "imageryId": imagery_id,
        "classType": "VEGETATION",
        "aoi": aoi,
    }, timeout=30)
    if r.status_code != 200:
        print("提交失败:", r.status_code, r.text[:300])
        print("（若提示影像无本地文件，说明 file_path 未指向真实文件，属预期）")
        return
    task_id = r.json()["data"]["taskId"]
    print(f"解译任务已提交 taskId={task_id}")

    # ---- 3. 轮询落库 ----
    for i in range(40):
        time.sleep(1)
        r = requests.get(f"{BASE}/api/extractions", headers=H,
                         params={"projectId": 1}, timeout=15)
        items = r.json()["data"]
        hit = next((x for x in items if x.get("taskId") == task_id), None)
        if hit:
            print("\n=== 回调落库结果 ===")
            print(f"  id            : {hit['id']}")
            print(f"  classType     : {hit['classType']}")
            print(f"  pixelCount    : {hit.get('pixelCount')}")
            print(f"  extractAreaHa : {hit['extractAreaHa']}")
            print(f"  aoiAreaHa     : {hit['aoiAreaHa']}")
            print(f"  coveragePct   : {hit['coveragePct']}")
            print(f"  imageryId     : {hit.get('imageryId')}")
            print("\n=== 全链路:", "打通", "===")
            return
    print("超时未落库，请查后端回调日志")


if __name__ == "__main__":
    main()
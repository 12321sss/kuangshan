"""验证上传接口：52.7MB 影像（远超原 1MB 默认限制）能否成功入库。

顺带验证坐标系必选与覆盖范围校验。
"""
import requests

BASE = "http://localhost:8080"
import os
from pathlib import Path

# 上传测试用影像：默认取仓库内 inference/data/imagery，可用 RS_TEST_TIF 覆盖
SRC = os.environ.get("RS_TEST_TIF", str(
    Path(__file__).resolve().parents[2] / "data" / "imagery" / "test_scene.tif"))
# 与造图一致的覆盖范围（lng[115.2000,115.2821] lat[26.3000,26.3741]）
BOUNDS = [115.2000, 26.3000, 115.2821, 26.3741]


def login():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}


def main():
    H = login()
    print("登录成功\n")

    # ---- 用例1：正常上传（选 CRS）----
    with open(SRC, "rb") as f:
        files = {"file": ("big_test_scene.tif", f, "image/tiff")}
        data = [
            ("projectId", "1"),
            ("name", "宁都河源高分测试影像"),
            ("crs", "EPSG:4326"),          # 用户选择的坐标系
            ("acquisitionDate", "2023-12-07"),
            ("resolutionM", "8"),
        ] + [("bounds", str(b)) for b in BOUNDS]
        r = requests.post(f"{BASE}/api/imagery/upload", headers=H,
                          files=files, data=data, timeout=300)
    print(f"[{'PASS' if r.status_code == 200 else 'FAIL'}] 52.7MB 影像上传 http={r.status_code}")
    if r.status_code != 200:
        print("  响应:", r.text[:300])
        return
    img = r.json()["data"]
    print(f"  id={img['id']}  name={img['name']}")
    print(f"  crs={img['crs']}  source={img['source']}  status={img['status']}")
    print(f"  范围 lng[{img['west']},{img['east']}] lat[{img['south']},{img['north']}]")
    print(f"  落盘路径存在: {img.get('filePath') is not None}")
    print(f"  分辨率={img.get('resolutionM')}m  拍摄日期={img['acquisitionDate']}")

    # ---- 用例2：不选坐标系应被拒 ----
    with open(SRC, "rb") as f:
        files = {"file": ("t.tif", f, "image/tiff")}
        data = [("projectId", "1"), ("acquisitionDate", "2023-12-07")] + \
               [("bounds", str(b)) for b in BOUNDS]
        r2 = requests.post(f"{BASE}/api/imagery/upload", headers=H,
                           files=files, data=data, timeout=120)
    ok2 = r2.status_code == 400 and "坐标系" in r2.text
    print(f"\n[{'PASS' if ok2 else 'FAIL'}] 不选坐标系被拒 http={r2.status_code}")
    print(f"  提示: {r2.json().get('message', '')[:60]}")

    # ---- 用例3：不画覆盖范围应被拒 ----
    with open(SRC, "rb") as f:
        files = {"file": ("t.tif", f, "image/tiff")}
        data = [("projectId", "1"), ("crs", "EPSG:4326"),
                ("acquisitionDate", "2023-12-07")]
        r3 = requests.post(f"{BASE}/api/imagery/upload", headers=H,
                           files=files, data=data, timeout=120)
    ok3 = r3.status_code == 400
    print(f"\n[{'PASS' if ok3 else 'FAIL'}] 不画覆盖范围被拒 http={r3.status_code}")
    print(f"  提示: {r3.json().get('message', '')[:60]}")

    print("\n=== 上传链路验证结束 ===")


if __name__ == "__main__":
    main()
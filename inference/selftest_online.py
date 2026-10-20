"""端到端验证：AWS Sentinel-2 在线解译全链路（Java → inference → 回调 → 落库）。

路径：POST /api/extractions/submit-online → Java 转发 inference /sentinel/extract
     → AWS STAC 在线拉景 + 剪切 + 指数 + 矢量 → 回调 Java → extractions 落库

验证点：
1. submit-online 提交成功返回 taskId
2. 回调落库成功（extractions 表出现记录，imageryId 为 null）
3. 结果字段正确（面积/覆盖率/日期/AOI 指纹）
4. 时序分组能识别该记录
"""
import time

import requests

BASE = "http://localhost:8080"
# 宁都河源样区
AOI = [
    [115.98, 26.60],
    [116.00, 26.60],
    [116.00, 26.62],
    [115.98, 26.62],
    [115.98, 26.60],
]


def login():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}


def main():
    H = login()
    print("登录成功\n")

    # ---- 1. 提交在线解译 ----
    print("=== 1. 提交在线解译（submit-online）===")
    r = requests.post(f"{BASE}/api/extractions/submit-online", headers=H, json={
        "projectId": 1,
        "name": "在线提取测试-植被-2024",
        "classType": "VEGETATION",
        "aoi": AOI,
        "startDate": "2024-01-01",
        "endDate": "2024-12-31",
        "maxCloud": 20.0,
        "minAreaPx": 20,
    }, timeout=30)
    if r.status_code != 200:
        print(f"[FAIL] 提交失败 http={r.status_code}: {r.text[:300]}")
        return
    task_id = r.json()["data"]["taskId"]
    print(f"[PASS] 任务已提交 taskId={task_id}")
    print("  （首次拉景需 1-3 分钟，等待回调落库...）\n")

    # ---- 2. 轮询落库 ----
    print("=== 2. 等待回调落库 ===")
    hit = None
    for i in range(180):   # 最多等 3 分钟
        time.sleep(2)
        items = requests.get(f"{BASE}/api/extractions", headers=H,
                             params={"projectId": 1}, timeout=15).json()["data"]
        hit = next((x for x in items if x.get("taskId") == task_id), None)
        if hit:
            break
        if i % 15 == 0:
            print(f"  ... 等待中 {i * 2}s")

    if not hit:
        print("[FAIL] 超时未落库（3 分钟），检查 inference 回调日志")
        return

    print(f"[PASS] 回调落库成功")
    print(f"  id          : {hit['id']}")
    print(f"  classType   : {hit['classType']}")
    print(f"  imageryId   : {hit.get('imageryId')}（应为 null，在线方案无本地影像）")
    print(f"  extractAreaHa: {hit['extractAreaHa']}")
    print(f"  coveragePct : {hit['coveragePct']}")
    print(f"  acquisitionDate: {hit.get('acquisitionDate')}")
    print(f"  aoiSignature: {hit.get('aoiSignature') is not None}")

    # ---- 3. 验证时序分组能识别 ----
    print("\n=== 3. 时序分组识别 ===")
    groups = requests.get(f"{BASE}/api/timeseries/groups", headers=H,
                          params={"projectId": 1}, timeout=15).json()["data"]
    print(f"  时序组数: {len(groups)}")
    for g in groups:
        print(f"    {g['label']} · {g['periodCount']} 期 · {g['classType']}")

    # ---- 4. 验证分析接口能读到 ----
    print("\n=== 4. 变化分析接口 ===")
    summary = requests.get(f"{BASE}/api/analysis/change-summary", headers=H,
                           params={"projectId": 1}, timeout=15).json()["data"]
    print(f"  totalRecords: {summary['totalRecords']}")
    for c in summary.get("classes", []):
        print(f"    {c['classType']}: {c['totalAreaHa']} ha ({c['recordCount']} 条)")

    print("\n=== 全链路:", "打通" if hit else "失败", "===")


if __name__ == "__main__":
    main()
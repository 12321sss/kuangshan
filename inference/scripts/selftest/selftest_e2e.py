"""端到端验证：提交真实解译任务 -> 后台计算 -> 回调落库。

用合成影像（selftest_classify 生成的同一景）+ 一个本地假回调服务，
验证 submit -> 计算 -> 回调 的完整链路真的通。
"""
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import sys
from pathlib import Path

# 直接运行脚本时，把 inference 根目录加进 sys.path，才能 import algorithms
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from selftest_classify import D_LON, NORTH, SOUTH, WEST, build_synthetic

CALLBACK_PORT = 8899
received = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        received["payload"] = json.loads(self.rfile.read(n).decode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code":0,"message":"success","data":null}')

    def log_message(self, *args):
        pass  # 静默


def main():
    srv = HTTPServer(("127.0.0.1", CALLBACK_PORT), CallbackHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    tif = os.path.join(tempfile.gettempdir(), "s2_synth_test.tif")
    build_synthetic(tif)
    print(f"合成影像: {tif}")

    # 构造 AOI：左上象限（植被区），四周走 WGS84
    aoi = [
        [WEST + 0.001, NORTH - 128 * D_LON],
        [WEST + 128 * D_LON, NORTH - 128 * D_LON],
        [WEST + 128 * D_LON, NORTH],
        [WEST + 0.001, NORTH],
        [WEST + 0.001, NORTH - 128 * D_LON],
    ]

    print("\n提交解译任务（classType=VEGETATION）...")
    r = requests.post("http://127.0.0.1:8010/api/v1/inference/submit", json={
        "imagePath": tif,
        "satellite": "SENTINEL2",
        "classType": "VEGETATION",
        "aoi": aoi,
        "callbackUrl": f"http://127.0.0.1:{CALLBACK_PORT}/api/callback/task-complete",
    }, timeout=30)
    r.raise_for_status()
    task_id = r.json()["taskId"]
    print(f"  taskId = {task_id}")

    # 轮询直到回调到达
    for _ in range(40):
        time.sleep(0.5)
        if "payload" in received:
            break
    else:
        print("  [FAIL] 60 秒内未收到回调")
        return

    p = received["payload"]
    print("\n=== 回调内容 ===")
    print(f"  status        : {p['status']}")
    print(f"  classType     : {p['classType']} ({p['label']})")
    print(f"  polygonCount  : {len(p['polygons'])}")
    print(f"  pixelCount    : {p['pixelCount']}")
    print(f"  extractAreaHa : {p['extractAreaHa']}")
    print(f"  aoiAreaHa     : {p['aoiAreaHa']}")
    print(f"  覆盖率        : {p['extractAreaHa'] / p['aoiAreaHa'] * 100:.1f}%")
    print(f"  stats         : {json.dumps(p['stats'], ensure_ascii=False)}")

    ok = True
    if p["status"] != "SUCCESS":
        ok = False
        print("  [FAIL] 状态非SUCCESS")
    if not p["polygons"]:
        ok = False
        print("  [FAIL] 无结果多边形")
    ratio = p["extractAreaHa"] / p["aoiAreaHa"] if p["aoiAreaHa"] else 0
    if not (0.7 < ratio <= 1.05):
        ok = False
        print(f"  [FAIL] AOI 覆盖率异常: {ratio:.2f}")

    # 状态查询端点
    st = requests.get(
        f"http://127.0.0.1:8010/api/v1/inference/{task_id}/status", timeout=10).json()
    print(f"\n  status 端点: {st['data']['status']} progress={st['data']['progress']}")

    srv.shutdown()
    print("\n=== 端到端结果:", "通过" if ok else "失败", "===")


if __name__ == "__main__":
    main()
"""NISAR GUNW 时序数据获取：检索 + 批量下载 + 断点续传。

这是 A 阶段（时序 SBAS）的正式数据入口，不是一次性探针。
后续 `algorithms/sbas.py` 直接消费这里下好的 HDF5 文件。

用法：
    python scripts/fetch_nisar.py list [--track 18] [--bbox w,s,e,n]
    python scripts/fetch_nisar.py download --track 18 --bbox w,s,e,n   # 下载该轨道全部期次
    python scripts/fetch_nisar.py download --track 18 --latest         # 只下最新一期

凭据：读用户主目录 ~/.netrc（机器 urs.earthdata.nasa.gov），不入库。
"""
from __future__ import annotations

import argparse
import json
import netrc
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 茜坑锂矿（江西），与平台影像库演示矿区一致
DEFAULT_BBOX = (114.87, 28.57, 114.93, 28.62)
SEARCH_API = "https://api.daac.asf.alaska.edu/services/search/param"
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "nisar"
CHUNK = 4 << 20  # 4MB


def _session(authenticated: bool = False) -> requests.Session:
    s = requests.Session()
    s.trust_env = True   # 走环境变量代理(127.0.0.1:55979)；urs/earthdatacloud 直连被墙，必须走代理
    if authenticated:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
        if not auth:
            raise SystemExit("未找到 ~/.netrc 里的 urs.earthdata.nasa.gov 凭据")
        user, _, password = auth
        # 直接拿 Bearer token，再带 Authorization 头下载。
        # 为什么不走 asf_search.ASFSession：它内部 POST /api/users/find_or_create_token，
        # 该端点走本机代理时 SSL 握手会 EOF（UNEXPECTED_EOF_WHILE_READING）。
        # GET /api/users/tokens 走代理是通的，拿到的 token 直接 Bearer 用即可。
        r = s.get("https://urs.earthdata.nasa.gov/api/users/tokens",
                  auth=(user, password), timeout=60)
        if r.status_code != 200:
            raise SystemExit(f"Earthdata 认证失败 HTTP {r.status_code}: {r.text[:200]}")
        tokens = r.json()
        if not tokens:
            raise SystemExit("Earthdata 账号下没有任何 token，请先到 urs 页面生成")
        s.headers.update({"Authorization": f"Bearer {tokens[0]['access_token']}"})
    return s


def search(bbox: tuple[float, float, float, float], track: int | None) -> list[dict]:
    params = {
        "platform": "NISAR", "processingLevel": "GUNW",
        "bbox": ",".join(str(v) for v in bbox),
        "output": "json", "maxResults": 200,
    }
    rows = (_session().get(SEARCH_API, params=params, timeout=60).json() or [[]])[0] or []
    if track is not None:
        rows = [r for r in rows if int(r.get("track") or 0) == track]
    return sorted(rows, key=lambda r: r.get("startTime") or "")


def download(url: str, dest: Path) -> None:
    """带断点续传；单景 2.2GB，走代理易断，续传避免每次重头拉。"""
    if dest.exists() and dest.stat().st_size > 0:
        done = dest.stat().st_size
        headers = {"Range": f"bytes={done}-"}
        mode = "ab"
        print(f"    续传（已有 {done / 1024 / 1024:.0f} MB）")
    else:
        done, headers, mode = 0, {}, "wb"

    sess = _session(authenticated=True)
    with sess.get(url, headers=headers, stream=True, timeout=1800) as r:
        if r.status_code not in (200, 206):
            raise SystemExit(f"下载失败 HTTP {r.status_code}")
        if mode == "wb":
            done = 0
        total = done + int(r.headers.get("Content-Length") or 0)
        last = 0
        with open(dest, mode) as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                done += len(chunk)
                if done - last >= 200 * 1024 * 1024:
                    last = done
                    pct = f"{done / total * 100:.0f}%" if total else "?"
                    print(f"    {done / 1024 / 1024:.0f} MB ({pct})", flush=True)
    print(f"    完成 {dest.stat().st_size / 1024 / 1024:.0f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description="NISAR GUNW 检索与批量下载")
    ap.add_argument("action", choices=["list", "download"])
    ap.add_argument("--track", type=int, help="限定轨道号")
    ap.add_argument("--bbox", default=",".join(map(str, DEFAULT_BBOX)),
                    help="w,s,e,n（默认茜坑矿区）")
    ap.add_argument("--latest", action="store_true", help="只下载最新一期")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    rows = search(bbox, args.track)

    if args.action == "list":
        print(f"共 {len(rows)} 景")
        for r in rows:
            print(f"  {r['startTime'][:10]}  {r['flightDirection'][:4]:4s}  "
                  f"track {r.get('track')}  frame {r.get('frameNumber')}  {r['fileName']}")
        return

    if not rows:
        raise SystemExit("没有符合条件的景")

    if args.latest:
        rows = rows[-1:]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = CACHE_DIR / "manifest.json"
    done = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}

    for r in rows:
        dest = CACHE_DIR / r["fileName"]
        if dest.exists() and dest.stat().st_size > 100 * 1024 * 1024:
            print(f"[跳过] {r['fileName']}（已下载）")
            done[r["fileName"]] = {"date": r["startTime"], "track": r.get("track"),
                                   "flightDirection": r.get("flightDirection")}
            continue
        print(f"[下载] {r['startTime'][:10]} track {r.get('track')} {r['fileName']}")
        download(r["downloadUrl"], dest)
        done[r["fileName"]] = {"date": r["startTime"], "track": r.get("track"),
                               "flightDirection": r.get("flightDirection")}

    manifest.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nmanifest 已写 {manifest}（{len(done)} 条）")


if __name__ == "__main__":
    main()

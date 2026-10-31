"""Sentinel-1 SLC 数据获取（isce2 干涉处理的输入）。

与 fetch_nisar.py 职责对称：那个管 NISAR GUNW，这个管 S1 SLC。
两者共用同一套 ASF 认证方式（Bearer token），但产品格式、目录、解压流程不同，
所以拆成两个模块而不是塞进一个 —— 避免 if/else 分支膨胀。

为什么需要 SLC 而不是 GUNW/IFG：
  茜坑矿区在 ASF 上**没有** Sentinel-1 GUNW 或 IFG 产品（ARIA 覆盖不含中国），
  只有 SLC 原始数据。要拿到 S1 干涉图，必须自己用 isce2 跑 topsApp。

用法：
    python scripts/fetch_s1.py list --track 40
    python scripts/fetch_s1.py download --track 40 --count 2
"""
from __future__ import annotations

import argparse
import json
import netrc
import sys
import time
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BBOX = (114.87, 28.57, 114.93, 28.62)   # 茜坑矿区
SEARCH_API = "https://api.daac.asf.alaska.edu/services/search/param"
TOKEN_API = "https://urs.earthdata.nasa.gov/api/users/tokens"
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "s1"
CHUNK = 4 << 20
# SLC zip 完整约 4.5~5GB；低于此值视为未完成，走续传
MIN_COMPLETE_BYTES = 3_000_000_000


def _session(authenticated: bool = False) -> requests.Session:
    """构造会话；authenticated=True 时注入 Bearer token。

    与 fetch_nisar 同样的坑：asf_search 的 ASFSession 会 POST
    /api/users/find_or_create_token，走代理时 SSL 握手 EOF；
    改用 GET /api/users/tokens 拿 token 再 Bearer，实测稳定。
    """
    s = requests.Session()
    s.trust_env = True          # 走环境变量代理（urs/datapool 直连被墙）
    if authenticated:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
        if not auth:
            raise SystemExit("未找到 ~/.netrc 里的 urs.earthdata.nasa.gov 凭据")
        user, _, password = auth
        r = s.get(TOKEN_API, auth=(user, password), timeout=60)
        if r.status_code != 200:
            raise SystemExit(f"Earthdata 认证失败 HTTP {r.status_code}: {r.text[:200]}")
        tokens = r.json()
        if not tokens:
            raise SystemExit("Earthdata 账号下没有 token")
        s.headers.update({"Authorization": f"Bearer {tokens[0]['access_token']}"})
    return s


def search(bbox: tuple[float, float, float, float],
           track: int | None = None,
           start: str | None = None,
           end: str | None = None) -> list[dict]:
    """检索 S1 IW SLC，按时间升序返回。

    start / end：ISO 时间（如 2023-01-01T00:00:00Z），用于挑历史数据。
    为什么需要：isce2 2.6.5 对 2025 年新发射的 S1D 有兼容问题（burst 判定为 0），
    S1A/S1B 数据是成熟支持的。挑 2022-2023 的数据可以稳定跑通。
    """
    params = {
        "platform": "SENTINEL-1", "processingLevel": "SLC", "beamMode": "IW",
        "bbox": ",".join(str(v) for v in bbox),
        "output": "json", "maxResults": 500,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    rows = (_session().get(SEARCH_API, params=params, timeout=90).json() or [[]])[0] or []
    if track is not None:
        rows = [r for r in rows if str(r.get("track")) == str(track)]
    return sorted(rows, key=lambda r: r.get("startTime") or "")


def _download_once(url: str, dest: Path) -> None:
    """单次下载尝试（带断点续传）。"""
    if dest.exists() and dest.stat().st_size > 0:
        done = dest.stat().st_size
        headers = {"Range": f"bytes={done}-"}
        mode = "ab"
        print(f"    续传（已有 {done / 1024**3:.2f} GB）")
    else:
        done, headers, mode = 0, {}, "wb"

    sess = _session(authenticated=True)
    # timeout=300：半开连接会让 read 永久挂起，5 分钟无数据就抛异常交给重试
    with sess.get(url, headers=headers, stream=True, timeout=300) as r:
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
                if done - last >= 300 * 1024 * 1024:
                    last = done
                    pct = f"{done / total * 100:.0f}%" if total else "?"
                    print(f"    {done / 1024**3:.2f} GB ({pct})", flush=True)
    print(f"    完成 {dest.stat().st_size / 1024**3:.2f} GB")


def download(url: str, dest: Path) -> None:
    """带自动重试（4.5GB 走代理易半路断，重试 + Range 续传）。"""
    for attempt in range(3):
        try:
            _download_once(url, dest)
            return
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                print(f"    中断（{type(e).__name__}），3 秒后重试 {attempt + 2}/3 ...", flush=True)
                time.sleep(3)
            else:
                raise


def unzip_safe(zip_path: Path, out_dir: Path) -> Path:
    """解压 SLC zip → 返回 .SAFE 目录（isce2 需要）。

    S1 SLC zip 内是 `<name>.SAFE/` 目录树，解压后 topsApp 直接指向它。
    已解压则跳过（幂等）。
    """
    existing = list(out_dir.glob("*.SAFE"))
    if existing:
        print(f"    已解压：{existing[0].name}")
        return existing[0]
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    safes = list(out_dir.glob("*.SAFE"))
    if not safes:
        raise SystemExit(f"解压后未找到 .SAFE 目录：{out_dir}")
    print(f"    解压完成：{safes[0].name}")
    return safes[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Sentinel-1 SLC 检索与下载")
    ap.add_argument("action", choices=["list", "download"])
    ap.add_argument("--track", type=int, default=None, help="轨道号（茜坑降轨主力 40）")
    ap.add_argument("--bbox", default=",".join(map(str, DEFAULT_BBOX)))
    ap.add_argument("--count", type=int, default=2, help="下载最近的 N 景（默认 2，构成一个干涉对）")
    ap.add_argument("--start", default=None, help="起始时间 ISO，如 2023-01-01T00:00:00Z")
    ap.add_argument("--end", default=None, help="结束时间 ISO")
    ap.add_argument("--unzip", action="store_true", help="下载后解压 SAFE")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    rows = search(bbox, args.track, args.start, args.end)

    if args.action == "list":
        print(f"共 {len(rows)} 景")
        for r in rows[:10]:
            print(f"  {r['startTime'][:19]}  track {r.get('track')}  {r['fileName'][:55]}")
        return 0

    if not rows:
        raise SystemExit("没有符合条件的景")

    # 取最近 N 景（时间上相邻，构成短基线干涉对）
    picked = rows[-args.count:] if args.count else rows
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CACHE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    for r in picked:
        name = r["fileName"]
        # ASF 的 fileName 有的已带 .zip，避免出现 xxx.zip.zip
        dest = CACHE_DIR / (name if name.lower().endswith(".zip") else f"{name}.zip")
        if dest.exists() and dest.stat().st_size > MIN_COMPLETE_BYTES:
            print(f"[跳过] {name}（已下载 {dest.stat().st_size / 1024**3:.2f} GB）")
        else:
            print(f"[下载] {r['startTime'][:10]} track {r.get('track')} {name[:50]}")
            download(r["downloadUrl"], dest)
        manifest[name] = {
            "date": r["startTime"], "track": r.get("track"),
            "flightDirection": r.get("flightDirection"),
            "zip": dest.name,
        }
        if args.unzip:
            unzip_safe(dest, CACHE_DIR)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nmanifest: {manifest_path}（{len(manifest)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

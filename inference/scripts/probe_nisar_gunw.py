"""NISAR GUNW 最小验证探针（一次性排查脚本，不进生产链路）。

做四件事，每步都可在没跑通前停下：
  1. 检索矿区范围内的 NISAR GUNW（地理编码解缠干涉图，NASA 已算好，不用自己跑干涉）
  2. 用 Earthdata 账号认证（凭据读 ~/.netrc，不落仓库）
  3. 探体量（Range 请求只取头 1KB，避免先拖 1.5GB 才发现没权限）
  4. 可选：整景下载 + 打印 HDF5 结构

用法：
    python scripts/probe_nisar_gunw.py list
    python scripts/probe_nisar_gunw.py probe        # 认证 + 探体量
    python scripts/probe_nisar_gunw.py inspect      # 下载并打印 HDF5 结构

凭据准备（一次性）：
    在用户主目录建 .netrc，内容：
        machine urs.earthdata.nasa.gov
          login <用户名>
          password <密码>
"""
from __future__ import annotations

import json
import netrc
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 茜坑锂矿（江西）：与平台影像库里的演示矿区一致
MINE_BBOX = (114.87, 28.57, 114.93, 28.62)
SEARCH_API = "https://api.daac.asf.alaska.edu/services/search/param"
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "nisar"


def _session(authenticated: bool = False) -> requests.Session:
    s = requests.Session()
    # 本机有全局代理，ASF API 走代理会 502；直连反而通
    s.trust_env = False
    if authenticated:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
        if not auth:
            raise SystemExit("未找到 ~/.netrc 里的 urs.earthdata.nasa.gov 凭据")
        user, _, password = auth
        # Earthdata 用 OAuth 重定向，不是 Basic Auth；借 asf_search 处理这套流程
        from asf_search import ASFSession

        sess = ASFSession()
        sess.auth_with_creds(user, password)
        sess.trust_env = False
        return sess
    return s


def search(level: str = "GUNW") -> list[dict]:
    bbox = ",".join(str(v) for v in MINE_BBOX)
    resp = _session().get(SEARCH_API, params={
        "platform": "NISAR", "processingLevel": level,
        "bbox": bbox, "output": "json", "maxResults": 200,
    }, timeout=60)
    resp.raise_for_status()
    rows = (resp.json() or [[]])[0] or []
    return rows


def pick(rows: list[dict], track: int | None = None) -> dict:
    """挑一景：可指定 track；否则优先升轨、日期最新。

    为什么允许指定 track：GUNW 的幅宽有边缘（near/far range 两端像元无效），
    矿区若贴在边缘，mask 会大面积置 0。换一条轨道往往就落在幅宽中间。
    """
    pool = rows
    if track is not None:
        pool = [r for r in rows if int(r.get("track") or 0) == track]
        if not pool:
            raise SystemExit(f"没有 track {track} 的景")
    else:
        asc = [r for r in rows if r.get("flightDirection") == "ASCENDING"]
        pool = asc or rows
    return max(pool, key=lambda r: r.get("startTime") or "")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    # 可选：--track 18 指定轨道（避开幅宽边缘）
    track = None
    if "--track" in sys.argv:
        track = int(sys.argv[sys.argv.index("--track") + 1])
    rows = search("GUNW")
    if not rows:
        raise SystemExit("该范围没有 GUNW 数据")

    print(f"GUNW 共 {len(rows)} 景，范围 "
          f"{min(r['startTime'] for r in rows)[:10]} ~ {max(r['startTime'] for r in rows)[:10]}")

    if action == "list":
        for r in sorted(rows, key=lambda x: x["startTime"]):
            print(f"  {r['startTime'][:10]}  {r['flightDirection'][:4]:4s}  "
                  f"track {r.get('track')}  frame {r.get('frameNumber')}  {r['fileName']}")
        return

    scene = pick(rows, track)
    print(f"\n选中：{scene['fileName']}")
    print(f"  采集 {scene['startTime']}  方向 {scene['flightDirection']}  "
          f"track {scene.get('track')}")
    url = scene["downloadUrl"]

    if action in ("probe", "inspect"):
        sess = _session(authenticated=True)
        # Range 请求只取 1KB：验证权限与真实体量，不产生大流量
        r = sess.get(url, headers={"Range": "bytes=0-1023"}, stream=True, timeout=120)
        print(f"  认证结果：HTTP {r.status_code}")
        cr = r.headers.get("Content-Range") or ""
        if "/" in cr:
            total = int(cr.rsplit("/", 1)[1])
            print(f"  整景体量：{total / 1024 / 1024:.0f} MB")
        else:
            print(f"  Content-Length：{r.headers.get('Content-Length')}")
            print(f"  Content-Range：{cr or '未返回'}")
        r.close()
        if r.status_code in (401, 403):
            raise SystemExit("认证失败：检查 .netrc 里的账号密码")

    if action == "inspect":
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest = CACHE_DIR / scene["fileName"]
        if not dest.exists():
            download(url, dest, expected_mb=2256)
        dump_hdf5(dest)


def download(url: str, dest: Path, expected_mb: int | None = None) -> None:
    """带断点续传的下载。

    单景 2.2GB，走代理很容易中途断；断点续传能避免每次都从头拉。
    """
    done = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    if done:
        print(f"  续传：已有 {done / 1024 / 1024:.0f} MB")

    sess = _session(authenticated=True)
    with sess.get(url, headers=headers, stream=True, timeout=1800) as r:
        if r.status_code not in (200, 206):
            raise SystemExit(f"下载失败 HTTP {r.status_code}")
        mode = "ab" if (done and r.status_code == 206) else "wb"
        if mode == "wb":
            done = 0
        total = done + int(r.headers.get("Content-Length") or 0)
        print(f"  下载中 → {dest.name}（目标 {total / 1024 / 1024:.0f} MB）")
        last = 0
        with open(dest, mode) as f:
            for chunk in r.iter_content(chunk_size=4 << 20):
                f.write(chunk)
                done += len(chunk)
                if done - last >= 200 * 1024 * 1024:      # 每 200MB 打一行
                    last = done
                    pct = f"{done / total * 100:.0f}%" if total else "?"
                    print(f"    {done / 1024 / 1024:.0f} MB ({pct})", flush=True)
    print(f"  下载完成 {dest.stat().st_size / 1024 / 1024:.0f} MB")


def dump_hdf5(path: Path) -> None:
    """打印 HDF5 结构（只到第 4 层）并定位位移/相干数据集"""
    import h5py

    print(f"\n=== HDF5 结构 {path.name} ===")
    hits: list[str] = []
    with h5py.File(path, "r") as f:
        print("根属性:", dict(f.attrs).keys())

        def walk(name, obj):
            depth = name.count("/")
            if depth > 4:
                return
            if isinstance(obj, h5py.Dataset):
                print(f"  {'  ' * depth}{name}  shape={obj.shape} dtype={obj.dtype} "
                      f"fill={obj.fillvalue}")
                low = name.lower()
                if any(k in low for k in ("phase", "coheren", "displacement", "los")):
                    hits.append(name)
            else:
                print(f"  {'  ' * depth}{name}/")

        f.visititems(walk)

    print("\n=== 形变相关数据集 ===")
    for h in hits:
        print(" ", h)
    (CACHE_DIR / "h5_paths.json").write_text(
        json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n路径已存 {CACHE_DIR / 'h5_paths.json'}")


if __name__ == "__main__":
    main()

"""
Sentinel-2 影像在线拉取 + AOI 剪切 + 指数提取服务

数据源：AWS Earth Search (Element84) STAC —— 无需账号/token，实测本机可直连。
流程：
  1. STAC 检索：AOI 中心点 + 日期范围 + 云量过滤 → 选最优景
  2. COG 剪切：HTTP Range 请求只拉 AOI 覆盖的瓦片字节（Cloud-Optimized GeoTIFF 特性）
  3. 真彩合成：B04(红)/B03(绿)/B02(蓝) → RGB PNG（贴地图显示）
  4. 指数提取：NDVI/NDWI/NDBI/裸土指数 → 阈值分割 → 矢量化 → GeoJSON

真实算法，依赖 rasterio（GDAL）。
"""
from __future__ import annotations

import io
import json
import math
import time
import zlib
from typing import Any

import httpx
import numpy as np

try:
    import rasterio
    from rasterio import warp as _warp
    from rasterio.io import MemoryFile
    from rasterio.windows import from_bounds
    HAS_RASTERIO = True
except ImportError:  # pragma: no cover
    HAS_RASTERIO = False

import tifffile  # 纯 Python TIFF/COG 结构解析，用于精确读取 tile 偏移表

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# 波段 → COG 文件名关键字（L2A 产品 asset 名）
BAND_KEYS = {
    "B02": "blue",     # 蓝
    "B03": "green",    # 绿
    "B04": "red",      # 红
    "B08": "nir",      # 近红外，NDVI/NDWI 用
    "B11": "swir16",   # 短波红外，NDBI/裸土用
}

# 提取类型 → 指数计算
CLASS_INDEX = {
    "VEGETATION": "ndvi",   # 植被
    "WATER": "ndwi",        # 水体
    "BUILDING": "ndbi",     # 建筑/不透水面
    "BARE": "bai",          # 裸地（bare soil）
    "MOUNTAIN": "ndvi",     # 山体：以高海拔+植被/裸岩区分，这里简化为坡度无关的植被负向+亮度
}

_http = httpx.Client(timeout=60.0, follow_redirects=True)


def search_scene(aoi: list[list[float]], start: str, end: str,
                 max_cloud: float = 30.0) -> dict | None:
    """STAC 检索：用 AOI 多边形 intersects 命中、日期范围内、云量最小的景"""
    # 闭合多边形（STAC 要求首尾一致）
    poly = aoi if aoi[0] == aoi[-1] else aoi + [aoi[0]]
    body = {
        "collections": [COLLECTION],
        "intersects": {"type": "Polygon", "coordinates": [poly]},
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        "limit": 3,
    }
    r = _http.post(f"{STAC_URL}/search", json=body)
    r.raise_for_status()
    feats = r.json().get("features", [])
    # 在候选里选 AOI 完整落于 footprint 的景（避免边缘擦到的景）
    for f in feats:
        if _aoi_inside(aoi, f["geometry"]):
            return f
    # 退而求其次：返回第一景
    return feats[0] if feats else None


def _aoi_inside(aoi: list[list[float]], footprint: dict) -> bool:
    """判断 AOI 所有顶点是否都落在景 footprint 内（粗略：多边形包含点）"""
    coords = footprint["coordinates"][0]  # 外环
    lngs = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    minx, maxx = min(lngs), max(lngs)
    miny, maxy = min(lats), max(lats)
    return all(minx <= p[0] <= maxx and miny <= p[1] <= maxy for p in aoi)


def _asset_href(feature: dict, band: str) -> str:
    assets = feature["assets"]
    key = BAND_KEYS[band]
    # 精确匹配优先（如 blue/green/red/nir），否则前缀匹配兜底
    if key in assets:
        return assets[key]["href"]
    for k, v in assets.items():
        if k == key or k.startswith(key):
            return v["href"]
    raise KeyError(f"波段 {band} 在 asset 中找不到")


class _TileCache:
    """tile 级本地磁盘缓存：同一景同一 tile 只下载一次，跨 AOI 复用。

    缓存路径：inference/.cache/<href_md5>/<tile_idx>.bin
    首次下载慢（受代理限速），之后秒读。演示前可先"预热"目标矿区。
    """

    def __init__(self, href: str):
        import hashlib
        import os as _os
        base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".cache")
        self.dir = _os.path.join(base, hashlib.md5(href.encode()).hexdigest())
        _os.makedirs(self.dir, exist_ok=True)
        self.href = href

    def _path(self, idx: int):
        import os as _os
        return _os.path.join(self.dir, f"{idx}.bin")

    def get(self, idx: int, offset: int, bytecount: int) -> bytes:
        import os as _os
        p = self._path(idx)
        if _os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
        r = _http.get(self.href, headers={"Range": f"bytes={offset}-{offset + bytecount - 1}"})
        r.raise_for_status()
        with open(p, "wb") as f:
            f.write(r.content)
        return r.content


def _read_band_window(href: str, west: float, south: float, east: float, north: float,
                      max_dim: int = 2048):
    """COG 云端精确窗口读取：只拉 AOI 覆盖的 tile，zlib 手动解码。

    实测：Sentinel-2 单波段 COG 的 tile 是 1024×1024 uint16 Deflate 压缩，
    单 tile 压缩后仅约 2~8KB，zlib 解压出 2MB。AOI 通常只覆盖 1~4 个 tile，
    所以整个读取在秒级完成，绕开整景 175MB 下载与 GDAL /vsicurl/ 的 utf-8 bug。
    """
    HEADER_SIZE = 128 * 1024

    # 1. 拉头，解析 tile 偏移表
    r = _http.get(href, headers={"Range": f"bytes=0-{HEADER_SIZE - 1}"})
    r.raise_for_status()
    header = r.content

    tf = tifffile.TiffFile(io.BytesIO(header))
    page = tf.pages[0]
    tile_w, tile_h = page.tilewidth, page.tilelength
    width, height = page.shape[1], page.shape[0]
    offsets = page.dataoffsets
    bytecounts = page.databytecounts
    ncols = (width + tile_w - 1) // tile_w
    nrows = (height + tile_h - 1) // tile_h
    compression = page.compression  # 8 = Deflate/Adobe

    # 2. 地理变换（从 header 用 rasterio 读，MemoryFile 只读头不碰远程）
    with MemoryFile(header) as mf:
        with mf.open() as src:
            scene_transform = src.transform
            crs = str(src.crs)
            # AOI 是 WGS84 经纬度，需先投影到影像 CRS（如 UTM），再 from_bounds 拿窗口
            if src.crs.is_geographic:
                bx, by = west, south
                ex, ey = east, north
            else:
                bx, by, ex, ey = _warp.transform_bounds(
                    {"init": "EPSG:4326"}, crs, west, south, east, north)
            win = from_bounds(bx, by, ex, ey, scene_transform)
            win = win.round_offsets().round_lengths()
            # clamp 到影像范围（AOI 可能部分落在景外）
            win = win.intersection(rasterio.windows.Window(0, 0, width, height))
            # 窗口 transform：原点 = 窗口左上角（不是全景原点！之前用全景 transform
            # 导致矢量化坐标整体偏移 1 度）
            win_transform = src.window_transform(win)

    # 3. 覆盖的 tile 行列范围
    col0 = max(0, int(win.col_off) // tile_w)
    col1 = min(ncols - 1, int(win.col_off + win.width - 1) // tile_w)
    row0 = max(0, int(win.row_off) // tile_h)
    row1 = min(nrows - 1, int(win.row_off + win.height - 1) // tile_h)

    # 4. 逐 tile 拉取 + zlib 解码 + 拼装（带本地磁盘缓存：同一景同一 tile 只下载一次）
    out_rows = (row1 - row0 + 1) * tile_h
    out_cols = (col1 - col0 + 1) * tile_w
    canvas = np.zeros((out_rows, out_cols), dtype=page.dtype)
    cache = _TileCache(href)
    for tr in range(row0, row1 + 1):
        for tc in range(col0, col1 + 1):
            idx = tr * ncols + tc
            off, cnt = offsets[idx], bytecounts[idx]
            raw = cache.get(idx, off, cnt)
            if compression in (8, 32946, 5):  # Deflate / AdobeDeflate / LZW 兜底用 zlib
                dec = zlib.decompress(raw)
            else:
                raise NotImplementedError(f"不支持的压缩方式: {compression}")
            tile = np.frombuffer(dec, dtype=page.dtype).reshape(tile_h, tile_w)
            # 关键：COG 用了水平差分预测器（predictor=2），解压出来的是相邻像素差值，
            # 必须按行前缀和还原（uint16 模 65536 回绕），否则全是噪点
            if page.predictor == 2:
                acc = tile.astype(np.uint32)
                tile = np.cumsum(acc, axis=1).astype(np.uint16)  # astype 截断即模 65536
            rr = (tr - row0) * tile_h
            cc = (tc - col0) * tile_w
            canvas[rr:rr + tile_h, cc:cc + tile_w] = tile

    # 5. 裁到精确窗口（去掉 tile 边缘多读的部分）
    r_off = int(win.row_off) - row0 * tile_h
    c_off = int(win.col_off) - col0 * tile_w
    result = canvas[r_off:r_off + int(win.height), c_off:c_off + int(win.width)]

    # 6. 下采样控制处理尺寸；transform 必须同步缩放（否则坐标错位 1 度的根因之一）
    scale = max(1.0, max(result.shape) / max_dim)
    if scale > 1.0:
        step = int(math.ceil(scale))
        result = result[::step, ::step]
    # 窗口 transform 乘以采样比：原点不变，像素尺寸放大
    from affine import Affine
    out_transform = win_transform * Affine.scale(
        win.width / result.shape[1], win.height / result.shape[0])
    return result, out_transform, crs


def clip_aoi(feature: dict, aoi: list[list[float]], bands: list[str],
             max_dim: int = 2048) -> dict[str, Any]:
    """按 AOI 边界剪切多个波段，返回 dict[band] = 2D numpy 数组 + 元数据"""
    if not HAS_RASTERIO:
        raise RuntimeError("rasterio 未安装，无法处理影像")

    lngs = [p[0] for p in aoi]
    lats = [p[1] for p in aoi]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)

    out: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for band in bands:
        href = _asset_href(feature, band)
        data, transform, crs = _read_band_window(href, west, south, east, north, max_dim)
        out[band] = data
        meta[band] = {"transform": transform, "crs": crs, "shape": data.shape}

    # B11 等 20m 波段窗口是 10m 波段的一半，指数计算要求同形，最近邻重采样到 10m
    if "B04" in out:
        ref_shape = out["B04"].shape
        for band in list(out.keys()):
            if out[band].shape != ref_shape:
                sh, sw = ref_shape[0] // out[band].shape[0], ref_shape[1] // out[band].shape[1]
                out[band] = np.repeat(np.repeat(out[band], sh, axis=0), sw, axis=1)
                meta[band]["shape"] = out[band].shape
    return {"bands": out, "meta": meta}


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    """反射率(0-1 或 0-10000)拉伸到 0-255"""
    arr = arr.astype(np.float32)
    if arr.max() > 1.5:
        arr = arr / 10000.0  # Sentinel-2 L2A 反射率 * 10000
    arr = np.clip(arr, 0, 1)
    p2, p98 = np.percentile(arr, 2), np.percentile(arr, 98)
    if p98 - p2 < 1e-6:
        return np.zeros(arr.shape, dtype=np.uint8)
    arr = np.clip((arr - p2) / (p98 - p2), 0, 1)
    return (arr * 255).astype(np.uint8)


def true_color_png(bands: dict[str, np.ndarray]) -> bytes:
    """B04/B03/B02 → RGB PNG 字节"""
    r = _to_uint8(bands["B04"])
    g = _to_uint8(bands["B03"])
    b = _to_uint8(bands["B02"])
    rgb = np.dstack([r, g, b]).astype(np.uint8)
    # 用 PIL 编码 PNG（rasterio 自带 PIL 依赖链可能不全，这里手写最小 PNG 依赖）
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def _norm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a.astype(np.float32) / 10000.0
    b = b.astype(np.float32) / 10000.0
    return np.divide(a - b, a + b, out=np.zeros_like(a), where=(a + b) != 0)


def compute_index(bands: dict[str, np.ndarray], class_type: str) -> np.ndarray:
    """按类型计算归一化指数（返回 -1~1 浮点数组）

    指数选择依据（硬岩锂矿场景）：
    - 植被：NDVI（近红-红），对绿色植被敏感，但道路/裸地也可能是中低值
    - 水体：MNDWI（绿-短波红外）比 NDWI 更稳，能压掉阴影
    - 建筑/不透水面：NDBI（短波红外-近红），道路和建筑同属不透水面，纯指数难分，
      需靠最小面积过滤 + 光谱形状区分
    - 裸地：BARE 指数（短波红外-红）
    - 山体：以 NDVI 负向 + 高亮度识别裸岩
    """
    if class_type == "VEGETATION":
        return _norm(bands["B08"], bands["B04"])          # NDVI
    if class_type == "WATER":
        return _norm(bands["B03"], bands["B11"])          # MNDWI 更抗阴影
    if class_type == "BUILDING":
        return _norm(bands["B11"], bands["B08"])          # NDBI
    if class_type == "BARE":
        b4 = bands["B04"].astype(np.float32) / 10000.0
        b11 = bands["B11"].astype(np.float32) / 10000.0
        return (b11 - b4) / (b11 + b4 + 1e-6)             # 裸土指数
    if class_type == "MOUNTAIN":
        return _norm(bands["B04"], bands["B08"])          # 负 NDVI = 裸岩/山体
    raise ValueError(f"未知类型: {class_type}")


# 各类型的默认阈值（可调）
CLASS_THRESHOLD = {
    "VEGETATION": 0.25,   # 提高阈值，滤掉稀疏植被/道路
    "WATER": 0.0,
    "BUILDING": 0.0,
    "BARE": 0.0,
    "MOUNTAIN": -0.2,
}


def _label_connected(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """连通域标记（numpy 手写 BFS，无 scipy 依赖）→ (labels, num_labels)

    对小 AOI（几百×几百）足够快，避免引入 scipy 重依赖。
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    next_label = 0
    for r in range(h):
        for c in range(w):
            if not mask[r, c] or labels[r, c]:
                continue
            next_label += 1
            cur = next_label
            # BFS 栈
            stack = [(r, c)]
            labels[r, c] = cur
            while stack:
                y, x = stack.pop()
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = cur
                        stack.append((ny, nx))
    return labels, next_label


def extract_class(bands: dict[str, np.ndarray], class_type: str,
                  transform: Any, crs: str,
                  min_area_px: int = 20) -> dict[str, Any]:
    """指数 → 阈值 → 二值化 → 连通域 → 最小面积过滤 → 矢量化

    最小面积过滤是关键去噪步骤：道路、孤立像元等碎斑面积小，被过滤掉后
    结果更接近真实地物斑块（矿山/植被/水体的连续区域）。
    """
    idx = compute_index(bands, class_type)
    thr = CLASS_THRESHOLD[class_type]
    mask = idx > thr

    # 连通域 + 最小面积过滤
    labels, num = _label_connected(mask)
    keep = np.zeros_like(mask)
    for lb in range(1, num + 1):
        area = int((labels == lb).sum())
        if area >= min_area_px:
            keep |= (labels == lb)

    features = _mask_to_polygons(keep, transform, crs)
    return {
        "class": class_type,
        "threshold": thr,
        "min_area_px": min_area_px,
        "coverage_pct": round(float(keep.mean()) * 100, 2),
        "feature_count": len(features),
        "features": features,
    }


def _mask_to_polygons(mask: np.ndarray, transform: Any, crs: str) -> list[dict]:
    """二值掩膜 → GeoJSON 多边形（rasterio.features.shapes 矢量化 + 重投影到 WGS84）

    矢量化产出的坐标在影像投影坐标系（如 UTM，单位米），
    前端 Cesium 需要经纬度，所以这里统一 transform_geom 到 EPSG:4326。
    """
    from rasterio import features as riof
    geoms = []
    for geom, value in riof.shapes(mask.astype(np.uint8), mask=mask > 0, transform=transform):
        if value:
            geoms.append(geom)
    # 投影坐标 → WGS84 经纬度
    import json as _json
    feats = []
    for i, g in enumerate(geoms):
        g4326 = _warp.transform_geom(crs, "EPSG:4326", g)
        geojson = _json.loads(_json.dumps(g4326))
        feats.append({
            "type": "Feature",
            "properties": {"id": i},
            "geometry": geojson,
        })
    return feats


def health() -> dict:
    return {"rasterio": HAS_RASTERIO, "stac": STAC_URL}

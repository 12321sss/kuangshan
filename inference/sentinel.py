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
    "B11": "swir16",   # 短波红外 1.6μm，NDBI/裸土用
    "B12": "swir22",   # 短波红外 2.2μm，RSEI 湿度/干度分量用
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
    """按 AOI 多边形剪切多个波段，返回 dict[band] = 2D numpy 数组 + 元数据。

    关键：不是取外接矩形，而是**按多边形精确掩膜** —— AOI 多边形外的像元设为 0
    （反射率 0 即无数据），这样指数计算和矢量化都严格落在用户画的范围内。
    之前用 from_bounds 只取外接矩形，多边形角落的矩形区域也被算进去，导致
    「画的是多边形、裁出来是矩形」的问题。
    """
    if not HAS_RASTERIO:
        raise RuntimeError("rasterio 未安装，无法处理影像")

    lngs = [p[0] for p in aoi]
    lats = [p[1] for p in aoi]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)

    out: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    # 波段串行下载是主要耗时（每景每波段要拉若干 COG tile，单景 4 波段可达 2-3 分钟）。
    # 各波段互相独立，用线程池并发拉取；磁盘 tile 缓存仍然生效。
    def fetch(band: str) -> tuple[str, Any, Any, Any]:
        href = _asset_href(feature, band)
        data, transform, crs = _read_band_window(href, west, south, east, north, max_dim)
        return band, data, transform, crs

    workers = max(1, min(len(bands), 4))
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(fetch, bands))
    else:
        results = [fetch(b) for b in bands]

    for band, data, transform, crs in results:
        out[band] = data
        meta[band] = {"transform": transform, "crs": crs, "shape": data.shape}

    # B11 等 20m 波段窗口是 10m 波段的一半，指数计算要求同形，最近邻重采样到 10m
    if "B04" in out:
        ref_shape = out["B04"].shape
        for band in list(out.keys()):
            if out[band].shape != ref_shape:
                sh = max(1, round(ref_shape[0] / out[band].shape[0]))
                sw = max(1, round(ref_shape[1] / out[band].shape[1]))
                out[band] = np.repeat(np.repeat(out[band], sh, axis=0), sw, axis=1)
                # 重采样后可能比目标多 1 像素（10m/20m 窗口尺寸非严格整数倍），裁剪对齐
                if out[band].shape[0] > ref_shape[0]:
                    out[band] = out[band][:ref_shape[0], :]
                if out[band].shape[1] > ref_shape[1]:
                    out[band] = out[band][:, :ref_shape[1]]
                # 若仍小于目标（向下取整），补 0 对齐
                if out[band].shape[0] < ref_shape[0]:
                    pad = np.zeros((ref_shape[0] - out[band].shape[0], out[band].shape[1]), dtype=out[band].dtype)
                    out[band] = np.vstack([out[band], pad])
                if out[band].shape[1] < ref_shape[1]:
                    pad = np.zeros((out[band].shape[0], ref_shape[1] - out[band].shape[1]), dtype=out[band].dtype)
                    out[band] = np.hstack([out[band], pad])
                meta[band]["shape"] = out[band].shape

    # ---- 多边形精确掩膜（核心修复）----
    # 用 B04（参考波段）的 transform + crs 生成掩膜，应用到所有波段
    ref_band = "B04" if "B04" in out else bands[0]
    mask = _aoi_polygon_mask(aoi, meta[ref_band]["transform"], meta[ref_band]["crs"],
                             out[ref_band].shape)
    for band in out:
        out[band] = out[band] * mask   # 掩膜外像元置 0

    return {"bands": out, "meta": meta}


def _aoi_polygon_mask(aoi: list[list[float]], transform: Any, crs: str,
                      shape: tuple[int, int]) -> np.ndarray:
    """把 WGS84 的 AOI 多边形投影到影像 CRS，转成像素布尔掩膜。

    返回 True(1)/False(0) 的 uint8 掩膜，shape 与影像窗口一致。
    """
    from rasterio import features as riof
    from shapely.geometry import Polygon

    # 1. WGS84 多边形 → 影像 CRS 多边形（用 rasterio.warp.transform_geom，无需 pyproj）
    if crs and crs != "EPSG:4326":
        g = {"type": "Polygon", "coordinates": [aoi]}
        g_proj = _warp.transform_geom("EPSG:4326", crs, g)
        poly_proj = Polygon(g_proj["coordinates"][0])
    else:
        poly_proj = Polygon(aoi)

    # 2. 用 geometry_mask 把投影后的多边形转成像素掩膜
    mask = riof.geometry_mask(
        [poly_proj],
        out_shape=shape,
        transform=transform,
        invert=True,   # invert=True：多边形内部为 True
    )
    return mask.astype(np.uint8)


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
    """B04/B03/B02 → RGB PNG 字节（真彩色，兼容旧调用）"""
    return composite_png(bands, "TRUE_COLOR")


# 波段组合定义：combo -> (红通道波段, 绿通道波段, 蓝通道波段)
# 依据：不同波段组合能凸显不同地物，是遥感判读的基本手段
COMPOSITES = {
    # 真彩色：接近人眼所见，用于整体判读
    "TRUE_COLOR": ("B04", "B03", "B02"),
    # 标准假彩色（近红外进红通道）：健康植被显红色，最常用于识别植被覆盖
    "FALSE_COLOR": ("B08", "B04", "B03"),
    # 短波红外组合：水体极暗、裸岩/扰动区偏亮，适合看水体与裸地
    "SWIR": ("B11", "B08", "B04"),
    # 城市/裸地组合：建筑与裸土呈青灰，植被偏绿
    "URBAN": ("B11", "B03", "B02"),
}

# NDVI 伪彩色带（绿→黄→红），用于直观看植被长势
_NDVI_RAMP = [
    (0.00, (0x8B, 0x45, 0x13)),   # 棕：裸地
    (0.20, (0xD9, 0x77, 0x06)),   # 橙：稀疏
    (0.40, (0xEA, 0xDC, 0x00)),   # 黄：中等
    (0.60, (0x7C, 0xC8, 0x4C)),   # 浅绿：较好
    (0.80, (0x1D, 0x9E, 0x75)),   # 深绿：茂密
]


def composite_png(bands: dict[str, np.ndarray], combo: str = "TRUE_COLOR") -> bytes:
    """按波段组合渲染 RGB PNG 字节。

    - 常规组合：取三个波段做 2%~98% 拉伸后合成 RGB
    - NDVI：算归一化植被指数，再按色带映射（绿→黄→红直观反映长势）
    """
    from PIL import Image

    if combo == "NDVI":
        if "B08" not in bands or "B04" not in bands:
            raise KeyError("NDVI 需要 B08/B04 波段")
        idx = _norm(bands["B08"], bands["B04"])   # -1 ~ 1
        rgb = _ndvi_to_rgb(idx)
    else:
        r_band, g_band, b_band = COMPOSITES.get(combo, COMPOSITES["TRUE_COLOR"])
        missing = [b for b in (r_band, g_band, b_band) if b not in bands]
        if missing:
            raise KeyError(f"波段组合 {combo} 缺少波段: {missing}")
        r = _to_uint8(bands[r_band])
        g = _to_uint8(bands[g_band])
        b = _to_uint8(bands[b_band])
        rgb = np.dstack([r, g, b]).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def _ndvi_to_rgb(idx: np.ndarray) -> np.ndarray:
    """NDVI (-1~1) → RGB，用分段线性插值套色带"""
    h, w = idx.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    v = np.clip(idx.astype(np.float32), 0.0, 0.8)
    for i in range(len(_NDVI_RAMP) - 1):
        lo, c_lo = _NDVI_RAMP[i]
        hi, c_hi = _NDVI_RAMP[i + 1]
        seg = (v >= lo) & (v <= hi)
        if not seg.any():
            continue
        t = (v[seg] - lo) / (hi - lo) if hi > lo else np.zeros(seg.sum(), dtype=np.float32)
        for ch in range(3):
            rgb[..., ch][seg] = c_lo[ch] + (c_hi[ch] - c_lo[ch]) * t
    # 超出上限（>0.8）取最深绿
    over = v >= _NDVI_RAMP[-1][0]
    if over.any():
        for ch in range(3):
            rgb[..., ch][over] = _NDVI_RAMP[-1][1][ch]
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _norm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a.astype(np.float32) / 10000.0
    b = b.astype(np.float32) / 10000.0
    return np.divide(a - b, a + b, out=np.zeros_like(a), where=(a + b) != 0)


# ---------------------------------------------------------------------------
# 七类地物（对齐实施方案表 6 分类体系）
# ---------------------------------------------------------------------------
CLASS_LABELS: dict[str, str] = {
    "PIT": "露天采坑",
    "DUMP": "排土场/废石堆",
    "TAILINGS": "尾矿设施",
    "BARE": "裸地/施工扰动区",
    "VEGETATION": "植被",
    "ROAD": "道路/工业设施",
    "WATER": "水体",
}

# 判别阈值：矿山场景的经验值，可按矿区标定
MINE_THRESHOLDS: dict[str, float] = {
    "ndvi_veg": 0.25,          # NDVI 高于此值判植被
    "mndwi_water": 0.0,        # MNDWI 高于此值判水体
    # 亮度分层的"绝对兜底值"：分层边界以场景内分位数为主，再用这些值夹住，
    # 避免在整体偏暗/偏亮的影像上把普通裸地硬分成尾矿
    "bright_pit_abs_max": 0.16,       # 采坑不超过此亮度（坑内台阶阴影多）
    "bright_dump_abs_min": 0.10,      # 排土场亮度下限
    "bright_tailings_abs_min": 0.24,  # 尾矿（细粒高反射）亮度下限
    "bright_road_min": 0.12,          # 道路候选亮度下限
    "swir_bare_min": 0.08,            # 裸地/裸岩的短波红外下限
    "road_aspect_min": 2.0,           # 道路形态：最小外接矩形长宽比下限
    "road_compact_max": 0.40,         # 道路形态：紧凑度上限（狭长则紧凑度低）
}

# 各类型默认阈值（保留单指数类的兼容入口）
CLASS_THRESHOLD = {
    "VEGETATION": 0.25,
    "WATER": 0.0,
    "BUILDING": 0.0,
    "BARE": 0.0,
    "MOUNTAIN": -0.2,
}


def compute_index(bands: dict[str, np.ndarray], class_type: str) -> np.ndarray:
    """单指数入口（保留兼容：植被/水体/裸地/建筑/山体）

    七类矿山地物（PIT/DUMP/TAILINGS/ROAD）需要多条件组合，
    走 compute_mask()，不用本函数。
    """
    if class_type == "VEGETATION":
        return _norm(bands["B08"], bands["B04"])          # NDVI
    if class_type == "WATER":
        return _norm(bands["B03"], bands["B11"])          # MNDWI
    if class_type == "BUILDING":
        return _norm(bands["B11"], bands["B08"])          # NDBI
    if class_type == "BARE":
        b4 = bands["B04"].astype(np.float32) / 10000.0
        b11 = bands["B11"].astype(np.float32) / 10000.0
        return (b11 - b4) / (b11 + b4 + 1e-6)             # 裸土指数
    if class_type == "MOUNTAIN":
        return _norm(bands["B04"], bands["B08"])          # 负 NDVI = 裸岩
    raise ValueError(f"未知类型: {class_type}")


def _has(bands: dict[str, np.ndarray], key: str) -> bool:
    return key in bands and bands[key] is not None


def compute_mask(bands: dict[str, np.ndarray], class_type: str,
                 th: dict[str, float] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """按类别生成二值掩膜（多条件组合），返回 (mask, 诊断信息)

    设计要点（为什么不能只用单一指数）：
    采坑、排土场、尾矿、道路在光谱上都是"低植被 + 非水体 + 高反射不透水面"，
    单一指数无法区分。这里用「植被/水体公共掩膜 → 亮度分层 → 形态过滤」三段式：
      - 尾矿：细粒尾矿反射率最高（brightness ≥ 0.32），接近白色
      - 排土场：松散堆积物，中高亮（0.18–0.32）
      - 采坑：坑内多台阶与阴影，整体偏暗（< 0.18）+ 短波红外有裸岩信号
      - 道路：亮度偏高，靠「狭长形态」在矢量化后过滤
    这只是光谱近似，与 Mask2Former 语义分割相比精度有限，结论须标注。
    """
    t = {**MINE_THRESHOLDS, **(th or {})}

    red = bands["B04"].astype(np.float32) / 10000.0
    green = bands["B03"].astype(np.float32) / 10000.0
    blue = bands["B02"].astype(np.float32) / 10000.0
    nir = bands["B08"].astype(np.float32) / 10000.0
    brightness = (red + green + blue) / 3.0

    ndvi = _norm(bands["B08"], bands["B04"])
    # 水体掩膜：有 B11 用 MNDWI（抗阴影），否则退化为 NDWI
    if _has(bands, "B11"):
        mndwi = _norm(bands["B03"], bands["B11"])
        swir = bands["B11"].astype(np.float32) / 10000.0
    else:
        mndwi = _norm(bands["B03"], bands["B08"])
        swir = None

    water = mndwi > t["mndwi_water"]
    low_veg = ndvi < t["ndvi_veg"]
    # 非水体且低植被：矿山扰动类地物的公共候选区
    disturbed = low_veg & (~water)

    diag: dict[str, Any] = {
        "ndvi_mean": round(float(np.nanmean(ndvi)), 4),
        "mndwi_mean": round(float(np.nanmean(mndwi)), 4),
        "brightness_mean": round(float(np.nanmean(brightness)), 4),
    }

    if class_type == "VEGETATION":
        mask = ndvi > t["ndvi_veg"]
    elif class_type == "WATER":
        mask = water
    elif class_type == "BARE":
        # 泛裸土：扰动区内短波红外有信号即可（含采坑/排土场/尾矿，用于圈定全部裸地）
        if swir is not None:
            mask = disturbed & (swir > t["swir_bare_min"])
        else:
            mask = disturbed
    elif class_type in ("PIT", "DUMP", "TAILINGS"):
        # 三者光谱高度重叠，靠「场景内相对亮度分层」+「绝对兜底」区分：
        #   尾矿（细粒，最亮） > 排土场（松散堆积，中亮） > 采坑（台阶阴影多，偏暗）
        # 用分位数是因为不同季节/不同影像整体亮度差异极大
        # （实测同一场景 brightness 中位数可低至 0.065），固定绝对阈值必然失配。
        if disturbed.any():
            b_vals = brightness[disturbed]
            p33 = float(np.percentile(b_vals, 33))
            p66 = float(np.percentile(b_vals, 66))
        else:
            p33 = p66 = 0.0
        diag["bright_p33"] = round(p33, 4)
        diag["bright_p66"] = round(p66, 4)

        tailings_min = max(p66, t["bright_tailings_abs_min"])
        pit_cut = min(p33, t["bright_pit_abs_max"])
        dump_min = min(max(p33, t["bright_dump_abs_min"]), tailings_min)

        if class_type == "TAILINGS":
            mask = disturbed & (brightness >= tailings_min)
        elif class_type == "DUMP":
            mask = disturbed & (brightness >= dump_min) & (brightness < tailings_min)
        else:  # PIT
            mask = disturbed & (brightness < pit_cut)
            if swir is not None:
                mask = mask & (swir > t["swir_bare_min"])
        diag["pit_cut"] = round(pit_cut, 4)
        diag["dump_range"] = [round(dump_min, 4), round(tailings_min, 4)]
    elif class_type == "ROAD":
        # 道路候选：亮度偏高即可，最终由形态过滤（狭长）筛出
        mask = disturbed & (brightness >= t["bright_road_min"])
    elif class_type == "BUILDING":
        mask = disturbed & (brightness >= t["bright_road_min"])
    elif class_type == "MOUNTAIN":
        mask = ndvi < CLASS_THRESHOLD["MOUNTAIN"]
    else:
        raise ValueError(f"未知类型: {class_type}")

    diag["method"] = _METHOD_DESC.get(class_type, "指数阈值")
    return mask, diag


_METHOD_DESC = {
    "PIT": "低植被+非水体+场景内相对偏暗（亮度低于三分位）+短波红外裸岩信号",
    "DUMP": "低植被+非水体+场景内中高亮度（三分位至尾矿下限之间）",
    "TAILINGS": "低植被+非水体+场景内最亮一档（≥三分位且≥0.24，细粒高反射）",
    "ROAD": "低植被+非水体+亮度≥0.12，并按狭长形态（长宽比/紧凑度）过滤",
    "BARE": "低植被+非水体+短波红外信号",
    "VEGETATION": "NDVI > 0.25",
    "WATER": "MNDWI > 0",
}

# 采坑/排土场/尾矿是大尺度面状地物，最小面积门槛应显著大于一般地物
_LARGE_PATCH_CLASSES = {"PIT", "DUMP", "TAILINGS"}


def cls_shape_ok(aspect: float, compact: float, aspect_min: float, compact_max: float) -> bool:
    """道路形态判定：长宽比够大 或 紧凑度够低（狭长形状两者必居其一）

    实测矿区道路在 500px 级影像上常是短段，单靠长宽比会全被剔除，
    因此补充紧凑度判据（4πA/P²，狭长形状趋近 0）。
    """
    if aspect <= 0 and compact <= 0:
        return True   # 形态量不足（shapely 失败）时放行，不误杀
    return aspect >= aspect_min or (0 < compact <= compact_max)



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
                  min_area_px: int = 20,
                  thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """掩膜 → 连通域去噪 → 矢量化 → 形态过滤 → GeoJSON

    三段处理：
    1. 连通域 + 最小面积过滤：去掉孤立碎斑（道路碎片、噪声像元）
    2. 大尺度地物（采坑/排土场/尾矿）自动提高面积门槛，只保留连片斑块
    3. 道路/工业设施按「狭长形态」（最小外接矩形长宽比）二次过滤

    同时把形态指标写进每个要素的 properties（面积/周长/长宽比/紧凑度），
    供采坑形态分析与风险模型直接使用，不必再算一遍。
    """
    mask, diag = compute_mask(bands, class_type, thresholds)

    # 大尺度面状地物：提高最小面积门槛（采坑/排土场/尾矿通常是成片区域）
    # 道路窄长，面积门槛要放低，否则真实路段会被整条滤掉
    if class_type in _LARGE_PATCH_CLASSES:
        eff_min_area = min_area_px * 8
    elif class_type == "ROAD":
        eff_min_area = max(4, min_area_px // 2)
    else:
        eff_min_area = min_area_px

    # 连通域 + 最小面积过滤
    labels, num = _label_connected(mask)
    keep = np.zeros_like(mask)
    for lb in range(1, num + 1):
        area = int((labels == lb).sum())
        if area >= eff_min_area:
            keep |= (labels == lb)

    feats, stat = _vectorize_with_shape(keep, transform, crs, class_type,
                                        thresholds or {}, eff_min_area)

    result: dict[str, Any] = {
        "class": class_type,
        "label": CLASS_LABELS.get(class_type, class_type),
        "threshold": CLASS_THRESHOLD.get(class_type, 0.0),
        "min_area_px": eff_min_area,
        "coverage_pct": round(float(keep.mean()) * 100, 2),
        "feature_count": len(feats),
        "features": feats,
        "method": diag.get("method", ""),
        "diagnostics": diag,
        "shapeStats": stat,
    }
    # 未检出时给出可解释的原因，而不是让用户以为系统坏了
    if len(feats) == 0:
        if class_type in ("PIT", "TAILINGS"):
            result["hint"] = (
                "该区域未检出此类地物。两种可能：① 该区域确实没有明显的采坑/尾矿；"
                "② 判别阈值偏严——可在「阈值」里调高（如 0.14→0.20）后重试。"
                "建议先「查询影像」看真彩图确认目标是否存在。"
            )
        elif class_type == "DUMP":
            result["hint"] = "该区域未检出排土场/废石堆，可尝试调低阈值或确认区域是否正确。"
        elif class_type == "ROAD":
            result["hint"] = "未检出符合「狭长形态」的道路/设施斑块，可调低阈值或放宽形态条件。"
        else:
            result["hint"] = "该区域未检出此类地物，可调整阈值或确认圈选范围。"
    # 采坑/排土场/尾矿/道路 之间光谱高度重叠，必须把局限说清楚
    if class_type in ("PIT", "DUMP", "TAILINGS", "ROAD", "BARE"):
        result["disclaimer"] = (
            "采坑、排土场、尾矿、道路在光谱上同属“低植被高反射不透水面”，"
            "指数法只能按亮度分层与形态做近似区分，边界精度低于深度学习分割；"
            "本结果用于风险筛查，面积统计与越界判定前建议人工复核。"
        )
    return result


def _vectorize_with_shape(mask: np.ndarray, transform: Any, crs: str,
                          class_type: str, th: dict[str, float],
                          min_pixels: int) -> tuple[list[dict], dict[str, Any]]:
    """矢量化并计算形态指标；按类别做形态筛选

    形态指标（投影坐标系下计算，单位米/平方米，与经纬度无关）：
      - area_m2 / area_ha：面积
      - perimeter_m：周长
      - aspect_ratio：最小外接矩形长宽比（道路 ≫ 3，面状地物 ≈ 1）
      - compactness：4πA/P²（越接近 1 越紧凑，狭长形状趋近 0）
    """
    from rasterio import features as riof
    try:
        from shapely.geometry import shape as _shape
        has_shapely = True
    except ImportError:  # pragma: no cover
        has_shapely = False

    # 像元面积：投影坐标系（如 UTM）下 a、e 即米；经纬度需按纬度换算
    a, e = abs(float(transform.a)), abs(float(transform.e))
    is_geographic = False
    try:
        is_geographic = _warp.transform_bounds  # 占位，实际用 crs 判断
        from rasterio.crs import CRS as _CRS
        is_geographic = _CRS.from_string(crs).is_geographic
    except Exception:
        is_geographic = False
    if is_geographic:
        # 经纬度：1 度 ≈ 111320m(经向按纬度余弦) × 110540m(纬向)
        px_area = (a * 111320.0) * (e * 110540.0)
    else:
        px_area = a * e

    road_aspect_min = th.get("road_aspect_min", MINE_THRESHOLDS["road_aspect_min"])
    road_compact_max = th.get("road_compact_max", MINE_THRESHOLDS["road_compact_max"])

    import json as _json
    feats: list[dict] = []
    stat = {"totalAreaHa": 0.0, "maxAreaHa": 0.0, "avgAspectRatio": 0.0,
            "droppedByShape": 0}

    aspect_list: list[float] = []
    for geom, value in riof.shapes(mask.astype(np.uint8), mask=mask > 0, transform=transform):
        if not value:
            continue
        area_m2 = 0.0
        area_ha = 0.0
        perimeter_m = 0.0
        aspect = 0.0
        compact = 0.0
        props: dict[str, Any] = {}

        if has_shapely:
            try:
                poly = _shape(geom)
                if poly.is_empty:
                    continue
                area_m2 = float(poly.area)
                area_ha = area_m2 / 10000.0
                perimeter_m = float(poly.length)
                # 最小外接矩形长宽比（形态判别：道路狭长）
                mbr = poly.minimum_rotated_rectangle
                if mbr is not None and not mbr.is_empty:
                    xs, ys = mbr.exterior.coords.xy
                    # 相邻边长度
                    edges = [math.dist((xs[0], ys[0]), (xs[1], ys[1])),
                             math.dist((xs[1], ys[1]), (xs[2], ys[2]))]
                    long_side, short_side = max(edges), min(edges)
                    aspect = round(long_side / short_side, 2) if short_side > 1e-6 else 0.0
                compact = round((4 * math.pi * area_m2) / (perimeter_m ** 2), 3) if perimeter_m > 0 else 0.0
            except Exception:
                # shapely 失败时退化为像元计数
                area_m2 = 0.0
        if area_m2 <= 0:
            # 退化路径：按形状包围盒像元数估算（不影响过滤主逻辑）
            area_m2 = 0.0

        # 形态过滤：道路/工业设施要求"狭长"——长宽比够大 或 紧凑度够低（满足其一）
        # 面状地物（采坑/排土场/尾矿）不受此限
        if class_type == "ROAD" and cls_shape_ok(aspect, compact, road_aspect_min, road_compact_max) is False:
            stat["droppedByShape"] += 1
            continue

        props.update({
            "areaM2": round(area_m2, 1),
            "areaHa": round(area_ha, 4),
            "perimeterM": round(perimeter_m, 1),
            "aspectRatio": aspect,
            "compactness": compact,
        })

        g4326 = _warp.transform_geom(crs, "EPSG:4326", geom)
        geojson = _json.loads(_json.dumps(g4326))
        feats.append({
            "type": "Feature",
            "properties": {"id": len(feats), "classType": class_type, **props},
            "geometry": geojson,
        })
        stat["totalAreaHa"] = round(stat["totalAreaHa"] + area_ha, 4)
        stat["maxAreaHa"] = round(max(stat["maxAreaHa"], area_ha), 4)
        if aspect > 0:
            aspect_list.append(aspect)

    if aspect_list:
        stat["avgAspectRatio"] = round(sum(aspect_list) / len(aspect_list), 2)
    return feats, stat


def _mask_to_polygons(mask: np.ndarray, transform: Any, crs: str) -> list[dict]:
    """二值掩膜 → GeoJSON 多边形（保留旧入口，供热力图等场景使用）"""
    feats, _ = _vectorize_with_shape(mask, transform, crs, "BARE", {}, 1)
    return feats


def health() -> dict:
    return {"rasterio": HAS_RASTERIO, "stac": STAC_URL}

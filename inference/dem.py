"""
DEM 读取与地形分析（AWS Terrain Tiles · Terrarium 编码）

为什么选 Terrarium 而不是 Copernicus GLO-30：
1. Copernicus DEM 的 COG 用 predictor=3（浮点预测器），解码需要按行做字节平面
   还原 + uint32 累加 + 大端组装，实现极易出错（实测多次得到 ±3.4e38 垃圾值）；
   而 Terrarium 是 **PNG 三通道编码**，一行公式即得高程，稳定可靠。
2. Terrarium z=14 在本纬度约 9.6m/像素，精度优于 30m；单瓦片仅几十 KB，
   沙箱限速下也能秒级拿到。

高程解码公式（Terrarium）：
    elevation_m = (R * 256 + G + B / 256) - 32768

数据源（AWS Open Data，免费无认证）：
    https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png

精度限制（必须写进产品说明）：
    10–15m 像元仍大于矿坑台阶宽度（10–15m），
    因此**不能用于计算台阶坡面角、坑深、体积**。
    可支撑：区域坡度/坡向、低洼汇水、地形起伏度、排土场选址风险、道路切坡背景。
"""
from __future__ import annotations

import io
import math
import os
from typing import Any

import httpx
import numpy as np

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_ZOOM = 14
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "terrarium")

_http = httpx.Client(timeout=60.0, follow_redirects=True)


# ---------------------------------------------------------------------------
# 投影换算
# ---------------------------------------------------------------------------
def lonlat_to_pixel(lon: float, lat: float, z: int) -> tuple[float, float]:
    """经纬度 → 全球像素坐标（Web Mercator，像素原点在左上）"""
    n = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def pixel_to_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    n = 256 * (2 ** z)
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return lon, math.degrees(lat_rad)


def meters_per_pixel(lat: float, z: int) -> float:
    """该纬度下每像素对应的地面米数"""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


# ---------------------------------------------------------------------------
# 瓦片下载与解码
# ---------------------------------------------------------------------------
def _fetch_tile(z: int, x: int, y: int) -> np.ndarray:
    """下载并解码单张 Terrarium 瓦片，返回 256×256 float32 高程（米）"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f"{z}_{x}_{y}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
    else:
        r = _http.get(TILE_URL.format(z=z, x=x, y=y))
        r.raise_for_status()
        raw = r.content
        with open(path, "wb") as f:
            f.write(raw)

    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    arr = np.asarray(img, dtype=np.float32)
    # Terrarium 解码：R 高字节、G 中字节、B 小数部分
    elev = (arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0) - 32768.0
    return elev


def read_dem_window(west: float, south: float, east: float, north: float,
                    zoom: int = DEFAULT_ZOOM, max_dim: int = 512,
                    max_tiles: int = 16) -> dict[str, Any]:
    """读取 AOI 范围的高程窗口

    返回 elevation / mPerPixel / bounds / zoom / tileCount

    AOI 大到超过 max_tiles 时**自动降低 zoom**（精度降一档）而不是直接报错——
    客户圈整个矿区是常态，拒绝分析等于功能不可用。降级后 mPerPixel 会变大，
    返回值里带上实际 zoom，前端据此标注精度。
    """
    cx, cy = (west + east) / 2.0, (south + north) / 2.0

    def _tile_span(z: int) -> tuple[int, int, int, int]:
        _x0, _y0 = lonlat_to_pixel(west, north, z)
        _x1, _y1 = lonlat_to_pixel(east, south, z)
        return (int(_x0 // 256), int(_y0 // 256),
                int((_x1 - 1e-6) // 256), int((_y1 - 1e-6) // 256))

    # 逐级降 zoom，直到瓦片数落在上限内（z14→z13→z12→z11→z10）
    effective_zoom = max(10, min(zoom, 15))
    tx0, ty0, tx1, ty1 = _tile_span(effective_zoom)
    while (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > max_tiles and effective_zoom > 10:
        effective_zoom -= 1
        tx0, ty0, tx1, ty1 = _tile_span(effective_zoom)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > max_tiles * 4:
        raise ValueError(
            f"AOI 过大（z{effective_zoom} 仍需 {(tx1-tx0+1)*(ty1-ty0+1)} 张瓦片），"
            "请缩小圈选范围")
    if tx0 < 0 or ty0 < 0:
        raise ValueError("AOI 超出 Web Mercator 有效范围")

    zoom = effective_zoom

    n = 2 ** zoom
    canvas = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype=np.float32)
    fetched = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            # 瓦片 x 需按 2^z 回绕（跨 180° 经线），y 越界则跳过
            if ty < 0 or ty >= n:
                continue
            tile = _fetch_tile(zoom, tx % n, ty)
            rr, cc = (ty - ty0) * 256, (tx - tx0) * 256
            canvas[rr:rr + 256, cc:cc + 256] = tile
            fetched += 1

    # 裁剪到 AOI（zoom 可能被降级，需按最终 zoom 重算像素坐标）
    x0, y0 = lonlat_to_pixel(west, north, zoom)
    x1, y1 = lonlat_to_pixel(east, south, zoom)
    r0, c0 = int(round(y0 - ty0 * 256)), int(round(x0 - tx0 * 256))
    r1, c1 = int(round(y1 - ty0 * 256)), int(round(x1 - tx0 * 256))
    r0, c0 = max(0, r0), max(0, c0)
    r1, c1 = min(canvas.shape[0], r1), min(canvas.shape[1], c1)
    if r1 <= r0 or c1 <= c0:
        raise ValueError("AOI 与高程瓦片无交集")
    win = canvas[r0:r1, c0:c1]

    # 下采样控制处理尺寸
    step = max(1, int(math.ceil(max(win.shape) / max_dim)))
    if step > 1:
        win = win[::step, ::step]

    # 异常值清理：Terrarium 在瓦片边界/海洋/无数据区会给出极端值
    # （实测出现过 -1050m），必须按物理合理性过滤，否则坡度/起伏度全错
    win = _clean_elevation(win)

    return {
        "elevation": win,
        "mPerPixel": meters_per_pixel(cy, zoom) * step,
        "zoom": zoom,
        "shape": win.shape,
        "tileCount": fetched,
        "bounds": {"west": west, "south": south, "east": east, "north": north},
    }


def _clean_elevation(elev: np.ndarray, lo: float = -500.0, hi: float = 9000.0) -> np.ndarray:
    """把物理上不可能的高程视为无效，用邻域中位数替换

    中国境内陆地高程在 -160 ~ 8850m 之间，超出即判定为数据噪声。
    """
    bad = (~np.isfinite(elev)) | (elev < lo) | (elev > hi)
    if not bad.any():
        return elev
    out = elev.copy()
    good = elev[~bad]
    fill = float(np.median(good)) if good.size else 0.0
    out[bad] = fill
    return out


# ---------------------------------------------------------------------------
# 地形指标
# ---------------------------------------------------------------------------
def slope_aspect(elev: np.ndarray, m_per_px: float) -> tuple[np.ndarray, np.ndarray]:
    """坡度（度）与坡向（度，0=北，顺时针）

    Horn 三阶差分（与 ArcGIS/GDAL 口径一致），比简单中心差分抗噪。
    """
    dx = dy = float(m_per_px)
    z = np.pad(elev.astype(np.float32), 1, mode="edge")
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]

    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * dy)

    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype(np.float32)
    aspect = np.degrees(np.arctan2(dzdy, -dzdx))
    aspect = np.mod(90.0 - aspect, 360.0).astype(np.float32)
    return slope, aspect


def flow_proxy(slope: np.ndarray, dem: np.ndarray) -> np.ndarray:
    """低洼汇水代理指标：3×3 邻域均值 − 当前高程，再按坡度反加权

    数值越大越可能是汇水/积水处。真水文分析需 D8/多流向 + 填洼迭代，
    本指标只用于"低洼汇水"的快速筛查。
    """
    pad = np.pad(dem.astype(np.float32), 1, mode="edge")
    local_mean = (
        pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:] +
        pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:] +
        pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]
    ) / 9.0
    depression = (local_mean - dem).astype(np.float32)
    weight = np.clip(1.0 - slope / 15.0, 0, 1)
    return (np.clip(depression, 0, None) * weight).astype(np.float32)


def terrain_summary(elev: np.ndarray, slope: np.ndarray) -> dict[str, Any]:
    """地形统计摘要（按坡度分级给面积占比，直接用于风险因子打分）"""
    total = float(slope.size) or 1.0
    bins = [
        ("平坦(<2°)", slope < 2),
        ("缓坡(2-6°)", (slope >= 2) & (slope < 6)),
        ("缓陡(6-15°)", (slope >= 6) & (slope < 15)),
        ("陡坡(15-25°)", (slope >= 15) & (slope < 25)),
        ("极陡(≥25°)", slope >= 25),
    ]
    dist = [{"label": lb, "pct": round(float(m.sum()) / total * 100, 2)} for lb, m in bins]
    return {
        "elevMin": round(float(np.nanmin(elev)), 1),
        "elevMax": round(float(np.nanmax(elev)), 1),
        "elevMean": round(float(np.nanmean(elev)), 1),
        "reliefM": round(float(np.nanmax(elev) - np.nanmin(elev)), 1),
        "slopeMean": round(float(np.nanmean(slope)), 1),
        "slopeMax": round(float(np.nanmax(slope)), 1),
        "slopeP90": round(float(np.nanpercentile(slope, 90)), 1),
        "steepPct": round(float((slope >= 15).mean() * 100), 2),
        "distribution": dist,
    }

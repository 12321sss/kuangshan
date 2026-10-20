"""
真实解译核心：指数法分类 + 多边形矢量化

设计要点
--------
1. **只依赖 rasterio + shapely + numpy**，不依赖 GPU/torch，CPU 可跑。
   GPU 服务器就位后，本模块整体替换为 Mask2Former 推理，接口不变。

2. **波段映射可配置**：Sentinel-2 与 Landsat 的波段编号不同，
   通过 BANDS 表映射；GF-2 等商业高分影像为四波段（B1蓝 B2绿 B3红 B4近红），
   映射到同一套语义通道（B02/B03/B04/B08），上层判据完全复用。

3. **判据口径（红线）**：本模块输出的是「**潜在水土流失风险筛查**」结果，
   不是实测侵蚀量。采坑/排土场/尾矿在无DEM、无分割模型的条件下
   只能靠光谱+纹理近似区分，精度有限，界面与报告必须标注该局限。

4. **面积计算**：先算像素面积（m2），再乘像元数，避免经纬度直接算面积
   在矿区尺度上的累积误差（沿用同一套 EPSG:4326 球面近似，与 Java 侧交叉校验）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
import rasterio.windows
from rasterio.features import shapes as rio_shapes
from rasterio.windows import from_bounds
from shapely.geometry import shape as shapely_shape

# ---------------------------------------------------------------------------
# 波段映射：卫星 -> {语义通道: 波段号}
# 语义通道固定为 B02蓝 B03绿 B04红 B08近红，统一到 Sentinel-2 编号习惯
# ---------------------------------------------------------------------------
BANDS: dict[str, dict[str, int]] = {
    # Sentinel-2 (MSI)：10m 分辨率 B02/B03/B04/B08
    "SENTINEL2": {"B02": 2, "B03": 3, "B04": 4, "B08": 8},
    # Landsat 9 (OLI-2)：30m，Band1..Band9
    "LANDSAT9": {"B02": 2, "B03": 3, "B04": 4, "B08": 7},
    # GF-2 (全色+多光谱，四波段)：蓝绿红近红
    "GF2": {"B02": 1, "B03": 2, "B04": 3, "B08": 4},
    # GF-7 (四波段：蓝绿红近红)，与 GF-2 同构
    "GF7": {"B02": 1, "B03": 2, "B04": 3, "B08": 4},
    # 通用四波段商业高分影像（上传时未指明具体型号）
    "UPLOAD": {"B02": 1, "B03": 2, "B04": 3, "B08": 4},
}

# 分类阈值（可在 params 覆盖）。取值参考遥感文献常用经验值，
# 赣南/闽赣丘陵林地矿区背景实测需现场标定，demo 期先给通用值。
DEFAULT_THRESHOLDS = {
    "ndvi_veg": 0.30,       # 高于此值判植被
    "ndwi_water": 0.10,     # 高于此值判水体
    "ndbi_bare": -0.10,     # 高于此值偏裸地（负值表示非建筑/非裸岩）
    "bright_road": 2200.0,  # 亮度高于此值且低植被 →道路/设施候选
}

# 七类地物中文名（前端配色与报告口径共用）
CLASS_LABELS = {
    "VEGETATION": "植被",
    "WATER": "水体",
    "BARE": "裸地扰动",
    "PIT": "采坑",
    "DUMP": "排土场",
    "TAILINGS": "尾矿库",
    "ROAD": "道路设施",
}


@dataclass
class ExtractionResult:
    """一次解译的完整结果"""

    class_type: str
    label: str
    # 结果多边形：[[[lng,lat],...],...]（外环坐标，符合前端 GeoJSON 习惯）
    polygons: list[list[list[float]]]
    pixel_count: int
    extract_area_ha: float
    # 诊断信息：各指数均值，便于判断结果是否合理
    stats: dict[str, float]


def _norm(arr: np.ndarray) -> np.ndarray:
    """把反射率归一化到 0-1（uint16 反射率量纲），并抑制无效值"""
    a = arr.astype("float32")
    # 常见哨兵值置 NaN
    a[a <= 0] = np.nan
    a[a > 10000] = np.nan
    return a / 10000.0


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """安全除法：分母接近 0 时给 NaN，避免 inf 污染统计"""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(b) > 1e-6, a / b, np.nan)
    return out


def src_crs_in(src) -> str:
    """返回影像 CRS 的 authority code（4326 等），无 CRS 时返回空串"""
    try:
        return src.crs.to_epsg() or ""
    except Exception:
        return ""


def _pixel_area_m2(transform, epsg: int | None = 4326) -> float:
    """
    计算像元面积（平方米）。

    关键：GeoTransform 的 a/e 在经纬度影像（EPSG:4326）下是「度」，
    直接 abs(a*e) 得到平方度而非平方米 —— 会让像元计数虚高约 12 个数量级。
    按所在纬度做米制换算即可；投影坐标系（如 UTM）本身单位即米，直接取行列式。
    """
    a, e = transform.a, transform.e
    if epsg and epsg != 4326:
        # 投影坐标系单位已是米
        return abs(a * e)
    # 经纬度：用像元中心纬度换算
    f = transform.f
    if abs(a) < 1e-9 or abs(e) < 1e-9:
        return 0.0
    col, row = 0.5, 0.5
    lng = transform.c + col * a
    lat = transform.f + row * e
    dx = abs(a) * 111320.0 * math.cos(math.radians(lat))
    dy = abs(e) * 110540.0
    return dx * dy


def classify(
    path: str,
    satellite: str,
    class_type: str,
    aoi_bounds: tuple[float, float, float, float] | None = None,
    thresholds: dict[str, float] | None = None,
    min_polygon_ha: float = 0.01,
) -> ExtractionResult:
    """
    在指定影像上按指数法提取指定地物类。

    :param path: 影像文件路径（GeoTIFF）
    :param satellite: SENTINEL2 / LANDSAT9 / GF2
    :param class_type: 七类之一
    :param aoi_bounds: (west, south, east, north) 限定范围；None 表示全图
    :param thresholds: 阈值覆盖
    :param min_polygon_ha: 小于该面积的多边形丢弃（去椒盐噪点）
    """
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    band_map = BANDS.get(satellite.upper())
    if not band_map:
        raise ValueError(f"不支持的数据源: {satellite}")

    with rasterio.open(path) as src:
        # ---- 读 AOI 窗口（不指定则读全图）----
        # 注意：from_bounds 要求 bounds 与影像同一 CRS。若影像是非经纬度投影
        # （UTM/CGCS2000），必须先用 transform_bounds 做基准面转换，否则算出的
        # 窗口是 0 x 0，MemoryDataset 会直接抛 Invalid dataset dimensions。
        if aoi_bounds:
            w, s, e, n = aoi_bounds
            try:
                if src_crs_in(src) != 4326:
                    from rasterio.warp import transform_bounds

                    w, s, e, n = transform_bounds("EPSG:4326", src_crs_in(src),
                                                  w, s, e, n)
                window = from_bounds(w, s, e, n, transform=src.transform)
                # 窗口与影像求交集后再取整，避免负宽高/超界
                window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                window = window.round_offsets().round_lengths()
                if window.width <= 0 or window.height <= 0:
                    raise ValueError("AOI 与影像无交集")
                data = src.read(window=window, boundless=False)
                transform = src.window_transform(window)
            except Exception:
                # AOI 无交集/越界等异常，退回全图
                data = src.read()
                transform = src.transform
        else:
            data = src.read()
            transform = src.transform

        nodata = src.nodata
        src_crs = src.crs

        # ---- 反射率归一化 ----
        refl = np.stack([_norm(b) for b in data])  # shape=(bands, h, w)

        def band(code: str) -> np.ndarray | None:
            idx = band_map.get(code)
            if idx is None or idx > refl.shape[0]:
                return None
            return refl[idx - 1]

        blue, green, red, nir = band("B02"), band("B03"), band("B04"), band("B08")
        swir = None
        # Sentinel-2/Landsat 的短波红外用于裸地判据（B11 / Band6）
        if satellite.upper() == "SENTINEL2" and refl.shape[0] >= 11:
            swir = _norm(data[10])
        elif satellite.upper() == "LANDSAT9" and refl.shape[0] >= 6:
            swir = _norm(data[5])

        # ---- 指数计算 ----
        ndvi = _safe_div(nir - red, nir + red) if nir is not None and red is not None else None
        ndwi = _safe_div(green - nir, green + nir) if green is not None and nir is not None else None
        ndbi = _safe_div(swir - nir, swir + nir) if swir is not None and nir is not None else None
        brightness = np.nanmean(
            np.stack([b for b in (blue, green, red) if b is not None]), axis=0
        )

        # ---- 按目标类别生成掩膜 ----
        # 有效像元：亮度非 NaN（_norm 已把 <=0 与 >10000 的哨兵值置 NaN）。
        # 不再直接比对 nodata：窗口读取时数组按窗口形状缩放，
        # 用整幅的 nodata 标量比较虽仍成立，但哨兵值法已覆盖多数情况，
        # 保留 nodata 兜底（窗口越界时 rasterio 会填 nodata）。
        valid = ~np.isnan(brightness)
        if nodata is not None and data.shape[1] > 0 and data.shape[2] > 0:
            valid &= (data[0] != nodata)

        if class_type == "VEGETATION":
            mask = valid & (ndvi > th["ndvi_veg"])
        elif class_type == "WATER":
            mask = valid & (ndwi > th["ndwi_water"])
        elif class_type == "BARE":
            base = valid & (ndvi <= th["ndvi_veg"])
            mask = base & (ndbi > th["ndbi_bare"]) if ndbi is not None else base
        elif class_type in ("PIT", "DUMP", "TAILINGS"):
            # 采矿扰动区：裸地/低植被 + 非水体。
            # 三者在本机条件下无法靠光谱可靠区分（需形态与DEM），
            # 故统一按「人工扰动裸地」提取，并在报告中标注不可细分。
            base = valid & (ndvi <= th["ndvi_veg"])
            if ndbi is not None:
                base = base & (ndbi > th["ndbi_bare"])
            mask = base
            if ndwi is not None:
                mask = mask & ~(ndwi > th["ndwi_water"])
        elif class_type == "ROAD":
            mask = valid & (ndvi <= th["ndvi_veg"]) & (brightness > th["bright_road"])
        else:
            raise ValueError(f"不支持的类别: {class_type}")

        mask = mask.astype("uint8")

        # ---- 矢量化 ----
        raw_shapes = list(rio_shapes(mask, mask=mask, transform=transform, connectivity=8))
        # 像元面积（平方米）：transform.a/e 在经纬度影像下是「度」，
        # 直接 abs(a*e) 得到的是平方度，会让像元数虚高 12 个数量级。
        # 必须按所在纬度做米制换算：dx = dlon*111320*cos(lat)，dy = dlat*110540
        epsg = 0
        try:
            epsg = src_crs.to_epsg()
        except Exception:
            epsg = 0
        pixel_area_m2 = _pixel_area_m2(transform, epsg)

        polygons: list[list[list[float]]] = []
        kept_pixels = 0
        for geom, val in raw_shapes:
            if val != 1:
                continue
            poly = shapely_shape(geom)
            if poly.is_empty:
                continue
            # 只取外环，投影到经纬度（WGS84）
            if src_crs is not None and src_crs.to_epsg() != 4326:
                from rasterio.warp import transform as warp_transform
                from rasterio.warp import transform_bounds

                ring = poly.exterior.coords
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                bx = warp_transform(src_crs, "EPSG:4326", xs, ys)
                ring = list(zip(bx[0], bx[1]))
            else:
                ring = list(poly.exterior.coords)

            area_ha = _ring_area_ha(ring)
            if area_ha < min_polygon_ha:
                continue
            # 闭合环（首尾点相同）
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            polygons.append([[round(float(x), 7), round(float(y), 7)] for x, y in ring])
            kept_pixels += int(round(area_ha * 10000 / pixel_area_m2))

        total_ha = round(sum(_ring_area_ha(p) for p in polygons), 4)

        # 诊断量只对「命中掩膜的像元」求均值 —— 用全图均值会被背景稀释，
        # 导致明明提取到高 NDVI 植被区、诊断值却接近 0，无法判断结果是否合理
        stats = {
            "ndvi_mean": _masked_mean(ndvi, mask),
            "ndwi_mean": _masked_mean(ndwi, mask),
            "ndbi_mean": _masked_mean(ndbi, mask),
            "brightness_mean": _masked_mean(brightness, mask),
            "ndvi_scene_mean": _nan_mean(ndvi),
            "valid_pixel_ratio": round(float(np.count_nonzero(valid)) / max(valid.size, 1), 4),
            "masked_pixel_ratio": round(
                float(np.count_nonzero(mask)) / max(valid.size, 1), 4),
            "pixel_area_m2": round(pixel_area_m2, 4),
        }

        return ExtractionResult(
            class_type=class_type,
            label=CLASS_LABELS.get(class_type, class_type),
            polygons=polygons,
            pixel_count=kept_pixels,
            extract_area_ha=total_ha,
            stats=stats,
        )


def _nan_mean(a: np.ndarray | None) -> float:
    if a is None:
        return float("nan")
    with np.errstate(invalid="ignore"):
        v = np.nanmean(a) if a.size else float("nan")
    return round(float(v), 4) if not math.isnan(v) else -1.0


def _masked_mean(a: np.ndarray | None, mask: np.ndarray) -> float:
    """只在掩膜命中区域求均值：无命中时返回 -1，便于前端判断「提取为空」"""
    if a is None or not np.any(mask):
        return -1.0
    with np.errstate(invalid="ignore"):
        v = np.nanmean(a[mask.astype(bool)])
    return round(float(v), 4) if not math.isnan(v) else -1.0


def _ring_area_ha(ring: list[tuple[float, float]] | list[list[float]]) -> float:
    """
    球面近似面积（Shoelace + 纬度余弦修正），单位公顷。
    矿区尺度（<100km²）误差可忽略；与 Java 侧同一套公式便于交叉校验。
    """
    pts = [(p[0], p[1]) for p in ring]
    if len(pts) < 3:
        return 0.0
    lat0 = math.radians(pts[0][1])
    R = 6371000.0
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        px1 = R * math.radians(x1 - pts[0][0]) * math.cos(lat0)
        py1 = R * math.radians(y1 - pts[0][1])
        px2 = R * math.radians(x2 - pts[0][0]) * math.cos(lat0)
        py2 = R * math.radians(y2 - pts[0][1])
        area += px1 * py2 - px2 * py1
    return abs(area) / 2 / 10000.0


def ring_area_ha(ring) -> float:
    """对外暴露的面积计算，供 Java 侧回调校验时复用同一公式"""
    return _ring_area_ha(ring)
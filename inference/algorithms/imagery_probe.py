"""影像元数据自动识别：GeoTIFF 自带坐标系与范围，不该让用户手画

读什么：
- CRS（EPSG 或 WKT）→ 记录并用于定位
- 原生范围 → 转 WGS84 供 Cesium 贴图
- 分辨率 → 投影坐标要按纬度换算成真实地面分辨率（EPSG:3857 的米在 28°N 会被拉伸）
- 波段数 / 尺寸 / 数据类型
- 日期：TIFF 标签优先，没有就从文件名里找 YYYYMMDD / YYYYMM / YYYY
- 卫星：文件名里的 GF2/GF7/GF1/S2/SENTINEL

口径：识别结果只作为**默认值**填进表单，用户可以改；
年份不精确时要明确告诉用户「只识别到年份」，不要假装是 1 月 1 日拍的。
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

DISCLAIMER = "自动识别用于减少手工录入，识别到的日期/卫星仅作默认值，请核对后保存。"


def _guess_date(name: str, tags: dict) -> tuple[str | None, str]:
    """返回 (YYYY-MM-DD 或 None, 来源说明)"""
    # 1) TIFF 标签（GDAL 常见 TIFFTAG_DATETIME / ACQUISITION_DATE）
    for key in ("TIFFTAG_DATETIME", "ACQUISITION_DATE", "DATE_ACQUIRED", "datetime"):
        v = tags.get(key)
        if not v:
            continue
        m = re.search(r"(\d{4})[:/-](\d{1,2})[:/-](\d{1,2})", str(v))
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}", "影像元数据标签"

    stem = os.path.splitext(os.path.basename(name))[0]
    # 2) 8 位日期 YYYYMMDD
    for m in re.finditer(r"(20\d{2}|19\d{2})(\d{2})(\d{2})", stem):
        y, mo, d = m.groups()
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{mo}-{d}", "文件名"
    # 3) 6 位 YYYYMM
    for m in re.finditer(r"(20\d{2}|19\d{2})(\d{2})(?!\d)", stem):
        y, mo = m.groups()
        if 1 <= int(mo) <= 12:
            return f"{y}-{mo}-01", "文件名（仅到月份，日填 01，请核对）"
    # 4) 4 位年份
    for m in re.finditer(r"(20\d{2}|19\d{2})(?!\d)", stem):
        y = m.group(1)
        return f"{y}-01-01", f"文件名（仅识别到年份 {y}，默认 01-01，请核对）"
    return None, "未识别到日期"


def _guess_satellite(name: str, band_count: int, res_m: float | None) -> tuple[str | None, str]:
    upper = os.path.basename(name).upper()
    rules = [
        ("GF7", ("GF7", "GAOFEN7", "高分七号")),
        ("GF2", ("GF2", "GAOFEN2", "高分二号")),
        ("GF1", ("GF1", "GAOFEN1", "高分一号")),
        ("SENTINEL2", ("S2", "SENTINEL", "哨兵")),
        ("LANDSAT9", ("LC9", "LANDSAT")),
    ]
    for code, keys in rules:
        if any(k in upper for k in keys):
            return code, "文件名"
    # 4 波段且亚米级 → 大概率国产高分
    if band_count == 4 and res_m is not None and res_m <= 2.5:
        return "GF2", "按 4 波段 + 亚米级推断（可改）"
    return None, "未识别"


def _preview_png(path: str, max_dim: int = 1100) -> str | None:
    """生成预览图（base64 PNG）：降采样 + 2%-98% 线性拉伸

    为什么需要：用户选完影像应该"看到影像"，而不是只看到一个空框。
    直接贴原始 TIFF 浏览器不支持，所以后端渲染一张 RGB 预览回传。
    """
    import base64
    import io as _io

    import numpy as np
    import rasterio

    try:
        from PIL import Image
    except ImportError:
        return None

    with rasterio.open(path) as ds:
        step = max(1, int(math.ceil(max(ds.width, ds.height) / max_dim)))
        out_h = max(1, ds.height // step)
        out_w = max(1, ds.width // step)
        data = ds.read(out_shape=(ds.count, out_h, out_w))
        count = ds.count

    # 4 波段（GF2 等常见顺序 B/G/R/NIR）取 3、2、1 组成 RGB；单波段按灰度
    if count >= 4:
        arr = np.stack([data[2], data[1], data[0]], axis=-1).astype(np.float32)
    elif count == 3:
        arr = np.stack([data[2], data[1], data[0]], axis=-1).astype(np.float32)
    elif count == 1:
        arr = np.repeat(data[0:1], 3, axis=0).transpose(1, 2, 0).astype(np.float32)
    else:
        arr = np.stack([data[0], data[0], data[0]], axis=-1).astype(np.float32)

    # 逐波段 2/98 百分位拉伸（uint8 影像也能出对比度）
    out = np.zeros_like(arr, dtype=np.uint8)
    for i in range(3):
        band = arr[:, :, i]
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, [2, 98])
        if hi <= lo:
            hi = lo + 1
        scaled = np.clip((band - lo) / (hi - lo), 0, 1) * 255
        out[:, :, i] = np.nan_to_num(scaled, nan=0).astype(np.uint8)

    buf = _io.BytesIO()
    Image.fromarray(out, mode="RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def inspect(path: str) -> dict[str, Any]:
    """读取影像文件，返回可自动填表的信息"""
    import rasterio
    from rasterio.warp import transform_bounds

    if not path or not os.path.exists(path):
        raise ValueError(f"影像文件不存在：{path}")

    with rasterio.open(path) as ds:
        crs = ds.crs
        width, height = ds.width, ds.height
        band_count = ds.count
        dtype = str(ds.dtypes[0]) if ds.dtypes else ""
        res = ds.res
        bounds = ds.bounds
        tags = ds.tags() or {}

        epsg = None
        crs_label = None
        try:
            epsg = crs.to_epsg() if crs else None
            crs_label = f"EPSG:{epsg}" if epsg else (crs.to_string() if crs else None)
        except Exception:  # noqa: BLE001
            crs_label = str(crs) if crs else None

        warnings: list[str] = []
        if crs is None:
            warnings.append("影像没有坐标系（未定义 CRS），无法自动定位，需要手动画范围")
            wgs = None
            res_m = None
            ground_res = None
        else:
            try:
                wgs = list(transform_bounds(crs, "EPSG:4326", *bounds))
            except Exception:  # noqa: BLE001
                wgs = None
                warnings.append("坐标系无法转换为 WGS84，可能缺少基准参数")
            # 分辨率：地理坐标单位是度；投影坐标单位一般是米
            try:
                res_abs = abs(float(res[0])) if res else None
            except Exception:  # noqa: BLE001
                res_abs = None
            if crs.is_geographic:
                lat_c = (wgs[1] + wgs[3]) / 2 if wgs else 0
                res_m = res_abs * 111320.0 if res_abs else None
                ground_res = res_m
                if res_abs:
                    warnings.append(f"影像为地理坐标（度），像元约 {res_abs:.6f}°")
            else:
                res_m = res_abs
                lat_c = (wgs[1] + wgs[3]) / 2 if wgs else 0
                # 3857 等墨卡托投影在非赤道会把米「拉长」，按纬度回收
                if "3857" in (crs_label or "") and res_abs:
                    ground_res = res_abs * max(0.2, abs(math.cos(math.radians(lat_c))))
                else:
                    ground_res = res_abs

    date, date_src = _guess_date(path, tags)
    sat, sat_src = _guess_satellite(path, band_count, ground_res)

    preview = None
    try:
        preview = _preview_png(path)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"预览图生成失败：{e}")

    # 面积按中心纬度做等距近似（与 aoi_boundary / 报告口径一致）
    area_km2 = None
    if wgs:
        lat_mid = math.radians((wgs[1] + wgs[3]) / 2)
        area_km2 = round(
            (wgs[2] - wgs[0]) * 111.32 * abs(math.cos(lat_mid)) * (wgs[3] - wgs[1]) * 110.54, 3)

    return {
        "file": os.path.basename(path),
        "path": path,
        "crs": crs_label,
        "epsg": epsg,
        "bounds": {"west": round(wgs[0], 7), "south": round(wgs[1], 7),
                   "east": round(wgs[2], 7), "north": round(wgs[3], 7)} if wgs else None,
        "width": width,
        "height": height,
        "bandCount": band_count,
        "dtype": dtype,
        "resolutionM": round(ground_res, 3) if ground_res else None,
        "pixelSize": round(res_m, 6) if res_m else None,
        "acquisitionDate": date,
        "dateSource": date_src,
        "satellite": sat,
        "satelliteSource": sat_src,
        "areaKm2": area_km2,
        "previewBase64": preview,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


def health() -> dict:
    try:
        import rasterio  # noqa: F401
        ok = True
    except ImportError:
        ok = False
    return {"rasterio": ok}

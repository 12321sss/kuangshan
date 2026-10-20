"""
Sentinel-2 公开数据源（在线提取专用）

与「上传遥感图像解译」的区别：
- 上传解译 = 高分影像（GF-2 等商业数据），用户上传文件，本模块不参与
- 在线提取 = 本模块，按 AOI + 时间窗检索 Copernicus 公开数据，平台自己拉

数据源：Copernicus Data Space（欧空局官方 2023 起的新门户，无需注册即可检索元数据）
    https://catalogue.dataspace.copernicus.eu

已实测（2026-10-16，江西宁都河源样区 115.2E/26.3N）：
    - 2023 全年该样区命中 284 景 Sentinel-2
    - 2023-09-08 一景云量 2.5%，瓦片 T50RLQ 完整覆盖样区
    - QUICKLOOK 预览图可正常下载（27KB JPEG，已目视确认为真实赣南林地影像）

关键实现要点（均为实测踩坑结论）：
1. 必须显式传 SSL context（certifi）：Windows 下 Python 标准库证书链
   不含 Copernicus 根证书，直连会 SSL 握手中断
2. 云量过滤走 OData 属性语法：
   Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/...Value lt 15)
3. Assets 用 ?$expand=Assets 展开；直接访问 /Assets 会 404
4. 像素下载入口：
   https://catalogue.dataspace.copernicus.eu/odata/v1/Assets(<assetId>)/$value
   （整景 SAFE 约 666MB，生产应先做服务端 AOI 裁剪；demo 阶段优先取 QUICKLOOK
   与按波段裁剪，避免拉整景）
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import certifi
import requests

BASE = "https://catalogue.dataspace.copernicus.eu/odata/v1"

# Windows 下 Python 证书链缺 Copernicus 根证书，必须显式指定 CA bundle 路径。
# requests 的 verify 参数只接受路径/布尔值（不接受 SSLContext 对象），
# 而它内部本来就读这个 cafile，所以直接传 certifi 的 cacert.pem 路径即可。
CA_BUNDLE = certifi.where()
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "rs-platform/0.1 (remote-sensing-demo)"})


@dataclass
class Scene:
    """一景 Sentinel-2 影像的检索结果（元数据层）"""

    product_id: str
    name: str
    acquisition_date: date
    cloud_cover: float
    tile_id: str
    platform: str          # S2A / S2B
    processing_level: str  # MSIL1C / MSIL2A
    # 影像覆盖范围（经纬度）
    west: float = 0.0
    south: float = 0.0
    east: float = 0.0
    north: float = 0.0
    size_mb: float = 0.0
    quicklook_url: str = ""
    assets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north)"""
        return self.west, self.south, self.east, self.north

    @property
    def center(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2, (self.south + self.north) / 2)

    def contains(self, lng: float, lat: float) -> bool:
        return self.west <= lng <= self.east and self.south <= lat <= self.north


def _parse_product(item: dict[str, Any]) -> Scene:
    """从 OData Products 条目解析成 Scene"""
    name = item.get("Name", "")
    parts = name.split("_")
    platform = parts[0] if parts else ""
    level = parts[1] if len(parts) > 1 else ""
    tile = parts[4] if len(parts) > 4 else ""

    cloud = None
    for attr in item.get("Attributes") or []:
        if attr.get("Name") == "cloudCover":
            cloud = float(attr.get("Value"))
            break

    ring = (item.get("GeoFootprint") or {}).get("coordinates", [[]])[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]

    raw_date = (item.get("ContentDate") or {}).get("Start", "")[:10]
    try:
        acq = date.fromisoformat(raw_date)
    except ValueError:
        acq = date(2000, 1, 1)

    return Scene(
        product_id=item.get("Id", ""),
        name=name,
        acquisition_date=acq,
        cloud_cover=cloud if cloud is not None else -1.0,
        tile_id=tile,
        platform=platform,
        processing_level=level,
        west=min(lons) if lons else 0.0,
        south=min(lats) if lats else 0.0,
        east=max(lons) if lons else 0.0,
        north=max(lats) if lats else 0.0,
        size_mb=round((item.get("ContentLength") or 0) / 1048576, 1),
    )


def search(
    lng: float,
    lat: float,
    start: str,
    end: str,
    max_cloud: float = 15.0,
    limit: int = 20,
    level: str = "MSIL1C",
) -> list[Scene]:
    """
    按空间位置 + 时间窗 + 云量上限检索 Sentinel-2 场景。

    :param lng, lat: AOI 中心经纬度（十进制度）
    :param start, end: 日期字符串 YYYY-MM-DD
    :param max_cloud: 云量上限（%），0-100
    :param limit:最多返回场景数
    :param level: 处理级别，MSIL1C（原始） / MSIL2A（大气校正）
    """
    flt = (
        "Collection/Name eq 'SENTINEL-2' "
        f"and OData.CRS.Intersects(area=geography'SRID=4326;POINT({lng} {lat})') "
        f"and ContentDate/Start gt {start}T00:00:00.000Z "
        f"and ContentDate/Start lt {end}T00:00:00.000Z "
        "and Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
        f"and att/OData.CSC.DoubleAttribute/Value lt {max_cloud})"
    )
    params = [
        ("$filter", flt),
        ("$orderby", "ContentDate/Start desc"),
        ("$top", str(limit)),
        # 必须同时展开两个：Attributes 才有 cloudCover（不展开则云量解析不到，
        # 只能用于过滤而无法回显给前端）；Assets 才有 QUICKLOOK 下载入口。
        # 注意：Copernicus 的 OData 实现不接受 $expand=Attributes,Assets（400），
        # 只认重复参数写法 $expand=Attributes&$expand=Assets
        ("$expand", "Attributes"),
        ("$expand", "Assets"),
    ]
    # quote_via=quote：默认 urlencode 会把空格编成 '+'，而 OData 的
    # geography'POINT(115.2 26.3)' 里空格是有效分隔符，编成 '+' 会被服务端拒绝
    url = f"{BASE}/Products?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"

    resp = HTTP.get(url, timeout=90, verify=CA_BUNDLE)
    resp.raise_for_status()
    items = resp.json().get("value", [])

    scenes: list[Scene] = []
    for it in items:
        sc = _parse_product(it)
        if level and sc.processing_level != level:
            continue
        # QUICKLOOK 下载入口（演示与前端预览用，仅几十 KB）
        for a in it.get("Assets") or []:
            if a.get("Type") == "QUICKLOOK":
                sc.quicklook_url = a.get("DownloadLink", "")
        scenes.append(sc)
    return scenes


def quicklook_bytes(scene: Scene) -> bytes:
    """下载场景预览图（JPEG，约几十 KB），用于前端影像库缩略图"""
    if not scene.quicklook_url:
        raise ValueError(f"场景无 QUICKLOOK 入口: {scene.name}")
    resp = HTTP.get(scene.quicklook_url, timeout=120, verify=CA_BUNDLE)
    resp.raise_for_status()
    return resp.content
"""边界文件导入：SHP / GeoJSON / KML → 统一 AOI 环（WGS84 经纬度）

设计要点（详见 docs/12）：
1. **不引 pyproj**：Windows + Python 3.13 无预编译轮子。坐标系转换统一走
   rasterio 自带的 CRS / warp.transform，sentinel.py 已在用同一套。
2. **不猜坐标系**：.prj 缺失时，如果坐标值超出经纬度范围（>180 / >90）
   直接报错要求用户提供，而不是按 WGS84 硬转——偏几百米的边界比报错更危险。
3. **多要素**：一个 shp 常含多个矿权区块，全部返回，由前端/Java 决定取哪个或合并。
4. **保留内洞**：矿区里可能有保护区（inner ring），丢了会导致面积和越界判定都错。
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from typing import Any

from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.validation import make_valid

# 单个文件解压后允许的最大字节，防止 zip 炸弹
MAX_UNZIPPED = 80 * 1024 * 1024


def _local_area_ha(ring_4326: list[list[float]], lat0: float) -> float:
    """经纬度环 → 平方米 → 公顷（按中心纬度做等距近似，误差 <1%）"""
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    poly = Polygon([(p[0] * kx, p[1] * ky) for p in ring_4326])
    return abs(poly.area) / 10000.0


def _ring_from_coords(coords: list[tuple[float, float]]) -> list[list[float]]:
    out = [[round(float(x), 7), round(float(y), 7)] for x, y in coords]
    # 闭合环（首尾相同）：Cesium 与 shapely 都需要
    if out and out[0] != out[-1]:
        out.append(out[0][:])
    return out


def _transform_ring(ring: list[tuple[float, float]], src: CRS | None) -> list[list[float]]:
    if src is None:
        return _ring_from_coords(ring)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    tx, ty = warp_transform(src, "EPSG:4326", xs, ys)
    return _ring_from_coords(list(zip(tx, ty)))


def _shapely_to_rings(geom) -> list[dict]:
    """shapely 几何 → [{outer:[[x,y]...], holes:[[...]]}]（已为 WGS84）"""
    out: list[dict] = []
    polys = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    for poly in polys:
        if poly.is_empty or len(poly.exterior.coords) < 4:
            continue
        out.append({
            "outer": _ring_from_coords(list(poly.exterior.coords)),
            "holes": [_ring_from_coords(list(r.coords)) for r in poly.interiors],
        })
    return out


def _crs_from_wkt(wkt: str | None, override: str | None = None) -> tuple[CRS | None, str]:
    """WKT → rasterio CRS；用户手选的 EPSG 优先于文件里的 .prj

    为什么允许手选：CAD 直接导出的 .shp 常常只有几何（没有 .prj），
    此时无法判断坐标系；让用户显式指定 EPSG 是唯一可靠的办法——
    宁可让他选一次，也不要猜错把边界偏到几百米外。
    """
    if override:
        try:
            crs = CRS.from_user_input(override)
            return crs, f"按用户指定坐标系 {crs.to_string()}"
        except Exception as ex:  # noqa: BLE001
            raise ValueError(f"指定的坐标系无法识别：{override}（{ex}）") from ex
    if not wkt:
        return None, "文件未包含 .prj 坐标系定义"
    try:
        crs = CRS.from_wkt(wkt)
        return crs, crs.to_string()
    except Exception as ex:  # noqa: BLE001
        return None, f"坐标系定义无法解析：{ex}"


def _plausible_wgs84(rings: list[list[list[float]]]) -> bool:
    for ring in rings:
        for x, y in ring:
            if abs(x) > 180 or abs(y) > 90:
                return False
    return True


# ---------------------------------------------------------------------------
# 各格式解析
# ---------------------------------------------------------------------------

def _read_shapefile(shp: bytes, dbf: bytes | None, shx: bytes | None,
                    prj: str | None, base_name: str,
                    override_crs: str | None = None) -> dict[str, Any]:
    import shapefile  # pyshp

    kwargs: dict[str, Any] = {"shp": io.BytesIO(shp)}
    if dbf:
        kwargs["dbf"] = io.BytesIO(dbf)
    if shx:
        kwargs["shx"] = io.BytesIO(shx)
    reader = shapefile.Reader(**kwargs)

    # 注意：没有 .dbf 时 pyshp 的 numRecords 是 None，直接参与比较会抛
    # TypeError: '>' not supported between instances of 'NoneType' and 'int'。
    # 单传 .shp（CAD 导出最常见）就会踩到，这里统一按 0 处理。
    n_rec = reader.numRecords or 0
    field_names = [f[0] for f in reader.fields[1:]] if n_rec else []
    crs, crs_note = _crs_from_wkt(prj, override_crs)

    # 图层类型先看一眼：CAD 导出的常是线（POLYLINE），提前给出人话提示
    shp_type = reader.shapeType
    if shp_type in (shapefile.POINT, shapefile.POINTM, shapefile.POINTZ,
                    shapefile.MULTIPOINT, shapefile.MULTIPOINTM, shapefile.MULTIPOINTZ):
        raise ValueError(
            f"{base_name} 是**点**要素图层，不是面。边界必须是闭合面（Polygon），"
            "请在 CAD/ArcGIS 中导出为面图层（或先用「面域/闭合多段线」构面）后再上传")
    if shp_type in (shapefile.POLYLINE, shapefile.POLYLINEM, shapefile.POLYLINEZ):
        raise ValueError(
            f"{base_name} 是**线**要素图层（CAD 导出的多段线），不是面。"
            "请先在 ArcGIS/QGIS 里用「要素转面（Feature To Polygon）」转成面，或上传闭合的 GeoJSON/KML")

    features: list[dict] = []
    raw_bounds: list[list[float]] = []
    for idx, shp_rec in enumerate(reader.shapes()):
        geom = shp_rec.__geo_interface__
        gtype = geom.get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            continue
        g = shape(geom)
        if not g.is_valid:
            g = make_valid(g)
        # 先记录原始坐标范围，用于判断 .prj 缺失时坐标是否可能已是经纬度
        for poly in (g.geoms if isinstance(g, MultiPolygon) else [g]):
            if isinstance(poly, Polygon) and not poly.is_empty:
                raw_bounds.append(list(poly.bounds))

        # 逐环转换（rasterio.warp 需要坐标数组，不能直接喂 shapely）
        if crs is None:
            if not _plausible_wgs84([_ring_from_coords(list(p.exterior.coords))
                                     for p in (g.geoms if isinstance(g, MultiPolygon) else [g])
                                     if isinstance(p, Polygon) and not p.is_empty]):
                raise ValueError(
                    f"{base_name} 缺少 .prj 且坐标值不在经纬度范围内，无法自动判定坐标系。"
                    "请随 shp 一起提供 .prj 文件，或先在地理信息软件中转换为 WGS84。"
                )
            rings = _shapely_to_rings(g)
        else:
            polys = g.geoms if isinstance(g, MultiPolygon) else [g]
            transformed = []
            for poly in polys:
                if not isinstance(poly, Polygon) or poly.is_empty:
                    continue
                outer = _transform_ring(list(poly.exterior.coords), crs)
                holes = [_transform_ring(list(r.coords), crs) for r in poly.interiors]
                transformed.append({"outer": outer, "holes": holes})
            rings = transformed

        rec = reader.record(idx).as_dict() if n_rec > idx else {}
        name = ""
        for key in ("name", "NAME", "Name", "名称", "MC", "矿权名称"):
            if key in rec and str(rec[key]).strip():
                name = str(rec[key]).strip()
                break

        for r in rings:
            lat0 = sum(p[1] for p in r["outer"]) / max(len(r["outer"]), 1)
            area = _local_area_ha(r["outer"], lat0)
            for hole in r["holes"]:
                hl = sum(p[1] for p in hole) / max(len(hole), 1)
                area -= _local_area_ha(hole, hl)
            features.append({
                "name": name or f"{base_name} #{len(features) + 1}",
                "outer": r["outer"],
                "holes": r["holes"],
                "areaHa": round(max(area, 0.0), 4),
                "vertexCount": len(r["outer"]),
                "attributes": {k: str(v) for k, v in list(rec.items())[:12]},
            })

    return {
        "features": features,
        "sourceFormat": "SHP",
        "sourceCrs": crs.to_string() if crs else "WGS84(假定)",
        "crsNote": crs_note if crs else (
            "缺少 .prj，按 WGS84 处理（坐标范围合理）。若实际为投影坐标，结果会偏移。"
        ),
        "rawBounds": raw_bounds,
        "attributeFields": field_names,
    }


def _read_geojson(content: bytes) -> dict[str, Any]:
    doc = json.loads(content.decode("utf-8-sig"))
    feats: list[dict] = []
    if doc.get("type") == "FeatureCollection":
        feats = doc.get("features", [])
    elif doc.get("type") == "Feature":
        feats = [doc]
    else:
        feats = [{"type": "Feature", "properties": {}, "geometry": doc}]

    # GeoJSON 规范要求 WGS84，但仍然检查一下，防止有人把投影坐标存进 GeoJSON
    out: list[dict] = []
    for f in feats:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = make_valid(g)
        rings = _shapely_to_rings(g)
        if not rings or not _plausible_wgs84([r["outer"] for r in rings]):
            raise ValueError("GeoJSON 坐标超出经纬度范围，可能不是 WGS84（4326），请先转换")
        props = f.get("properties") or {}
        name = str(props.get("name") or props.get("NAME") or props.get("名称") or "")
        for r in rings:
            lat0 = sum(p[1] for p in r["outer"]) / max(len(r["outer"]), 1)
            area = _local_area_ha(r["outer"], lat0)
            for hole in r["holes"]:
                hl = sum(p[1] for p in hole) / max(len(hole), 1)
                area -= _local_area_ha(hole, hl)
            out.append({
                "name": name or f"要素 #{len(out) + 1}",
                "outer": r["outer"],
                "holes": r["holes"],
                "areaHa": round(max(area, 0.0), 4),
                "vertexCount": len(r["outer"]),
                "attributes": {k: str(v) for k, v in list(props.items())[:12]},
            })
    return {
        "features": out,
        "sourceFormat": "GeoJSON",
        "sourceCrs": "EPSG:4326",
        "crsNote": "GeoJSON 规范要求 WGS84，已按 4326 处理",
        "rawBounds": [],
        "attributeFields": list((feats[0].get("properties") or {}).keys()) if feats else [],
    }


def _read_kml(content: bytes) -> dict[str, Any]:
    """KML：只用标准库解析 Polygon/outerBoundaryIs/innerBoundaryIs（KML 恒为 WGS84）"""
    import xml.etree.ElementTree as ET

    text = content.decode("utf-8-sig", errors="replace")
    root = ET.fromstring(text)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[: root.tag.index("}") + 1]

    def tag(name: str) -> str:
        return f"{ns}{name}"

    def parse_coords(node) -> list[list[float]]:
        pts: list[tuple[float, float]] = []
        for c in node.iter(tag("coordinates")):
            for token in (c.text or "").split():
                parts = token.split(",")
                if len(parts) >= 2:
                    pts.append((float(parts[0]), float(parts[1])))
        return _ring_from_coords(pts)

    out: list[dict] = []
    placemarks = root.iter(tag("Placemark"))
    for pm in placemarks:
        name_el = pm.find(tag("name"))
        name = (name_el.text or "").strip() if name_el is not None else ""
        for poly in pm.iter(tag("Polygon")):
            outer_el = poly.find(f"{tag('outerBoundaryIs')}/{tag('LinearRing')}")
            if outer_el is None:
                continue
            outer = parse_coords(outer_el)
            if len(outer) < 4:
                continue
            holes = []
            for inner in poly.findall(f"{tag('innerBoundaryIs')}/{tag('LinearRing')}"):
                h = parse_coords(inner)
                if len(h) >= 4:
                    holes.append(h)
            lat0 = sum(p[1] for p in outer) / len(outer)
            area = _local_area_ha(outer, lat0)
            for h in holes:
                area -= _local_area_ha(h, sum(p[1] for p in h) / len(h))
            out.append({
                "name": name or f"多边形 #{len(out) + 1}",
                "outer": outer,
                "holes": holes,
                "areaHa": round(max(area, 0.0), 4),
                "vertexCount": len(outer),
                "attributes": {},
            })

    return {
        "features": out,
        "sourceFormat": "KML",
        "sourceCrs": "EPSG:4326",
        "crsNote": "KML 固定使用 WGS84",
        "rawBounds": [],
        "attributeFields": [],
    }


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def import_boundary(filename: str, content: bytes,
                    source_crs: str | None = None) -> dict[str, Any]:
    """解析边界文件，返回统一的要素列表

    支持：.zip（内含 shp 四件套）/ .shp / .geojson / .json / .kml
    source_crs：用户手选的坐标系（如 EPSG:4547），优先于文件内 .prj；
                单传 .shp 没有 .prj 时靠它兜底
    """
    if not content:
        raise ValueError("文件内容为空")

    lower = filename.lower()
    warnings: list[str] = []

    if lower.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as ex:
            raise ValueError(f"zip 文件损坏：{ex}") from ex

        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_UNZIPPED:
            raise ValueError(f"压缩包解压后 {total / 1024 / 1024:.0f}MB，超过 80MB 上限")

        names = zf.namelist()
        shp_names = [n for n in names if n.lower().endswith(".shp")]
        if not shp_names:
            geo = [n for n in names if n.lower().endswith((".geojson", ".json"))]
            if geo:
                return import_boundary(geo[0], zf.read(geo[0]))
            raise ValueError("压缩包里没有 .shp 或 .geojson 文件")

        shp_name = shp_names[0]
        if len(shp_names) > 1:
            warnings.append(f"压缩包含 {len(shp_names)} 个 shp，已只解析 {shp_name}")

        base = shp_name[:-4]

        def find(ext: str) -> bytes | None:
            for n in names:
                if n.lower() in (base.lower() + ext, base + ext):
                    return zf.read(n)
            return None

        dbf, shx = find(".dbf"), find(".shx")
        prj_bytes = find(".prj")
        prj = prj_bytes.decode("utf-8-sig", errors="replace") if prj_bytes else None
        if dbf is None:
            warnings.append("缺少 .dbf，要素名称等属性不可用")
        if prj is None:
            warnings.append("缺少 .prj，将按坐标范围判断是否为经纬度")

        result = _read_shapefile(zf.read(shp_name), dbf, shx, prj,
                                 base.rsplit("/", 1)[-1], source_crs)
    elif lower.endswith(".shp"):
        # 单传 shp：几何能读，但坐标系和属性缺失
        warnings.append("只上传了 .shp：属性不可用；坐标系若不在下方指定，只能按坐标值推断")
        result = _read_shapefile(content, None, None, None, filename[:-4], source_crs)
    elif lower.endswith((".geojson", ".json")):
        result = _read_geojson(content)
    elif lower.endswith(".kml"):
        result = _read_kml(content)
    elif lower.endswith(".kmz"):
        zf = zipfile.ZipFile(io.BytesIO(content))
        kml = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml:
            raise ValueError("kmz 里没有 kml 文件")
        result = _read_kml(zf.read(kml[0]))
    else:
        raise ValueError("不支持的文件类型，请上传 .zip（含 shp 四件套）/ .shp / .geojson / .kml")

    return _finalize(result, warnings)


def _finalize(result: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """统一收尾：合并提示、校验要素非空、算汇总"""
    result["warnings"] = warnings + ([result["crsNote"]] if result.get("crsNote") else [])

    if not result["features"]:
        raise ValueError(
            "文件中没有有效的面要素。请确认：① 图层类型是面（Polygon）而非线或点；"
            "② 要素没有被全部过滤掉"
        )

    total_ha = sum(f["areaHa"] for f in result["features"])
    result["summary"] = {
        "featureCount": len(result["features"]),
        "totalAreaHa": round(total_ha, 4),
        "totalVertexCount": sum(f["vertexCount"] for f in result["features"]),
        "hasHoles": any(f["holes"] for f in result["features"]),
        "largestAreaHa": round(max(f["areaHa"] for f in result["features"]), 4),
    }
    return result


def import_boundary_files(files: list[dict[str, Any]],
                          source_crs: str | None = None) -> dict[str, Any]:
    """多文件导入：shp / shx / dbf / prj 分开选中也能正确配对

    为什么需要它：CAD 导出的是一个文件夹里的四个文件，用户很自然会
    「全选」而不是先打包 zip；只收单个 .shp 会丢坐标系。
    """
    items = [(str(f.get("filename") or ""), f.get("content") or b"") for f in files]
    items = [(n, c) for n, c in items if n and c]
    if not items:
        raise ValueError("没有收到文件内容")

    if len(items) == 1:
        return import_boundary(items[0][0], items[0][1], source_crs)

    # 有 zip 就按 zip 处理（zip 里可能就是一整套）
    for name, content in items:
        if name.lower().endswith(".zip"):
            return import_boundary(name, content, source_crs)

    shp_list = [(n, c) for n, c in items if n.lower().endswith(".shp")]
    if not shp_list:
        # 没有 shp：交给单文件逻辑处理 geojson/kml
        return import_boundary(items[0][0], items[0][1], source_crs)
    if len(shp_list) > 1:
        raise ValueError(f"选择了 {len(shp_list)} 个 .shp，一次只能导入一个图层")

    shp_name, shp_bytes = shp_list[0]
    stem = shp_name.rsplit(".", 1)[0].lower()

    def sibling(ext: str) -> bytes | None:
        for n, c in items:
            ln = n.lower()
            if ln.endswith(ext) and ln.rsplit(".", 1)[0] == stem:
                return c
        return None

    dbf, shx, prj_bytes = sibling(".dbf"), sibling(".shx"), sibling(".prj")
    prj = prj_bytes.decode("utf-8-sig", errors="replace") if prj_bytes else None

    warnings: list[str] = []
    if dbf is None:
        warnings.append("未选中 .dbf：要素名称等属性不可用（几何与面积不受影响）")
    if prj is None and not source_crs:
        warnings.append("未选中 .prj 且没有指定坐标系：只能按坐标值判断是否为经纬度")

    result = _read_shapefile(shp_bytes, dbf, shx, prj,
                             shp_name.rsplit(".", 1)[0], source_crs)
    return _finalize(result, warnings)


def health() -> dict:
    try:
        import shapefile  # noqa: F401
        has_pyshp = True
    except ImportError:
        has_pyshp = False
    return {"pyshp": has_pyshp}

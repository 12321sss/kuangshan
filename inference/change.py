"""周尺度监测：影像可用性检查（L1）+ 突变事件检测（L2）

为什么周尺度只做「事件检测」而不是「面积统计」（docs/13 的结论）：
- 采坑边界一年推进 20-50 m，一周才 0.4-1 m，只有 10m 像元的 1/10~1/25，
  面积变化测出来全是噪声；
- 所以周尺度正确的产物是「**这周有 3 处可疑新增水体，请看一下**」，
  而不是「采坑减少 0.3 公顷」这种假精度。

L1：查最近 N 天有没有满足云量的影像。没有就说没有——"没数据"和"没变化"是两件事。
L2：两期指数差值 → 阈值 → 斑块提取 → 输出可疑变化点，人工点进去确认。
"""

from __future__ import annotations

import base64
import io
from datetime import date, timedelta
from typing import Any

import numpy as np
from scipy import ndimage

import sentinel as sentinel_mod

DISCLAIMER = (
    "本页为突变**筛查**：光学影像只能看到已经发生的地表变化（新滑坡体、新增积水、"
    "植被被清除），看不到缓慢形变；「无异常」不等于「安全」。"
)

EVENT_TYPES = {
    "NEW_WATER": {"label": "新增水体", "color": "#1e88e5"},
    "LOST_WATER": {"label": "水体消失", "color": "#90a4ae"},
    "NEW_BARE": {"label": "新增裸地/扰动", "color": "#d32f2f"},
    "VEG_RECOVERY": {"label": "植被恢复", "color": "#43a047"},
}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _stac_list(aoi: list[list[float]], start: str, end: str,
               max_cloud: float, limit: int = 60) -> list[dict]:
    """STAC 列表检索（search_scene 只返回最优一景，可用性检查需要全部）"""
    poly = aoi if aoi[0] == aoi[-1] else aoi + [aoi[0]]
    body = {
        "collections": [sentinel_mod.COLLECTION],
        "intersects": {"type": "Polygon", "coordinates": [poly]},
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        "limit": limit,
    }
    r = sentinel_mod._http.post(f"{sentinel_mod.STAC_URL}/search", json=body)
    r.raise_for_status()
    return r.json().get("features", [])


def availability(payload: dict[str, Any]) -> dict[str, Any]:
    """L1：最近 N 天影像可用性

    返回可用景列表 + 结论（有没有、最近是哪天、建议怎么做）。
    云量先按用户阈值查；查不到时**再放宽到 60% 查一次**，用于区分
    「完全没影像」和「有影像但云太多」——这两种情况处置方式完全不同。
    """
    aoi = payload.get("aoi") or []
    days = int(payload.get("days") or 30)
    max_cloud = float(payload.get("maxCloud") or 20)

    if len(aoi) < 3:
        raise ValueError("分析区至少需要 3 个点")

    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    scenes = _stac_list(aoi, start, end, max_cloud)
    relaxed: list[dict] = []
    if not scenes:
        relaxed = _stac_list(aoi, start, end, 60)

    def brief(f: dict) -> dict:
        props = f.get("properties") or {}
        dt = str(props.get("datetime") or "")
        return {
            "id": f.get("id"),
            "date": dt[:10],
            "datetime": dt,
            "cloudCover": round(float(props.get("eo:cloud_cover") or 0), 1),
            "platform": props.get("platform"),
        }

    usable = [brief(f) for f in scenes]
    # 同一天可能有多景（相邻轨道），按日期去重保留云量最低的
    by_day: dict[str, dict] = {}
    for s in usable:
        cur = by_day.get(s["date"])
        if cur is None or s["cloudCover"] < cur["cloudCover"]:
            by_day[s["date"]] = s
    usable = sorted(by_day.values(), key=lambda x: x["date"], reverse=True)

    if usable:
        level = "充足" if len(usable) >= 3 else "偏少"
        latest = usable[0]
        gap = (today - date.fromisoformat(latest["date"])).days
        message = (f"近 {days} 天有 {len(usable)} 天可用影像，最近一期为 {latest['date']}"
                   f"（{gap} 天前，云量 {latest['cloudCover']}%）")
        advice = ("可以直接做两期突变检测" if gap <= 15
                  else "最近一期距今天数较多，做变化对比时注意时间跨度内可能有多次扰动")
    else:
        level = "无可用影像"
        latest = None
        if relaxed:
            best = min(relaxed, key=lambda f: float((f.get("properties") or {}).get("eo:cloud_cover") or 99))
            days_ago = (today - date.fromisoformat(str(best["properties"]["datetime"])[:10])).days
            cloud = round(float(best["properties"].get("eo:cloud_cover") or 0), 1)
            message = (f"近 {days} 天没有云量低于 {max_cloud:.0f}% 的影像；"
                       f"放宽到 60% 后最近一期是 {days_ago} 天前（云量 {cloud}%）")
            advice = "放宽云量阈值重试，或延长统计窗口；云量高的影像变化信号会被云影干扰，需人工确认"
        else:
            message = f"近 {days} 天完全没有覆盖该区域的影像（云量放宽到 60% 也没有）"
            advice = "延长统计窗口到 60/90 天；Sentinel-2 在雨季常出现整月无可用影像"

    return {
        "level": level,
        "message": message,
        "advice": advice,
        "range": {"start": start, "end": end, "days": days},
        "sceneCount": len(usable),
        "scenes": usable[:20],
        "relaxedCloudCount": len(relaxed),
        "maxCloud": max_cloud,
        "note": "「没有可用影像」与「没有变化」是两件事：前者只能说明缺少观测",
    }


def _index_pair(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    b3 = bands["B03"].astype(np.float32) / 10000.0
    b4 = bands["B04"].astype(np.float32) / 10000.0
    b8 = bands["B08"].astype(np.float32) / 10000.0
    b11 = bands["B11"].astype(np.float32) / 10000.0

    def norm(a, b):
        return np.divide(a - b, a + b, out=np.zeros_like(a), where=(a + b) != 0)

    return {
        "ndwi": norm(b3, b11),
        "ndvi": norm(b8, b4),
        "valid": (b3 > 0) & (b4 > 0) & (b8 > 0) & (b11 > 0),
    }


def _patches(mask: np.ndarray, transform, crs: str, min_area_ha: float) -> list[dict]:
    """连通域 → 斑块（面积 ha + 中心经纬度）

    注意：sentinel._vectorize_with_shape 的 min_pixels 参数在当前版本并未真正过滤，
    所以**必须在这里按面积再筛一次**，否则 0.02 ha 的噪声会全部返回给前端。
    """
    opened = ndimage.binary_opening(mask, structure=np.ones((3, 3), dtype=bool))
    if not opened.any():
        opened = mask
    feats, _stats = sentinel_mod._vectorize_with_shape(opened, transform, crs, "BARE", {}, 1)
    out = []
    for f in feats:
        props = f.get("properties") or {}
        area_ha = float(props.get("areaHa") or 0.0)
        if area_ha < min_area_ha:
            continue
        ring = (f.get("geometry") or {}).get("coordinates", [[]])[0]
        if not ring:
            continue
        lngs = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        out.append({
            "lng": _r(sum(lngs) / len(lngs), 6),
            "lat": _r(sum(lats) / len(lats), 6),
            "areaHa": _r(area_ha),
            "perimeterM": _r(props.get("perimeterM") or 0.0),
        })
    out.sort(key=lambda x: -x["areaHa"])
    return out


def detect(payload: dict[str, Any]) -> dict[str, Any]:
    """L2：两期突变检测

    payload: aoi, d1Start/d1End, d2Start/d2End, maxCloud, minAreaHa, withImage
    """
    aoi = payload.get("aoi") or []
    if len(aoi) < 3:
        raise ValueError("分析区至少需要 3 个点")

    max_cloud = float(payload.get("maxCloud") or 20)
    # 默认 0.5 ha：实测 15 天间隔下，<0.5 ha 的斑块九成是阈值抖动/阴影，
    # 给小阈值会让用户被几十个噪声点淹没，反而找不到真正要看的地方
    min_area_ha = float(payload.get("minAreaHa") or 0.5)
    max_dim = int(payload.get("maxDim") or 768)

    d1 = (payload.get("d1Start") or "", payload.get("d1End") or "")
    d2 = (payload.get("d2Start") or "", payload.get("d2End") or "")
    if not all(d1) or not all(d2):
        raise ValueError("两期都要给日期范围")

    scene1 = sentinel_mod.search_scene(aoi, d1[0], d1[1], max_cloud)
    scene2 = sentinel_mod.search_scene(aoi, d2[0], d2[1], max_cloud)
    if scene1 is None:
        raise ValueError(f"第一期（{d1[0]} ~ {d1[1]}）没有满足云量的影像")
    if scene2 is None:
        raise ValueError(f"第二期（{d2[0]} ~ {d2[1]}）没有满足云量的影像")
    if scene1.get("id") == scene2.get("id"):
        raise ValueError("两期检索到同一景影像，无法对比：请把日期范围分开")

    need = ["B03", "B04", "B08", "B11"]
    c1 = sentinel_mod.clip_aoi(scene1, aoi, need, max_dim=max_dim)
    c2 = sentinel_mod.clip_aoi(scene2, aoi, need, max_dim=max_dim)

    # 两期尺寸一致（同一 AOI 同一 max_dim）；保险起见裁到最小公共尺寸
    h = min(c1["bands"]["B04"].shape[0], c2["bands"]["B04"].shape[0])
    w = min(c1["bands"]["B04"].shape[1], c2["bands"]["B04"].shape[1])
    b1 = {k: v[:h, :w] for k, v in c1["bands"].items()}
    b2 = {k: v[:h, :w] for k, v in c2["bands"].items()}

    i1 = _index_pair(b1)
    i2 = _index_pair(b2)
    valid = i1["valid"] & i2["valid"]

    transform = c1["meta"]["B04"]["transform"]
    crs = c1["meta"]["B04"]["crs"]
    # 像元面积（ha）：Sentinel-2 COG 的 CRS 是 UTM，transform 单位是米
    px_area_ha = abs(transform.a * transform.e) / 10000.0
    if px_area_ha <= 0:
        px_area_ha = 0.01

    ndwi_diff = np.where(valid, i2["ndwi"] - i1["ndwi"], 0).astype(np.float32)
    ndvi_diff = np.where(valid, i2["ndvi"] - i1["ndvi"], 0).astype(np.float32)

    rules = {
        "NEW_WATER": (ndwi_diff > 0.15) & (i2["ndwi"] > 0.05),
        "LOST_WATER": (ndwi_diff < -0.15) & (i1["ndwi"] > 0.05),
        "NEW_BARE": (ndvi_diff < -0.15) & (i2["ndvi"] < 0.28),
        "VEG_RECOVERY": (ndvi_diff > 0.15) & (i2["ndvi"] > 0.3),
    }

    events = []
    for key, mask in rules.items():
        if not mask.any():
            events.append({
                "type": key, "label": EVENT_TYPES[key]["label"],
                "color": EVENT_TYPES[key]["color"], "count": 0,
                "totalAreaHa": 0.0, "patches": [],
            })
            continue
        patches = _patches(mask & valid, transform, crs, min_area_ha)
        total = sum(p["areaHa"] for p in patches)
        events.append({
            "type": key,
            "label": EVENT_TYPES[key]["label"],
            "color": EVENT_TYPES[key]["color"],
            "count": len(patches),
            "totalAreaHa": _r(total),
            "patches": patches[:20],
        })

    total_events = sum(e["count"] for e in events)
    biggest = max(events, key=lambda e: e["totalAreaHa"]) if events else None
    if total_events == 0:
        conclusion = (f"两期之间没有检出超过 {min_area_ha} ha 的突变斑块。"
                      "注意：这只说明没有明显的地表突变，不代表没有缓慢形变")
    else:
        conclusion = (f"检出 {total_events} 处超过 {min_area_ha} ha 的可疑变化，"
                      f"其中以「{biggest['label']}」为主（{biggest['totalAreaHa']} ha）")

    # ---- 可比性提示：间隔太短、云量差异大时，部分"变化"其实是成像条件差异 ----
    warnings: list[str] = []
    try:
        d_a = date.fromisoformat(_scene_brief(scene1)["datetime"])
        d_b = date.fromisoformat(_scene_brief(scene2)["datetime"])
        gap = abs((d_b - d_a).days)
        if gap < 15:
            warnings.append(
                f"两期仅相隔 {gap} 天，小面积斑块多为阈值抖动；建议以 ≥0.5 ha 的斑块为重点")
    except Exception:  # noqa: BLE001
        pass
    c1 = _scene_brief(scene1)["cloudCover"]
    c2 = _scene_brief(scene2)["cloudCover"]
    if abs(c1 - c2) > 10:
        warnings.append(
            f"两期云量差异较大（{c1}% vs {c2}%），薄云与阴影可能被误判为变化，需人工确认")
    if min_area_ha < 0.3:
        warnings.append("当前最小斑块阈值较小，噪声点会明显增多")

    image = _diff_png(ndwi_diff, ndvi_diff, rules) if payload.get("withImage") else None

    return {
        "periods": {
            "first": {**_scene_brief(scene1), "range": list(d1)},
            "second": {**_scene_brief(scene2), "range": list(d2)},
        },
        "events": events,
        "totalEvents": total_events,
        "conclusion": conclusion,
        "warnings": warnings,
        "params": {"maxCloud": max_cloud, "minAreaHa": min_area_ha},
        "grid": {"width": w, "height": h, "pixelAreaHa": _r(px_area_ha, 4)},
        "imageBase64": image,
        "legend": [
            {"label": "新增水体", "color": "#1e88e5"},
            {"label": "水体消失", "color": "#90a4ae"},
            {"label": "新增裸地/扰动", "color": "#d32f2f"},
            {"label": "植被恢复", "color": "#43a047"},
        ],
        "disclaimer": DISCLAIMER,
    }


def math_ceil(v: float) -> float:
    import math
    return math.ceil(v)


def _scene_brief(f: dict) -> dict:
    props = f.get("properties") or {}
    return {
        "id": f.get("id"),
        "datetime": str(props.get("datetime") or "")[:10],
        "cloudCover": round(float(props.get("eo:cloud_cover") or 0), 1),
    }


def _diff_png(ndwi_diff, ndvi_diff, rules) -> str | None:
    """变化专题图：白底 + 四类变化上色"""
    try:
        from PIL import Image
    except ImportError:
        return None

    h, w = ndvi_diff.shape
    rgb = np.full((h, w, 3), 255, dtype=np.uint8)
    # 背景给一点灰度，便于看出 AOI 范围
    rgb[(ndwi_diff == 0) & (ndvi_diff == 0)] = (245, 246, 248)
    paint = {
        "NEW_WATER": (30, 136, 229),
        "LOST_WATER": (144, 164, 174),
        "NEW_BARE": (211, 47, 47),
        "VEG_RECOVERY": (67, 160, 71),
    }
    # 先画面积大的，避免小斑块被覆盖
    for key in ("VEG_RECOVERY", "LOST_WATER", "NEW_BARE", "NEW_WATER"):
        mask = rules.get(key)
        if mask is not None and mask.any():
            rgb[mask] = paint[key]
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

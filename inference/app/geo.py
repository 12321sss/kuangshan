"""AOI 几何小工具（经纬度环 → 外接矩形 / 面积）。

放在这里而不是算法包，是因为它们只服务于路由层入参归一化：
上传解译与在线解译两条链路都要把前端传来的 [[lng,lat],...] 转成
外接矩形（给影像裁剪用）和面积（给报告与回调落库用）。
"""
from __future__ import annotations

from algorithms.classify import ring_area_ha


def aoi_bounds(aoi: list[list[float]] | None) -> tuple[float, float, float, float] | None:
    """从 AOI 环算外接矩形 (west, south, east, north)；点不足 3 个返回 None"""
    if not aoi or len(aoi) < 3:
        return None
    xs = [p[0] for p in aoi]
    ys = [p[1] for p in aoi]
    return (min(xs), min(ys), max(xs), max(ys))


def aoi_area_ha(aoi: list[list[float]] | None) -> float:
    """AOI 面积（公顷），球面近似，与 classify.ring_area_ha 同口径"""
    if not aoi:
        return 0.0
    return round(ring_area_ha(aoi), 4)

"""地形分析：DEM 坡度/坡向/低洼汇水筛查。"""
from __future__ import annotations

import base64

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import dem as dem_mod

router = APIRouter(tags=["terrain"])


# ---------------------------------------------------------------------------
# 地形分析（DEM 接入）：坡度/坡向/低洼汇水
# ---------------------------------------------------------------------------

# 坡度分级配色（与前端图例一致）
_SLOPE_COLORS = [
    (2, (76, 175, 80)),      # <2°   绿
    (6, (174, 213, 129)),    # 2-6°  黄绿
    (15, (255, 213, 79)),    # 6-15° 黄
    (25, (255, 152, 0)),     # 15-25° 橙
    (999, (211, 47, 47)),    # ≥25°  红
]


class TerrainRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="AOI 环 [[lng,lat],...]")
    zoom: int = Field(14, description="DEM 瓦片级别，14≈9.6m/px，15≈4.8m/px")
    withImage: bool = Field(True, alias="with_image", description="是否返回坡度分级 PNG")


def _slope_png(slope: np.ndarray) -> bytes:
    """坡度分级 → PNG（叠加到三维地球做风险专题图底图）"""
    from PIL import Image
    h, w = slope.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for limit, color in _SLOPE_COLORS:
        rgb[slope < limit] = color
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


@router.post("/api/v1/terrain/analyze")
def terrain_analyze(req: TerrainRequest):
    """地形分析：高程统计 + 坡度分级 + 低洼汇水筛查

    精度口径：Terrarium z14 约 9.6m/像元，**不能用于计算台阶坡面角/坑深/体积**；
    可支撑区域坡度、汇水筛查、排土场选址与道路切坡的背景地形判断。
    """
    lngs = [p[0] for p in req.aoi]
    lats = [p[1] for p in req.aoi]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)

    try:
        win = dem_mod.read_dem_window(west, south, east, north,
                                      zoom=max(10, min(req.zoom, 15)), max_dim=512)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DEM 读取失败: {e}") from e

    elev = win["elevation"]
    mpp = win["mPerPixel"]
    slope, aspect = dem_mod.slope_aspect(elev, mpp)
    flow = dem_mod.flow_proxy(slope, elev)
    summary = dem_mod.terrain_summary(elev, slope)

    # 低洼汇水候选：flow 超过 95 分位且坡度平缓（<10°）
    thr = float(np.percentile(flow, 95)) if flow.size else 0.0
    pond = (flow >= max(thr, 1.0)) & (slope < 10)
    pond_pct = round(float(pond.mean()) * 100, 2)

    data: dict = {
        "summary": summary,
        "grid": {"width": int(slope.shape[1]), "height": int(slope.shape[0]),
                 "mPerPixel": round(mpp, 2), "zoom": win["zoom"],
                 "tileCount": win["tileCount"]},
        "pond": {
            "threshold": round(thr, 3),
            "areaPct": pond_pct,
            "note": "低洼汇水候选区：邻域高程显著偏低的平坦区，需结合排水设施与影像复核；"
                    "为筛查指标，非水文模型的汇流累积结果。",
        },
        "precision": {
            "source": f"AWS Terrarium DEM z{win['zoom']}",
            "groundResolutionM": round(mpp, 1),
            "limitation": "10m 级 DEM 不适用于台阶坡面角、坑深、体积计算；"
                          "精细边坡指标需亚米级 DSM（无人机航测或立体像对）。",
        },
    }
    if req.withImage:
        data["slopeImageBase64"] = base64.b64encode(_slope_png(slope)).decode()
        data["legend"] = [
            {"label": "<2° 平坦", "color": "#4caf50"},
            {"label": "2-6° 缓坡", "color": "#aed581"},
            {"label": "6-15° 缓陡", "color": "#ffd54f"},
            {"label": "15-25° 陡坡", "color": "#ff9800"},
            {"label": "≥25° 极陡", "color": "#d32f2f"},
        ]
    return {"code": 0, "message": "success", "data": data}

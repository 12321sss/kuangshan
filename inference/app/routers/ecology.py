"""遥感生态指数 RSEI（绿度/湿度/干度三因子 PCA）。"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algorithms import ecology as ecology_mod
from algorithms import sentinel as aws_sentinel

router = APIRouter(tags=["ecology"])


# ---------------------------------------------------------------------------
# 遥感生态指数 RSEI（三因子：绿度/湿度/干度）
# ---------------------------------------------------------------------------


class RseiRequest(BaseModel):
    model_config = {"populate_by_name": True}

    aoi: list[list[float]] = Field(..., description="AOI 环")
    startDate: str = Field(..., alias="start_date")
    endDate: str = Field(..., alias="end_date")
    maxCloud: float = Field(30.0, alias="max_cloud")
    withImage: bool = Field(True, alias="with_image")
    # 对比期（可选）：传入则返回两期 RSEI 变化统计
    compareStart: str | None = Field(None, alias="compare_start")
    compareEnd: str | None = Field(None, alias="compare_end")


def _rsei_once(feat: dict, aoi: list[list[float]]) -> dict:
    """对单景计算 RSEI：拉 6 个波段（含 B12）→ 掩膜剪切 → PCA"""
    need = ["B02", "B03", "B04", "B08", "B11", "B12"]
    clipped = aws_sentinel.clip_aoi(feat, aoi, need)
    res = ecology_mod.compute_rsei(clipped["bands"])
    stats = ecology_mod.rsei_levels(res["rsei"])
    return {"rsei": res, "stats": stats}


@router.post("/api/v1/ecology/rsei")
def ecology_rsei(req: RseiRequest):
    """遥感生态指数 RSEI 计算（三因子版）。

    口径：Sentinel-2 无热红外波段，采用绿度(NDVI)+湿度(WET)+干度(NDBSI)
    三因子 PCA，**不含热环境维度**，非完整版四因子 RSEI。
    """
    try:
        feat = aws_sentinel.search_scene(req.aoi, req.startDate, req.endDate, req.maxCloud)
        if feat is None:
            return {"code": 404, "message": "该 AOI/日期范围内无可用的无云影像", "data": None}

        cur = _rsei_once(feat, req.aoi)
        data: dict = {
            "sceneId": feat.get("id"),
            "datetime": feat.get("properties", {}).get("datetime"),
            "cloudCover": feat.get("properties", {}).get("eo:cloud_cover"),
            "mean": cur["stats"]["mean"],
            "levels": cur["stats"]["levels"],
            "pc1Weight": cur["rsei"]["pc1Weight"],
            "explainRatio": cur["rsei"].get("explainRatio"),
            "weightLabels": ["绿度 NDVI", "湿度 WET", "干度 NDBSI"],
            "formula": {
                "ndvi": "(B8-B4)/(B8+B4)",
                "wet": "缨帽变换湿度分量（S2 系数）",
                "ndbsi": "(SI+IBI)/2",
                "compose": "三因子归一化 → PCA 第一主成分 → 方向调整 → 归一化到 0~1",
            },
            "precision": {
                "resolution": "10m（Sentinel-2 L2A）",
                "level": "三因子 RSEI-3",
                "limitation": "不含热环境维度：Sentinel-2 无热红外波段，无法反演地表温度 LST。"
                              "完整四因子 RSEI 需融合 Landsat 8/9 B10 热红外，属后续增强项。",
            },
            "reference": "徐涵秋. 城市生态环境质量评价的遥感定量方法——遥感生态指数(RSEI). 生态学报, 2013.",
        }
        if req.withImage:
            data["imageBase64"] = base64.b64encode(
                ecology_mod.rsei_png(cur["rsei"]["rsei"])).decode()

        # 对比期
        if req.compareStart and req.compareEnd:
            feat2 = aws_sentinel.search_scene(
                req.aoi, req.compareStart, req.compareEnd, req.maxCloud)
            if feat2 is not None:
                prev = _rsei_once(feat2, req.aoi)
                data["compare"] = {
                    "sceneId": feat2.get("id"),
                    "datetime": feat2.get("properties", {}).get("datetime"),
                    "mean": prev["stats"]["mean"],
                    "levels": prev["stats"]["levels"],
                    **ecology_mod.compare_rsei(prev["rsei"]["rsei"], cur["rsei"]["rsei"]),
                }
        return {"code": 0, "message": "success", "data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"RSEI 计算失败: {e}") from e

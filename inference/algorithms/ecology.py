"""
遥感生态指数 RSEI（Remote Sensing Ecological Index）

学术依据
--------
徐涵秋. 城市生态环境质量评价的遥感定量方法——遥感生态指数(RSEI)[J]. 生态学报, 2013.
RSEI 用四个指标做主成分分析(PCA)，取第一主成分代表生态综合状况：
  绿度 NDVI、湿度 WET、干度 NDBSI、热度 LST

**本项目的重要限制（必须向客户如实说明）**
--------------------------------------
Sentinel-2 没有热红外波段（B10 是卷云检测波段，不是地表温度），
无法计算 LST，因此本实现采用**三因子 RSEI（绿度 + 湿度 + 干度）**，
记为 RSEI-3。这不是完整版 RSEI，缺少热环境维度。

若需要完整四因子 RSEI，需引入 Landsat 8/9 的 B10（热红外）做温度反演，
两源数据融合会带来配准与尺度问题，属于后续增强项。

指标公式
--------
绿度  NDVI = (B8 - B4) / (B8 + B4)
湿度  WET  = 0.1509*B2 + 0.1973*B3 + 0.3279*B4 + 0.3406*B8 - 0.7112*B11 - 0.4572*B12
            （Sentinel-2 缨帽变换湿度分量，Baig et al. 2014）
干度  NDBSI = (SI + IBI) / 2
      SI  = ((B11+B4)-(B8+B2)) / ((B11+B4)+(B8+B2))          裸土指数
      IBI = (2B11/(B11+B8) - (B8/(B8+B4) + B3/(B3+B11)))
            / (2B11/(B11+B8) + (B8/(B8+B4) + B3/(B3+B11)))    建筑指数

合成
----
三指标归一化 → PCA → 取第一主成分 PC1 → 调整方向使「值大=生态好」
→ RSEI0 = 1 - PC1 → 再归一化到 [0,1]
"""
from __future__ import annotations

from typing import Any

import numpy as np

# RSEI 分级（徐涵秋原文的 5 级划分）
RSEI_LEVELS = [
    (0.2, "差", "#d73027"),
    (0.4, "较差", "#fc8d59"),
    (0.6, "中等", "#fee08b"),
    (0.8, "良", "#a6d96a"),
    (1.01, "优", "#1a9850"),
]


def _norm01(a: np.ndarray) -> np.ndarray:
    """线性拉伸到 0~1（按 2%~98% 分位，避免极值拉偏）"""
    a = a.astype(np.float32)
    if a.size == 0:
        return a
    lo, hi = np.percentile(a, 2), np.percentile(a, 98)
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def _ndvi(b: dict) -> np.ndarray:
    nir = b["B08"].astype(np.float32)
    red = b["B04"].astype(np.float32)
    den = nir + red
    return np.divide(nir - red, den, out=np.zeros_like(nir), where=den != 0)


def _wet(b: dict) -> np.ndarray:
    """缨帽变换湿度分量（Sentinel-2 系数，Baig et al. 2014）"""
    f = {k: v.astype(np.float32) / 10000.0 for k, v in b.items()}
    return (0.1509 * f["B02"] + 0.1973 * f["B03"] + 0.3279 * f["B04"]
            + 0.3406 * f["B08"] - 0.7112 * f["B11"] - 0.4572 * f["B12"])


def _ndbsi(b: dict) -> np.ndarray:
    """干度：裸土指数 SI 与建筑指数 IBI 的均值"""
    f = {k: v.astype(np.float32) / 10000.0 for k, v in b.items()}
    swir1, red, nir, blue, green = f["B11"], f["B04"], f["B08"], f["B02"], f["B03"]

    den_si = (swir1 + red) + (nir + blue)
    si = np.divide((swir1 + red) - (nir + blue), den_si,
                   out=np.zeros_like(swir1), where=den_si != 0)

    a = np.divide(2 * swir1, swir1 + nir, out=np.zeros_like(swir1), where=(swir1 + nir) != 0)
    b1 = np.divide(nir, nir + red, out=np.zeros_like(nir), where=(nir + red) != 0)
    b2 = np.divide(green, green + swir1, out=np.zeros_like(green), where=(green + swir1) != 0)
    den_ibi = a + (b1 + b2)
    ibi = np.divide(a - (b1 + b2), den_ibi, out=np.zeros_like(a), where=den_ibi != 0)

    return (si + ibi) / 2.0


def compute_rsei(bands: dict[str, np.ndarray]) -> dict[str, Any]:
    """计算 RSEI-3（绿度+湿度+干度，PCA 第一主成分）

    返回 rsei 栅格(0~1) 与各指标，供分级统计与专题图渲染。
    """
    ndvi = _ndvi(bands)
    wet = _wet(bands)
    ndbsi = _ndbsi(bands)

    # 三个指标分别归一化（量纲不同，必须统一后再 PCA）
    g = _norm01(ndvi)      # 绿度：越大越好
    w = _norm01(wet)       # 湿度：越大越好
    d = _norm01(ndbsi)     # 干度：越大越差

    # 堆叠为 (像素数, 3)，PCA
    stack = np.stack([g.ravel(), w.ravel(), d.ravel()], axis=1)
    # 去掉无效像元（全 0 的）以免污染协方差
    valid = stack.sum(axis=1) > 0
    if valid.sum() < 10:
        zeros = np.zeros(ndvi.shape, dtype=np.float32)
        return {"rsei": zeros, "ndvi": ndvi, "wet": wet, "ndbsi": ndbsi,
                "pc1Weight": [0, 0, 0], "valid": False}

    x = stack[valid]
    x = x - x.mean(axis=0)
    # 协方差矩阵特征分解（3x3，比 SVD 快且够用）
    cov = np.cov(x, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    idx = np.argsort(eigvals)[::-1]
    pc1_vec = eigvecs[:, idx[0]]
    explain = float(eigvals[idx[0]] / eigvals.sum()) if eigvals.sum() > 0 else 0.0

    pc1 = x @ pc1_vec

    # 方向调整：RSEI 应满足「绿度越高、生态越好」——若 PC1 与绿度负相关则取反
    corr_g = float(np.corrcoef(x[:, 0], pc1)[0, 1]) if pc1.std() > 1e-9 else 0.0
    if corr_g < 0:
        pc1 = -pc1
        pc1_vec = -pc1_vec

    rsei0 = 1.0 - _norm01(pc1)

    full = np.zeros(ndvi.size, dtype=np.float32)
    full[valid] = rsei0
    rsei = _norm01(full).reshape(ndvi.shape)

    return {
        "rsei": rsei,
        "ndvi": ndvi,
        "wet": wet,
        "ndbsi": ndbsi,
        # PC1 各指标权重，用于解释「哪一项主导了生态状况」
        "pc1Weight": [round(float(v), 4) for v in pc1_vec],
        "explainRatio": round(explain, 4),
        "valid": True,
    }


def rsei_levels(rsei: np.ndarray) -> dict[str, Any]:
    """RSEI 分级统计：各等级面积占比 + 均值"""
    if rsei.size == 0:
        return {"mean": 0.0, "levels": []}
    mean = float(np.nanmean(rsei))
    dist = []
    total = rsei.size
    prev = 0.0
    for limit, label, color in RSEI_LEVELS:
        cnt = int(((rsei >= prev) & (rsei < limit)).sum())
        dist.append({
            "label": label,
            "range": f"{prev:.1f}-{min(limit, 1.0):.1f}",
            "pct": round(cnt / total * 100, 2),
            "color": color,
        })
        prev = limit
    return {"mean": round(mean, 4), "levels": dist}


def rsei_png(rsei: np.ndarray) -> bytes:
    """RSEI 分级专题图"""
    import io as _io
    from PIL import Image
    h, w = rsei.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    prev = 0.0
    for limit, _label, color in RSEI_LEVELS:
        rgb[(rsei >= prev) & (rsei < limit)] = tuple(
            int(color[i:i + 2], 16) for i in (1, 3, 5))
        prev = limit
    buf = _io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def compare_rsei(early: np.ndarray, late: np.ndarray) -> dict[str, Any]:
    """两期 RSEI 对比：改善 / 稳定 / 退化 面积占比

    分级差：>+0.05 改善，<-0.05 退化，其余稳定
    """
    if early.shape != late.shape:
        # 尺寸不同时粗配准（最近邻重采样到同一尺寸）
        from PIL import Image as _Img
        late = np.asarray(
            _Img.fromarray((late * 255).astype(np.uint8)).resize(
                (early.shape[1], early.shape[0]), _Img.NEAREST),
            dtype=np.float32) / 255.0

    delta = late - early
    total = delta.size or 1
    improved = float((delta > 0.05).sum()) / total * 100
    degraded = float((delta < -0.05).sum()) / total * 100
    stable = 100 - improved - degraded
    return {
        "earlyMean": round(float(np.nanmean(early)), 4),
        "lateMean": round(float(np.nanmean(late)), 4),
        "deltaMean": round(float(np.nanmean(late) - np.nanmean(early)), 4),
        "improvedPct": round(improved, 2),
        "stablePct": round(stable, 2),
        "degradedPct": round(degraded, 2),
        "verdict": ("生态质量改善" if np.nanmean(delta) > 0.02
                    else "生态质量退化" if np.nanmean(delta) < -0.02
                    else "生态质量基本稳定"),
        "note": "本指标为三因子 RSEI（绿度/湿度/干度），不含热环境维度；"
                "受 Sentinel-2 无热红外波段限制，详细口径见文档。",
    }

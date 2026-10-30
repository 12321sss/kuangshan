"""多源形变速率场融合（NISAR L 波段 × Sentinel-1 C 波段）。

两个数据源互补，各管各的盲区：

- NISAR（L 波段 24cm）：穿透植被，**复绿排土场/尾矿库**仍能测到
- Sentinel-1（C 波段 5.6cm）：裸露地表精度更高，时序更长（12 年）

融合策略（逐像元，按「植被度」与「相干性」双权重）：
  1. 各自归一化相干性作基础权重（谁信噪比高听谁的）
  2. 植被区（NDVI 高）→ 抬高 NISAR 权重、压低 Sentinel-1
  3. 裸露区 → 反过来
  4. 最终速率 = Σ(w_i · v_i) / Σ(w_i)

局限
----
- 融合前提是两个速率场已经过各自的 SBAS + 参考区归零 + 大气校正
- 两源重访/波长不同，融合的是「同区域的长期平均速率」，不是逐期配准
- 若某像元只有一个源有值，则直接用该源（不硬凑）

只依赖 numpy，可被脚本与测试直接调用。
"""
from __future__ import annotations

from typing import Any

import numpy as np


def fuse_velocity_fields(
    vel_a: np.ndarray, coh_a: np.ndarray, band_a: str,
    vel_b: np.ndarray, coh_b: np.ndarray, band_b: str,
    ndvi: np.ndarray | None = None,
) -> dict[str, Any]:
    """融合两个速率场。

    vel_a/vel_b：速率场（mm/yr），NaN 表示无效
    coh_a/coh_b：相干性 0~1（作信噪比权重）
    band_a/band_b：'L' 或 'C'（NISAR / Sentinel-1）
    ndvi：可选，植被指数 0~1（-1~1 可，内部 clip 到 0~1），
          高植被 → L 波段占优

    返回 {velocity, weight_a, weight_b, source, note}
    """
    H, W = vel_a.shape
    # 统一形状（若 b 尺寸不同，需调用方先重采样对齐；这里仅做 NaN 对齐校验）
    if vel_b.shape != (H, W):
        raise ValueError("两个速率场尺寸不一致，请先重采样对齐")

    a_ok = np.isfinite(vel_a) & np.isfinite(coh_a)
    b_ok = np.isfinite(vel_b) & np.isfinite(coh_b)

    # 基础权重 = 相干性（0~1）
    wa = np.where(a_ok, np.clip(coh_a, 0, 1), 0.0)
    wb = np.where(b_ok, np.clip(coh_b, 0, 1), 0.0)

    # 植被度调制：ndvi 高 → L 波段（band_a 若为 L）权重↑
    if ndvi is not None and ndvi.shape == (H, W):
        veg = np.clip(ndvi, 0.0, 1.0)  # 0=裸地, 1=密植被
        # L 波段植被穿透强，权重随植被度放大；C 波段反之
        if band_a.upper() == "L":
            wa = wa * (0.5 + 0.5 * veg)
            wb = wb * (1.0 - 0.5 * veg)
        elif band_b.upper() == "L":
            wb = wb * (0.5 + 0.5 * veg)
            wa = wa * (1.0 - 0.5 * veg)

    total = wa + wb
    vel = np.full((H, W), np.nan, dtype=np.float64)
    both = total > 0
    vel[both] = (wa[both] * vel_a[both] + wb[both] * vel_b[both]) / total[both]

    # 单源覆盖的像元：直接用该源
    only_a = a_ok & ~b_ok
    only_b = b_ok & ~a_ok
    vel[only_a] = vel_a[only_a]
    vel[only_b] = vel_b[only_b]

    # 来源标注（用于前端区分「哪边有数据」）
    source = np.full((H, W), "", dtype="<U8")
    source[both] = "FUSED"
    source[only_a] = band_a.upper()
    source[only_b] = band_b.upper()

    return {
        "velocity_mmyr": vel.astype(np.float32),
        "weight_a": wa.astype(np.float32),
        "weight_b": wb.astype(np.float32),
        "source": source,
        "note": "按相干性加权 + 植被度调制融合；单源覆盖的像元直接用该源",
    }


def decompose_los_to_2d(
    vel_asc: np.ndarray, los_asc: tuple[float, float, float],
    vel_desc: np.ndarray, los_desc: tuple[float, float, float],
) -> dict[str, Any]:
    """升降轨 LOS 位移 → 垂直 + 东西向二维分量。

    单轨只能测视线向(LOS)，升降轨联合可解垂直(V)与东西(E)两个分量。
    南北向因轨道近极地几乎测不到，标记为不可解。

    los_asc / los_desc：升/降轨的单位视线向量 (E, N, U)，已归一化。
    返回 {vertical, east_west, north_south(全 NaN), solved_mask}
    """
    H, W = vel_asc.shape
    a = np.asarray(los_asc, dtype=np.float64)
    d = np.asarray(los_desc, dtype=np.float64)

    # 解方程：los_asc · (E, N, U) = vel_asc
    #         los_desc · (E, N, U) = vel_desc
    # 两个方程三个未知，N 分量不可解（轨道近极地），置 N=0 解 E、U
    A = np.array([[a[0], a[2]],   # E, U 系数（N 项忽略）
                  [d[0], d[2]]])
    if abs(np.linalg.det(A)) < 1e-6:
        raise ValueError("升降轨几何退化，无法分解（LOS 向量近乎平行）")

    A_inv = np.linalg.inv(A)
    east = np.full((H, W), np.nan)
    vert = np.full((H, W), np.nan)
    valid = np.isfinite(vel_asc) & np.isfinite(vel_desc)
    for r in range(H):
        for c in range(W):
            if not valid[r, c]:
                continue
            b = np.array([vel_asc[r, c], vel_desc[r, c]])
            sol = A_inv @ b
            east[r, c] = sol[0]
            vert[r, c] = sol[1]

    return {
        "vertical_mmyr": vert.astype(np.float32),
        "east_west_mmyr": east.astype(np.float32),
        "north_south_mmyr": np.full((H, W), np.nan, dtype=np.float32),
        "solved_mask": valid,
        "note": "垂直+东西向可解；南北向因轨道近极地不可解",
    }

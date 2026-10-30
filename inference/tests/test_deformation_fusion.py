"""多源形变融合的单元测试。"""
from __future__ import annotations

import numpy as np
import pytest

from algorithms.deformation_fusion import decompose_los_to_2d, fuse_velocity_fields


def test_fuse_weights_by_coherence():
    """高相干源应主导融合结果"""
    H, W = 4, 4
    vel_a = np.full((H, W), 10.0)  # NISAR L
    coh_a = np.full((H, W), 0.9)
    vel_b = np.full((H, W), 50.0)  # Sentinel-1 C
    coh_b = np.full((H, W), 0.3)
    res = fuse_velocity_fields(vel_a, coh_a, "L", vel_b, coh_b, "C")
    v = res["velocity_mmyr"]
    # 无植被调制时，权重=相干性，A(0.9) >> B(0.3)，结果接近 10
    assert np.all(v < 25)
    assert np.all(v >= 10)


def test_fuse_vegetation_boosts_l_band():
    """高植被区应让 L 波段权重升高，结果偏向 L 波段的值"""
    H, W = 4, 4
    vel_a = np.full((H, W), 10.0)  # L 波段（NISAR）
    coh_a = np.full((H, W), 0.5)
    vel_b = np.full((H, W), 50.0)  # C 波段（Sentinel-1）
    coh_b = np.full((H, W), 0.5)
    ndvi = np.full((H, W), 1.0)    # 密植被
    res = fuse_velocity_fields(vel_a, coh_a, "L", vel_b, coh_b, "C", ndvi)
    v = res["velocity_mmyr"]
    # 植被调制：L 权重 0.5*(0.5+0.5*1)=0.5，C 权重 0.5*(1-0.5*1)=0.25
    # 融合 = (0.5*10 + 0.25*50)/(0.75) = 23.3，偏向 L 的 10
    assert np.allclose(v, 23.33, atol=0.1)


def test_fuse_single_source_coverage():
    """单源覆盖的像元直接用该源"""
    H, W = 3, 3
    vel_a = np.full((H, W), 10.0)
    coh_a = np.full((H, W), 0.8)
    vel_b = np.full((H, W), 50.0)
    coh_b = np.full((H, W), 0.8)
    vel_b[0, 0] = np.nan  # B 在 (0,0) 无覆盖
    res = fuse_velocity_fields(vel_a, coh_a, "L", vel_b, coh_b, "C")
    assert res["velocity_mmyr"][0, 0] == 10.0  # 直接用 A
    assert res["source"][0, 0] == "L"


def test_decompose_los():
    """升降轨联合解垂直/东西向"""
    H, W = 2, 2
    # 升轨 LOS（向东看）：(E=+0.6, N=0, U=-0.8)（负 U=朝下）
    # 降轨 LOS（向西看）：(E=-0.6, N=0, U=-0.8)
    asc = (0.6, 0.0, -0.8)
    desc = (-0.6, 0.0, -0.8)
    # 纯垂直沉降：LOS 位移 = U 分量 * (-0.8)，若沉降 -10mm → LOS = +8mm（朝卫星）
    vel_asc = np.full((H, W), 8.0)
    vel_desc = np.full((H, W), 8.0)
    res = decompose_los_to_2d(vel_asc, asc, vel_desc, desc)
    # 垂直 = -10 mm（下沉），东西 = 0
    assert np.allclose(res["vertical_mmyr"], -10.0, atol=0.1)
    assert np.allclose(res["east_west_mmyr"], 0.0, atol=0.1)

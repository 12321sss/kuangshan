"""解缠模块的单元测试（纯 Python 部分，不依赖 snaphu）。"""
from __future__ import annotations

import numpy as np
import pytest

from algorithms.unwrap import phase_to_los_mm, to_phase_corr


def _wrapped(phase: np.ndarray) -> np.ndarray:
    """相位 → 复指数（模拟 wrapped 干涉图）"""
    return np.exp(1j * phase).astype(np.complex64)


def test_to_phase_corr_recovers_wrapped_phase():
    """缠绕相位在 [-π,π] 内应被 angle() 精确还原"""
    true = np.array([0.5, -0.5, 1.0, -1.0, 3.0, -3.0], dtype=np.float32)
    wr = _wrapped(true)
    coh = np.ones_like(true)
    mask = np.ones_like(true, dtype=np.uint32)
    ph, c = to_phase_corr(wr, coh, mask)
    # 3.0 和 -3.0 会 wrap 到 [-π,π]，用 np.isclose 对 wrap 后的值
    expected = np.angle(np.exp(1j * true))
    assert np.allclose(ph, expected, atol=1e-6)
    assert np.allclose(c, 1.0)


def test_to_phase_corr_masks_invalid():
    """mask=0 的像元应置 NaN"""
    wr = _wrapped(np.array([0.5, 0.5], dtype=np.float32))
    coh = np.array([0.8, 0.8], dtype=np.float32)
    mask = np.array([1, 0], dtype=np.uint32)
    ph, c = to_phase_corr(wr, coh, mask)
    assert np.isnan(ph[1]) and np.isnan(c[1])
    assert not np.isnan(ph[0])


def test_phase_to_los_mm_matches_sbas():
    """与 sbas 的相位→位移换算一致（同波长口径）"""
    from algorithms.sbas import phase_to_los_mm as sbas_conv
    lam = 299792458.0 / 1.229e9
    ph = np.array([0.0, 1.0, -2.5])
    assert np.allclose(phase_to_los_mm(ph, lam), sbas_conv(ph, lam))

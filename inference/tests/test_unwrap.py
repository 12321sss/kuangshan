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


# ---------------------------------------------------------------------------
# snaphu 可执行文件后端（ESA 官方 Windows 预编译包 / Linux apt 安装）
# ---------------------------------------------------------------------------

def test_find_snaphu_exe_returns_path_or_none():
    """查找函数必须稳定返回 str 或 None，不能抛异常"""
    from algorithms.unwrap import find_snaphu_exe
    p = find_snaphu_exe()
    assert p is None or isinstance(p, str)


@pytest.mark.skipif(
    __import__("algorithms.unwrap", fromlist=["find_snaphu_exe"]).find_snaphu_exe() is None,
    reason="本机未安装 snaphu 可执行文件（Windows 可下 ESA 预编译包，Linux 用 apt）")
def test_unwrap_snaphu_exe_recovers_ramp():
    """snaphu.exe 解缠应还原一个已知的斜坡相位（跨越多个 2π）

    这个用例专门防「格式踩坑」：snaphu 默认输入是 COMPLEX_DATA、输出是
    ALT_LINE_DATA（双通道），若按单通道读写会读到乱码——残差会大到几十 mm。
    """
    import numpy as np
    from algorithms.unwrap import unwrap_snaphu_exe

    # 构造一个跨 ±3π 的斜坡（会缠绕），验证能正确展开
    ny, nx = 40, 50
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
    truth = (xx / nx - 0.5) * 6 * np.pi        # -3π ~ +3π
    wrapped = np.angle(np.exp(1j * truth)).astype(np.float32)
    corr = np.full((ny, nx), 0.9, dtype=np.float32)

    unw = unwrap_snaphu_exe(wrapped, corr)

    # 去常数后应与真值一致（容差 1 个 2π 周期的 1%）
    a = truth - truth.mean()
    b = unw - np.nanmean(unw)
    rms = float(np.sqrt(np.mean((a - b) ** 2)))
    assert rms < 0.2, f"斜坡还原残差过大: {rms:.3f} rad"


@pytest.mark.skipif(
    __import__("algorithms.unwrap", fromlist=["find_snaphu_exe"]).find_snaphu_exe() is None,
    reason="本机未安装 snaphu 可执行文件")
def test_unwrap_auto_prefers_snaphu_exe():
    """装了 snaphu.exe 时，auto 应报告 snaphu-exe 而不是 python"""
    import numpy as np
    from algorithms.unwrap import unwrap_auto

    ny, nx = 20, 24
    ph = np.zeros((ny, nx), dtype=np.float32)
    co = np.full((ny, nx), 0.8, dtype=np.float32)
    _, backend = unwrap_auto(ph, co)
    assert backend in ("snaphu", "snaphu-exe"), f"期望工业级后端，实得 {backend}"

"""纯 Python 解缠后端测试（Windows / Linux 均可跑）。

覆盖点：
  1. 已知线性形变场能否被正确还原（精度）
  2. 低相干区是否被正确屏蔽，且不污染邻域
  3. 全无效输入不崩
  4. 相位→位移换算是否符合波长公式
  5. 合成数据端到端（跑 scripts/unwrap.py 的合成分支，检查产物）

这个后端存在的意义：snaphu 装不上 Windows，原先 C 阶段（20m 解缠）在 Windows 卡死。
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algorithms.unwrap import (  # noqa: E402
    L_BAND_WAVELENGTH_M,
    phase_to_los_mm,
    unwrap_python,
)

ROOT = Path(__file__).resolve().parents[1]


def _wrap(x: np.ndarray) -> np.ndarray:
    """把连续相位缠绕到 [-pi, pi)"""
    return np.angle(np.exp(1j * x))


def test_unwrap_linear_ramp_restores_phase():
    """线性斜坡：解缠后应与真值只差一个 2π 整数倍常数"""
    ny, nx = 100, 140
    yy, xx = np.mgrid[0:ny, 0:nx]
    truth = 0.02 * xx + 0.015 * yy

    out = unwrap_python(_wrap(truth).astype(np.float32),
                        np.full((ny, nx), 0.8, dtype=np.float32))

    assert np.isfinite(out).all()
    diff = out - truth
    resid = diff - np.median(diff)
    # Herráez 对无噪声线性场应几乎精确
    assert np.abs(resid).max() < 1e-3


def test_unwrap_masks_low_coherence_region():
    """低相干区必须为 NaN，且不把噪声扩散到邻域"""
    ny, nx = 120, 140
    yy, xx = np.mgrid[0:ny, 0:nx]
    truth = 0.03 * xx + 0.02 * yy

    phase = _wrap(truth).astype(np.float32)
    rng = np.random.default_rng(0)
    phase[0:40, 0:50] = rng.uniform(-np.pi, np.pi, (40, 50))  # 纯噪声

    corr = np.full((ny, nx), 0.7, dtype=np.float32)
    corr[0:40, 0:50] = 0.01  # 低相干 → 应被屏蔽

    out = unwrap_python(phase, corr)

    assert np.isnan(out[0:40, 0:50]).all(), "低相干区未屏蔽"
    assert np.isfinite(out[40:, 50:]).all(), "邻域被污染"

    # 邻域精度仍要好
    diff = out[40:, 50:] - truth[40:, 50:]
    resid = diff - np.median(diff)
    assert np.abs(resid).max() < 0.05


def test_unwrap_all_invalid_returns_nan():
    """全无效输入不应抛异常"""
    phase = np.full((30, 40), np.nan, dtype=np.float32)
    corr = np.zeros((30, 40), dtype=np.float32)
    out = unwrap_python(phase, corr)
    assert out.shape == (30, 40)
    assert np.isnan(out).all()


def test_phase_to_los_uses_l_band_wavelength():
    """位移换算口径：ΔR = φ·λ/(4π)，因此一个完整条纹（2π）对应单程位移 λ/2。

    推导：雷达是双程观测，相位 φ = 4π/λ·ΔR（ΔR 为单程距离变化），
    所以 φ 走完 2π（一个条纹）时，ΔR = λ/2，不是 λ/4。
    与 algorithms/sbas.phase_to_los_mm 口径一致（同一公式，测试保证两处不漂移）。
    """
    one_cycle = np.array([2 * math.pi], dtype=np.float32)
    disp_mm = phase_to_los_mm(one_cycle)
    expect = L_BAND_WAVELENGTH_M / 2 * 1000  # λ/2
    assert disp_mm[0] == pytest.approx(expect, rel=1e-5)
    # L 波段（1.229 GHz）λ≈244mm，一个条纹对应约 122mm 单程位移
    assert 115 < disp_mm[0] < 130


def test_synthetic_end_to_end_writes_products(tmp_path):
    """跑 scripts/unwrap.py --synthetic，确认三份 GeoTIFF + 元数据都被写出且可读"""
    out_dir = tmp_path / "unwrapped"
    cmd = [sys.executable, str(ROOT / "scripts" / "unwrap.py"),
           "--synthetic", "--backend", "python", "--out", str(out_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 0, f"脚本失败：{r.stdout}\n{r.stderr}"

    for name in ("unwrapped_phase.tif", "los_disp_mm.tif", "coherence.tif"):
        assert (out_dir / name).exists(), f"缺产物 {name}"

    import json

    import rasterio

    with rasterio.open(out_dir / "los_disp_mm.tif") as ds:
        assert ds.crs.to_epsg() == 4326
        assert ds.width == 320 and ds.height == 240
        arr = ds.read(1)
        assert np.isfinite(arr).sum() > 0

    meta = json.loads((out_dir / "unwrap_meta.json").read_text(encoding="utf-8"))
    assert meta["backend"] == "python"
    assert meta["validPixels"] > 0
    assert "dispStats" in meta

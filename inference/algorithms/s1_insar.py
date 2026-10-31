"""Sentinel-1 SLC → isce2 topsApp 干涉处理封装。

职责：把「两景 SLC SAFE 目录」变成「可执行的 topsApp 配置」，并在其后解析产物。
不直接调用 topsApp 的 Python API（那个 API 状态化、难并行），而是生成标准 XML
交给 topsApp 命令行执行 —— 这是 isce2 官方推荐做法，也便于把处理过程放进队列。

为什么单独成模块而不是塞进脚本：
  配置生成有十几个参数（极化、ROI、DEM、解缠、多视），后续会被 API 和批处理复用；
  放在 algorithms/ 可以单测，脚本只做 CLI 薄包装。

平台约束（WSL 实测）：
  - isce2 在 conda 环境 ~/.mamba/envs/isce，topsApp.py 在
    .../site-packages/isce/applications/topsApp.py
  - snaphu 用系统 /usr/bin/snaphu（apt 装的），isce 环境里可直接调用
  - WSL 访问不了 GitHub/外网，DEM 必须由外部提供（demfilename），
    不能依赖 isce2 自动下载
"""
from __future__ import annotations

import os
from pathlib import Path
from xml.sax.saxutils import escape


def build_topsapp_xml(
    ref_safe: str | Path,
    sec_safe: str | Path,
    work_dir: str | Path,
    *,
    polarization: str = "VV",
    dem_file: str | Path | None = None,
    roi: tuple[float, float, float, float] | None = None,
    unwrap: bool = True,
    output_name: str = "topsapp.xml",
) -> Path:
    """生成 topsApp 输入 XML。

    参数
    ----
    ref_safe / sec_safe：两景 SLC 的 .SAFE 目录（时间早的作 reference）
    work_dir：处理目录（所有中间产物落在这里）
    polarization：极化，S1 IW 常用 VV
    dem_file：本地 DEM（WSL 无法自动下载 DEM，必须给）
    roi：(south, north, west, east) 度；给定时只处理该窗口，大幅省内存和时间
    unwrap：是否做解缠（验证链路时开，只看干涉图可关）

    返回：生成的 XML 路径
    """
    # 重要：WSL 路径（/mnt/c/...）必须以 **str** 传入。
    # 若传 Path，Windows 的 WindowsPath 会把 '/' 规范化成 '\'，生成
    # \mnt\c\... 这种坏路径。所以这里用 str() 而不是 Path()。
    work_s = str(work_dir)
    # WSL 路径（/mnt/...）不能在 Windows 侧 mkdir，交给 WSL 侧或 isce2 自己建
    if not work_s.startswith("/mnt/"):
        Path(work_s).mkdir(parents=True, exist_ok=True)

    props: list[str] = [
        '<property name="Sensor name">SENTINEL1</property>',
    ]
    if roi is not None:
        s, n, w, e = roi
        # topsApp 的 regionOfInterest 顺序是 [south, north, west, east]
        # isce2 的 XML 属性名用 public_name（带空格），不是内部变量名
        props.append(
            f'<property name="region of interest">[{s}, {n}, {w}, {e}]</property>')
    if dem_file is not None:
        # 注意是大写 F 的 demFilename，isce2 的 public_name 就是这么写的
        props.append(f'<property name="demFilename">{escape(str(dem_file))}</property>')
    props.append(f'<property name="do unwrap">{"True" if unwrap else "False"}</property>')
    # 多视：TOPS 干涉常用 range looks=5 / azimuth looks=1（20m×5m 原始 → 100m 网格）
    # 保持默认不显式设置，isce2 会按 S1 IW 的默认值处理
    #
    # 注意：isce2 的 XML 属性名是 public_name（'do unwrap'、'region of interest'、
    # 'demFilename'），与内部变量名（do_unwrap / regionOfInterest / demfilename）不同。
    # 写内部名会报 "attribute ... is not present in the object"，已踩过。

    xml = f"""<topsApp>
  <component name="topsinsar">
    {chr(10).join("    " + p for p in props)}
    <component name="reference">
      <property name="safe">{escape(str(ref_safe))}</property>
      <property name="output directory">reference</property>
      <property name="polarization">{polarization}</property>
    </component>
    <component name="secondary">
      <property name="safe">{escape(str(sec_safe))}</property>
      <property name="output directory">secondary</property>
      <property name="polarization">{polarization}</property>
    </component>
  </component>
</topsApp>
"""
    out = Path(work_s) / output_name
    out.write_text(xml, encoding="utf-8")
    return out


def find_products(work_dir: Path) -> dict[str, list[Path]]:
    """扫描 topsApp 产物，按类型归类。

    产物目录结构（isce2 标准）：
      work_dir/reference/    参考影像
      work_dir/secondary/    从影像
      work_dir/interferograms/*/filt_topophase.unw.geo  解缠相位（地理编码）
      work_dir/interferograms/*/filt_topophase.flat.geo 滤波后干涉图
      work_dir/interferograms/*/coherence_*.geo         相干性
      work_dir/merged/       merged 产品
    """
    out: dict[str, list[Path]] = {
        "unwrapped": [], "wrapped": [], "coherence": [], "other": [],
    }
    if not work_dir.exists():
        return out
    for p in work_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if "unw" in name and ("phase" in name or name.endswith(".unw") or ".unw." in name):
            out["unwrapped"].append(p)
        elif "coherence" in name:
            out["coherence"].append(p)
        elif "phase" in name or "interferogram" in name:
            out["wrapped"].append(p)
        elif p.suffix.lower() in (".tif", ".unw", ".int", ".cor", ".xml"):
            out["other"].append(p)
    for k in out:
        out[k].sort()
    return out

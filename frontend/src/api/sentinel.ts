import axios from 'axios'

/** Sentinel-2 遥感提取服务客户端（走 /sentinel 代理 → inference 8000） */
const sentinel = axios.create({ baseURL: '/sentinel', timeout: 600000 })

export interface SceneInfo {
  scene_id: string
  datetime: string
  cloud_cover: number
}

export interface ExtractResult {
  class: string
  /** 中文类别名（七类矿山地物） */
  label?: string
  threshold: number
  coverage_pct: number
  feature_count: number
  features: Array<{
    type: 'Feature'
    properties: {
      id: number
      classType?: string
      /** 面积（平方米 / 公顷）—— 采坑形态分析用 */
      areaM2?: number
      areaHa?: number
      perimeterM?: number
      /** 最小外接矩形长宽比（道路 ≫ 2，面状地物 ≈ 1） */
      aspectRatio?: number
      /** 紧凑度 4πA/P² */
      compactness?: number
    }
    geometry: any
  }>
  scene_id: string
  datetime: string
  cloud_cover: number
  /** 判别方法说明（如"低植被+非水体+相对偏暗"） */
  method?: string
  /** 方法局限声明（采坑/排土场/尾矿光谱重叠时给出） */
  disclaimer?: string
  /** 未检出时的原因提示 */
  hint?: string
  /** 诊断量（NDVI/亮度分位数等） */
  diagnostics?: Record<string, any>
  /** 形态统计：总面积/最大斑块/平均长宽比/形态剔除数 */
  shapeStats?: {
    totalAreaHa: number
    maxAreaHa: number
    avgAspectRatio: number
    droppedByShape: number
  }
}

export interface PreviewResult extends SceneInfo {
  image_base64: string
  /** 本次渲染用的波段组合 */
  combo?: string
}

export interface DiffHeatmapResult {
  added: Array<{ type: string; properties: any; geometry: any }>
  removed: Array<{ type: string; properties: any; geometry: any }>
  unchanged: Array<{ type: string; properties: any; geometry: any }>
  addedAreaHa: number
  removedAreaHa: number
}

export const sentinelApi = {
  /** 检索影像（不下载数据），返回景信息 */
  search(aoi: number[][], startDate: string, endDate: string, maxCloud = 30): Promise<SceneInfo> {
    return sentinel
      .post('/api/v1/sentinel/search', { aoi, start_date: startDate, end_date: endDate, max_cloud: maxCloud })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 真彩预览：AOI 剪切后的 RGB PNG（base64） */
  preview(aoi: number[][], startDate: string, endDate: string, maxCloud = 30, combo = 'TRUE_COLOR'): Promise<PreviewResult> {
    return sentinel
      .post('/api/v1/sentinel/preview', { aoi, start_date: startDate, end_date: endDate, max_cloud: maxCloud, combo })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 指数提取：返回矢量化 GeoJSON */
  extract(aoi: number[][], startDate: string, endDate: string, classType: string, maxCloud = 30, threshold?: number, minAreaPx = 20): Promise<ExtractResult> {
    return sentinel
      .post('/api/v1/sentinel/extract', {
        aoi, start_date: startDate, end_date: endDate,
        class_type: classType, max_cloud: maxCloud, threshold, min_area_px: minAreaPx
      })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 多期对比热力图：两期矢量空间求差 → 新增/消失/不变 */
  diffHeatmap(early: any[], late: any[]): Promise<DiffHeatmapResult> {
    return sentinel
      .post('/api/v1/sentinel/diff-heatmap', { early, late })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 导出 GeoTIFF：AOI 影像 + 提取掩膜打包成单波段 GeoTIFF */
  exportGeoTiff(params: {
    aoi: number[][]
    startDate: string
    endDate: string
    classType: string
    maxCloud: number
  }): Promise<{ filename: string; tif_base64: string }> {
    return sentinel
      .post('/api/v1/sentinel/export-geotiff', {
        aoi: params.aoi,
        start_date: params.startDate,
        end_date: params.endDate,
        class_type: params.classType,
        max_cloud: params.maxCloud
      })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 生成离线演示数据包（预下载影像 + 预生成多类解译结果） */
  demoBundle(params: {
    aoi: number[][]
    startDate: string
    endDate: string
    maxCloud?: number
    classes?: string[]
  }): Promise<any> {
    return sentinel
      .post('/api/v1/sentinel/demo-bundle', {
        aoi: params.aoi,
        start_date: params.startDate,
        end_date: params.endDate,
        max_cloud: params.maxCloud,
        classes: params.classes
      })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  },
  /** 读取已生成的离线演示包（断网时也能读） */
  getDemoBundle(bundleId: string): Promise<any> {
    return sentinel
      .get(`/api/v1/sentinel/demo-bundle/${bundleId}`)
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message)
        return r.data.data
      })
  }
}

/** 地形分析结果（DEM 坡度/汇水） */
export interface TerrainResult {
  summary: {
    elevMin: number
    elevMax: number
    elevMean: number
    reliefM: number
    slopeMean: number
    slopeMax: number
    slopeP90: number
    steepPct: number
    distribution: Array<{ label: string; pct: number }>
  }
  grid: { width: number; height: number; mPerPixel: number; zoom: number; tileCount: number }
  pond: { threshold: number; areaPct: number; note: string }
  precision: { source: string; groundResolutionM: number; limitation: string }
  slopeImageBase64?: string
  legend?: Array<{ label: string; color: string }>
}

export const terrainApi = {
  /** 地形分析：高程/坡度/低洼汇水（DEM 来自 AWS Terrarium，约 10m） */
  analyze(aoi: number[][], zoom = 14, withImage = true): Promise<TerrainResult> {
    return sentinel
      .post('/api/v1/terrain/analyze', { aoi, zoom, with_image: withImage }, { timeout: 180000 })
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message || '地形分析失败')
        return r.data.data
      })
  }
}

/** 报告生成：基于数据库真实统计生成 Word 报告（走 /sentinel 代理 → inference） */
export const reportApi = {
  generate(data: {
    projectName: string
    timeseries: any[]
    summary: any[]
    forecast: any
    sensorOnline: number
    sensorAlarm: number
  }): Promise<{ filename: string; docx_base64: string }> {
    return sentinel
      .post('/api/v1/report/generate', data)
      .then((r) => {
        if (r.data.code !== 0) throw new Error(r.data.message || '报告生成失败')
        return r.data.data
      })
  }
}

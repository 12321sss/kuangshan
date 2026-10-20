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
  threshold: number
  coverage_pct: number
  feature_count: number
  features: Array<{
    type: 'Feature'
    properties: { id: number }
    geometry: any
  }>
  scene_id: string
  datetime: string
  cloud_cover: number
}

export interface PreviewResult extends SceneInfo {
  image_base64: string
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
  preview(aoi: number[][], startDate: string, endDate: string, maxCloud = 30): Promise<PreviewResult> {
    return sentinel
      .post('/api/v1/sentinel/preview', { aoi, start_date: startDate, end_date: endDate, max_cloud: maxCloud })
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
  }
}

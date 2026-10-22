import http from './http'
import type {
  AdminUser, Alarm, AreaTimeseriesResult, CrsOption, DisplacementSeries, Extraction, Imagery,
  InterpretTask, OverviewStats, PermCatalog, PitForecast, PitYearly, Project, Role, SafetyEvaluation,
  AvailabilityResult, AoiOption, ChangeEventsResult, ClassifySample, SceneItem, ScreenSummary,
  Sensor, SensorDataPoint, SlopeUnitsResult, SpatialRelationsResult, Station, SupervisedResult,
  TimeSeriesFrame,
  TimeSeriesGroup, VegetationYearly, WarningRule
} from './types'

/** 业务 API 集中定义（认证相关走 stores/auth.ts 直连）
 *  数据中台：列表类接口都带 projectId，按当前选中项目过滤 */

export const projectApi = {
  list: (): Promise<Project[]> => http.get('/projects'),
  get: (id: number): Promise<Project> => http.get(`/projects/${id}`),
  create: (p: Partial<Project>): Promise<Project> => http.post('/projects', p),
  update: (id: number, p: Partial<Project>): Promise<Project> => http.put(`/projects/${id}`, p),
  remove: (id: number): Promise<void> => http.delete(`/projects/${id}`),
  setMembers: (id: number, members: string[]): Promise<Project> =>
    http.put(`/projects/${id}/members`, members),
  /** 合规边界：矿权红线/扰动边界/生态红线（GeoJSON 字符串） */
  boundary: (id: number): Promise<string> => http.get(`/projects/${id}/boundary`)
}

export const sensorApi = {
  list: (projectId?: number): Promise<Sensor[]> =>
    http.get('/sensors', { params: { projectId } }),
  data: (id: string, hours = 24): Promise<SensorDataPoint[]> =>
    http.get(`/sensors/${id}/data`, { params: { hours } }),
  displacement: (id: string, hours = 24): Promise<DisplacementSeries> =>
    http.get(`/sensors/${id}/displacement`, { params: { hours } }),
  /** 导出传感器历史数据 CSV（axios 拿 blob，令牌走拦截器） */
  exportCsv: (id: string, hours = 168): Promise<Blob> =>
    http.get(`/sensors/${encodeURIComponent(id)}/export`, {
      params: { hours },
      responseType: 'blob',
      transformResponse: [(d) => d]
    }) as unknown as Promise<Blob>
}

export const taskApi = {
  list: (projectId?: number): Promise<InterpretTask[]> =>
    http.get('/tasks', { params: { projectId } }),
  get: (id: number): Promise<InterpretTask> => http.get(`/tasks/${id}`),
  create: (req: { name: string; projectId: number; algoType: string; imageName?: string }): Promise<InterpretTask> =>
    http.post('/tasks', req),
  remove: (id: number): Promise<void> => http.delete(`/tasks/${id}`)
}

export const overviewApi = {
  stats: (projectId?: number): Promise<OverviewStats> =>
    http.get('/overview/stats', { params: { projectId } })
}

export const alarmApi = {
  list: (projectId?: number): Promise<Alarm[]> => http.get('/alarms', { params: { projectId } }),
  ack: (id: number): Promise<Alarm> => http.post(`/alarms/${id}/ack`),
  resolve: (id: number, handledBy: string, handleComment: string): Promise<Alarm> =>
    http.post(`/alarms/${id}/resolve`, { handledBy, handleComment })
}

export const warningApi = {
  list: (): Promise<WarningRule[]> => http.get('/warning-rules'),
  update: (rule: WarningRule): Promise<WarningRule> => http.put(`/warning-rules/${rule.id}`, rule)
}

export const stationApi = {
  list: (projectId?: number): Promise<Station[]> => http.get('/stations', { params: { projectId } }),
  create: (s: Partial<Station>): Promise<Station> => http.post('/stations', s),
  update: (id: string, s: Partial<Station>): Promise<Station> => http.put(`/stations/${id}`, s),
  remove: (id: string): Promise<void> => http.delete(`/stations/${id}`)
}

export const analysisApi = {
  /** 可选分析区（来自「边界管理」导入的边界，含外环） */
  aoiOptions: (projectId: number): Promise<{ options: AoiOption[]; permitAreaNote?: string }> =>
    http.get('/analysis/aoi-options', { params: { projectId } }),

  /** 监督分类：选样本 → 随机森林 → 混淆矩阵/OA/Kappa */
  classifySupervised: (body: {
    projectId: number
    aoi?: number[][]
    samples: ClassifySample[]
    start: string
    end: string
    maxCloud?: number
    maxDim?: number
    minSamples?: number
  }): Promise<SupervisedResult> =>
    http.post('/analysis/classify-supervised', body, { timeout: 420000 }),

  /** L1：最近 N 天影像可用性 */
  monitorAvailability: (body: {
    projectId: number
    aoi?: number[][]
    days?: number
    maxCloud?: number
  }): Promise<AvailabilityResult> =>
    http.post('/analysis/monitor-availability', body, { timeout: 120000 }),

  /** L2：两期突变事件检测 */
  changeEvents: (body: {
    projectId: number
    aoi?: number[][]
    d1Start: string
    d1End: string
    d2Start: string
    d2End: string
    maxCloud?: number
    minAreaHa?: number
    withImage?: boolean
  }): Promise<ChangeEventsResult> =>
    http.post('/analysis/change-events', body, { timeout: 420000 }),

  /**
   * 趋势研判（B4）+ 持续复绿判定（C3）
   * 结论口径：扰动扩张/收缩、植被"持续复绿"（不等于生态修复成功）
   */
  trendJudgement: (projectId?: number): Promise<{
    available: boolean
    message?: string
    periods?: Array<{ period: string; disturbHa: number; pitHa: number; vegHa: number; byType: Record<string, number> }>
    disturbTrend?: {
      prevPeriod?: string
      lastPeriod?: string
      prevHa?: number
      lastHa?: number
      deltaHa?: number
      deltaPct?: number | null
      direction: string
      overallDeltaHa?: number
      firstPeriod?: string
      note?: string
    }
    regreening?: Array<{
      signature: string
      periodCount: number
      upStreak: number
      growthPct: number | null
      verdict: string
      note: string
      series: Array<{ period: string; areaHa: number }>
    }>
    conclusion?: string
    hint?: string
  }> => http.get('/analysis/trend-judgement', { params: { projectId } }),
  /**
   * 空间关系与专项风险：坑内积水 / 尾矿水面 / 排土场汇流 / 道路切坡 / 生态缓冲区 / 采坑形态
   * 六项全部由现成图层 + DEM 叠加得出，不依赖外部数据
   */
  spatialRelations: (projectId?: number, bufferKm = 2, slopeCutDeg = 15): Promise<SpatialRelationsResult> =>
    http.post('/analysis/spatial-relations', null, {
      params: { projectId, bufferKm, slopeCutDeg },
      timeout: 180000
    }),
  /** 地物面积时序（真实解译结果按日期聚合） */
  /**
   * 地物面积时序（存量口径）
   * granularity: month 按月（默认）/ year 按年；同一区域同一期多次提取只取最新一次
   */
  areaTimeseries: (params?: {
    projectId?: number
    classType?: string
    granularity?: 'month' | 'year'
  }): Promise<AreaTimeseriesResult> =>
    http.get('/analysis/area-timeseries', { params }),
  /** 采坑趋势外推（含免责声明与不确定性带宽，非实测） */
  pitForecast: (projectId?: number): Promise<PitForecastResult> =>
    http.get('/analysis/pit-forecast', { params: { projectId } }),
  /** 变化概览（各类地物面积与记录数） */
  changeSummary: (projectId?: number): Promise<ChangeSummary> =>
    http.get('/analysis/change-summary', { params: { projectId } }),
  /** 检测面积突变：环比超阈值生成趋势告警 */
  checkTrends: (projectId?: number, thresholdPct = 20): Promise<{
    triggered: any[]; thresholdPct: number; comparableGroups?: number; message: string
  }> => http.post('/analysis/check-trends', null, { params: { projectId, thresholdPct } }),
  /** 单区域纵向体检：某块地全类型的历年变化 */
  aoiProfile: (projectId?: number, signature?: string): Promise<{
    signature: string | null
    classCount?: number
    recordCount?: number
    totalAreaHa: number
    message?: string
    note?: string
    classes: Array<{
      classType: string
      latestAreaHa: number
      latestDate?: string
      periodCount: number
      series: Array<{ date: string; areaHa: number }>
    }>
    timeline: Array<{ date: string; totalAreaHa: number; changeHa: number }>
  }> => http.get('/analysis/aoi-profile', { params: { projectId, signature } }),

  /**
   * 开采安全风险评估（六维评分 + 风险分级图 + 热点清单）
   * @param withSlope 是否先用边坡单元细化形态维度（会多花 10–30 秒，但更贴近实际）
   * 口径：潜在安全风险筛查，不是边坡稳定性评价，不给安全系数
   */
  safetyEvaluate: (projectId?: number, withGrid = true, withSlope = false): Promise<SafetyEvaluation> =>
    http.post('/analysis/safety-evaluate', null, {
      params: { projectId, withGrid, withSlope },
      timeout: 300000
    }),

  /** 安全评估元信息（可用记录数提示） */
  safetyMeta: (projectId?: number): Promise<{ recordCount: number; hint: string }> =>
    http.get('/analysis/safety-latest-meta', { params: { projectId } }),

  /**
   * 边坡单元识别与三区扰动（切脚/削坡/堆载）
   * 口径：潜在失稳风险筛查，不构成边坡稳定性评价
   */
  slopeUnits: (projectId?: number): Promise<SlopeUnitsResult> =>
    http.post('/analysis/slope-units', null, { params: { projectId }, timeout: 240000 }),
  /** @deprecated 旧硬编码接口已随 AnalysisController 重写移除 */
  pitYearlyOld: (projectId?: number): Promise<PitYearly[]> =>
    http.get('/analysis/pit-yearly', { params: { projectId } }),
}

export const screenApi = {
  summary: (projectId: number): Promise<ScreenSummary> =>
    http.get('/screen/summary', { params: { projectId } })
}

export const userApi = {
  list: (): Promise<AdminUser[]> => http.get('/users'),
  options: (): Promise<{ username: string; displayName: string }[]> => http.get('/users/options'),
  create: (u: { username: string; displayName: string; password: string; phone?: string; role: string }): Promise<AdminUser> =>
    http.post('/users', u),
  update: (username: string, u: { displayName: string; phone?: string; role: string; status: string; newPassword?: string }): Promise<AdminUser> =>
    http.put(`/users/${username}`, u),
  remove: (username: string): Promise<void> => http.delete(`/users/${username}`)
}

export const roleApi = {
  list: (): Promise<Role[]> => http.get('/roles'),
  catalog: (): Promise<PermCatalog> => http.get('/roles/catalog'),
  create: (r: Partial<Role>): Promise<Role> => http.post('/roles', r),
  update: (code: string, r: Partial<Role>): Promise<Role> => http.put(`/roles/${code}`, r),
  remove: (code: string): Promise<void> => http.delete(`/roles/${code}`)
}

export const extractionApi = {
  list: (projectId?: number): Promise<Extraction[]> => http.get('/extractions', { params: { projectId } }),
  get: (id: number): Promise<Extraction> => http.get(`/extractions/${id}`),
  /** 提交真实解译任务（选影像 + 圈 AOI + 选类别），返回 inference taskId */
  submit: (req: {
    projectId: number
    imageryId: number
    name?: string
    classType: string
    aoi: number[][]
    /** 上传影像需指定数据源（GF2/GF7）决定波段映射 */
    satellite?: string
  }): Promise<{ taskId: string; status: string }> => http.post('/extractions/submit', req),
  /** 提交在线 Sentinel-2 解译（无需本地影像，AWS STAC 在线拉景） */
  submitOnline: (req: {
    projectId: number
    name?: string
    classType: string
    aoi: number[][]
    startDate: string
    endDate: string
    maxCloud?: number
    threshold?: number
    minAreaPx?: number
  }): Promise<{ taskId: string; status: string }> => http.post('/extractions/submit-online', req),
  /** 直接保存前端已算好的解译结果（遥感提取页用） */
  save: (req: {
    projectId: number
    name?: string
    classType: string
    features: number[][][]
    aoiJson: string
    coveragePct: number
    aoiAreaHa: number
    acquisitionDate?: string
    satellite?: string
  }): Promise<Extraction> => http.post('/extractions/save', req),
  /** 删除到回收站（软删除，可还原） */
  remove: (id: number): Promise<void> => http.delete(`/extractions/${id}`),
  /** 回收站列表 */
  trash: (projectId?: number): Promise<Extraction[]> =>
    http.get('/extractions/trash', { params: { projectId } }),
  /** 从回收站还原 */
  restore: (id: number): Promise<Extraction> => http.post(`/extractions/${id}/restore`),
  /** 彻底删除（不可恢复） */
  purge: (id: number): Promise<void> => http.delete(`/extractions/${id}/purge`),
  /** 某影像关联的解译记录数 */
  countByImagery: (imageryId: number): Promise<number> =>
    http.get('/extractions/count-by-imagery', { params: { imageryId } }),
  /** 影像删除时级联把关联解译记录放入回收站 */
  trashByImagery: (imageryId: number): Promise<number> =>
    http.post('/extractions/trash-by-imagery', null, { params: { imageryId } })
}

export const imageryApi = {
  list: (params?: { projectId?: number; source?: string }): Promise<Imagery[]> =>
    http.get('/imagery', { params }),
  get: (id: number): Promise<Imagery> => http.get(`/imagery/${id}`),
  /** 可选坐标系列表（上传时选择） */
  crsOptions: (): Promise<CrsOption[]> => http.get('/imagery/crs-options'),
  /** 更新影像档案元数据（离轴角/正射等级/授权范围/供应商等 12 项） */
  updateMetadata: (id: number, meta: Record<string, any>): Promise<Imagery> =>
    http.put(`/imagery/${id}/metadata`, meta),
  /** 检索 Sentinel-2 公开场景
   *  实测后端转发 Copernicus 需 20-30 秒（跨境 + 云量属性过滤），
   *  必须单独给更长超时，否则会被全局 15s 掐断并误报「网络异常」 */
  searchScenes: (params: {
    lng: number
    lat: number
    start: string
    end: string
    maxCloud: number
  }): Promise<SceneItem[]> =>
    http.get('/imagery/scenes/search', { params, timeout: 90000 }),
  /** 上传高分影像（multipart），坐标系由用户选择 */
  upload: (req: {
    file: File
    projectId?: number
    name?: string
    crs: string
    acquisitionDate: string
    resolutionM?: number
    bounds: number[]
  }): Promise<Imagery> => {
    const fd = new FormData()
    fd.append('file', req.file)
    if (req.projectId !== undefined) fd.append('projectId', String(req.projectId))
    if (req.name) fd.append('name', req.name)
    fd.append('crs', req.crs)
    fd.append('acquisitionDate', req.acquisitionDate)
    if (req.resolutionM !== undefined) fd.append('resolutionM', String(req.resolutionM))
    // bounds 重复参数：Spring 的 List<Double> 接多值
    req.bounds.forEach((b) => fd.append('bounds', String(b)))
    // 去掉默认的 JSON Content-Type，让浏览器自己带 multipart boundary
    return http.post('/imagery/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000
    })
  },
  /** 登记一景公开数据到影像库 */
  registerPublic: (req: {
    projectId: number
    name: string
    source: string
    productId: string
    acquisitionDate: string
    cloudCover?: number
    resolutionM?: number
    bounds: number[]
    note?: string
  }): Promise<Imagery> => http.post('/imagery/register-public', req),
  remove: (id: number): Promise<void> => http.delete(`/imagery/${id}`),
  /** 切换收藏（不传 value 则取反） */
  toggleFavorite: (id: number, value?: boolean): Promise<Imagery> =>
    http.put(`/imagery/${id}/favorite`, null, { params: { value } })
}

export const timeSeriesApi = {
  /** 按 AOI 指纹分组的时序列表（期数多的排前面） */
  groups: (projectId?: number): Promise<TimeSeriesGroup[]> =>
    http.get('/timeseries/groups', { params: { projectId } }),
  /** 某个 AOI 的完整时序序列（按日期升序，含几何） */
  sequence: (signature: string): Promise<TimeSeriesFrame[]> =>
    http.get(`/timeseries/${signature}`)
}

/** 全局搜索：聚合工程/影像/解译/告警 */
export const searchApi = {
  global: (keyword: string): Promise<Array<{ type: string; typeLabel: string; name: string; path: string }>> =>
    http.get('/search', { params: { keyword } })
}

/** 操作日志审计 */
export const auditApi = {
  list: (limit = 200): Promise<Array<{
    id: number; username: string; action: string; entityType: string
    entityRef: string; detail: string; ip: string; createdAt: string
  }>> => http.get('/audit-logs', { params: { limit } })
}

/** 数据字典 */
export const dictApi = {
  list: (category?: string): Promise<Array<{
    id: number; category: string; code: string; label: string; color?: string; sortOrder: number
  }>> => http.get('/dict', { params: { category } }),
  update: (id: number, req: { label?: string; color?: string; sortOrder?: number }) =>
    http.put(`/dict/${id}`, req)
}

/** 依赖健康检查 */
export const healthApi = {
  checks: (): Promise<{
    items: Array<{ name: string; target: string; ok: boolean; error?: string; latencyMs: number }>
    okCount: number
    total: number
    allOk: boolean
  }> => http.get('/health/checks', { timeout: 20000 })
}

/** 访客分享链接 */
export const shareApi = {
  create: (projectId: number, validDays = 7): Promise<{ token: string; projectName: string; expiresAt: string; path: string }> =>
    http.post('/share', { projectId, validDays }),
  list: (projectId: number): Promise<Array<{ id: number; token: string; createdBy: string; createdAt: string; expiresAt: string; revoked: boolean }>> =>
    http.get('/share', { params: { projectId } }),
  revoke: (id: number): Promise<void> => http.delete(`/share/${id}`),
  /** 只读访问（匿名，无需登录） */
  view: (token: string): Promise<{
    projectName: string; region: string; expiresAt: string; recordCount: number
    classes: Array<{ classType: string; totalAreaHa: number; recordCount: number }>
    records: Array<{ name: string; classType: string; date: string; areaHa: number; coveragePct: number }>
    note: string
  }> => http.get(`/share/view/${token}`)
}

/** AOI 监测订阅：圈一次关注区，持续跟踪该区域的地物变化 */
export const aoiWatchApi = {
  list: (projectId: number): Promise<Array<{
    id: number
    name: string
    classType: string
    aoiJson: string
    signature: string | null
    createdAt: string
    lastCheckAt: string | null
    periodCount: number
    latestDate?: string | null
    latestAreaHa?: number | null
    latestCoveragePct?: number | null
  }>> => http.get('/aoi-watch', { params: { projectId } }),

  create: (req: { projectId: number; name?: string; aoi: number[][]; classType: string }) =>
    http.post('/aoi-watch', req),

  remove: (id: number): Promise<void> => http.delete(`/aoi-watch/${id}`),

  /** 检查变化：对比该区域最近两期解译结果 */
  check: (id: number): Promise<{
    id: number
    name: string
    classType: string
    periodCount: number
    insufficient: boolean
    message: string
    prevDate?: string
    lastDate?: string
    prevAreaHa?: number
    lastAreaHa?: number
    deltaHa?: number
    deltaPct?: number
    significant?: boolean
  }> => http.post(`/aoi-watch/${id}/check`)
}

// ============================================================
// 边界管理（客户 SHP/GeoJSON/KML 导入当 AOI）
// ============================================================

export interface AoiBoundaryItem {
  id: number
  projectId: number
  name: string
  /** PERMIT 矿权范围 / DISTURBANCE 实际扰动边界 / ECO 生态缓冲区 */
  boundaryType: 'PERMIT' | 'DISTURBANCE' | 'ECO'
  areaHa: number
  vertexCount: number
  sourceFormat?: string
  sourceCrs?: string
  sourceFile?: string
  /** 解析时的提示：缺 .prj、按 WGS84 假定等，要如实展示 */
  warnings?: string
  createdBy?: string
  createdAt?: string
  /** 仅详情接口返回 */
  geometry?: { outer: number[][]; holes?: number[][][] }
}

export const boundaryApi = {
  list: (projectId: number, type?: string): Promise<AoiBoundaryItem[]> =>
    http.get('/aoi-boundaries', { params: { projectId, type } }),

  get: (id: number): Promise<AoiBoundaryItem> => http.get(`/aoi-boundaries/${id}`),

  /** 项目边界概况：越界检测有没有基准可用 */
  summary: (projectId: number): Promise<{
    total: number
    permit: number
    disturbance: number
    eco: number
    permitAreaHa: number
    encroachReady: boolean
    hint: string
  }> => http.get('/aoi-boundaries/summary', { params: { projectId } }),

  /** 导入边界文件（内容走 base64，避免 multipart 多层转发）
   *  files 支持 shp/shx/dbf/prj 分开选中；sourceCrs 用于 .prj 缺失时手选坐标系 */
  importFile: (req: {
    projectId: number
    boundaryType: 'PERMIT' | 'DISTURBANCE' | 'ECO'
    filename?: string
    contentBase64?: string
    files?: Array<{ filename: string; contentBase64: string }>
    sourceCrs?: string
    name?: string
    merge?: boolean
  }): Promise<{
    saved: AoiBoundaryItem[]
    count: number
    sourceFormat: string
    sourceCrs: string
    warnings: string
    boundaryType: string
  }> => http.post('/aoi-boundaries/import', req, { timeout: 180000 }),

  /** 把手圈/当前的 AOI 存为正式边界（在线解译、本地解译页的「存为边界」） */
  saveDrawn: (req: {
    projectId: number
    name?: string
    boundaryType: 'PERMIT' | 'DISTURBANCE' | 'ECO'
    ring: number[][]
  }): Promise<{
    saved: AoiBoundaryItem
    count: number
    sourceFormat: string
    sourceCrs: string
    boundaryType: string
    warnings: string
  }> => http.post('/aoi-boundaries/save', req),

  remove: (id: number): Promise<void> => http.delete(`/aoi-boundaries/${id}`)
}

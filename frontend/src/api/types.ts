/** 后端数据类型定义（与 Java 端实体对齐） */

export interface Project {
  id: number
  name: string
  region: string
  status: 'RUNNING' | 'PLANNING' | 'ARCHIVED'
  manager: string
  createdAt: string
  description: string
  members: string[]

  // ---- 矿山业务档案（2026-10-22 新增，后端 Project 实体同步）----
  /** 矿种：锂矿 / 铁矿 / 石灰岩 等 */
  mineralType?: string
  /** 采矿许可证号 */
  licenseNo?: string
  /** 矿权面积（km²），越界分析的对比基准 */
  licenseAreaKm2?: number
  /** 开采方式：露天 / 井下 / 联合 */
  miningMethod?: string
  /** 矿区中心点经度（新建后地图默认定位） */
  centerLng?: number
  /** 矿区中心点纬度 */
  centerLat?: number
  /** 客户方对接人 */
  contactPerson?: string
  /** 客户方联系方式 */
  contactPhone?: string
  /** 成果与影像采用的坐标系 */
  crs?: string
}

export type SensorType = 'DISP' | 'RAIN' | 'SOIL' | 'WATER'
export type SensorStatus = 'ONLINE' | 'OFFLINE' | 'ALARM'

export interface Sensor {
  id: string
  projectId: number
  name: string
  type: SensorType
  lng: number
  lat: number
  status: SensorStatus
  latestValue: number
  unit: string
  updatedAt: string
}

export interface SensorDataPoint {
  time: string
  value: number
}

export interface InterpretTask {
  id: number
  name: string
  projectId: number
  algoType: 'SEGMENTATION' | 'CHANGE_DETECTION' | 'INDEX'
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  imageName: string
  createdAt: string
}

export interface OverviewStats {
  imageCount: number
  taskRunning: number
  sensorOnline: number
  sensorAlarm: number
  pitAreaHa: number
  pitAreaChangeHa: number
  vegetationLossHa: number
  recoveryAreaHa: number
}

export type AlarmLevel = 'RED' | 'ORANGE' | 'YELLOW' | 'BLUE'
export type AlarmStatus = 'UNACK' | 'ACKED' | 'RESOLVED'

export interface Alarm {
  id: number
  projectId: number
  sensorId: string
  sensorName: string
  level: AlarmLevel
  indicator: string
  value: number
  threshold: number
  unit: string
  status: AlarmStatus
  createdAt: string
  alarmType?: string
  handledBy?: string
  handleComment?: string
  handleTime?: string
}

export interface WarningRule {
  id: number
  sensorType: SensorType
  sensorTypeName: string
  indicator: string
  unit: string
  yellowThreshold: number
  orangeThreshold: number
  redThreshold: number
  enabled: boolean
}

export interface Station {
  id: string
  projectId: number
  projectNo: string
  region: string
  stationName: string
  stationType: string
  workStatus: 'NORMAL' | 'ABNORMAL' | 'MAINTAIN'
  firstMonitorAt: string
  lastMonitorAt: string
  deviceSn: string
  deviceWorkStatus: string
  deviceModel: string
  firmware: string
  sensorId: string
}

/** GNSS 位移多分量时序 */
export interface DisplacementSeries {
  x: SensorDataPoint[]
  y: SensorDataPoint[]
  z: SensorDataPoint[]
  total: SensorDataPoint[]
}

export interface ScreenSummary {
  projectName: string
  orgName: string
  monitorSubject: string
  address: string
  contact: string
  safeDays: number
  stationCount: number
  todayAlarms: number
  deviceOnline: number
  deviceTotal: number
  alarmRed: number
  alarmOrange: number
  alarmYellow: number
  alarmBlue: number
}

export interface PitYearly {
  year: number
  areaHa: number
  changeHa: number
}

export interface PitForecast {
  year: number
  areaHa: number
  lowerHa: number
  upperHa: number
}

export interface VegetationYearly {
  year: number
  lossHa: number
  recoveryHa: number
  ndvi: number
}

export interface AdminUser {
  username: string
  displayName: string
  role: string
  phone: string
  status: 'ENABLED' | 'DISABLED'
}

export interface Role {
  code: string
  name: string
  description: string
  pagePerms: string[]
  actionPerms: string[]
  builtin: boolean
}

export interface PermItem {
  code: string
  name: string
}

export interface PermCatalog {
  pages: PermItem[]
  actions: PermItem[]
}

/** 在线提取记录（AOI/结果几何为 JSON 字符串坐标） */
export interface Extraction {
  id: number
  projectId: number
  taskId?: string
  imageryId?: number
  pixelCount?: number
  name: string
  classType: 'VEGETATION' | 'WATER' | 'PIT' | 'DUMP' | 'BARE' | 'TAILINGS' | 'ROAD' | 'BUILDING' | 'MOUNTAIN'
  satellite: 'SENTINEL2' | 'LANDSAT9' | 'GF2'
  year: number
  acquisitionDate?: string
  aoiJson?: string
  aoiSignature?: string
  featuresJson: string
  aoiAreaHa: number
  extractAreaHa: number
  coveragePct: number
  /** 解译方法：INDEX 指数阈值 / SUPERVISED 监督分类 / FUSION 融合结果 */
  method?: 'INDEX' | 'SUPERVISED' | 'FUSION' | string
  /** 精度或融合元信息（JSON 字符串） */
  accuracyJson?: string | null
  createdBy?: string
  createdAt: string
  /** 软删除标记：true 表示在回收站 */
  deleted?: boolean
  deletedAt?: string
  deletedBy?: string
}

/** 影像库条目（imagery 表）
 *  source=UPLOAD 为用户上传的高分影像；SENTINEL2/LANDSAT9 为公开数据源
 *  crs 原样记录用户选择的坐标系；west/south/east/north 统一为 WGS84 经纬度 */
export interface Imagery {
  id: number
  projectId: number
  name: string
  source: 'UPLOAD' | 'SENTINEL2' | 'LANDSAT9' | 'GF2'
  filePath?: string
  productId?: string
  originalName?: string
  crs?: string
  acquisitionDate: string
  cloudCover?: number | null
  resolutionM?: number
  west: number
  south: number
  east: number
  north: number
  quicklookPath?: string
  status: 'READY' | 'PROCESSING' | 'FAILED'
  /** 收藏标记：星标影像在列表中优先展示 */
  favorite?: boolean
  note?: string
  createdAt: string

  // ---- 影像档案元数据（方案附录 B）----
  /** 离轴角（度）：越大侧视越强，正射精度越差 */
  offNadirAngle?: number | null
  /** 太阳高度角（度）：过低会拉长阴影 */
  sunElevation?: number | null
  /** 太阳方位角（度） */
  sunAzimuth?: number | null
  /** RAW / L1T / L2A / ORTHO / OTHER */
  orthoLevel?: string | null
  /** INTERNAL / TRAIN / PUBLISH / CROSS_BORDER */
  licenseScope?: string | null
  vendor?: string | null
  price?: number | null
  priceCurrency?: string | null
  orderNo?: string | null
  deliveryDate?: string | null
  bandCount?: number | null
  sensorName?: string | null
}

/** 上传时可选的坐标系 */
export interface CrsOption {
  code: string
  name: string
  label: string
}

/** Sentinel-2 检索结果（在线提取的数据源） */
export interface SceneItem {
  productId: string
  name: string
  date: string
  cloudCover: number
  tileId: string
  platform: string
  level: string
  bounds: [number, number, number, number]
  center: [number, number]
  sizeMb: number
  hasQuicklook: boolean
}

/** 时序分组（同一 AOI 的多期提取结果汇总） */
export interface TimeSeriesGroup {
  signature: string
  aoiJson?: string
  classType: string
  periodCount: number
  startDate: string
  endDate: string
  startAreaHa: number
  endAreaHa: number
  areaChangeHa: number
  changePct: number
  label: string
}

/** 时序单帧（一期提取结果） */
export interface TimeSeriesFrame {
  id: number
  date: string
  name: string
  imageryId?: number
  satellite: string
  classType: string
  featuresJson: string
  extractAreaHa: number
  coveragePct: number
  aoiAreaHa: number
}

/** 面积时序行（真实解译聚合） */
export interface AreaTimeseriesRow {
  date: string
  totalAreaHa: number
  changeHa: number
  byClass: Record<string, number>
  /** 该期参与统计的解译记录数（同区域重复提取已去重） */
  recordCount?: number
}

/** 面积时序响应：带聚合粒度与口径说明 */
export interface AreaTimeseriesResult {
  granularity: 'month' | 'year'
  rows: AreaTimeseriesRow[]
  note: string
}

/** 采坑趋势外推结果（含不确定性，非实测） */
export interface PitForecastResult {
  method: string
  disclaimer: string
  insufficient: boolean
  message?: string
  historyPeriods?: number
  lastDate?: string | null
  lastAreaHa?: number
  forecast: Array<{
    date: string
    areaHa: number
    lowerHa: number
    upperHa: number
    uncertaintyHa: number
  }>
}

/** 变化概览 */
export interface ChangeSummary {
  totalRecords: number
  classes: Array<{ classType: string; totalAreaHa: number; recordCount: number }>
  note: string
}

// ============================================================
// 开采安全风险评估
// ============================================================

/** 单个风险维度（含分项得分、证据与建议） */
export interface SafetyDimension {
  key: string
  label: string
  weight: number
  score: number
  weighted: number
  /** 数据可信度：期数/地形数据充足度决定 */
  confidence: 'low' | 'medium' | 'high'
  /** 支撑该评分的具体数值（如「陡坡占比 12.3%」） */
  evidence: string[]
  advice: string
  /** 计算依据：slope_units=边坡单元聚合，fallback=全区统计 */
  basis?: 'slope_units' | 'fallback' | null
}

/** 风险热点：栅格风险超过阈值的连片区域 */
export interface SafetyHotspot {
  lng: number
  lat: number
  areaHa: number
  score: number
  maxScore: number
  pixelCount: number
}

/** 安全评估完整结果 */
export interface SafetyEvaluation {
  available: boolean
  message?: string
  projectName?: string
  recordCount?: number
  generatedAt?: string
  score?: {
    total: number
    level: string
    color: string
    dimensions: SafetyDimension[]
  }
  encroachment?: {
    available: boolean
    areaHa: number
    pctOfDisturbance: number
    permitAreaHa?: number
    note?: string
  }
  terrain?: Record<string, any>
  areaSummary?: {
    aoiHa: number
    disturbanceHa: number
    byClass: Record<string, number>
    sumOfClassesHa?: number
    note: string
    /** 面积自检：各类之和明显超过分析区时给出提示 */
    check?: string | null
  }
  trend?: Record<string, any>
  hotspots?: SafetyHotspot[]
  /** 热点阈值（自适应：整体风险偏低时退到 P90 相对阈值） */
  hotspotThreshold?: number
  riskImageBase64?: string
  levelStats?: Array<{ label: string; color: string; pct: number }>
  legend?: Array<{ label: string; color: string }>
  grid?: { width: number; height: number; mPerPixel: number; zoom: number }
  gridError?: string
  disclaimer?: string
}

// ============================================================
// 边坡单元与三区扰动（docs/13 阶段一）
// ============================================================

/** 单个边坡单元 */
export interface SlopeUnit {
  id: number
  label: number
  sector: number
  facility: 'PIT' | 'DUMP' | 'TAILINGS'
  areaHa: number
  pixelCount: number
  centerLng: number
  centerLat: number
  /** 坡脚（单元最低点）—— 现场核查从这里开始 */
  toeLng: number
  toeLat: number
  /** 坡顶（单元最高点） */
  crestLng: number
  crestLat: number
  slopeHeightM: number
  meanSlopeDeg: number
  maxSlopeDeg: number
  aspectDeg: number
  /** 剖面曲率近似：负=凸形坡（坡脚应力集中），正=凹形坡 */
  curvature: number
  /** 坡脚到采坑边界最短距离（米）；<10m 视为已切脚 */
  toeDistanceM: number | null
  /** 坡脚周围被采坑覆盖的比例（%） */
  toeCutRatio: number
  /** 坡顶是否有堆载（仅采坑单元有意义） */
  topLoaded: boolean
  riskLevel: '高' | '较高' | '中' | '低'
  /** 判定依据（人可读） */
  reasons: string[]
}

export interface SlopeUnitsResult {
  available: boolean
  message?: string
  units: SlopeUnit[]
  summary?: {
    unitCount: number
    high: number
    higher: number
    medium: number
    low: number
    totalAreaHa: number
    maxSlopeHeightM: number
    cutToeCount: number
    note?: string
  }
  imageBase64?: string | null
  legend?: Array<{ label: string; color: string }>
  /** 诊断信息：解释"为什么没有单元"或"为什么切脚算不出" */
  diagnostics?: {
    slopeMeanDeg: number
    slopeP90Deg: number
    steepPixelsInDisturbed: number
    disturbedPixels: number
    minSlopeDeg: number
    minUnitPixels: number
  }
  disclaimer?: string
  precision?: {
    groundResolutionM: number
    minSlopeDeg: number
    toeCutDistM: number
    limitation: string
  }
}

// ============================================================
// 空间关系与专项风险（B6/B7/B8/B9/C4/A3）
// ============================================================

export interface SpatialMetric {
  label: string
  value: number | string
  unit?: string
  hint?: string
}

export interface SpatialItem {
  key: 'pond_in_pit' | 'tailings_water' | 'dump_flow' | 'road_cut' | 'eco_buffer' | 'pit_shape'
  label: string
  available: boolean
  /** 高 / 较高 / 中 / 低 / 不可用 */
  level: string
  color: string
  finding: string
  advice: string
  metrics: SpatialMetric[]
  note?: string
}

export interface PitShape {
  id: number
  areaHa: number
  perimeterM: number
  /** 4πA/P²，1=正圆；越低说明边界越曲折、多向扩张 */
  shapeIndex: number
  equivRadiusM: number
  /** 与上一期相比的等效半径推进（米）；无上一期时为 null */
  advanceM: number | null
}

export interface SpatialRelationsResult {
  available: boolean
  message?: string
  projectName?: string
  items?: SpatialItem[]
  summary?: {
    total: number
    available: number
    high: number
    higher: number
    medium: number
    low: number
    headline: string
  }
  pitShapes?: PitShape[]
  grid?: { width: number; height: number; mPerPixel: number; zoom: number }
  imageBase64?: string | null
  legend?: Array<{ label: string; color: string }>
  permitSource?: string
  disclaimer?: string
  generatedAt?: string
}

// ============================================================
// 监督分类（精细模式）
// ============================================================

/** 可选分析区（来自边界管理导入的边界，含外环） */
export interface AoiOption {
  id: number
  name: string
  boundaryType: 'PERMIT' | 'DISTURBANCE' | 'ECO'
  areaHa: number
  ring: number[][]
}

export interface ClassifySample {
  classType: string
  lng: number
  lat: number
}

export interface ClassifyClassResult {
  classType: string
  label: string
  color: string
  areaHa: number
  pixelCount: number
  pctOfAoi: number
  featureCount: number
  sampleCount: number
  precision: number
  recall: number
  f1: number
  /** 制图精度（= recall） */
  producerAccuracy: number
  /** 用户精度（= precision） */
  userAccuracy: number
  validationCount: number
}

export interface SupervisedResult {
  available: boolean
  message?: string
  projectName?: string
  scene?: { id: string; datetime: string; cloudCover: number }
  grid?: { width: number; height: number; featureCount: number; validPixels: number }
  classes?: ClassifyClassResult[]
  /** 各类 GeoJSON 要素，保存解译记录时直接复用 */
  features?: Record<string, Array<{ type: string; properties: any; geometry: any }>>
  accuracy?: {
    overallAccuracy: number
    kappa: number
    oobScore: number | null
    labels: string[]
    labelNames: string[]
    confusionMatrix: number[][]
    sampleCount: number
    validationCount: number
    split: string
  }
  featureImportance?: Array<{ name: string; importance: number }>
  imageBase64?: string | null
  method?: string
  samples?: Array<{ classType: string; count: number }>
  warnings?: string[]
  disclaimer?: string
}

// ============================================================
// 周尺度监测：影像可用性（L1）+ 突变事件（L2）
// ============================================================

export interface AvailabilityResult {
  level: string
  message: string
  advice: string
  range: { start: string; end: string; days: number }
  sceneCount: number
  scenes: Array<{ id: string; date: string; datetime: string; cloudCover: number; platform?: string }>
  relaxedCloudCount: number
  maxCloud: number
  note: string
}

export interface ChangePatch {
  lng: number
  lat: number
  areaHa: number
  perimeterM: number
}

export interface ChangeEventItem {
  type: string
  label: string
  color: string
  count: number
  totalAreaHa: number
  patches: ChangePatch[]
}

export interface ChangeEventsResult {
  periods: {
    first: { id: string; datetime: string; cloudCover: number; range: string[] }
    second: { id: string; datetime: string; cloudCover: number; range: string[] }
  }
  events: ChangeEventItem[]
  totalEvents: number
  conclusion: string
  warnings: string[]
  params: { maxCloud: number; minAreaHa: number }
  grid: { width: number; height: number; pixelAreaHa: number }
  imageBase64?: string | null
  legend: Array<{ label: string; color: string }>
  disclaimer: string
}

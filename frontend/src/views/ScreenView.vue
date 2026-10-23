<template>
  <div class="screen-root">
    <!-- 顶部标题栏 -->
    <header class="top-bar">
      <div class="top-left">
        <div class="icon-btn" title="收起/展开左栏" @click="leftVisible = !leftVisible">
          <el-icon color="#7dd3fc"><Expand v-if="!leftVisible" /><Fold v-else /></el-icon>
        </div>
        <div class="icon-btn" title="收起/展开右栏" @click="rightVisible = !rightVisible">
          <el-icon color="#7dd3fc"><Fold v-if="!rightVisible" /><Expand v-else /></el-icon>
        </div>
        <!-- 页面跳转菜单（参考平台：放在顶栏左侧） -->
        <el-dropdown popper-class="screen-dark-popper" @command="onMenu">
          <div class="icon-btn" title="前往其他页面">
            <el-icon color="#7dd3fc"><Menu /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="/">首页</el-dropdown-item>
              <el-dropdown-item disabled>GIS 大屏（当前）</el-dropdown-item>
              <el-dropdown-item command="/monitor/data">监测数据</el-dropdown-item>
              <el-dropdown-item command="/warning/rules">预警管理</el-dropdown-item>
              <el-dropdown-item command="/ops/stations">运维管理</el-dropdown-item>
              <el-dropdown-item command="/analysis">遥感分析</el-dropdown-item>
              <el-dropdown-item command="/imagery">解译中心</el-dropdown-item>
              <el-dropdown-item command="/platform/projects">平台管理</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="top-center">
        <h1 class="screen-title">{{ summary?.projectName || '矿区边坡监测' }}</h1>
        <div class="screen-sub">
          <el-icon><Location /></el-icon>
          {{ summary?.address || '' }}&nbsp;·&nbsp;多云 24°C 今天&nbsp;·&nbsp;{{ nowText }}
        </div>
      </div>
      <div class="top-right">
        <div class="icon-btn" title="地图工具箱" @click="toolboxVisible = !toolboxVisible">
          <el-icon color="#7dd3fc"><Tools /></el-icon>
        </div>
        <div class="icon-btn" title="退出登录" @click="onLogout">
          <el-icon color="#f87171"><SwitchButton /></el-icon>
        </div>
      </div>
    </header>

    <!-- 地图 -->
    <div ref="cesiumRef" class="cesium-container"></div>

    <!-- 未配置天地图密钥时的提示 -->
    <div v-if="!hasToken" class="token-notice">
      未检测到天地图密钥，底图未加载。请在 frontend/.env.local 配置 VITE_TIANDITU_TOKEN 后重启 vite。
    </div>

    <!-- 测量提示 -->
    <div v-if="measureMode !== 'none'" class="measure-hint">
      {{ measureMode === 'distance' ? '距离测量' : '面积测量' }}：左键加点 · 右键结束
      <span class="measure-cancel" @click="clearMeasure">取消</span>
    </div>

    <!-- 地图工具箱 -->
    <transition name="fade">
      <div v-if="toolboxVisible" class="toolbox">
        <div class="tb-header">
          <span class="tb-title">地图工具箱</span>
          <el-icon class="tb-close" @click="toolboxVisible = false"><Close /></el-icon>
        </div>
        <div class="tb-tabs">
          <div class="tb-tab" :class="{ active: toolboxTab === 'view' }" @click="toolboxTab = 'view'">视图显示</div>
          <div class="tb-tab" :class="{ active: toolboxTab === 'measure' }" @click="toolboxTab = 'measure'">测量工具</div>
          <div class="tb-tab" :class="{ active: toolboxTab === 'legend' }" @click="toolboxTab = 'legend'">图例</div>
        </div>

        <!-- 视图显示 -->
        <div v-show="toolboxTab === 'view'" class="tb-body">
          <div class="tb-section">场景选择</div>
          <el-radio-group v-model="sceneMode" size="small" @change="switchSceneMode">
            <el-radio-button value="3d">三维场景</el-radio-button>
            <el-radio-button value="2d">二维场景</el-radio-button>
          </el-radio-group>

          <div class="tb-section">底图选择</div>
          <div class="basemap-cards">
            <div class="bm-card" :class="{ active: basemap === 'img' }" @click="basemap = 'img'; switchBasemap()">
              <div class="bm-thumb bm-img"></div>
              <span>天地图影像</span>
            </div>
            <div class="bm-card" :class="{ active: basemap === 'vec' }" @click="basemap = 'vec'; switchBasemap()">
              <div class="bm-thumb bm-vec"></div>
              <span>天地图矢量</span>
            </div>
          </div>

          <div class="tb-section">显示开关</div>
          <div class="lp-row"><span>位置信息（底部状态栏）</span><el-switch v-model="showStatusBar" size="small" /></div>
          <div class="lp-row"><span>传感器点位</span><el-switch v-model="layers.sensors" size="small" @change="toggleLayer" /></div>
          <div class="lp-row"><span>采坑范围（示例）</span><el-switch v-model="layers.pit" size="small" @change="toggleLayer" /></div>
          <div class="lp-row"><span>排土场范围（示例）</span><el-switch v-model="layers.dump" size="small" @change="toggleLayer" /></div>

          <div class="tb-footer">
            <div class="tb-btn" @click="flyHome">初始视图</div>
          </div>
        </div>

        <!-- 测量工具 -->
        <div v-show="toolboxTab === 'measure'" class="tb-body">
          <div class="tb-section">测量（左键加点，右键结束）</div>
          <div class="measure-btns">
            <div class="tb-btn" :class="{ active: measureMode === 'distance' }" @click="startMeasure('distance')">距离测量</div>
            <div class="tb-btn" :class="{ active: measureMode === 'area' }" @click="startMeasure('area')">面积测量</div>
            <div class="tb-btn warn" @click="clearMeasure">清除测量</div>
          </div>
          <div class="tb-note">测量结果为椭球面近似值，仅供演示参考</div>
        </div>

        <!-- 图例 -->
        <div v-show="toolboxTab === 'legend'" class="tb-body">
          <div class="tb-section">图层开关</div>
          <div class="layer-switch" @click="toggleImagery">
            <i class="sw" :class="{ on: showImagery }"></i><span>最新影像</span>
          </div>
          <div class="layer-switch" @click="toggleVector">
            <i class="sw" :class="{ on: showVector }"></i><span>解译结果（{{ rsLayers?.vectorDate || '无' }}）</span>
          </div>

          <div v-if="rsLayers?.imagery && !rsLayers.imagery.samePeriod" class="tb-note">
            影像 {{ rsLayers.imagery.date }} 与解译期次不同期，仅供参照
          </div>

          <div class="tb-section">传感器状态</div>
          <div class="lg-row"><i class="dot" style="background:#22d3ee"></i><span>在线</span></div>
          <div class="lg-row"><i class="dot" style="background:#ef4444"></i><span>告警</span></div>
          <div class="lg-row"><i class="dot" style="background:#64748b"></i><span>离线</span></div>

          <div class="tb-section">解译要素</div>
          <div v-for="c in rsLayers?.classes || []" :key="c.classType" class="lg-row">
            <i class="swatch" :style="{ background: hexA(CLASS_COLOR[c.classType] || '#94a3b8', 0.45) }"></i>
            <span>{{ classLabel(c.classType) }}</span>
          </div>
          <div v-if="!(rsLayers?.classes || []).length" class="tb-note">当前项目暂无解译结果</div>
        </div>
      </div>
    </transition>

    <!-- 左侧面板组 -->
    <transition name="slide-left">
      <div v-show="leftVisible" class="panel-col left">
        <div class="panel">
          <div class="panel-title">矿山概况</div>
          <div class="kv-list">
            <div class="kv"><span class="k">工程名称</span><span class="v">{{ summary?.projectName }}</span></div>
            <div class="kv"><span class="k">组织机构</span><span class="v">{{ summary?.orgName }}</span></div>
            <div class="kv"><span class="k">监测主题</span><span class="v">{{ summary?.monitorSubject }}</span></div>
            <div class="kv"><span class="k">项目地址</span><span class="v">{{ summary?.address }}</span></div>
            <div class="kv"><span class="k">联系方式</span><span class="v">{{ summary?.contact }}</span></div>
          </div>
        </div>

        <!-- 遥感成果 KPI：大屏最该先回答"解译了多少、覆盖多大" -->
        <div class="panel">
          <div class="panel-title">遥感解译成果</div>
          <div class="ops-grid">
            <div class="ops-item">
              <div class="ops-value">{{ rs?.kpi?.imageryCount ?? '-' }}</div>
              <div class="ops-label">影像景数</div>
            </div>
            <div class="ops-item">
              <div class="ops-value">{{ rs?.kpi?.extractionCount ?? '-' }}</div>
              <div class="ops-label">解译记录</div>
            </div>
            <div class="ops-item">
              <div class="ops-value">{{ km2(rs?.kpi?.extractionAreaHa) }}</div>
              <div class="ops-label">解译面积 km²</div>
            </div>
            <div class="ops-item">
              <div class="ops-value">{{ km2(rs?.kpi?.imageryAreaHa) }}</div>
              <div class="ops-label">影像覆盖 km²</div>
            </div>
            <div class="ops-item">
              <div class="ops-value">{{ rs?.kpi?.supervisedCount ?? 0 }}</div>
              <div class="ops-label">监督分类</div>
            </div>
            <div class="ops-item">
              <div class="ops-value">{{ rs?.kpi?.fusionCount ?? 0 }}</div>
              <div class="ops-label">融合结果</div>
            </div>
          </div>
          <div class="rs-foot">
            <span>最近解译 {{ rs?.kpi?.latestDate || '-' }}</span>
            <span v-if="rs?.accuracy" class="acc-badge">
              精度 OA {{ rs.accuracy.oa }}% · Kappa {{ rs.accuracy.kappa }}
            </span>
          </div>
        </div>

        <!-- 地物构成：解译结果按类累计面积，与「地物构成」分析页口径一致 -->
        <div class="panel flex-panel">
          <div class="panel-title">地物构成（累计）</div>
          <div ref="classPieRef" class="donut"></div>
        </div>
      </div>
    </transition>

    <!-- 右侧面板组 -->
    <transition name="slide-right">
      <div v-show="rightVisible" class="panel-col right">
        <!-- 解译成果时序：按拍摄日期堆叠，能看出哪期扩了多少 -->
        <div class="panel flex-panel">
          <div class="panel-title">解译成果时序</div>
          <div ref="seriesRef" class="donut"></div>
        </div>

        <div class="panel flex-panel">
          <div class="panel-title">最新监测数据</div>
          <div class="sensor-scroll">
            <div v-for="s in sensors" :key="s.id" class="sensor-item" @click="flyToSensor(s)">
              <div class="sensor-head">
                <span class="sensor-name">{{ s.name }}</span>
                <span class="sensor-status" :style="{ color: statusColor(s.status) }">● {{ statusText(s.status) }}</span>
              </div>
              <div class="sensor-body">
                <span>{{ typeText(s.type) }}</span>
                <span class="sensor-value" :class="{ danger: s.status === 'ALARM' }">{{ s.latestValue }} {{ s.unit }}</span>
              </div>
            </div>
          </div>
        </div>
        <!-- 最近解译记录：表格比图更直观，客户看的就是"最近做了什么" -->
        <div class="panel recent-panel">
          <div class="panel-title">最近解译记录</div>
          <div class="recent-table">
            <div v-for="r in rs?.recent || []" :key="r.id" class="recent-row">
              <span class="rc-date">{{ r.date }}</span>
              <span class="rc-cls">{{ classLabel(r.classType) }}</span>
              <span class="rc-method" :class="'m-' + r.method">{{ methodLabel(r.method) }}</span>
              <span class="rc-area">{{ km2(r.areaHa) }} km²</span>
            </div>
            <div v-if="!rs?.recent?.length" class="recent-empty">暂无解译记录</div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 解译要素属性卡：点地图直接看这一块是什么、多大、哪期 -->
    <transition name="fade">
      <div v-if="picked" class="rs-info">
        <div class="rs-info-head">
          <span class="rs-info-title">{{ classLabel(picked.classType) }}</span>
          <span class="rs-info-close" @click="picked = null">×</span>
        </div>
        <div class="rs-info-row"><span>面积</span><b>{{ km2(picked.areaHa) }} km²</b></div>
        <div class="rs-info-row"><span>影像日期</span><b>{{ picked.date }}</b></div>
        <div class="rs-info-row"><span>解译方法</span><b>{{ methodLabel(picked.method) }}</b></div>
        <div class="rs-info-row"><span>记录</span><b class="ellip">{{ picked.name }}</b></div>
      </div>
    </transition>

    <!-- 底部状态栏（位置信息，可通过工具箱开关） -->
    <footer v-show="showStatusBar" class="status-bar">
      <span>经度: {{ cursor.lng }}</span>
      <span>纬度: {{ cursor.lat }}</span>
      <span>视高: {{ cursor.height }}</span>
      <span>方向: {{ cursor.heading }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { Expand, Fold, Location, Menu, SwitchButton, Tools, Close } from '@element-plus/icons-vue'
import {
  Viewer, Cartesian3, Color, ImageryLayer, Entity,
  ScreenSpaceEventHandler, ScreenSpaceEventType, Cartographic, Math as CMath,
  EllipsoidGeodesic, CallbackProperty, PolygonHierarchy,
  SingleTileImageryProvider, Rectangle
} from 'cesium'
import { screenApi, sensorApi } from '@/api'
import type { ScreenSummary, Sensor, SensorStatus, SensorType } from '@/api/types'
import { tiandituBaseLayers } from '@/map/basemap'
import { autoAdjustPerformance } from '@/map/perf'
import { TIANDITU_TOKEN, MINE_CENTER } from '@/config'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'

const router = useRouter()
const auth = useAuthStore()
const projectStore = useProjectStore()

const cesiumRef = ref<HTMLDivElement>()
const donutRef = ref<HTMLDivElement>()
const classPieRef = ref<HTMLDivElement>()
const seriesRef = ref<HTMLDivElement>()
const rs = ref<any>(null)
const rsLayers = ref<any>(null)
const showImagery = ref(true)
const showVector = ref(true)
/** 点中的解译要素（null = 不显示属性卡） */
const picked = ref<any>(null)
let imageryHandle: ImageryLayer | null = null
const rsEntities: Entity[] = []
let pickHandler: ScreenSpaceEventHandler | null = null
const summary = ref<ScreenSummary | null>(null)
const sensors = ref<Sensor[]>([])
const leftVisible = ref(true)
const rightVisible = ref(true)
const toolboxVisible = ref(false)
const toolboxTab = ref<'view' | 'measure' | 'legend'>('view')
const sceneMode = ref<'3d' | '2d'>('3d')
const showStatusBar = ref(true)
const basemap = ref<'img' | 'vec'>('img')
const layers = reactive({ sensors: true, pit: true, dump: true })
const nowText = ref('')
const cursor = reactive({ lng: '-', lat: '-', height: '-', heading: '-' })

const hasToken = !!TIANDITU_TOKEN

let viewer: Viewer | null = null
let donut: echarts.ECharts | undefined
let classPie: echarts.ECharts | undefined
let seriesChart: echarts.ECharts | undefined

/** 七类地物中文名 + 配色：与大屏「地物构成」图例保持一致 */
const CLASS_LABEL: Record<string, string> = {
  PIT: '露天采坑', DUMP: '排土场', TAILINGS: '尾矿', BARE: '裸地扰动',
  ROAD: '道路', VEGETATION: '植被', WATER: '水体', BUILDING: '建筑', MOUNTAIN: '山体'
}
const CLASS_COLOR: Record<string, string> = {
  PIT: '#787878', DUMP: '#b08960', TAILINGS: '#e2dac4', BARE: '#c4a882',
  ROAD: '#fad65a', VEGETATION: '#4caf50', WATER: '#2182d6', BUILDING: '#f97316', MOUNTAIN: '#6b7280'
}
function classLabel(c: string) {
  return CLASS_LABEL[c] || c || '-'
}
function methodLabel(m: string) {
  return m === 'SUPERVISED' ? '分类' : m === 'FUSION' ? '融合' : '指数'
}
/** ha → km²，大屏只留 2 位小数 */
function km2(ha?: number) {
  return ((ha || 0) / 100).toFixed(2)
}
let moveHandler: ScreenSpaceEventHandler | null = null
let clockTimer: ReturnType<typeof setInterval> | undefined
let statusTimer: ReturnType<typeof setInterval> | undefined

// 业务图层实体引用（开关用）
const sensorEntities: Entity[] = []
const pitEntities: Entity[] = []
const dumpEntities: Entity[] = []

const alarmCards = computed(() => [
  { label: '红色预警', value: summary.value?.alarmRed ?? 0, color: '#ef4444' },
  { label: '橙色预警', value: summary.value?.alarmOrange ?? 0, color: '#f97316' },
  { label: '黄色预警', value: summary.value?.alarmYellow ?? 0, color: '#eab308' },
  { label: '蓝色预警', value: summary.value?.alarmBlue ?? 0, color: '#3b82f6' }
])

function statusColor(s: SensorStatus) {
  return { ONLINE: '#22d3ee', OFFLINE: '#64748b', ALARM: '#ef4444' }[s]
}
function statusText(s: SensorStatus) {
  return { ONLINE: '在线', OFFLINE: '离线', ALARM: '告警' }[s]
}
function typeText(t: SensorType) {
  return { DISP: 'GNSS 地表位移监测站', RAIN: '雨量监测站', SOIL: '土壤含水率监测站', WATER: '水位监测站' }[t]
}

function tickClock() {
  const d = new Date()
  nowText.value = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

/** 底图切换：清空影像层后按选择重建（影像=img+cia，矢量=vec+cva） */
function switchBasemap() {
  if (!viewer || !hasToken) return
  viewer.imageryLayers.removeAll()
  const { base, label } = tiandituBaseLayers(basemap.value)
  viewer.imageryLayers.addImageryProvider(base)
  viewer.imageryLayers.addImageryProvider(label)
}

/** 业务图层开关 */
function toggleLayer() {
  sensorEntities.forEach((e) => (e.show = layers.sensors))
  pitEntities.forEach((e) => (e.show = layers.pit))
  dumpEntities.forEach((e) => (e.show = layers.dump))
}

/** 二维/三维切换：morph 动画期间需要关掉按需渲染，完成后恢复 */
function switchSceneMode() {
  if (!viewer) return
  viewer.scene.requestRenderMode = false
  const restore = () => {
    if (viewer) {
      viewer.scene.requestRenderMode = true
      viewer.scene.morphComplete.removeEventListener(restore)
    }
  }
  viewer.scene.morphComplete.addEventListener(restore)
  if (sceneMode.value === '2d') {
    viewer.scene.morphTo2D(1.2)
  } else {
    viewer.scene.morphTo3D(1.2)
  }
}

function flyHome() {
  viewer?.camera.flyTo({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.014, 5200),
    orientation: { pitch: -0.72 },
    duration: 1.5
  })
}

function flyToSensor(s: Sensor) {
  viewer?.camera.flyTo({
    destination: Cartesian3.fromDegrees(s.lng, s.lat - 0.003, 1200),
    orientation: { pitch: -0.9 },
    duration: 1.2
  })
}

/** 采坑/排土场示例范围：显式 height: 0 关闭贴地裁剪，outline 才生效（贴地几何不支持描边） */
function addMockAreas(v: Viewer) {
  const pitRing = [
    [116.0178, 26.4712], [116.0196, 26.4736], [116.0224, 26.4740],
    [116.0242, 26.4724], [116.0226, 26.4702], [116.0196, 26.4698]
  ].flat()
  const pit = v.entities.add({
    name: '露天采坑（示例范围）',
    polygon: {
      hierarchy: Cartesian3.fromDegreesArray(pitRing),
      height: 0,
      material: Color.fromCssColorString('#ef4444').withAlpha(0.35),
      outline: true,
      outlineColor: Color.fromCssColorString('#ef4444')
    }
  })
  pitEntities.push(pit)
  const dumpRing = [
    [116.0236, 26.4778], [116.0268, 26.4796], [116.0284, 26.4772],
    [116.0262, 26.4752], [116.0238, 26.4758]
  ].flat()
  const dump = v.entities.add({
    name: '排土场（示例范围）',
    polygon: {
      hierarchy: Cartesian3.fromDegreesArray(dumpRing),
      height: 0,
      material: Color.fromCssColorString('#f59e0b').withAlpha(0.35),
      outline: true,
      outlineColor: Color.fromCssColorString('#f59e0b')
    }
  })
  dumpEntities.push(dump)
}

function addSensors(v: Viewer, list: Sensor[]) {
  for (const s of list) {
    const e = v.entities.add({
      id: `sensor-${s.id}`,
      name: s.name,
      position: Cartesian3.fromDegrees(s.lng, s.lat, 10),
      point: {
        pixelSize: s.status === 'ALARM' ? 14 : 10,
        color: Color.fromCssColorString(statusColor(s.status)),
        outlineColor: Color.WHITE,
        outlineWidth: 2
      },
      label: {
        text: s.name,
        font: '12px sans-serif',
        fillColor: Color.WHITE,
        style: 2,
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        pixelOffset: new Cartesian3(0, -22, 0)
      }
    })
    sensorEntities.push(e)
  }
}

// ==================== 测量工具 ====================
// 关键设计：形状/标注实体整个测量过程只建一次，几何用 CallbackProperty 动态求值——
// 反复增删贴地图元在低端 GPU 上会把渲染循环打崩（GroundPolyline 批次更新崩溃）
// 距离：椭球面测地线累加；面积：局部切平面投影 + Shoelace 公式（矿区尺度误差可忽略）

const measureMode = ref<'none' | 'distance' | 'area'>('none') // 只驱动提示 UI
let mType: 'distance' | 'area' = 'distance'                    // 形状类型的真实记录（结束后模式清空也不影响它）
let mPositions: Cartesian3[] = []
let mFloat: Cartesian3 | null = null
let mEntities: Entity[] = []
let mHandler: ScreenSpaceEventHandler | null = null

function activePositions(): Cartesian3[] {
  return mFloat ? [...mPositions, mFloat] : mPositions
}

function startMeasure(mode: 'distance' | 'area') {
  clearMeasure()
  measureMode.value = mode
  mType = mode
  if (!viewer) return

  // 折线/多边形：CallbackProperty 动态几何 + show 属性保证点数不足时不参与渲染
  const shape: Entity = mode === 'distance'
    ? viewer.entities.add({
        polyline: {
          positions: new CallbackProperty(() => activePositions(), false),
          width: 3,
          material: Color.fromCssColorString('#22d3ee'),
          show: new CallbackProperty(() => activePositions().length >= 2, false)
        }
      })
    : viewer.entities.add({
        polygon: {
          hierarchy: new CallbackProperty(() => new PolygonHierarchy(activePositions()), false),
          material: Color.fromCssColorString('#22d3ee').withAlpha(0.25),
          height: 0,
          outline: true,
          outlineColor: Color.fromCssColorString('#22d3ee'),
          show: new CallbackProperty(() => activePositions().length >= 3, false)
        }
      })
  mEntities.push(shape)

  // 数值标注：位置/文字均动态，点数不足时隐藏
  const label = viewer.entities.add({
    position: new CallbackProperty(() => {
      const pts = activePositions()
      return pts.length > 0
        ? pts[pts.length - 1]
        : Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat, 0)
    }, false) as any,
    label: {
      text: new CallbackProperty(() => measureText(), false),
      font: '13px sans-serif',
      fillColor: Color.WHITE,
      style: 2,
      outlineColor: Color.BLACK,
      outlineWidth: 3,
      pixelOffset: new Cartesian3(0, -18, 0),
      show: new CallbackProperty(() => mPositions.length >= (mType === 'distance' ? 2 : 3), false)
    }
  })
  mEntities.push(label)

  mHandler = new ScreenSpaceEventHandler(viewer.scene.canvas)
  mHandler.setInputAction((e: ScreenSpaceEventHandler.PositionedEvent) => {
    const pos = viewer?.camera.pickEllipsoid(e.position, viewer.scene.globe.ellipsoid)
    if (!pos) return
    // 双击会产生两个紧邻的 LEFT_CLICK，重复点会让测地线计算抛 DeveloperError，直接跳过
    const last = mPositions[mPositions.length - 1]
    if (last && Cartesian3.distanceSquared(last, pos) < 0.01) return
    mPositions.push(pos)
    mEntities.push(viewer!.entities.add({
      position: pos,
      point: { pixelSize: 8, color: Color.fromCssColorString('#22d3ee'), outlineColor: Color.WHITE, outlineWidth: 2 }
    }))
    viewer?.scene.requestRender()
  }, ScreenSpaceEventType.LEFT_CLICK)
  mHandler.setInputAction((e: ScreenSpaceEventHandler.MotionEvent) => {
    if (mPositions.length === 0) return
    const pos = viewer?.camera.pickEllipsoid(e.endPosition, viewer.scene.globe.ellipsoid)
    if (pos) {
      mFloat = pos
      viewer?.scene.requestRender()
    }
  }, ScreenSpaceEventType.MOUSE_MOVE)
  mHandler.setInputAction(() => finishMeasure(), ScreenSpaceEventType.RIGHT_CLICK)
}

function measureText(): string {
  const pts = activePositions()
  if (mType === 'distance') {
    if (pts.length < 2) return '0 m'
    let sum = 0
    for (let i = 1; i < pts.length; i++) {
      const geo = new EllipsoidGeodesic(
        Cartographic.fromCartesian(pts[i - 1]),
        Cartographic.fromCartesian(pts[i])
      )
      sum += geo.surfaceDistance
    }
    return sum >= 1000 ? `总长 ${(sum / 1000).toFixed(2)} km` : `总长 ${sum.toFixed(1)} m`
  }
  if (pts.length < 3) return '0 m²'
  // 局部切平面近似投影
  const c0 = Cartographic.fromCartesian(pts[0])
  const R = 6371000
  const cosLat = Math.cos(c0.latitude)
  const xy = pts.map((p) => {
    const c = Cartographic.fromCartesian(p)
    return [R * (c.longitude - c0.longitude) * cosLat, R * (c.latitude - c0.latitude)]
  })
  let area = 0
  for (let i = 0; i < xy.length; i++) {
    const [x1, y1] = xy[i]
    const [x2, y2] = xy[(i + 1) % xy.length]
    area += x1 * y2 - x2 * y1
  }
  area = Math.abs(area) / 2
  return area >= 10000 ? `面积 ${(area / 1000000).toFixed(2)} km²` : `面积 ${area.toFixed(0)} m²`
}

/** 右键结束：冻结浮动点、销毁交互，实体保留在图上（CallbackProperty 读的是静态数组，不再变化） */
function finishMeasure() {
  mFloat = null
  mHandler?.destroy()
  mHandler = null
  measureMode.value = 'none'
  viewer?.scene.requestRender()
}

function clearMeasure() {
  mHandler?.destroy()
  mHandler = null
  if (viewer) {
    mEntities.forEach((e) => viewer!.entities.remove(e))
  }
  mEntities = []
  mPositions = []
  mFloat = null
  measureMode.value = 'none'
  viewer?.scene.requestRender()
}

// ==================== 状态栏 ====================

/** 底部状态栏：鼠标经纬度 + 相机视高/方向 */
function bindStatusBar(v: Viewer) {
  moveHandler = new ScreenSpaceEventHandler(v.scene.canvas)
  moveHandler.setInputAction((movement: ScreenSpaceEventHandler.MotionEvent) => {
    const cartesian = v.camera.pickEllipsoid(movement.endPosition, v.scene.globe.ellipsoid)
    if (cartesian) {
      const carto = Cartographic.fromCartesian(cartesian)
      cursor.lng = CMath.toDegrees(carto.longitude).toFixed(4) + '°'
      cursor.lat = CMath.toDegrees(carto.latitude).toFixed(4) + '°'
    }
  }, ScreenSpaceEventType.MOUSE_MOVE)

  statusTimer = setInterval(() => {
    if (!viewer) return
    const h = viewer.camera.positionCartographic.height
    cursor.height = h > 1000 ? (h / 1000).toFixed(1) + ' km' : h.toFixed(0) + ' m'
    cursor.heading = CMath.toDegrees(viewer.camera.heading).toFixed(1) + '°'
  }, 500)
}

/** 半透明色：图例色块用 8 位 hex 加 alpha，避免 rgba 字符串拼接出错 */
function hexA(hex: string, alpha: number) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0')
  return hex.length === 7 ? hex + a : hex
}

/** 加载影像预览 + 最新一期解译矢量（只做一次，不进轮询） */
async function loadRsLayers() {
  const pid = projectStore.currentId
  if (!pid || !viewer) return
  try {
    const data = await screenApi.rsLayers(pid)
    rsLayers.value = data
    if (data?.imagery?.previewBase64 && data.imagery.bounds) {
      applyImageryLayer(data.imagery)
    }
    applyVectorLayer(data?.classes || [])
    // 有影像就飞到影像范围，没影像但有矢量就飞到矢量范围
    const b = data?.imagery?.bounds
    if (b) {
      viewer.camera.flyTo({
        destination: Rectangle.fromDegrees(b.west, b.south, b.east, b.north),
        duration: 1.2
      })
    }
  } catch (e: any) {
    // 大屏不因图层失败而报错打断，只在控制台留痕
    console.warn('遥感图层加载失败：', e?.message || e)
  }
}

function applyImageryLayer(meta: any) {
  if (!viewer) return
  if (imageryHandle) {
    viewer.imageryLayers.remove(imageryHandle, true)
    imageryHandle = null
  }
  const b = meta.bounds
  imageryHandle = viewer.imageryLayers.addImageryProvider(
    new SingleTileImageryProvider({
      url: 'data:image/png;base64,' + meta.previewBase64,
      rectangle: Rectangle.fromDegrees(b.west, b.south, b.east, b.north)
    })
  )
  imageryHandle.show = showImagery.value
}

function applyVectorLayer(classes: any[]) {
  if (!viewer) return
  for (const e of rsEntities) viewer.entities.remove(e)
  rsEntities.length = 0

  for (const c of classes) {
    const color = Color.fromCssColorString(CLASS_COLOR[c.classType] || '#94a3b8')
    for (const f of c.features || []) {
      const ring = f.geometry?.coordinates?.[0]
      if (!ring || ring.length < 3) continue
      const ent = viewer.entities.add({
        polygon: {
          hierarchy: new PolygonHierarchy(
            ring.map((p: number[]) => Cartesian3.fromDegrees(p[0], p[1]))
          ),
          material: color.withAlpha(0.42),
          outline: true,
          outlineColor: color.withAlpha(0.9),
          // 贴地显示：大屏视角低，抬高会出现"飘在空中"
          height: 0
        },
        properties: f.properties
      })
      rsEntities.push(ent)
    }
  }
  rsEntities.forEach((e) => { e.show = showVector.value })
}

function toggleImagery() {
  showImagery.value = !showImagery.value
  if (imageryHandle) imageryHandle.show = showImagery.value
}

function toggleVector() {
  showVector.value = !showVector.value
  rsEntities.forEach((e) => { e.show = showVector.value })
  if (!showVector.value) picked.value = null
}

/** 点地图拾取解译要素：只在没在测量时生效，避免和测量抢点击 */
function bindPick() {
  if (!viewer) return
  pickHandler = new ScreenSpaceEventHandler(viewer.scene.canvas)
  pickHandler.setInputAction((e: ScreenSpaceEventHandler.PositionedEvent) => {
    if (measureMode.value !== 'none' || !showVector.value) return
    const pos = viewer!.scene.pick(e.position)
    const ent = pos?.id as Entity | undefined
    if (!ent || !ent.properties) {
      picked.value = null
      return
    }
    try {
      const p: any = ent.properties.getValue(viewer!.clock.currentTime)
      picked.value = p || null
    } catch {
      picked.value = null
    }
  }, ScreenSpaceEventType.LEFT_CLICK)
}

function renderClassPie() {
  if (!classPieRef.value || !rs.value?.classes?.length) return
  if (!classPie) classPie = echarts.init(classPieRef.value)
  classPie.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} km² ({d}%)' },
    legend: {
      type: 'scroll', orient: 'vertical', right: 0, top: 'center',
      itemWidth: 8, itemHeight: 8, itemGap: 8,
      textStyle: { color: '#94a3b8', fontSize: 10 }
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['32%', '50%'],
      label: { show: false },
      itemStyle: { borderColor: '#0b2135', borderWidth: 1 },
      data: rs.value.classes.map((c: any) => ({
        name: classLabel(c.classType),
        value: +(c.totalHa / 100).toFixed(2),
        itemStyle: { color: CLASS_COLOR[c.classType] || '#94a3b8' }
      }))
    }]
  })
}

function renderSeries() {
  if (!seriesRef.value || !rs.value?.series?.length) return
  if (!seriesChart) seriesChart = echarts.init(seriesRef.value)
  const rows = rs.value.series
  const dates = rows.map((r: any) => r.date)
  // 取出出现过的所有类别，按堆叠顺序排列
  const classes = Array.from(new Set(rows.flatMap((r: any) => Object.keys(r.byClass || {})))) as string[]
  seriesChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      type: 'scroll', bottom: 0, itemWidth: 8, itemHeight: 8,
      textStyle: { color: '#94a3b8', fontSize: 10 }
    },
    grid: { left: 40, right: 12, top: 12, bottom: 46 },
    xAxis: {
      type: 'category', data: dates,
      axisLabel: { color: '#64748b', fontSize: 10, formatter: (v: string) => v.slice(2) },
      axisLine: { lineStyle: { color: '#1e3a5f' } }
    },
    yAxis: {
      type: 'value', name: 'km²', nameTextStyle: { color: '#64748b', fontSize: 10 },
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(30,58,95,0.6)' } }
    },
    series: classes.map((cls) => ({
      name: classLabel(cls),
      type: 'bar',
      stack: 'total',
      barMaxWidth: 18,
      itemStyle: { color: CLASS_COLOR[cls] || '#94a3b8' },
      data: rows.map((r: any) => +(((r.byClass || {})[cls] || 0) / 100).toFixed(2))
    }))
  })
}


function onMenu(path: string) {
  router.push(path)
}

async function onLogout() {
  await auth.logout()
  router.push('/login')
}

onMounted(async () => {
  tickClock()
  clockTimer = setInterval(tickClock, 1000)

  if (!cesiumRef.value) return
  // 影像图层：有天地图密钥用天地图，否则裸地球（深色球面）+ 顶部提示
  const imageryLayers = hasToken ? (() => {
    const { base, label } = tiandituBaseLayers('img')
    return [new ImageryLayer(base), new ImageryLayer(label)]
  })() : []

  viewer = new Viewer(cesiumRef.value, {
    baseLayer: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    creditContainer: document.createElement('div') // 隐藏默认版权条
  })
  if (imageryLayers.length) {
    imageryLayers.forEach((l) => viewer!.imageryLayers.add(l))
  }
  // 深蓝太空底色，贴合大屏风格
  viewer.scene.backgroundColor = Color.fromCssColorString('#04121f')
  viewer.scene.globe.baseColor = Color.fromCssColorString('#0b1b2b')

  // 低配机器（Quadro K2200）：按需渲染
  viewer.scene.requestRenderMode = true
  viewer.scene.maximumRenderTimeChange = Infinity
  // 帧率不足时自动降渲染精度，保证大屏滚动与交互流畅
  autoAdjustPerformance(viewer)

  // 测量期间双击会触发默认的实体追踪/缩放，先摘掉默认行为
  viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK)

  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.014, 5200),
    orientation: { pitch: -0.72 }
  })

  addMockAreas(viewer)
  bindStatusBar(viewer)

  try {
    // 项目清单可能尚未加载（直接从大屏进入），先确保有上下文
    if (projectStore.projects.length === 0) {
      await projectStore.load()
    }
    const pid = projectStore.currentId
    const [sum, sensorList, rsData] = await Promise.all([
      screenApi.summary(pid), sensorApi.list(pid), screenApi.rsOverview(pid).catch(() => null)
    ])
    summary.value = sum
    sensors.value = sensorList
    rs.value = rsData
    addSensors(viewer, sensorList)
    // 视角落到当前项目的传感器中心；没有点位就回默认矿区
    if (sensorList.length > 0) {
      const lng = sensorList.reduce((a, s) => a + s.lng, 0) / sensorList.length
      const lat = sensorList.reduce((a, s) => a + s.lat, 0) / sensorList.length
      viewer.camera.setView({
        destination: Cartesian3.fromDegrees(lng, lat - 0.012, 5200),
        orientation: { pitch: -0.72 }
      })
    }
    // DOM 更新后再渲染图表（等 v-show 生效，容器才有尺寸）
    setTimeout(() => {
      renderClassPie()
      renderSeries()
    }, 60)
    // 图层只在进页面/切项目时取一次（预览图 MB 级，不能进 5 秒轮询）
    bindPick()
    loadRsLayers()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
})

onBeforeUnmount(() => {
  if (clockTimer) clearInterval(clockTimer)
  if (statusTimer) clearInterval(statusTimer)
  moveHandler?.destroy()
  pickHandler?.destroy()
  mHandler?.destroy()
  donut?.dispose()
  classPie?.dispose()
  seriesChart?.dispose()
  viewer?.destroy()
  viewer = null
})
</script>

<style scoped>
.screen-root {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: #04121f;
  color: #cbd5e1;
  font-size: 13px;
}

.cesium-container { position: absolute; inset: 0; }

/* ---- 顶部标题栏 ---- */
.top-bar {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: linear-gradient(180deg, rgba(4, 18, 31, 0.92), rgba(4, 18, 31, 0.55) 80%, transparent);
  z-index: 10;
  pointer-events: none;
}

.top-bar > * { pointer-events: auto; }

.top-left, .top-right { display: flex; gap: 8px; align-items: center; width: 220px; }
.top-right { justify-content: flex-end; }

.icon-btn {
  width: 32px; height: 32px;
  border: 1px solid rgba(125, 211, 252, 0.35);
  border-radius: 6px;
  background: rgba(8, 47, 73, 0.6);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  outline: none;
}
.icon-btn:hover { background: rgba(8, 47, 73, 0.9); }

.top-center { text-align: center; }

.screen-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 4px;
  color: #e0f2fe;
  text-shadow: 0 0 18px rgba(34, 211, 238, 0.5);
}

.screen-sub {
  display: flex; align-items: center; justify-content: center; gap: 4px;
  font-size: 12px; color: #7dd3fc; margin-top: 2px;
}

/* ---- 地图工具箱 ---- */
.toolbox {
  position: absolute;
  top: 78px;
  left: 50%;
  transform: translateX(-50%);
  width: 380px;
  background: rgba(6, 28, 46, 0.94);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 12px;
  z-index: 12;
  backdrop-filter: blur(8px);
}

.tb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 0;
}

.tb-title { font-size: 14px; font-weight: 600; color: #7dd3fc; }
.tb-close { cursor: pointer; color: #64748b; }
.tb-close:hover { color: #e2e8f0; }

.tb-tabs { display: flex; gap: 6px; padding: 10px 16px 0; }

.tb-tab {
  flex: 1;
  text-align: center;
  padding: 7px 0;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  color: #94a3b8;
  cursor: pointer;
}

.tb-tab.active {
  background: rgba(34, 211, 238, 0.15);
  border-color: #22d3ee;
  color: #22d3ee;
  font-weight: 600;
}

.tb-body { padding: 6px 16px 14px; }

.tb-section {
  font-size: 12px;
  font-weight: 600;
  color: #5eead4;
  margin: 12px 0 8px;
}

.basemap-cards { display: flex; gap: 10px; }

.bm-card {
  flex: 1;
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 8px;
  padding: 6px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
  cursor: pointer;
}

.bm-card.active { border-color: #22d3ee; color: #22d3ee; }

.bm-thumb { height: 52px; border-radius: 6px; margin-bottom: 6px; }
.bm-img { background: linear-gradient(135deg, #1a3a2a, #0f2537 60%, #2a3a1a); }
.bm-vec { background: linear-gradient(135deg, #e8e4d8, #cfd8c8 60%, #dcd6c8); }

.lp-row { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; font-size: 12px; }

.lg-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }

/* 工具箱内的 Element 单选按钮：深色适配（默认白色皮肤在大屏上刺眼） */
.tb-body :deep(.el-radio-button__inner) {
  background: rgba(8, 47, 73, 0.6);
  border-color: rgba(56, 189, 248, 0.3);
  color: #94a3b8;
  box-shadow: none !important;
}

.tb-body :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: rgba(34, 211, 238, 0.18);
  border-color: #22d3ee;
  color: #22d3ee;
}

.tb-footer { margin-top: 14px; display: flex; justify-content: center; }

.tb-btn {
  padding: 7px 18px;
  border-radius: 7px;
  border: 1px solid rgba(56, 189, 248, 0.35);
  background: rgba(8, 47, 73, 0.7);
  color: #7dd3fc;
  font-size: 12px;
  cursor: pointer;
  text-align: center;
}

.tb-btn:hover { background: rgba(8, 47, 73, 1); }
.tb-btn.active { border-color: #22d3ee; color: #22d3ee; }
.tb-btn.warn { border-color: rgba(239, 68, 68, 0.4); color: #f87171; }

.measure-btns { display: flex; gap: 8px; }
.measure-btns .tb-btn { flex: 1; padding: 7px 0; }

.tb-note { margin-top: 10px; font-size: 11px; color: #475569; }

.measure-hint {
  position: absolute;
  top: 78px; left: 50%;
  transform: translateX(-50%);
  background: rgba(8, 47, 73, 0.9);
  border: 1px solid rgba(34, 211, 238, 0.5);
  color: #22d3ee;
  padding: 7px 16px;
  border-radius: 8px;
  font-size: 12px;
  z-index: 12;
}

.measure-cancel { margin-left: 12px; color: #f87171; cursor: pointer; }

/* ---- 侧栏面板 ---- */
.panel-col {
  position: absolute;
  top: 76px;
  bottom: 52px;
  width: 268px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  z-index: 9;
}

.panel-col.left { left: 14px; }
.panel-col.right { right: 14px; }

.panel {
  background: rgba(6, 28, 46, 0.78);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 10px;
  padding: 12px 14px;
  backdrop-filter: blur(6px);
}

.flex-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }

.layer-switch {
  display: flex; align-items: center; gap: 8px; padding: 4px 2px;
  font-size: 12px; color: #cbd5e1; cursor: pointer;
}
.layer-switch .sw {
  width: 26px; height: 14px; border-radius: 7px; background: #1e3a5f;
  position: relative; transition: background .15s;
}
.layer-switch .sw::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 10px; height: 10px; border-radius: 50%; background: #64748b;
  transition: left .15s, background .15s;
}
.layer-switch .sw.on { background: rgba(34, 211, 238, .35); }
.layer-switch .sw.on::after { left: 14px; background: #22d3ee; }

.rs-info {
  position: absolute; right: 300px; bottom: 64px; z-index: 12;
  width: 220px; padding: 10px 12px; border-radius: 8px;
  background: rgba(6, 28, 46, 0.92);
  border: 1px solid rgba(56, 189, 248, 0.35);
  backdrop-filter: blur(6px); font-size: 12px; color: #cbd5e1;
}
.rs-info-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.rs-info-title { color: #5eead4; font-weight: 600; }
.rs-info-close { cursor: pointer; color: #64748b; font-size: 14px; line-height: 1; }
.rs-info-row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
.rs-info-row span { color: #64748b; }
.rs-info-row b { color: #e2e8f0; font-weight: 500; }
.ellip { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.rs-foot {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-top: 6px; font-size: 11px; color: #64748b;
}
.acc-badge {
  padding: 1px 6px; border-radius: 4px; color: #5eead4;
  background: rgba(20, 184, 166, 0.12); border: 1px solid rgba(20, 184, 166, 0.3);
}
.recent-panel { max-height: 216px; }
.recent-table { display: flex; flex-direction: column; gap: 3px; overflow-y: auto; }
.recent-row {
  display: grid; grid-template-columns: 74px 1fr 40px 66px;
  align-items: center; gap: 6px; font-size: 11px;
  padding: 3px 4px; border-radius: 4px; background: rgba(30, 58, 95, 0.25);
}
.rc-date { color: #7dd3fc; }
.rc-cls { color: #cbd5e1; }
.rc-method { text-align: center; border-radius: 3px; font-size: 10px; }
.m-SUPERVISED { color: #5eead4; background: rgba(20, 184, 166, 0.15); }
.m-FUSION { color: #fbbf24; background: rgba(251, 191, 36, 0.15); }
.m-INDEX { color: #93c5fd; background: rgba(59, 130, 246, 0.15); }
.rc-area { text-align: right; color: #e2e8f0; }
.recent-empty { font-size: 11px; color: #64748b; text-align: center; padding: 10px 0; }

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #7dd3fc;
  border-left: 3px solid #22d3ee;
  padding-left: 8px;
  margin-bottom: 10px;
}

.kv-list { display: flex; flex-direction: column; gap: 7px; }
.kv { display: flex; justify-content: space-between; font-size: 12px; }
.kv .k { color: #64748b; }
.kv .v { color: #e2e8f0; max-width: 170px; text-align: right; }

.ops-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ops-item { text-align: center; padding: 6px 0; }
.ops-value { font-size: 24px; font-weight: 700; color: #22d3ee; font-variant-numeric: tabular-nums; }
.ops-value.danger { color: #ef4444; }
.ops-label { font-size: 11px; color: #64748b; margin-top: 2px; }

.donut-wrap { display: flex; align-items: center; }
.donut { width: 130px; height: 130px; }
.donut-side { flex: 1; display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.donut-row { display: flex; align-items: center; gap: 6px; }

.alarm-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; text-align: center; }
.alarm-num { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.alarm-label { font-size: 11px; color: #64748b; }

.sensor-scroll { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 2px; }
.sensor-scroll::-webkit-scrollbar { width: 4px; }
.sensor-scroll::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 2px; }

.sensor-item {
  border: 1px solid rgba(56, 189, 248, 0.18);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.sensor-item:hover { border-color: rgba(56, 189, 248, 0.5); }

.sensor-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.sensor-name { font-size: 13px; font-weight: 600; color: #e2e8f0; }
.sensor-status { font-size: 11px; }
.sensor-body { display: flex; justify-content: space-between; font-size: 12px; color: #64748b; }
.sensor-value { color: #22d3ee; font-weight: 600; }
.sensor-value.danger { color: #ef4444; }

/* ---- 底部 ---- */
.status-bar {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 34px;
  display: flex;
  align-items: center;
  gap: 26px;
  padding: 0 18px;
  background: rgba(4, 18, 31, 0.85);
  border-top: 1px solid rgba(56, 189, 248, 0.15);
  font-size: 12px;
  color: #64748b;
  z-index: 8;
  font-variant-numeric: tabular-nums;
}

.token-notice {
  position: absolute;
  top: 80px; left: 50%;
  transform: translateX(-50%);
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.5);
  color: #fbbf24;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 12px;
  z-index: 12;
}

.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }

/* ---- 动画 ---- */
.slide-left-enter-active, .slide-left-leave-active,
.slide-right-enter-active, .slide-right-leave-active { transition: all 0.25s ease; }
.slide-left-enter-from, .slide-left-leave-to { transform: translateX(-110%); opacity: 0; }
.slide-right-enter-from, .slide-right-leave-to { transform: translateX(110%); opacity: 0; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

<template>
  <div class="rs-page">
    <!-- 左侧地图 -->
    <div class="map-wrap">
      <div ref="cesiumRef" class="cesium-container"></div>

      <!-- 地图工具条 -->
      <div class="map-toolbar">
        <el-button size="small" :type="drawing ? 'danger' : 'primary'" @click="toggleDraw">
          {{ drawing ? '圈选中（左键加点·右键结束）' : '圈选 AOI' }}
        </el-button>
        <el-button size="small" :disabled="aoi.length === 0" @click="clearAoi">清除</el-button>
        <span v-if="aoiAreaText" class="aoi-info">AOI {{ aoiAreaText }}</span>
      </div>

      <!-- 影像图层开关 -->
      <div class="layer-switch">
        <div class="ls-title">影像图层</div>
        <div class="ls-row">
          <span>剪切影像</span>
          <el-switch v-model="showClipped" size="small" @change="toggleClipped" />
        </div>
        <div class="ls-row">
          <span>提取结果</span>
          <el-switch v-model="showResult" size="small" @change="toggleResult" />
        </div>
        <div class="ls-title" style="margin-top:8px">底图</div>
        <div class="ls-row">
          <el-radio-group v-model="basemap" size="small" @change="switchBasemap">
            <el-radio-button value="tdt">天地图</el-radio-button>
            <el-radio-button value="gaode">高德</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <div v-if="!hasToken" class="token-notice">未配置天地图密钥，底图未加载</div>
      <div v-if="busy" class="busy-mask">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ busyText }}</span>
      </div>
    </div>

    <!-- 右侧面板 -->
    <div class="side">
      <!-- 参数卡片 -->
      <el-card shadow="never" class="side-card">
        <template #header><span class="side-title">1. 影像参数</span></template>
        <el-form label-width="72px" size="default">
          <el-form-item label="开始日期">
            <el-date-picker v-model="startDate" type="date" value-format="YYYY-MM-DD"
                            style="width: 100%" placeholder="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="endDate" type="date" value-format="YYYY-MM-DD"
                            style="width: 100%" placeholder="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="最大云量">
            <el-slider v-model="maxCloud" :min="0" :max="100" show-input :show-input-controls="false" />
          </el-form-item>
          <el-button type="primary" style="width: 100%" :loading="previewing" :disabled="aoi.length < 3" @click="doPreview">
            查询影像
          </el-button>
          <div v-if="sceneInfo" class="scene-info">
            <div class="si-row"><span>景 ID</span><code>{{ sceneInfo.scene_id }}</code></div>
            <div class="si-row"><span>日期</span>{{ (sceneInfo.datetime || '').slice(0, 10) }}</div>
            <div class="si-row"><span>云量</span>{{ sceneInfo.cloud_cover }}%</div>
          </div>
        </el-form>
      </el-card>

      <!-- 提取卡片 -->
      <el-card shadow="never" class="side-card">
        <template #header><span class="side-title">2. 提取类型</span></template>
        <div class="class-grid">
          <div
            v-for="c in classOptions"
            :key="c.value"
            class="class-item"
            :class="{ active: classType === c.value }"
            @click="classType = c.value"
          >
            <span class="class-dot" :style="{ background: c.color }"></span>
            {{ c.label }}
          </div>
        </div>
        <el-form-item label="阈值" style="margin-top: 10px">
          <el-input-number v-model="threshold" :precision="2" :step="0.05" :min="-0.5" :max="0.9" style="width: 100%" />
          <div class="threshold-hint">留空用类型默认阈值（当前 {{ defaultThreshold }}）</div>
        </el-form-item>
        <el-form-item label="最小面积(px)">
          <el-input-number v-model="minArea" :precision="0" :step="5" :min="1" :max="500" style="width: 100%" />
          <div class="threshold-hint">过滤道路/碎斑噪声，值越大越干净</div>
        </el-form-item>
        <el-button type="success" style="width: 100%" :loading="extracting" :disabled="aoi.length < 3" @click="doExtract">
          开始提取
        </el-button>
      </el-card>

      <!-- 结果样式 + 保存 + 变化对比 -->
      <el-card shadow="never" class="side-card">
        <template #header><span class="side-title">3. 结果与变化</span></template>

        <!-- 结果样式：颜色 + 透明度 -->
        <div v-if="lastResult" class="style-panel">
          <div class="sp-row">
            <span class="sp-label">结果颜色</span>
            <el-color-picker v-model="resultColor" size="small" @change="onStyleChange" />
          </div>
          <div class="sp-row">
            <span class="sp-label">透明度</span>
            <el-slider v-model="resultOpacity" :min="10" :max="100" size="small" @input="onStyleChange" />
          </div>
        </div>

        <!-- 保存 -->
        <div class="save-row">
          <el-input v-model="saveName" placeholder="记录名称（留空自动生成）" size="small" />
          <el-button size="small" type="primary" :disabled="!lastResult" @click="saveResult">保存</el-button>
        </div>

        <!-- 历史记录（按类型分组，勾选加入播放清单） -->
        <div class="timeline">
          <div class="tl-title">提取记录（按类型分组）</div>
          <div v-if="history.length === 0" class="empty">保存后这里显示记录</div>
          <div v-for="group in groupedHistory" :key="group.type" class="tl-group">
            <div class="tl-group-title">
              <span class="g-dot" :style="{ background: group.color }"></span>
              {{ group.label }}
              <span class="g-count">{{ group.items.length }} 条</span>
            </div>
            <div
              v-for="h in group.items"
              :key="h.id"
              class="tl-item"
              :class="{ picked: playlistIds.includes(h.id) }"
              @click="togglePlaylist(h)"
            >
              <el-checkbox :model-value="playlistIds.includes(h.id)" @click.stop="togglePlaylist(h)" />
              <span class="tl-name">{{ h.name }}</span>
              <span class="tl-meta">{{ h.datetime.slice(0, 10) }}</span>
              <span class="tl-cov">{{ h.coverage }}%</span>
            </div>
          </div>
        </div>

        <!-- 播放清单（可排序） -->
        <div v-if="playlist.length > 0" class="playlist">
          <div class="tl-title">播放清单（按顺序，可调整）</div>
          <div v-for="(h, idx) in playlist" :key="h.id" class="pl-item">
            <span class="pl-idx">{{ idx + 1 }}</span>
            <span class="pl-name">{{ h.name }} · {{ h.datetime.slice(0, 10) }}</span>
            <span class="pl-ops">
              <el-button size="small" text :disabled="idx === 0" @click="movePlaylist(idx, -1)">↑</el-button>
              <el-button size="small" text :disabled="idx === playlist.length - 1" @click="movePlaylist(idx, 1)">↓</el-button>
              <el-button size="small" text type="danger" @click="removeFromPlaylist(h)">✕</el-button>
            </span>
          </div>
        </div>

        <!-- 播放/对比 -->
        <div v-if="playlist.length >= 1" class="compare-actions">
          <el-button size="small" :type="playing ? 'warning' : 'primary'" @click="toggleAnimation">
            {{ playing ? '⏸ 暂停' : '▶ 播放变化动画' }}（{{ playlist.length }} 帧）
          </el-button>
          <el-button size="small" :disabled="playlist.length < 2" @click="showDiff">对比差异</el-button>
        </div>
        <div v-else-if="history.length > 0" class="empty">勾选记录加入播放清单（可跨类型，按清单顺序播放）</div>
      </el-card>
    </div>

    <!-- 差异统计弹窗 -->
    <el-dialog v-model="diffVisible" title="跨年份变化对比" width="520px">
      <div v-if="diffRows.length" class="diff-table">
        <div class="diff-head">
          <span>指标</span>
          <span>{{ diffRows[0].earlyLabel }}</span>
          <span>{{ diffRows[0].lateLabel }}</span>
          <span>变化</span>
        </div>
        <div v-for="r in diffRows" :key="r.label" class="diff-row">
          <span>{{ r.label }}</span>
          <span>{{ r.early }}</span>
          <span>{{ r.late }}</span>
          <span :style="{ color: r.deltaColor }">{{ r.delta }}</span>
        </div>
      </div>
      <div v-else class="empty">请先在记录里勾选两条加入播放清单</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import {
  Viewer, Cartesian3, Color, ImageryLayer, Entity,
  ScreenSpaceEventHandler, ScreenSpaceEventType, Cartographic,
  CallbackProperty, PolygonHierarchy, SingleTileImageryProvider, Rectangle, Cartesian2
} from 'cesium'
import { sentinelApi } from '@/api/sentinel'
import type { ExtractResult, PreviewResult } from '@/api/sentinel'
import { tiandituBaseLayers, gaodeSatelliteProvider } from '@/map/basemap'
import { TIANDITU_TOKEN, MINE_CENTER } from '@/config'

const cesiumRef = ref<HTMLDivElement>()
const hasToken = !!TIANDITU_TOKEN

const startDate = ref('2026-09-01')
const endDate = ref('2026-10-01')
const maxCloud = ref(30)
const classType = ref('VEGETATION')
const threshold = ref<number | undefined>(undefined)
const minArea = ref(20)
const saveName = ref('')
const resultColor = ref('#22c55e')
const resultOpacity = ref(50)
const playlistIds = ref<string[]>([])
const diffVisible = ref(false)
const playing = ref(false)
let animationTimer: ReturnType<typeof setInterval> | undefined
let animationItems: HistoryItem[] = []
let animationIndex = 0

const aoi = ref<number[][]>([])
const drawing = ref(false)
const showClipped = ref(true)
const showResult = ref(true)
const basemap = ref<'tdt' | 'gaode'>('tdt')
const busy = ref(false)
const busyText = ref('')
const previewing = ref(false)
const extracting = ref(false)
const sceneInfo = ref<{ scene_id: string; datetime: string; cloud_cover: number } | null>(null)
const lastResult = ref<ExtractResult | null>(null)

const classOptions = [
  { value: 'VEGETATION', label: '植被', color: '#22c55e', thr: 0.25 },
  { value: 'BUILDING', label: '建筑', color: '#ef4444', thr: 0.0 },
  { value: 'BARE', label: '裸地', color: '#a8a29e', thr: 0.0 },
  { value: 'WATER', label: '水体', color: '#3b82f6', thr: 0.0 },
  { value: 'MOUNTAIN', label: '山体', color: '#78716c', thr: -0.2 }
]
const defaultThreshold = computed(() => classOptions.find((c) => c.value === classType.value)?.thr ?? 0)

// 按类型分组的历史记录
const groupedHistory = computed(() => {
  const groups: { type: string; label: string; color: string; items: HistoryItem[] }[] = []
  const seen = new Map<string, number>()
  for (const h of history.value) {
    if (!seen.has(h.classType)) {
      const opt = classOptions.find((c) => c.value === h.classType)
      seen.set(h.classType, groups.length)
      groups.push({ type: h.classType, label: opt?.label || h.classType, color: opt?.color || '#999', items: [] })
    }
    groups[seen.get(h.classType)!].items.push(h)
  }
  // 组内按时间排序
  for (const g of groups) g.items.sort((a, b) => a.datetime.localeCompare(b.datetime))
  return groups
})

// 播放清单（按 playlistIds 顺序映射到 HistoryItem）
const playlist = computed(() =>
  playlistIds.value
    .map((id) => history.value.find((h) => h.id === id))
    .filter((h): h is HistoryItem => !!h)
)

// 历史记录（localStorage 持久化，跨会话保留）
interface HistoryItem {
  id: string
  name: string
  classLabel: string
  classType: string
  datetime: string
  coverage: number
  features: any[]
  aoi: number[][]
  color: string
}
const history = ref<HistoryItem[]>([])

let viewer: Viewer | null = null
let drawHandler: ScreenSpaceEventHandler | null = null
let aoiFloat: number[] | null = null
let aoiEntity: Entity | null = null
let aoiPointEntities: Entity[] = []
let resultEntities: Entity[] = []
let clippedLayer: ImageryLayer | null = null

const aoiAreaText = computed(() => {
  if (aoi.value.length < 3) return ''
  return ringAreaHa(aoi.value).toFixed(2) + ' ha'
})

// ---- 地图初始化 ----
onMounted(() => {
  loadHistory()
  if (!cesiumRef.value) return
  const layers = hasToken ? (() => {
    const { base, label } = tiandituBaseLayers('img')
    return [new ImageryLayer(base), new ImageryLayer(label)]
  })() : []
  viewer = new Viewer(cesiumRef.value, {
    baseLayer: false,
    baseLayerPicker: false, geocoder: false, homeButton: false,
    sceneModePicker: false, navigationHelpButton: false,
    animation: false, timeline: false, fullscreenButton: false,
    infoBox: false, creditContainer: document.createElement('div')
  })
  layers.forEach((l) => viewer!.imageryLayers.add(l))
  // 渲染错误浮出（否则 Cesium 静默停帧，页面全灰难排查）
  viewer.scene.renderError.addEventListener((_s: unknown, err: unknown) => {
    ElMessage.error(`渲染错误: ${(err as Error)?.message || err}`)
  })
  viewer.scene.requestRenderMode = true
  viewer.scene.maximumRenderTimeChange = Infinity
  viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK)
  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.012, 5200),
    orientation: { pitch: -0.72 }
  })
})

// ---- 底图/图层开关 ----
function switchBasemap() {
  if (!viewer) return
  viewer.imageryLayers.removeAll(true)
  clippedLayer = null // removeAll 后引用失效，需重置
  if (basemap.value === 'tdt' && hasToken) {
    const { base, label } = tiandituBaseLayers('img')
    viewer.imageryLayers.addImageryProvider(base)
    viewer.imageryLayers.addImageryProvider(label)
  } else {
    viewer.imageryLayers.addImageryProvider(gaodeSatelliteProvider())
  }
  viewer.scene.requestRender()
}

function toggleClipped(v: boolean) {
  if (clippedLayer) clippedLayer.show = v
  viewer?.scene.requestRender()
}

function toggleResult(v: boolean) {
  resultEntities.forEach((e) => (e.show = v))
  viewer?.scene.requestRender()
}

onBeforeUnmount(() => {
  stopAnimation()
  drawHandler?.destroy()
  viewer?.destroy()
  viewer = null
})

// ---- AOI 圈选 ----
function toggleDraw() {
  if (drawing.value) { finishDraw(); return }
  if (!viewer) return
  drawing.value = true
  clearResult()
  drawHandler = new ScreenSpaceEventHandler(viewer.scene.canvas)
  drawHandler.setInputAction((e: ScreenSpaceEventHandler.PositionedEvent) => {
    const pos = viewer?.camera.pickEllipsoid(e.position, viewer.scene.globe.ellipsoid)
    if (!pos) return
    const c = Cartographic.fromCartesian(pos)
    const lng = c.longitude * 180 / Math.PI
    const lat = c.latitude * 180 / Math.PI
    const last = aoi.value[aoi.value.length - 1]
    if (last && Math.abs(last[0] - lng) < 1e-9 && Math.abs(last[1] - lat) < 1e-9) return
    aoi.value.push([lng, lat])
    aoiPointEntities.push(viewer!.entities.add({
      position: pos,
      point: { pixelSize: 7, color: Color.fromCssColorString('#14b8a6'), outlineColor: Color.WHITE, outlineWidth: 2 }
    }))
    refreshAoi()
    viewer?.scene.requestRender()
  }, ScreenSpaceEventType.LEFT_CLICK)
  drawHandler.setInputAction((e: ScreenSpaceEventHandler.MotionEvent) => {
    if (aoi.value.length === 0) return
    const pos = viewer?.camera.pickEllipsoid(e.endPosition, viewer.scene.globe.ellipsoid)
    if (pos) {
      const c = Cartographic.fromCartesian(pos)
      aoiFloat = [c.longitude * 180 / Math.PI, c.latitude * 180 / Math.PI]
      refreshAoi()
      viewer?.scene.requestRender()
    }
  }, ScreenSpaceEventType.MOUSE_MOVE)
  drawHandler.setInputAction(() => finishDraw(), ScreenSpaceEventType.RIGHT_CLICK)
}

function refreshAoi() {
  if (!viewer) return
  if (aoiEntity) { viewer.entities.remove(aoiEntity); aoiEntity = null }
  if (activeAoi().length < 2) return
  aoiEntity = viewer.entities.add({
    polygon: {
      hierarchy: new CallbackProperty(() => {
        return new PolygonHierarchy(activeAoi().map(([lng, lat]) => Cartesian3.fromDegrees(lng, lat)))
      }, false) as any,
      material: Color.fromCssColorString('#14b8a6').withAlpha(0.2),
      height: 0, outline: true, outlineColor: Color.fromCssColorString('#14b8a6'),
      show: new CallbackProperty(() => activeAoi().length >= 3, false)
    }
  })
}

function activeAoi() { return aoiFloat ? [...aoi.value, aoiFloat] : aoi.value }

function finishDraw() {
  aoiFloat = null
  drawHandler?.destroy()
  drawHandler = null
  drawing.value = false
  refreshAoi()
  viewer?.scene.requestRender()
}

function clearAoi() {
  finishDraw()
  aoi.value = []
  if (viewer && aoiEntity) { viewer.entities.remove(aoiEntity); aoiEntity = null }
  aoiPointEntities.forEach((e) => viewer?.entities.remove(e))
  aoiPointEntities = []
  sceneInfo.value = null
  viewer?.scene.requestRender()
}

// ---- 影像查询（真彩预览）----
async function doPreview() {
  previewing.value = true
  busy.value = true
  busyText.value = '正在检索并下载影像（首次约 10 分钟，之后秒级）...'
  try {
    const res: PreviewResult = await sentinelApi.preview(aoi.value, startDate.value, endDate.value, maxCloud.value)
    sceneInfo.value = { scene_id: res.scene_id, datetime: res.datetime, cloud_cover: res.cloud_cover }
    // 把 base64 PNG 转成 blob，贴到地图
    const byteChars = atob(res.image_base64)
    const bytes = new Uint8Array(byteChars.length)
    for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
    const blob = new Blob([bytes], { type: 'image/png' })
    const url = URL.createObjectURL(blob)
    // 先读图片实际像素尺寸（SingleTileImageryProvider 要求 tileWidth/tileHeight 必填）
    const { width, height } = await readImageSize(url)
    // 用 SingleTileImageryProvider 贴到 AOI 范围
    if (clippedLayer) { viewer?.imageryLayers.remove(clippedLayer, true) }
    const bounds = aoiBounds()
    const rect = Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north)
    clippedLayer = viewer!.imageryLayers.addImageryProvider(
      new SingleTileImageryProvider({ url, rectangle: rect, tileWidth: width, tileHeight: height })
    )
    ElMessage.success(`影像已加载：${res.scene_id}（云量 ${res.cloud_cover}%）`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    previewing.value = false
    busy.value = false
  }
}

function aoiBounds() {
  const lngs = aoi.value.map((p) => p[0])
  const lats = aoi.value.map((p) => p[1])
  return { west: Math.min(...lngs), east: Math.max(...lngs), south: Math.min(...lats), north: Math.max(...lats) }
}

/** 读取图片 blob 的实际像素尺寸（供 SingleTileImageryProvider 用） */
function readImageSize(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => reject(new Error('影像解码失败'))
    img.src = url
  })
}

// ---- 提取 ----
async function doExtract() {
  extracting.value = true
  busy.value = true
  busyText.value = '正在提取（指数计算 + 矢量化）...'
  try {
    const res = await sentinelApi.extract(aoi.value, startDate.value, endDate.value, classType.value, maxCloud.value, threshold.value, minArea.value)
    lastResult.value = res
    // 提取后颜色跟随类型默认色
    resultColor.value = classOptions.find((c) => c.value === classType.value)?.color || '#22c55e'
    renderResult(res)
    ElMessage.success(`提取完成：覆盖率 ${res.coverage_pct}%，共 ${res.feature_count} 个要素`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    extracting.value = false
    busy.value = false
  }
}

function renderResult(res: ExtractResult) {
  clearResult()
  if (!viewer) return
  const color = resultColor.value
  const alpha = resultOpacity.value / 100
  for (const f of res.features) {
    const geom = f.geometry
    if (!geom) continue
    const coords = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates
    for (const ring of coords) {
      const outer = ring[0]
      resultEntities.push(viewer!.entities.add({
        polygon: {
          hierarchy: new PolygonHierarchy(outer.map(([lng, lat]: number[]) => Cartesian3.fromDegrees(lng, lat))),
          material: Color.fromCssColorString(color).withAlpha(alpha),
          height: 0, outline: true, outlineColor: Color.fromCssColorString(color)
        }
      }))
    }
  }
  viewer.scene.requestRender()
}

function onStyleChange() {
  if (lastResult.value) renderResult(lastResult.value)
}

function clearResult() {
  resultEntities.forEach((e) => viewer?.entities.remove(e))
  resultEntities = []
}

// ---- 保存与历史 ----
function saveResult() {
  if (!lastResult.value) return
  const item: HistoryItem = {
    id: Date.now().toString(),
    name: saveName.value || `${classType.value}-${(lastResult.value.datetime || '').slice(0, 10)}`,
    classLabel: classOptions.find((c) => c.value === classType.value)?.label || classType.value,
    classType: classType.value,
    datetime: lastResult.value.datetime,
    coverage: lastResult.value.coverage_pct,
    features: lastResult.value.features,
    aoi: aoi.value,
    color: resultColor.value
  }
  history.value.push(item)
  saveName.value = ''
  persistHistory()
  ElMessage.success('已保存')
}

function showHistory(h: HistoryItem) {
  classType.value = h.classType
  aoi.value = [...h.aoi]
  lastResult.value = { ...lastResult.value, features: h.features, coverage_pct: h.coverage, datetime: h.datetime } as any
  resultColor.value = h.color
  renderResult(lastResult.value!)
  ElMessage.success(`已加载「${h.name}」`)
}

/** 点选记录：切换加入/移出播放清单 */
function togglePlaylist(h: HistoryItem) {
  const idx = playlistIds.value.indexOf(h.id)
  if (idx >= 0) {
    playlistIds.value.splice(idx, 1)
  } else {
    playlistIds.value.push(h.id)
  }
}

function removeFromPlaylist(h: HistoryItem) {
  playlistIds.value = playlistIds.value.filter((id) => id !== h.id)
}

function movePlaylist(idx: number, dir: number) {
  const arr = playlistIds.value
  const target = idx + dir
  if (target < 0 || target >= arr.length) return
  const tmp = arr[idx]
  arr[idx] = arr[target]
  arr[target] = tmp
}

/** 播放变化动画：按时间顺序逐帧切换（直接切换，无平滑过渡） */
function renderAnimationFrame() {
  const h = animationItems[animationIndex]
  if (!h) return
  clearResult()
  const color = h.color
  for (const f of h.features) {
    const geom = f.geometry
    if (!geom) continue
    const coords = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates
    for (const ring of coords) {
      resultEntities.push(viewer!.entities.add({
        polygon: {
          hierarchy: new PolygonHierarchy(ring[0].map(([lng, lat]: number[]) => Cartesian3.fromDegrees(lng, lat))),
          material: Color.fromCssColorString(color).withAlpha(resultOpacity.value / 100),
          height: 0, outline: true, outlineColor: Color.fromCssColorString(color)
        }
      }))
    }
  }
  viewer?.scene.requestRender()
  ElMessage.info(`${h.classLabel} · ${h.datetime.slice(0, 10)}`)
  animationIndex = (animationIndex + 1) % animationItems.length
}

function startAnimation() {
  const items = playlist.value
  if (items.length < 1) {
    ElMessage.warning('请先勾选记录加入播放清单')
    return
  }
  stopAnimation()
  animationItems = items
  animationIndex = 0
  renderAnimationFrame()
  animationTimer = setInterval(renderAnimationFrame, 1500)
  playing.value = true
}

function pauseAnimation() {
  if (animationTimer) { clearInterval(animationTimer); animationTimer = undefined }
  playing.value = false
}

/** 播放/暂停切换 */
function toggleAnimation() {
  if (playing.value) {
    pauseAnimation()
  } else {
    startAnimation()
  }
}

function stopAnimation() {
  if (animationTimer) { clearInterval(animationTimer); animationTimer = undefined }
  playing.value = false
}

// ---- 差异统计 ----
const diffRows = computed(() => {
  const items = playlist.value
  if (items.length < 2) return []
  const a = items[0]
  const b = items[1]
  // 同类才对比；不同类提示
  if (a.classType !== b.classType) return []
  const early = a.datetime <= b.datetime ? a : b
  const late = a.datetime <= b.datetime ? b : a
  const dCov = late.coverage - early.coverage
  const dArea = late.coverage - early.coverage // 覆盖率差（AOI 相同，覆盖率差即面积差比例）
  return [
    {
      label: '覆盖率(%)',
      earlyLabel: early.datetime.slice(0, 10),
      lateLabel: late.datetime.slice(0, 10),
      early: early.coverage.toFixed(2),
      late: late.coverage.toFixed(2),
      delta: (dCov >= 0 ? '+' : '') + dCov.toFixed(2),
      deltaColor: dCov >= 0 ? '#ef4444' : '#22c55e'
    },
    {
      label: '要素数',
      earlyLabel: early.datetime.slice(0, 10),
      lateLabel: late.datetime.slice(0, 10),
      early: String(early.features.length),
      late: String(late.features.length),
      delta: (late.features.length - early.features.length >= 0 ? '+' : '') + (late.features.length - early.features.length),
      deltaColor: late.features.length >= early.features.length ? '#ef4444' : '#22c55e'
    },
    {
      label: '变化面积占比',
      earlyLabel: early.datetime.slice(0, 10),
      lateLabel: late.datetime.slice(0, 10),
      early: '-',
      late: '-',
      delta: (dArea >= 0 ? '+' : '') + dArea.toFixed(2) + '%',
      deltaColor: dArea >= 0 ? '#ef4444' : '#22c55e'
    }
  ]
})

function showDiff() {
  const items = playlist.value
  if (items.length < 2) {
    ElMessage.warning('请先勾选两条记录加入播放清单')
    return
  }
  const a = items[0]
  const b = items[1]
  if (a.classType !== b.classType) {
    ElMessage.warning('请选择同一类型的两条记录（如都是植被）')
    return
  }
  // 双色叠加：早=红 晚=蓝
  const early = a.datetime <= b.datetime ? a : b
  const late = a.datetime <= b.datetime ? b : a
  clearResult()
  const renderItem = (h: HistoryItem, color: string) => {
    for (const f of h.features) {
      const geom = f.geometry
      if (!geom) continue
      const coords = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates
      for (const ring of coords) {
        resultEntities.push(viewer!.entities.add({
          polygon: {
            hierarchy: new PolygonHierarchy(ring[0].map(([lng, lat]: number[]) => Cartesian3.fromDegrees(lng, lat))),
            material: Color.fromCssColorString(color).withAlpha(0.45),
            height: 0, outline: true, outlineColor: Color.fromCssColorString(color)
          }
        }))
      }
    }
  }
  renderItem(early, '#ef4444')
  renderItem(late, '#3b82f6')
  viewer?.scene.requestRender()
  diffVisible.value = true
  ElMessage.info(`红 = ${early.datetime.slice(0, 10)}，蓝 = ${late.datetime.slice(0, 10)}`)
}

function persistHistory() {
  localStorage.setItem('rs_extract_history', JSON.stringify(history.value.map((h) => ({ ...h, ver: 2 }))))
}

function loadHistory() {
  try {
    const raw = localStorage.getItem('rs_extract_history')
    if (!raw) return
    const items: (HistoryItem & { ver?: number })[] = JSON.parse(raw)
    // ver<2 的旧记录坐标是修复前的 UTM 错误坐标，直接丢弃
    history.value = items.filter((h) => h.ver === 2).map(({ ver: _v, ...h }) => h)
  } catch { /* ignore */ }
}

function ringAreaHa(ring: number[][]): number {
  if (ring.length < 3) return 0
  const R = 6371000
  const lat0 = ring[0][1], lng0 = ring[0][0]
  const cosLat = Math.cos(lat0 * Math.PI / 180)
  let area = 0
  for (let i = 0; i < ring.length; i++) {
    const [x1d, y1d] = ring[i]
    const [x2d, y2d] = ring[(i + 1) % ring.length]
    const x1 = R * (x1d - lng0) * Math.PI / 180 * cosLat
    const y1 = R * (y1d - lat0) * Math.PI / 180
    const x2 = R * (x2d - lng0) * Math.PI / 180 * cosLat
    const y2 = R * (y2d - lat0) * Math.PI / 180
    area += x1 * y2 - x2 * y1
  }
  return Math.abs(area) / 2 / 10000
}
</script>

<style scoped>
.rs-page {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 14px;
  height: calc(100vh - 132px);
}
.map-wrap { position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #eceef2; }
.cesium-container { width: 100%; height: 100%; }

.map-toolbar {
  position: absolute; top: 12px; left: 12px;
  display: flex; align-items: center; gap: 10px;
  background: rgba(255,255,255,0.92); border-radius: 8px; padding: 8px 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12); z-index: 5;
}
.aoi-info { font-size: 12px; color: #0d9488; font-weight: 600; }

.layer-switch {
  position: absolute; top: 12px; right: 12px;
  background: rgba(255,255,255,0.92); border-radius: 8px; padding: 10px 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12); z-index: 5; width: 150px;
}
.ls-title { font-size: 12px; font-weight: 600; color: #4e5969; margin-bottom: 6px; }
.ls-row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; padding: 3px 0; color: #4e5969; }

.token-notice {
  position: absolute; top: 60px; left: 50%; transform: translateX(-50%);
  background: #fef3c7; color: #b45309; font-size: 12px; padding: 6px 12px; border-radius: 6px; z-index: 6;
}
.busy-mask {
  position: absolute; inset: 0; z-index: 8;
  background: rgba(0,0,0,0.45); display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 12px; color: #fff; font-size: 14px;
}
.busy-mask .el-icon { font-size: 32px; }

.side { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow-y: auto; }
.side-card { border: 1px solid #eceef2; border-radius: 10px; flex-shrink: 0; }
.side-title { font-size: 14px; font-weight: 600; }

.scene-info { margin-top: 10px; font-size: 12px; color: #4e5969; }
.si-row { display: flex; justify-content: space-between; padding: 2px 0; }
.si-row code { font-size: 11px; color: #0d9488; }

.class-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.class-item {
  border: 1px solid #e5e6eb; border-radius: 8px; padding: 8px 6px;
  text-align: center; font-size: 12px; cursor: pointer; color: #4e5969;
  display: flex; align-items: center; justify-content: center; gap: 5px;
  transition: all 0.15s;
}
.class-item:hover { border-color: #14b8a6; }
.class-item.active { border-color: #0d9488; background: #f0fdfa; color: #0d9488; font-weight: 600; }
.class-dot { width: 8px; height: 8px; border-radius: 50%; }
.threshold-hint { font-size: 11px; color: #a9aeb8; line-height: 1.4; }

.save-row { display: flex; gap: 8px; margin-bottom: 10px; }
.timeline { border-top: 1px dashed #eceef2; padding-top: 8px; }
.tl-title { font-size: 12px; font-weight: 600; color: #4e5969; margin-bottom: 6px; }
.empty { font-size: 12px; color: #a9aeb8; padding: 4px 0; }
.tl-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12px;
}
.tl-item:hover { background: #f2f7f6; }
.tl-item.picked { background: #f0fdfa; outline: 1px solid #14b8a6; }
.tl-name { color: #1f2329; font-weight: 500; flex: 1; margin: 0 6px; }
.tl-meta { color: #86909c; }
.tl-cov { color: #0d9488; font-weight: 600; }

.tl-group { margin-bottom: 6px; }
.tl-group-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: #4e5969;
  padding: 4px 0 2px;
}
.g-dot { width: 8px; height: 8px; border-radius: 50%; }
.g-count { color: #a9aeb8; font-weight: 400; font-size: 11px; }

.playlist { margin-top: 8px; border-top: 1px dashed #eceef2; padding-top: 8px; }
.pl-item {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: 6px; font-size: 12px; background: #fafbfc;
  margin-bottom: 4px;
}
.pl-idx {
  width: 18px; height: 18px; border-radius: 50%; background: #14b8a6; color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 11px; flex-shrink: 0;
}
.pl-name { flex: 1; color: #1f2329; }
.pl-ops { display: flex; align-items: center; gap: 2px; }

.style-panel { border: 1px dashed #e5e6eb; border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
.sp-row { display: flex; align-items: center; justify-content: space-between; padding: 3px 0; }
.sp-label { font-size: 12px; color: #4e5969; }

.compare-actions { display: flex; gap: 8px; margin-top: 8px; }

.diff-table { font-size: 13px; }
.diff-head, .diff-row {
  display: grid; grid-template-columns: 1.2fr 1fr 1fr 1fr;
  padding: 8px 6px; border-bottom: 1px solid #f0f0f0;
}
.diff-head { font-weight: 600; color: #1f2329; background: #fafbfc; border-radius: 6px 6px 0 0; }
.diff-row span { text-align: center; }
</style>

<template>
  <div class="imagery-page">
    <!-- 左侧：Cesium 地图 -->
    <div class="map-wrap">
      <div ref="cesiumRef" class="cesium-container"></div>

      <div class="map-toolbar">
        <el-button-group>
          <el-button size="small" @click="flyToMine">定位矿区</el-button>
          <el-button size="small" :type="drawing ? 'primary' : 'default'" @click="toggleDraw">
            {{ drawing ? '圈选中（右键结束）' : '绘制影像范围' }}
          </el-button>
          <el-button size="small" :disabled="draftBounds.length < 4" @click="clearDraft">
            清除范围
          </el-button>
        </el-button-group>
        <span v-if="draftBounds.length >= 4" class="draft-info">
          范围已绘制（{{ areaText }} km²）· CRS {{ form.crs }}
        </span>
      </div>

      <!-- 首次进入时的操作指引，避免不知道往哪圈 -->
      <div v-if="showGuide" class="guide-tip">
        <div class="guide-title">怎么圈影像范围</div>
        <ol class="guide-list">
          <li>先点<b>「定位矿区」</b>飞到矿区上空（宁都河源）</li>
          <li>如果影像就在矿区附近 → 直接点<b>「绘制影像范围」</b>，在地图上沿影像边缘点几下，右键结束</li>
          <li>不知道具体位置 → 切到<b>「检索公开数据」</b>，输入经纬度检索，点场景卡片会自动飞到影像范围</li>
        </ol>
        <button class="guide-close" @click="showGuide = false">知道了</button>
      </div>

      <!-- 影像 footprint 列表 -->
      <div class="imagery-overlay">
        <div class="overlay-title">影像覆盖范围（{{ imagery.length }}）</div>
        <div v-if="!imagery.length" class="overlay-empty">影像库暂无数据</div>
        <div
          v-for="img in imagery"
          :key="img.id"
          class="overlay-item"
          :class="{ active: selectedId === img.id }"
          @click="flyTo(img)"
        >
          <span class="dot" :class="img.source.toLowerCase()"></span>
          <div class="meta">
            <div class="name">{{ img.name }}</div>
            <div class="sub">
              {{ img.acquisitionDate }}
              <template v-if="img.cloudCover !== null && img.cloudCover !== undefined">
                · 云量 {{ img.cloudCover.toFixed(1) }}%
              </template>
              · {{ img.crs }}
            </div>
          </div>
        </div>
      </div>

      <div v-if="!hasToken" class="token-notice">未配置天地图密钥，底图未加载</div>
    </div>

    <!-- 右侧面板 -->
    <div class="side">
      <el-card shadow="never" class="side-card">
        <el-tabs v-model="activeTab">
          <!-- ============ 上传高分影像 ============ -->
          <el-tab-pane label="上传影像" name="upload">
            <el-form label-width="92px" size="small">
              <el-form-item label="影像文件" required>
                <input
                  ref="fileInput"
                  type="file"
                  accept=".tif,.tiff,.TIF,.TIFF"
                  class="file-input"
                  @change="onFileChange"
                />
              </el-form-item>

              <!-- 自动识别结果：GeoTIFF 自带这些信息，不用手填手画 -->
              <div v-if="probing" class="probe-loading">
                <el-icon class="is-loading"><Loading /></el-icon> 正在读取影像自带信息…
              </div>
              <el-descriptions
                v-if="probeInfo && !probeInfo.error"
                :column="1"
                size="small"
                border
                class="probe-desc"
              >
                <template #title>
                  <span class="probe-title">已自动识别</span>
                  <span class="probe-title-sub">影像已贴到地图上，可直接上传</span>
                </template>
                <el-descriptions-item label="坐标系">{{ probeInfo.crs || '未定义' }}</el-descriptions-item>
                <el-descriptions-item label="影像尺寸">
                  {{ probeInfo.width }} × {{ probeInfo.height }} 像素 · {{ probeInfo.bandCount }} 波段
                </el-descriptions-item>
                <el-descriptions-item label="地面分辨率">约 {{ probeInfo.resolutionM }} m</el-descriptions-item>
                <el-descriptions-item label="覆盖范围">
                  {{ probeInfo.areaKm2 }} km²
                  <span class="probe-hint">已自动画框并定位</span>
                </el-descriptions-item>
                <el-descriptions-item label="拍摄日期">
                  {{ probeInfo.acquisitionDate }}
                  <span class="probe-hint">{{ probeInfo.dateSource }}</span>
                </el-descriptions-item>
                <el-descriptions-item v-if="(probeInfo.warnings || []).length" label="提示">
                  <span v-for="(w, i) in probeInfo.warnings" :key="i" class="probe-warn">{{ w }}</span>
                </el-descriptions-item>
              </el-descriptions>

              <el-form-item label="显示名称">
                <el-input v-model="form.name" placeholder="默认用原文件名" clearable />
              </el-form-item>

              <!-- 坐标系：上传时由用户选择（原样记录，不猜测） -->
              <el-form-item label="坐标系" required>
                <el-select v-model="form.crs" placeholder="请选择影像坐标系" style="width: 100%">
                  <el-option
                    v-for="c in crsOptions"
                    :key="c.code"
                    :value="c.label"
                    :label="`${c.name}（${c.label}）`"
                  />
                </el-select>
              </el-form-item>
              <el-alert
                type="info"
                :closable="false"
                show-icon
                title="高分影像常见为 UTM 投影或 CGCS2000，选错会导致地图定位到几内亚湾"
                class="crs-tip"
              />

              <el-form-item label="拍摄日期" required>
                <el-date-picker
                  v-model="form.acquisitionDate"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="选择日期"
                  style="width: 100%"
                />
              </el-form-item>

              <el-form-item label="分辨率">
                <el-select v-model="form.resolutionM" style="width: 100%">
                  <el-option :value="0.8" label="0.8 m（高分二号等）" />
                  <el-option :value="2" label="2 m" />
                  <el-option :value="10" label="10 m（Sentinel-2）" />
                  <el-option :value="30" label="30 m（Landsat）" />
                </el-select>
              </el-form-item>

              <el-form-item label="数据源">
                <el-select v-model="form.source" style="width: 100%">
                  <el-option value="GF2" label="高分二号（GF-2）" />
                  <el-option value="GF7" label="高分七号（GF-7）" />
                </el-select>
              </el-form-item>

              <el-alert
                v-if="draftBounds.length < 4"
                type="warning"
                :closable="false"
                show-icon
                title="请先在地图上点击「绘制影像范围」标出影像覆盖范围"
                class="crs-tip"
              />
              <el-form-item>
                <el-button
                  type="primary"
                  :loading="uploading"
                  :disabled="!form.file || !form.acquisitionDate || draftBounds.length < 4"
                  @click="doUpload"
                >
                  上传并入库
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <!-- ============ 检索公开数据 ============ -->
          <el-tab-pane label="检索公开数据" name="search">
            <el-form label-width="92px" size="small">
              <el-form-item label="中心经度">
                <el-input-number v-model="searchForm.lng" :precision="4" :step="0.01" style="width: 100%" />
              </el-form-item>
              <el-form-item label="中心纬度">
                <el-input-number v-model="searchForm.lat" :precision="4" :step="0.01" style="width: 100%" />
              </el-form-item>
              <el-form-item label="时间范围">
                <el-date-picker
                  v-model="searchRange"
                  type="daterange"
                  value-format="YYYY-MM-DD"
                  start-placeholder="开始"
                  end-placeholder="结束"
                  style="width: 100%"
                />
              </el-form-item>
              <el-form-item label="最大云量">
                <el-slider v-model="searchForm.maxCloud" :min="0" :max="100" :step="5" show-input />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="searching" @click="doSearch">
                  检索 Sentinel-2 场景
                </el-button>
              </el-form-item>
              <el-alert
                type="info"
                :closable="false"
                show-icon
                title="数据来自欧空局 Copernicus 公开门户，无需注册。云量越低越适合指数法提取"
              />
            </el-form>

            <div v-if="scenes.length" class="scene-list">
              <div
                v-for="s in scenes"
                :key="s.productId"
                class="scene-item"
                :class="{ active: previewScene?.productId === s.productId }"
                @click="previewSceneOnMap(s)"
              >
                <div class="scene-head">
                  <span class="scene-date">{{ s.date }}</span>
                  <span class="scene-cloud" :class="{ good: s.cloudCover < 10 }">
                    云量 {{ s.cloudCover.toFixed(1) }}%
                  </span>
                </div>
                <div class="scene-sub">
                  {{ s.platform }} · 瓦片 {{ s.tileId }} · {{ s.level }} · {{ s.sizeMb }} MB
                </div>
              </div>
              <div class="scene-note">
                提示：整景约 {{ scenes[0]?.sizeMb }} MB，需服务端按 AOI 裁剪后解译；
                demo 阶段可先登记到影像库，再在「在线提取」圈选 AOI。
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <!-- 影像库列表 -->
      <el-card shadow="never" class="side-card">
        <template #header>
          <div class="list-header">
            <span>影像库</span>
            <el-select v-model="filterSource" size="small" style="width: 130px" @change="loadImagery">
              <el-option value="" label="全部来源" />
              <el-option value="UPLOAD" label="上传影像" />
              <el-option value="SENTINEL2" label="Sentinel-2" />
            </el-select>
          </div>
        </template>

        <el-table :data="sortedImagery" size="small" empty-text="暂无影像" @row-click="onRowClick">
          <el-table-column label="" width="42">
            <template #default="{ row }">
              <!-- 收藏星标：常用影像一键星标，下次排在最前 -->
              <span class="star" :class="{ on: row.favorite }" @click.stop="toggleFavorite(row)">
                {{ row.favorite ? '★' : '☆' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
          <el-table-column label="来源" width="96">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'UPLOAD' ? 'warning' : 'success'">
                {{ sourceLabel(row.source) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="acquisitionDate" label="日期" width="104" />
          <el-table-column v-if="canManage" label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openMeta(row)">元数据</el-button>
              <el-button link type="danger" size="small" @click="removeImagery(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert v-if="selectedId" type="success" :closable="false" show-icon class="selected-tip">
          <template #title>
            已选中「{{ selectedName }}」· 到「在线提取」页圈选 AOI 即可开始解译
          </template>
        </el-alert>
      </el-card>
    </div>

    <!-- 影像档案元数据：方案附录 B 要求的字段，客户问"合规吗、能训练吗"要靠这张表 -->
    <el-dialog v-model="metaVisible" title="影像档案元数据" width="720px">
      <div v-if="metaRow" class="meta-head">
        当前影像：<b>{{ metaRow.name }}</b>
        <span class="meta-sub">{{ metaRow.acquisitionDate }} · {{ metaRow.source }}</span>
      </div>
      <el-form :model="metaForm" label-width="112px" size="small" class="meta-form">
        <div class="meta-grid">
          <el-form-item label="离轴角(°)">
            <el-input-number v-model="metaForm.offNadirAngle" :min="0" :max="65" :step="0.5" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="太阳高度角(°)">
            <el-input-number v-model="metaForm.sunElevation" :min="0" :max="90" :step="1" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="太阳方位角(°)">
            <el-input-number v-model="metaForm.sunAzimuth" :min="0" :max="360" :step="1" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="正射等级">
            <el-select v-model="metaForm.orthoLevel" clearable placeholder="选择" style="width: 100%">
              <el-option label="RAW 原始" value="RAW" />
              <el-option label="L1T 粗校正" value="L1T" />
              <el-option label="L2A 大气校正" value="L2A" />
              <el-option label="ORTHO 正射" value="ORTHO" />
              <el-option label="OTHER 其它" value="OTHER" />
            </el-select>
          </el-form-item>
          <el-form-item label="授权范围">
            <el-select v-model="metaForm.licenseScope" clearable placeholder="选择" style="width: 100%">
              <el-option label="仅内部使用" value="INTERNAL" />
              <el-option label="可用于训练" value="TRAIN" />
              <el-option label="可公开发表" value="PUBLISH" />
              <el-option label="允许跨境传输" value="CROSS_BORDER" />
            </el-select>
          </el-form-item>
          <el-form-item label="传感器">
            <el-input v-model="metaForm.sensorName" placeholder="如 MSI / PMS / WFV" />
          </el-form-item>
          <el-form-item label="波段数">
            <el-input-number v-model="metaForm.bandCount" :min="1" :max="200" :step="1" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="供应商">
            <el-input v-model="metaForm.vendor" placeholder="影像来源方" />
          </el-form-item>
          <el-form-item label="采购单号">
            <el-input v-model="metaForm.orderNo" placeholder="合同/订单号" />
          </el-form-item>
          <el-form-item label="交付日期">
            <el-date-picker v-model="metaForm.deliveryDate" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
          </el-form-item>
          <el-form-item label="价格">
            <el-input-number v-model="metaForm.price" :min="0" :step="1000" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="币种">
            <el-select v-model="metaForm.priceCurrency" clearable placeholder="CNY" style="width: 100%">
              <el-option label="人民币 CNY" value="CNY" />
              <el-option label="美元 USD" value="USD" />
              <el-option label="欧元 EUR" value="EUR" />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <div class="meta-tip">
        留空表示该字段未登记。授权范围直接决定这批影像能不能用于模型训练、能不能对外发表，
        客户审计时会查这一项。
      </div>
      <template #footer>
        <el-button size="small" @click="metaVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="metaSaving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import {
  Viewer, Cartesian3, Color, ImageryLayer, Entity, ScreenSpaceEventHandler,
  ScreenSpaceEventType, Cartographic, CallbackProperty, PolygonHierarchy,
  Rectangle, SingleTileImageryProvider, Math as CesiumMath
} from 'cesium'
import { extractionApi, imageryApi } from '@/api'
import { haToKm2 } from '@/utils/format'
import { tiandituBaseLayers } from '@/map/basemap'
import { autoAdjustPerformance } from '@/map/perf'
import { TIANDITU_TOKEN, MINE_CENTER } from '@/config'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { Imagery, SceneItem, CrsOption } from '@/api/types'

const router = useRouter()
const auth = useAuthStore()
const projectStore = useProjectStore()
const canManage = computed(() => auth.hasAction('action:imagery-manage'))

const cesiumRef = ref<HTMLDivElement>()
const hasToken = !!TIANDITU_TOKEN
const activeTab = ref('upload')
/** 首次进入显示操作指引 */
const showGuide = ref(true)

const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)
const searching = ref(false)
const imagery = ref<Imagery[]>([])
const crsOptions = ref<CrsOption[]>([])
const filterSource = ref('')

const form = reactive({
  file: null as File | null,
  name: '',
  crs: '',
  acquisitionDate: null as string | null,
  resolutionM: 0.8,
  source: 'GF2'
})

const searchForm = reactive({ lng: 115.2, lat: 26.3, maxCloud: 15 })
const searchRange = ref<[string, string] | null>(['2023-01-01', '2023-12-31'])
const scenes = ref<SceneItem[]>([])
const previewScene = ref<SceneItem | null>(null)

const selectedId = ref<number | null>(null)
const selectedName = computed(() =>
  imagery.value.find((i) => i.id === selectedId.value)?.name || '')

let viewer: Viewer | null = null
let drawHandler: ScreenSpaceEventHandler | null = null
const drawing = ref(false)
const draftPts = ref<number[][]>([])
/** 草稿范围外接矩形 [w,s,e,n]，上传时随请求提交（统一 WGS84） */
const draftBounds = ref<number[]>([])
/** 自动识别的结果（展示给用户核对） */
const probeInfo = ref<any>(null)
const probing = ref(false)
/** probe 阶段已存的临时文件，上传时复用 */
const detectedPath = ref('')
let draftEntity: Entity | null = null
let sceneEntity: Entity | null = null
const footprintEntities = new Map<number, Entity>()

const areaText = computed(() => {
  const b = draftBounds.value
  if (b.length < 4) return ''
  const [w, s, e, n] = b
  const mLat = 110540
  const mLng = 111320 * Math.cos((s * Math.PI) / 180)
  const ha = ((e - w) * mLng) * ((n - s) * mLat) / 10000
  return (ha / 100).toFixed(2)
})

// ---------------- Cesium 初始化 ----------------

function initMap() {
  if (!cesiumRef.value) return

  // 底图：天地图影像 + 注记。tiandituBaseLayers 返回 { base, label } 对象，
  // 必须解构后包成 ImageryLayer —— 直接对该对象调 forEach 会抛错且底图加载不出来
  const layers = hasToken
    ? (() => {
        const { base, label } = tiandituBaseLayers('img')
        return [new ImageryLayer(base), new ImageryLayer(label)]
      })()
    : []

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
    selectionIndicator: false,
    creditContainer: document.createElement('div')
  })
  layers.forEach((l) => viewer!.imageryLayers.add(l))

  // 初始视角：斜俯视矿区（4km 高空、俯角 50°），既能看清地物又能感知起伏
  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.012, 4000),
    orientation: { heading: 0, pitch: CesiumMath.toRadians(-50) }
  })
  // 低配机帧率不足时自动降渲染精度
  autoAdjustPerformance(viewer)
}

onMounted(async () => {
  initMap()
  await Promise.all([loadImagery(), loadCrs()])
})

onBeforeUnmount(() => {
  drawHandler?.destroy()
  viewer?.destroy()
  viewer = null
})

watch(() => projectStore.currentId, () => loadImagery())

async function loadCrs() {
  try {
    crsOptions.value = await imageryApi.crsOptions()
    if (!form.crs && crsOptions.value.length) {
      form.crs = crsOptions.value[0].label
    }
  } catch {
    ElMessage.error('坐标系选项加载失败')
  }
}

async function loadImagery() {
  try {
    imagery.value = await imageryApi.list({
      projectId: projectStore.currentId ?? undefined,
      source: filterSource.value || undefined
    })
    redrawFootprints()
  } catch {
    imagery.value = []
  }
}

// ---------------- footprint 上图 ----------------

function rectPolygon(west: number, south: number, east: number, north: number) {
  return new PolygonHierarchy([
    Cartesian3.fromDegrees(west, south),
    Cartesian3.fromDegrees(east, south),
    Cartesian3.fromDegrees(east, north),
    Cartesian3.fromDegrees(west, north)
  ])
}

function redrawFootprints() {
  if (!viewer) return
  footprintEntities.forEach((e) => viewer!.entities.remove(e))
  footprintEntities.clear()
  imagery.value.forEach((img) => {
    const ent = viewer!.entities.add({
      polygon: {
        hierarchy: rectPolygon(img.west, img.south, img.east, img.north),
        material: Color.fromCssColorString('#22d3ee').withAlpha(0.12),
        outline: true,
        outlineColor: Color.fromCssColorString('#22d3ee'),
        height: 0
      }
    })
    footprintEntities.set(img.id, ent)
  })
}

function flyTo(img: Imagery) {
  if (!viewer) return
  selectedId.value = img.id
  viewer.camera.flyTo({
    destination: Rectangle.fromDegrees(img.west, img.south, img.east, img.north),
    duration: 1.2
  })
}

/** 飞到矿区上空：初始视角太高空看不到地物，给一个明确的落点 */
function flyToMine() {
  if (!viewer) return
  viewer.camera.flyTo({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.012, 4000),
    orientation: { heading: 0, pitch: CesiumMath.toRadians(-50) },
    duration: 1.5
  })
}

function onRowClick(row: Imagery) {
  flyTo(row)
}

// ---------------- 绘制影像范围 ----------------

function toggleDraw() {
  if (drawing.value) {
    drawing.value = false
    drawHandler?.destroy()
    drawHandler = null
    return
  }
  drawing.value = true
  draftPts.value = []
  const handler = new ScreenSpaceEventHandler(viewer!.scene.canvas)
  drawHandler = handler

  // 左侧点击：加顶点。必须用 Cesium 官方事件类型，取字段才是 position；
  // 自定义 { position } 接口在 RIGHT_CLICK 下取不到值（事件给的是 endPosition），
  // 会抛 DeveloperError: windowPosition is required
  handler.setInputAction((e: ScreenSpaceEventHandler.PositionedEvent) => {
    const pos = viewer?.camera.pickEllipsoid(e.position, viewer.scene.globe.ellipsoid)
    if (!pos) return
    const c = Cartographic.fromCartesian(pos)
    draftPts.value.push([
      CesiumMath.toDegrees(c.longitude),
      CesiumMath.toDegrees(c.latitude)
    ])
    updateDraft()
  }, ScreenSpaceEventType.LEFT_CLICK)

  // 右键：结束绘制（RIGHT_CLICK 事件带 endPosition）
  handler.setInputAction((e: ScreenSpaceEventHandler.MotionEvent) => {
    const pos = viewer?.camera.pickEllipsoid(e.endPosition, viewer.scene.globe.ellipsoid)
    if (pos) {
      const c = Cartographic.fromCartesian(pos)
      draftPts.value.push([
        CesiumMath.toDegrees(c.longitude),
        CesiumMath.toDegrees(c.latitude)
      ])
    }
    updateDraft()
    drawing.value = false
    handler.destroy()
    drawHandler = null
  }, ScreenSpaceEventType.RIGHT_CLICK)
}

function updateDraft() {
  if (!viewer) return
  if (draftEntity) {
    viewer.entities.remove(draftEntity)
    draftEntity = null
  }
  const pts = draftPts.value
  if (pts.length < 3) {
    draftBounds.value = []
    return
  }
  draftEntity = viewer.entities.add({
    polygon: {
      hierarchy: new CallbackProperty(
        () => new PolygonHierarchy(pts.map((p) => Cartesian3.fromDegrees(p[0], p[1]))),
        false),
      material: Color.fromCssColorString('#f59e0b').withAlpha(0.2),
      outline: true,
      outlineColor: Color.fromCssColorString('#f59e0b')
    }
  })
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  draftBounds.value = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}

function clearDraft() {
  removeImageryPreview()
  draftPts.value = []
  draftBounds.value = []
  if (viewer && draftEntity) {
    viewer.entities.remove(draftEntity)
    draftEntity = null
  }
}

// ---------------- 上传 ----------------

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  form.file = input.files?.[0] ?? null
  if (form.file && !form.name) form.name = form.file.name
  if (form.file) probeFile()
}

/** 影像自带坐标与日期：选完文件自动读出来填表、并把范围画到地图上 */
async function probeFile() {
  if (!form.file) return
  probing.value = true
  probeInfo.value = null
  try {
    const meta = await imageryApi.probe(form.file)
    if (meta.error) {
      ElMessage.warning(`未能自动识别：${meta.error}`)
      return
    }
    probeInfo.value = meta
    detectedPath.value = meta.storedPath || ''

    // 1) 坐标系
    if (meta.crs) form.crs = meta.crs
    // 2) 日期
    if (meta.acquisitionDate) form.acquisitionDate = meta.acquisitionDate
    // 3) 分辨率
    if (meta.resolutionM) form.resolutionM = normalizeRes(meta.resolutionM)
    // 4) 卫星
    if (meta.satellite === 'GF7' || meta.satellite === 'GF2') form.source = meta.satellite
    // 5) 范围 → 自动画矩形并飞过去
    if (meta.bounds) {
      const b = meta.bounds
      draftPts.value = [
        [b.west, b.south], [b.east, b.south], [b.east, b.north], [b.west, b.north]
      ]
      updateDraft()
      flyToBounds(b)
    }
    showImageryPreview(meta)
    const dateWarn = meta.dateSource && meta.dateSource.includes('请核对') ? '（日期建议核对）' : ''
    ElMessage.success(
      `已识别：${meta.crs || '无坐标系'} · ${meta.width}×${meta.height} · ${meta.bandCount} 波段 · 约 ${meta.resolutionM} m${dateWarn}`
    )
  } catch (err: any) {
    ElMessage.warning(err?.message || '自动识别失败，可手动填写')
  } finally {
    probing.value = false
  }
}

/** 分辨率下拉里没有精确值时按最近档位收口 */
function normalizeRes(v: number) {
  const options = [0.8, 2, 10, 30]
  return options.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a), options[0])
}

/** 影像预览图层：把 probe 生成的 PNG 按真实范围贴到地球上（用户要"看到影像"） */
let previewLayer: ImageryLayer | null = null

function showImageryPreview(meta: any) {
  if (!viewer || !meta?.bounds || !meta?.previewBase64) return
  removeImageryPreview()
  const b = meta.bounds
  previewLayer = viewer.imageryLayers.addImageryProvider(
    new SingleTileImageryProvider({
      url: 'data:image/png;base64,' + meta.previewBase64,
      rectangle: Rectangle.fromDegrees(b.west, b.south, b.east, b.north)
    })
  )
  viewer.scene.requestRender()
}

function removeImageryPreview() {
  if (previewLayer && viewer) {
    viewer.imageryLayers.remove(previewLayer, true)
    previewLayer = null
    viewer.scene.requestRender()
  }
}

function flyToBounds(b: { west: number; south: number; east: number; north: number }) {
  if (!viewer) return
  const cx = (b.west + b.east) / 2
  const cy = (b.south + b.north) / 2
  const span = Math.max(b.east - b.west, b.north - b.south)
  viewer.camera.flyTo({
    destination: Cartesian3.fromDegrees(cx, cy, Math.max(1500, span * 111000 * 1.8)),
    orientation: { heading: 0, pitch: CesiumMath.toRadians(-60) },
    duration: 1.0
  })
}

async function doUpload() {
  if (!form.file || !form.acquisitionDate || draftBounds.value.length < 4) return
  uploading.value = true
  try {
    const created = await imageryApi.upload({
      file: form.file,
      projectId: projectStore.currentId,
      name: form.name,
      crs: form.crs,
      acquisitionDate: form.acquisitionDate,
      resolutionM: form.resolutionM,
      bounds: draftBounds.value,
      existingPath: detectedPath.value || undefined
    })
    ElMessage.success(`影像已入库：${created.name}，正在进入提取…`)
    clearDraft()
    form.file = null
    if (fileInput.value) fileInput.value.value = ''
    form.name = ''
    form.acquisitionDate = null
    probeInfo.value = null
    detectedPath.value = ''
    await loadImagery()
    // 上传后直接跳到提取页并带上影像，省得手动切页面再选一遍
    goExtract(created.id)
  } catch (e) {
    ElMessage.error((e as Error).message || '上传失败')
  } finally {
    uploading.value = false
  }
}

/** 跳转到在线提取页并自动选中该影像（query 传 id，提取页读取后清掉） */
function goExtract(imageryId: number) {
  router.push({ path: '/extract', query: { imageryId: String(imageryId) } })
}

// ---------------- 公开场景检索 ----------------

async function doSearch() {
  if (!searchRange.value) {
    ElMessage.warning('请选择时间范围')
    return
  }
  searching.value = true
  try {
    scenes.value = await imageryApi.searchScenes({
      lng: searchForm.lng,
      lat: searchForm.lat,
      start: searchRange.value[0],
      end: searchRange.value[1],
      maxCloud: searchForm.maxCloud
    })
    if (!scenes.value.length) {
      ElMessage.warning('该区域该时间段内无满足云量条件的场景')
    }
  } catch (e) {
    ElMessage.error('检索失败：' + ((e as Error).message || '公开数据源不可达'))
  } finally {
    searching.value = false
  }
}

function previewSceneOnMap(s: SceneItem) {
  previewScene.value = s
  if (!viewer) return
  const [w, so, e, n] = s.bounds
  viewer.camera.flyTo({
    destination: Rectangle.fromDegrees(w, so, e, n),
    duration: 1.2
  })
  if (sceneEntity) viewer.entities.remove(sceneEntity)
  sceneEntity = viewer.entities.add({
    polygon: {
      hierarchy: rectPolygon(w, so, e, n),
      material: Color.fromCssColorString('#f97316').withAlpha(0.18),
      outline: true,
      outlineColor: Color.fromCssColorString('#f97316')
    }
  })
}

/**
 * 删除影像：先查关联解译记录数。
 * 有数据时提示"一并移入回收站"，避免删完影像留下一堆孤儿解译记录。
 */
async function removeImagery(img: Imagery) {
  try {
    let related = 0
    try {
      related = await extractionApi.countByImagery(img.id)
    } catch {
      related = 0
    }
    if (related > 0) {
      await ElMessageBox.confirm(
        `该影像关联 ${related} 条解译记录。删除影像会把这些解译记录一并移入回收站（可在「回收站」还原）。是否继续？`,
        '确认删除',
        { type: 'warning', confirmButtonText: '一并删除', cancelButtonText: '取消' }
      )
      await extractionApi.trashByImagery(img.id)
    } else {
      await ElMessageBox.confirm('确定删除该影像？', '确认删除', { type: 'warning' })
    }
    await imageryApi.remove(img.id)
    ElMessage.success(related > 0 ? `已删除，${related} 条解译记录已移入回收站` : '已删除')
    await loadImagery()
  } catch (e: any) {
    // 用户取消不算错误
    if (e === 'cancel' || e?.message === 'cancel') return
    ElMessage.error(e?.message || '删除失败')
  }
}

/** 收藏优先排序：星标影像排最前，其余按日期降序 */
const sortedImagery = computed(() =>
  [...imagery.value].sort((a, b) => {
    const fa = a.favorite ? 1 : 0
    const fb = b.favorite ? 1 : 0
    if (fa !== fb) return fb - fa
    return String(b.acquisitionDate || '').localeCompare(String(a.acquisitionDate || ''))
  })
)

/** 切换收藏（星标常用影像） */
async function toggleFavorite(img: Imagery) {
  try {
    const updated = await imageryApi.toggleFavorite(img.id)
    img.favorite = updated.favorite
    ElMessage.success(updated.favorite ? '已加入收藏' : '已取消收藏')
  } catch {
    ElMessage.error('操作失败')
  }
}

function sourceLabel(s: string) {
  return { UPLOAD: '上传', SENTINEL2: 'Sentinel-2', LANDSAT9: 'Landsat-9', GF2: 'GF-2' }[s] || s
}

// ---- 影像档案元数据 ----
const metaVisible = ref(false)
const metaSaving = ref(false)
const metaRow = ref<Imagery | null>(null)
const metaForm = reactive<Record<string, any>>({
  offNadirAngle: null, sunElevation: null, sunAzimuth: null,
  orthoLevel: '', licenseScope: '', sensorName: '', bandCount: null,
  vendor: '', orderNo: '', deliveryDate: '', price: null, priceCurrency: 'CNY'
})

function openMeta(row: Imagery) {
  metaRow.value = row
  metaForm.offNadirAngle = row.offNadirAngle ?? null
  metaForm.sunElevation = row.sunElevation ?? null
  metaForm.sunAzimuth = row.sunAzimuth ?? null
  metaForm.orthoLevel = row.orthoLevel || ''
  metaForm.licenseScope = row.licenseScope || ''
  metaForm.sensorName = row.sensorName || ''
  metaForm.bandCount = row.bandCount ?? null
  metaForm.vendor = row.vendor || ''
  metaForm.orderNo = row.orderNo || ''
  metaForm.deliveryDate = row.deliveryDate || ''
  metaForm.price = row.price ?? null
  metaForm.priceCurrency = row.priceCurrency || 'CNY'
  metaVisible.value = true
}

async function saveMeta() {
  if (!metaRow.value) return
  metaSaving.value = true
  try {
    await imageryApi.updateMetadata(metaRow.value.id, { ...metaForm })
    ElMessage.success('元数据已保存')
    metaVisible.value = false
    await loadImagery()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    metaSaving.value = false
  }
}
</script>

/* 自动识别结果 */
.probe-desc { margin: 0 0 12px; }
.probe-desc :deep(.el-descriptions__header) { margin-bottom: 6px; }
.probe-title { font-size: 12px; font-weight: 600; color: #0f766e; }
.probe-title-sub { font-size: 11px; color: #a9aeb8; margin-left: 8px; font-weight: 400; }
.probe-desc :deep(.el-descriptions__label) { width: 76px; color: #6b7280; font-size: 11px; }
.probe-desc :deep(.el-descriptions__content) { font-size: 12px; color: #1f2937; }
.probe-hint { font-size: 10px; color: #a9aeb8; margin-left: 6px; }
.probe-loading {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 10px; padding: 8px 10px; border-radius: 6px;
  background: #f8fafb; border: 1px solid #eef0f3; font-size: 12px; color: #6b7280;
}
.probe-warn { display: block; font-size: 10px; color: #b45309; line-height: 1.5; }

/* 旧样式（保留避免影响其它引用） */
.probe-box {
  margin: 0 0 10px; padding: 8px 10px; border-radius: 6px;
  background: #f0fdfa; border: 1px solid #ccfbf1; font-size: 12px; color: #0f766e;
}
.probe-box.loading { color: #6b7280; background: #f8fafb; border-color: #eef0f3; }
.probe-title { font-weight: 600; margin-bottom: 4px; }
.probe-row { display: flex; justify-content: space-between; gap: 10px; padding: 1px 0; }
.probe-row b { color: #134e4a; font-weight: 500; }
.probe-src { font-size: 10px; color: #6b7280; margin-left: 6px; font-weight: 400; }
.probe-warn { font-size: 10px; color: #b45309; margin-top: 3px; line-height: 1.5; }

<style scoped>
/* 影像档案元数据弹窗 */
.meta-head { font-size: 13px; color: #1f2937; margin-bottom: 12px; }
.meta-sub { font-size: 11px; color: #a9aeb8; margin-left: 8px; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.meta-form :deep(.el-form-item) { margin-bottom: 12px; }
.meta-tip { font-size: 11px; color: #b45309; line-height: 1.7; margin-top: 4px; }
.star {
  font-size: 15px; color: #c9cdd4; cursor: pointer;
  line-height: 1; user-select: none; display: inline-block;
}
.star:hover { color: #f59e0b; }
.star.on { color: #f59e0b; }

.imagery-page {
  display: flex;
  height: 100%;
  gap: 12px;
  padding: 12px;
  box-sizing: border-box;
}
.map-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  border-radius: 8px;
  overflow: hidden;
  background: #0b1220;
}
.cesium-container {
  width: 100%;
  height: 100%;
}
.map-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}
.draft-info {
  font-size: 12px;
  color: #0d9488;
  font-weight: 600;
}
.guide-tip {
  position: absolute;
  top: 58px;
  right: 12px;
  z-index: 6;
  width: 290px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid var(--el-color-warning);
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  color: var(--el-text-color-primary);
}
.guide-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--el-color-warning-dark-2);
  margin-bottom: 8px;
}
.guide-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
}
.guide-list b {
  color: var(--el-color-primary);
  font-weight: 500;
}
.guide-close {
  margin-top: 10px;
  width: 100%;
  padding: 5px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.guide-close:hover {
  background: var(--el-fill-color);
}
.imagery-overlay {
  position: absolute;
  top: 58px;
  left: 12px;
  z-index: 5;
  width: 250px;
  max-height: calc(100% - 140px);
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}
.overlay-title {
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-bottom: 6px;
}
.overlay-empty {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.overlay-item {
  display: flex;
  gap: 8px;
  padding: 6px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--el-text-color-primary);
}
.overlay-item:hover,
.overlay-item.active {
  background: rgba(13, 148, 136, 0.12);
}
.overlay-item .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
  background: #22d3ee;
}
.overlay-item .dot.upload {
  background: #f59e0b;
}
.overlay-item .meta {
  min-width: 0;
}
.overlay-item .name {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.overlay-item .sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.token-notice {
  position: absolute;
  bottom: 12px;
  left: 12px;
  font-size: 12px;
  color: var(--el-color-warning);
  background: rgba(255, 255, 255, 0.92);
  padding: 4px 8px;
  border-radius: 4px;
}
.side {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}
.side-card {
  flex-shrink: 0;
}
.file-input {
  width: 100%;
  font-size: 12px;
}
.crs-tip {
  margin-bottom: 10px;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.scene-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.scene-item {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 8px;
  cursor: pointer;
}
.scene-item:hover,
.scene-item.active {
  border-color: #f97316;
  background: rgba(249, 115, 22, 0.08);
}
.scene-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
}
.scene-cloud {
  color: var(--el-color-danger);
  font-size: 12px;
}
.scene-cloud.good {
  color: var(--el-color-success);
}
.scene-sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.scene-note {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.selected-tip {
  margin-top: 10px;
}
</style>
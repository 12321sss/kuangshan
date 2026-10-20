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
        <!-- 复用上次 AOI：保证与历史记录的区域指纹一致，时序/对比才能正确匹配 -->
        <el-button size="small" :disabled="!lastAoiAvailable" @click="reuseLastAoi">复用上次 AOI</el-button>
        <span v-if="aoiAreaText" class="aoi-info">AOI {{ aoiAreaText }}</span>
        <el-divider direction="vertical" />
        <el-button size="small" :loading="demoLoading" @click="loadDemo">一键载入演示数据</el-button>
        <el-divider direction="vertical" />
        <el-button size="small" type="warning" plain :loading="terrainLoading" :disabled="aoi.length < 3" @click="doTerrain">
          地形分析
        </el-button>
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
        <div class="ls-row">
          <span>矿权边界</span>
          <el-switch v-model="showBoundary" size="small" @change="toggleBoundary" />
        </div>
        <div class="ls-row">
          <span>坡度图</span>
          <el-switch v-model="showSlope" size="small" :disabled="!terrainResult" @change="toggleSlope" />
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
        <span class="busy-title">{{ busyText }}</span>
        <!-- 分阶段进度 -->
        <div class="busy-steps">
          <div v-for="(s, i) in stageSteps" :key="s" class="busy-step" :class="{ done: i < stageIndex, active: i === stageIndex }">
            <span class="bs-dot"></span>
            <span>{{ s }}</span>
          </div>
        </div>
        <span v-if="busyHint" class="busy-hint">{{ busyHint }}</span>
      </div>
    </div>

    <!-- 右侧面板 -->
    <div class="side">
      <!-- 向导步骤条 -->
      <el-card shadow="never" class="side-card step-card">
        <el-steps :active="activeStep" align-center finish-status="success" :space="80">
          <el-step title="圈范围" />
          <el-step title="选影像" />
          <el-step title="提取" />
          <el-step title="保存" />
        </el-steps>
      </el-card>

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
          <el-form-item label="波段组合">
            <el-select v-model="combo" style="width: 100%" @change="onComboChange">
              <el-option v-for="c in comboOptions" :key="c.value" :label="c.label" :value="c.value">
                <span>{{ c.label }}</span>
                <span style="float:right;color:#a9aeb8;font-size:11px">{{ c.hint }}</span>
              </el-option>
            </el-select>
            <div class="threshold-hint">{{ comboHint }}</div>
          </el-form-item>
          <el-button type="primary" style="width: 100%" :loading="previewing" :disabled="aoi.length < 3" @click="doPreview">
            查询影像
          </el-button>
          <div v-if="sceneInfo" class="scene-info">
            <div class="si-row"><span>景 ID</span><code>{{ sceneInfo.scene_id }}</code></div>
            <div class="si-row"><span>日期</span>{{ (sceneInfo.datetime || '').slice(0, 10) }}</div>
            <div class="si-row"><span>云量</span><span :style="{ color: cloudWarn ? '#f59e0b' : '#4e5969' }">{{ sceneInfo.cloud_cover }}%{{ cloudWarn ? ' ⚠' : '' }}</span></div>
          </div>
          <!-- 云量偏高提示 -->
          <el-alert v-if="cloudWarn" type="warning" :closable="false" style="margin-top:8px"
                    title="本期云量偏高，解译结果可能受云影响" />
        </el-form>
      </el-card>

      <!-- 提取卡片 -->
      <el-card shadow="never" class="side-card" :class="{ 'step-disabled': activeStep < 1 }">
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
        <el-button type="success" style="width: 100%" :loading="extracting" :disabled="aoi.length < 3 || !sceneInfo" @click="doExtract">
          开始提取
        </el-button>
        <el-button
          style="width: 100%; margin-top: 8px"
          :loading="extracting"
          :disabled="aoi.length < 3 || !sceneInfo"
          @click="doBatchExtract"
        >
          批量提取全部类型
        </el-button>
        <!-- 批量结果汇总 -->
        <div v-if="batchResults.length" class="batch-sum">
          <div class="bs-title">本次批量结果</div>
          <div v-for="b in batchResults" :key="b.classType" class="bs-row">
            <span class="bs-dot" :style="{ background: b.color }"></span>
            <span class="bs-label">{{ b.label }}</span>
            <span class="bs-val">{{ b.coverage }}%</span>
            <span class="bs-cnt">{{ b.count }} 片</span>
          </div>
        </div>
        <div v-if="!sceneInfo && aoi.length >= 3" class="threshold-hint" style="margin-top:6px">
          请先点上方「查询影像」加载影像，再开始提取
        </div>
        <div v-else-if="classType === 'PIT' || classType === 'DUMP' || classType === 'TAILINGS'" class="threshold-hint" style="margin-top:6px">
          提示：采坑/排土场/尾矿需在确有露天开采的区域才有效；三者光谱高度重叠，按亮度分层区分，结果建议人工复核
        </div>
      </el-card>

      <!-- 地形与安全指标（DEM） -->
      <el-card v-if="terrainResult" shadow="never" class="side-card">
        <template #header>
          <div class="terrain-head">
            <span class="side-title">地形与安全指标</span>
            <span class="terrain-src">{{ terrainResult.precision.source }}</span>
          </div>
        </template>
        <div class="terrain-kpi">
          <div class="tk">
            <div class="tk-num">{{ terrainResult.summary.elevMin }}~{{ terrainResult.summary.elevMax }}</div>
            <div class="tk-label">高程范围(m)</div>
          </div>
          <div class="tk">
            <div class="tk-num">{{ terrainResult.summary.reliefM }}</div>
            <div class="tk-label">地形起伏(m)</div>
          </div>
          <div class="tk">
            <div class="tk-num">{{ terrainResult.summary.slopeMean }}°</div>
            <div class="tk-label">平均坡度</div>
          </div>
          <div class="tk">
            <div class="tk-num" :class="{ warn: terrainResult.summary.steepPct > 15 }">
              {{ terrainResult.summary.steepPct }}%
            </div>
            <div class="tk-label">陡坡(&ge;15°)占比</div>
          </div>
        </div>

        <!-- 坡度分级条 -->
        <div class="slope-bar">
          <div
            v-for="d in terrainResult.summary.distribution"
            :key="d.label"
            class="sb-seg"
            :style="{ width: d.pct + '%', background: slopeColorOf(d.label) }"
            :title="`${d.label} ${d.pct}%`"
          ></div>
        </div>
        <div class="slope-legend">
          <span v-for="d in terrainResult.summary.distribution" :key="d.label" class="sl-item">
            <i :style="{ background: slopeColorOf(d.label) }"></i>{{ d.label }} {{ d.pct }}%
          </span>
        </div>

        <div class="terrain-note">
          低洼汇水候选占 {{ terrainResult.pond.areaPct }}%：邻域高程显著偏低的平坦区，
          需结合排水设施与影像复核（筛查指标，非水文模型汇流结果）。
        </div>
        <div class="terrain-warn">{{ terrainResult.precision.limitation }}</div>
      </el-card>

      <!-- 结果样式 + 保存 + 变化对比 -->
      <el-card shadow="never" class="side-card" :class="{ 'step-disabled': activeStep < 2 }">
        <template #header><span class="side-title">3. 结果与变化</span></template>

        <!-- 结果样式：颜色 + 透明度 + 证据等级 -->
        <div v-if="lastResult" class="style-panel">
          <div class="sp-row">
            <span class="sp-label">结果颜色</span>
            <el-color-picker v-model="resultColor" size="small" @change="onStyleChange" />
          </div>
          <div class="sp-row">
            <span class="sp-label">透明度</span>
            <el-slider v-model="resultOpacity" :min="10" :max="100" size="small" @input="onStyleChange" />
          </div>
          <div class="sp-row">
            <span class="sp-label">证据等级</span>
            <el-tag :type="evidenceLevel.type" size="small">{{ evidenceLevel.label }}</el-tag>
          </div>
          <div class="evidence-hint">{{ evidenceLevel.hint }}</div>
          <!-- 判别方法 + 局限声明：让结果可解释、可复核 -->
          <div v-if="lastResult.method" class="method-note">
            判别方法：{{ lastResult.method }}
          </div>
          <div v-if="lastResult.shapeStats && lastResult.feature_count > 0" class="method-note">
            总面积 {{ lastResult.shapeStats.totalAreaHa }} ha ·
            最大斑块 {{ lastResult.shapeStats.maxAreaHa }} ha ·
            平均长宽比 {{ lastResult.shapeStats.avgAspectRatio }}
          </div>
          <div v-if="lastResult.disclaimer" class="warn-note">{{ lastResult.disclaimer }}</div>
        </div>

        <!-- 保存 -->
        <div class="save-row">
          <el-input v-model="saveName" placeholder="记录名称（留空自动生成）" size="small" />
          <el-button size="small" type="primary" :disabled="!lastResult" @click="saveResult">保存</el-button>
        </div>

        <!-- 导出 -->
        <div v-if="lastResult" class="export-row">
          <el-button size="small" @click="exportGeoJson">导出 GeoJSON</el-button>
          <el-button size="small" @click="exportGeoTiff">导出 GeoTIFF</el-button>
        </div>

        <!-- 保存为关注区：圈一次，之后持续跟踪这块地的变化 -->
        <div v-if="aoi.length >= 3" class="watch-row">
          <el-button size="small" type="warning" plain @click="saveAsWatch">
            保存为关注区（持续跟踪）
          </el-button>
        </div>

        <!-- 我的关注区列表 -->
        <div v-if="watches.length" class="timeline watch-list">
          <div class="tl-title">我的关注区</div>
          <div v-for="w in watches" :key="w.id" class="watch-item">
            <div class="w-line1">
              <span class="w-name">{{ w.name }}</span>
              <span class="w-tag">{{ classLabelOf(w.classType) }}</span>
              <span class="w-meta">{{ w.periodCount }} 期</span>
            </div>
            <div class="w-line2">
              <span class="w-meta">{{ w.latestDate || '暂无解译' }}</span>
              <span v-if="w.latestAreaHa != null" class="w-area">
                {{ haToKm2(w.latestAreaHa) }} km²
              </span>
            </div>
            <div class="w-ops">
              <el-button size="small" text @click="locateWatch(w)">定位</el-button>
              <el-button size="small" text type="primary" @click="checkWatch(w)">检查变化</el-button>
              <el-button size="small" text type="danger" @click="removeWatch(w)">删除</el-button>
            </div>
          </div>
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
    <el-dialog v-model="diffVisible" title="跨年份变化对比" width="560px">
      <!-- 热力图图例 -->
      <div v-if="heatmapResult" class="heatmap-legend">
        <span class="lg-item"><i class="lg-dot" style="background:#ef4444"></i>新增扰动 {{ heatmapResult.addedAreaHa.toFixed(2) }} ha</span>
        <span class="lg-item"><i class="lg-dot" style="background:#22c55e"></i>消失/复绿 {{ heatmapResult.removedAreaHa.toFixed(2) }} ha</span>
        <span class="lg-item"><i class="lg-dot" style="background:#9ca3af"></i>不变区域</span>
      </div>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import {
  Viewer, Cartesian3, Color, ImageryLayer, Entity,
  ScreenSpaceEventHandler, ScreenSpaceEventType, Cartographic,
  CallbackProperty, PolygonHierarchy, SingleTileImageryProvider, Rectangle
} from 'cesium'
import { sentinelApi, terrainApi } from '@/api/sentinel'
import { haToKm2 } from '@/utils/format'
import { extractionApi, projectApi, aoiWatchApi } from '@/api'
import { useProjectStore } from '@/stores/project'
import type { ExtractResult, PreviewResult, DiffHeatmapResult, TerrainResult } from '@/api/sentinel'
import type { Extraction } from '@/api/types'
import { tiandituBaseLayers, gaodeSatelliteProvider } from '@/map/basemap'
import { autoAdjustPerformance } from '@/map/perf'
import { TIANDITU_TOKEN, MINE_CENTER } from '@/config'

const projectStore = useProjectStore()

const cesiumRef = ref<HTMLDivElement>()
const hasToken = !!TIANDITU_TOKEN

const startDate = ref('2024-06-01')
const endDate = ref('2024-12-31')
const maxCloud = ref(30)
/** 波段组合：不同组合凸显不同地物，是遥感判读的基本手段 */
const combo = ref('TRUE_COLOR')
const comboOptions = [
  { value: 'TRUE_COLOR', label: '真彩色', hint: '接近肉眼所见' },
  { value: 'FALSE_COLOR', label: '标准假彩色', hint: '植被显红' },
  { value: 'NDVI', label: 'NDVI 植被指数', hint: '长势分级配色' },
  { value: 'SWIR', label: '短波红外', hint: '水体暗·裸地亮' },
  { value: 'URBAN', label: '城市裸地', hint: '建筑裸土偏青' }
]
const comboHint = computed(
  () => comboOptions.find((c) => c.value === combo.value)?.hint || ''
)

/** 切换波段组合：已加载过影像就重新渲染，避免用户再点一次查询 */
function onComboChange() {
  if (sceneInfo.value && aoi.value.length >= 3) {
    doPreview()
  }
}
const classType = ref('VEGETATION')
const threshold = ref<number | undefined>(undefined)
const minArea = ref(20)
const saveName = ref('')
const resultColor = ref('#22c55e')
const resultOpacity = ref(50)
const playlistIds = ref<string[]>([])
const diffVisible = ref(false)
const diffLoading = ref(false)
const heatmapVisible = ref(false)
const heatmapResult = ref<DiffHeatmapResult | null>(null)
const demoLoading = ref(false)
const playing = ref(false)
// AOI 关注区（监测订阅）
const watches = ref<Array<{
  id: number
  name: string
  classType: string
  aoiJson: string
  periodCount: number
  latestDate?: string | null
  latestAreaHa?: number | null
}>>([])
// 地形分析
const terrainLoading = ref(false)
const terrainResult = ref<TerrainResult | null>(null)
const showSlope = ref(false)
let animationTimer: ReturnType<typeof setInterval> | undefined
let animationItems: HistoryItem[] = []
let animationIndex = 0

const aoi = ref<number[][]>([])
const drawing = ref(false)
const showClipped = ref(true)
const showResult = ref(true)
const showBoundary = ref(false)
const basemap = ref<'tdt' | 'gaode'>('tdt')
const busy = ref(false)
const busyText = ref('')
const busyHint = ref('')
const stageIndex = ref(0)
const stageSteps = ref<string[]>([])
const previewing = ref(false)
const extracting = ref(false)
const sceneInfo = ref<{ scene_id: string; datetime: string; cloud_cover: number } | null>(null)
const lastResult = ref<ExtractResult | null>(null)

/** 向导步骤：0=圈范围 1=选影像 2=提取 3=保存 */
const activeStep = computed(() => {
  if (lastResult.value) return 3
  if (sceneInfo.value) return 2
  if (aoi.value.length >= 3) return 1
  return 0
})

/** 云量偏高提示（>=20% 提示，>=40% 更强提示） */
const cloudWarn = computed(() => {
  const c = sceneInfo.value?.cloud_cover
  return c !== undefined && c >= 20
})

/** 证据等级：Sentinel-2/Landsat(10-30m)=B级，GF-2/GF-7等亚米级=A级 */
const evidenceLevel = computed(() => {
  // 在线提取固定 Sentinel-2（10m），故为 B 级
  return {
    label: 'B 级（10m 分辨率）',
    type: 'warning' as 'warning',
    hint: '当前为 Sentinel-2 10m 分辨率结果，可识别采坑/排土场/植被等大尺度地物；如需识别道路级细节，请使用亚米级商业影像。'
  }
})

/** 七类矿山地物：严格对齐实施方案表 6 的分类体系 */
const classOptions = [
  { value: 'PIT', label: '露天采坑', color: '#ef4444', thr: 0.16 },
  { value: 'DUMP', label: '排土场', color: '#f59e0b', thr: 0.10 },
  { value: 'TAILINGS', label: '尾矿设施', color: '#8b5cf6', thr: 0.24 },
  { value: 'BARE', label: '裸地扰动', color: '#a8a29e', thr: 0.0 },
  { value: 'VEGETATION', label: '植被', color: '#22c55e', thr: 0.25 },
  { value: 'ROAD', label: '道路/设施', color: '#64748b', thr: 0.12 },
  { value: 'WATER', label: '水体', color: '#3b82f6', thr: 0.0 }
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
let slopeLayer: ImageryLayer | null = null
let boundaryEntities: Entity[] = []

const aoiAreaText = computed(() => {
  if (aoi.value.length < 3) return ''
  return haToKm2(ringAreaHa(aoi.value)) + ' km²'
})

// ---- 地图初始化 ----
onMounted(() => {
  loadHistory()
  loadWatches()
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
  // 低配机帧率不足时自动降渲染精度（Quadro K2200 等）
  autoAdjustPerformance(viewer)
  loadBoundary()
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

function toggleBoundary(v: boolean) {
  boundaryEntities.forEach((e) => (e.show = v))
  viewer?.scene.requestRender()
}

/** 加载矿权/扰动/生态边界（三图层） */
async function loadBoundary() {
  if (!projectStore.currentId || !viewer) return
  try {
    const json = await projectApi.boundary(projectStore.currentId)
    if (!json || json === '{}') return
    const b = JSON.parse(json)
    clearBoundary()
    const layers: Array<{ key: string; color: string; alpha: number; label: string }> = [
      { key: 'mining', color: '#ef4444', alpha: 0.15, label: '矿权红线' },
      { key: 'disturbance', color: '#f59e0b', alpha: 0.25, label: '扰动边界' },
      { key: 'ecological', color: '#22c55e', alpha: 0.15, label: '生态红线' }
    ]
    for (const l of layers) {
      const ring = b[l.key]
      if (!ring || ring.length < 3) continue
      const entity = viewer.entities.add({
        polygon: {
          hierarchy: new PolygonHierarchy(ring.map(([lng, lat]: number[]) => Cartesian3.fromDegrees(lng, lat))),
          material: Color.fromCssColorString(l.color).withAlpha(l.alpha),
          height: 0,
          outline: true,
          outlineColor: Color.fromCssColorString(l.color)
        },
        name: l.label
      })
      boundaryEntities.push(entity)
    }
    // 默认关闭，用户手动开
    boundaryEntities.forEach((e) => (e.show = showBoundary.value))
    viewer.scene.requestRender()
  } catch {
    // 无边界数据时静默
  }
}

function clearBoundary() {
  boundaryEntities.forEach((e) => viewer?.entities.remove(e))
  boundaryEntities = []
}

onBeforeUnmount(() => {
  stopAnimation()
  clearBoundary()
  drawHandler?.destroy()
  viewer?.destroy()
  viewer = null
})

// 切换项目：重载边界与历史
watch(() => projectStore.currentId, () => {
  loadBoundary()
  loadHistory()
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
  busyText.value = '正在加载卫星影像'
  busyHint.value = '首次拉取需从 AWS 下载影像（约 1-10 分钟），之后有本地缓存会快很多'
  stageSteps.value = ['检索无云影像', '下载影像波段', '合成真彩图']
  stageIndex.value = 0
  try {
    const res: PreviewResult = await sentinelApi.preview(
      aoi.value, startDate.value, endDate.value, maxCloud.value, combo.value)
    stageIndex.value = 2
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
    ElMessage.error(friendlyError(e))
  } finally {
    previewing.value = false
    busy.value = false
  }
}

/** 把后端/网络错误映射成中文友好提示 */
function friendlyError(e: any): string {
  const msg = String(e?.message || e || '')
  if (!msg) return '操作失败，请重试'
  if (msg.includes('无可用') || msg.includes('无可用的无云影像') || msg.includes('无云影像')) {
    return '该区域、该日期范围内没有可用的无云影像，请放宽日期范围或调高云量阈值'
  }
  if (msg.includes('检索失败') || msg.includes('Sentinel-2 检索')) {
    return '影像检索失败，可能是网络问题，请稍后重试'
  }
  if (msg.includes('网络') || msg.includes('Network') || msg.includes('ECONN') || msg.includes('timeout') || msg.includes('超时')) {
    return '网络连接异常或超时，请检查网络后重试'
  }
  if (msg.includes('不支持') || msg.includes('类别')) {
    return '不支持该地物类型或数据源'
  }
  if (msg.includes('剪切失败')) {
    return '影像剪切失败，请尝试缩小圈选范围'
  }
  // 兜底：保留原消息但去掉技术性堆栈
  return msg.length > 80 ? msg.slice(0, 80) + '…' : msg
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
/** 批量提取结果：每类地物的覆盖率/要素数，汇总展示 */
const batchResults = ref<Array<{
  classType: string
  label: string
  color: string
  coverage: number
  count: number
}>>([])

/**
 * 批量提取：一次跑完全部地物类型，不同颜色叠加到地图上。
 * 客户看整片矿区时，不用逐个类型点五遍。
 */
async function doBatchExtract() {
  if (aoi.value.length < 3 || !sceneInfo.value) return
  const types = classOptions.map((c) => c.value)
  extracting.value = true
  busy.value = true
  busyHint.value = '逐类提取，首次较慢；有 tile 缓存后更快'
  stageSteps.value = types.map((t) => classLabelOf(t))
  stageIndex.value = 0
  batchResults.value = []
  clearResult()
  try {
    for (let i = 0; i < types.length; i++) {
      const t = types[i]
      busyText.value = `正在提取 ${classLabelOf(t)}（${i + 1}/${types.length}）`
      stageIndex.value = i
      const res = await sentinelApi.extract(
        aoi.value, startDate.value, endDate.value, t,
        maxCloud.value, threshold.value, minArea.value)
      const color = classOptions.find((c) => c.value === t)?.color || '#22c55e'
      // 叠加渲染：不清空前面的类型
      renderResult(res, color, false)
      batchResults.value.push({
        classType: t,
        label: classLabelOf(t),
        color,
        coverage: res.coverage_pct,
        count: res.feature_count
      })
      // 让用户看到进度逐类出现
      viewer?.scene.requestRender()
    }
    ElMessage.success(`批量提取完成，共 ${batchResults.value.length} 类地物`)
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  } finally {
    extracting.value = false
    busy.value = false
  }
}

async function doExtract() {
  extracting.value = true
  busy.value = true
  busyText.value = '正在提取地物'
  busyHint.value = ''
  stageSteps.value = ['检索无云影像', '下载影像波段', '计算指数', '矢量化']
  stageIndex.value = 0
  try {
    const res = await sentinelApi.extract(aoi.value, startDate.value, endDate.value, classType.value, maxCloud.value, threshold.value, minArea.value)
    stageIndex.value = 3
    lastResult.value = res
    // 提取后颜色跟随类型默认色
    resultColor.value = classOptions.find((c) => c.value === classType.value)?.color || '#22c55e'
    renderResult(res)
    if (res.feature_count === 0 && res.hint) {
      // 未检出时给出可解释原因，而不是只弹"成功"
      ElMessage.warning(res.hint)
    } else {
      ElMessage.success(`提取完成：覆盖率 ${res.coverage_pct}%，共 ${res.feature_count} 个要素`)
    }
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  } finally {
    extracting.value = false
    busy.value = false
  }
}

/**
 * 渲染解译结果到地图。
 * @param colorOverride 指定颜色（批量提取时每类一个色）
 * @param clearBefore  是否先清空已有图层（批量叠加时传 false）
 */
function renderResult(res: ExtractResult, colorOverride?: string, clearBefore = true) {
  if (clearBefore) clearResult()
  if (!viewer) return
  const color = colorOverride || resultColor.value
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

// ---- 地形分析（DEM 坡度/汇水）----
/** 坡度分级配色，与后端 PNG 分级一致 */
function slopeColorOf(label: string): string {
  if (label.includes('<2')) return '#4caf50'
  if (label.includes('2-6')) return '#aed581'
  if (label.includes('6-15')) return '#ffd54f'
  if (label.includes('15-25')) return '#ff9800'
  return '#d32f2f'
}

async function doTerrain() {
  if (aoi.value.length < 3) {
    ElMessage.warning('请先圈选 AOI')
    return
  }
  terrainLoading.value = true
  busy.value = true
  busyText.value = '正在分析地形'
  busyHint.value = '首次读取高程瓦片约 10–30 秒（约 10m 分辨率），之后走本地缓存'
  try {
    const res = await terrainApi.analyze(aoi.value, 14, true)
    terrainResult.value = res
    if (res.slopeImageBase64) {
      await renderSlopeLayer(res.slopeImageBase64)
      showSlope.value = true
    }
    ElMessage.success(
      `地形分析完成：起伏 ${res.summary.reliefM}m，平均坡度 ${res.summary.slopeMean}°，` +
      `陡坡占比 ${res.summary.steepPct}%`
    )
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  } finally {
    terrainLoading.value = false
    busy.value = false
  }
}

/** 把坡度分级 PNG 贴到 AOI 范围（与真彩贴图同一套做法） */
async function renderSlopeLayer(b64: string) {
  const byteChars = atob(b64)
  const bytes = new Uint8Array(byteChars.length)
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
  const url = URL.createObjectURL(new Blob([bytes], { type: 'image/png' }))
  const { width, height } = await readImageSize(url)
  if (slopeLayer) { viewer?.imageryLayers.remove(slopeLayer, true); slopeLayer = null }
  const b = aoiBounds()
  slopeLayer = viewer!.imageryLayers.addImageryProvider(
    new SingleTileImageryProvider({
      url,
      rectangle: Rectangle.fromDegrees(b.west, b.south, b.east, b.north),
      tileWidth: width,
      tileHeight: height
    })
  )
  slopeLayer.alpha = 0.75
  viewer?.scene.requestRender()
}

function toggleSlope(v: boolean) {
  if (slopeLayer) slopeLayer.show = v
  viewer?.scene.requestRender()
}

// ---- AOI 关注区（监测订阅）----
/** 地物类型中文名（关注区列表用） */
function classLabelOf(code: string): string {
  return classOptions.find((c) => c.value === code)?.label || code
}

async function loadWatches() {
  const pid = projectStore.currentId
  if (!pid) return
  try {
    watches.value = (await aoiWatchApi.list(pid)) as any
  } catch {
    watches.value = []
  }
}

/** 把当前圈选的 AOI 存为关注区，之后可反复检查同一块地的变化 */
async function saveAsWatch() {
  const pid = projectStore.currentId
  if (!pid) {
    ElMessage.warning('请先在右上角选择项目')
    return
  }
  if (aoi.value.length < 3) {
    ElMessage.warning('请先圈选 AOI')
    return
  }
  try {
    await aoiWatchApi.create({
      projectId: pid,
      name: `${classLabelOf(classType.value)}关注区-${new Date().toLocaleDateString('zh-CN')}`,
      aoi: aoi.value,
      classType: classType.value
    })
    ElMessage.success('已保存为关注区，可在下方列表检查变化')
    await loadWatches()
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  }
}

/** 检查该关注区最近两期的变化 */
async function checkWatch(w: { id: number; name: string }) {
  try {
    const r = await aoiWatchApi.check(w.id)
    if (r.insufficient) {
      ElMessage.warning(r.message)
    } else {
      const sign = (r.deltaPct ?? 0) >= 0 ? '+' : ''
      const tip = `${w.name}：${r.prevDate} → ${r.lastDate}，面积 ${haToKm2(r.prevAreaHa)} → ${haToKm2(r.lastAreaHa)} km²（${sign}${r.deltaPct}%）`
      if (r.significant) {
        ElMessage.warning({ message: `${tip}｜${r.message}`, duration: 8000 })
      } else {
        ElMessage.success(tip)
      }
    }
    await loadWatches()
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  }
}

async function removeWatch(w: { id: number; name: string }) {
  try {
    await aoiWatchApi.remove(w.id)
    ElMessage.success(`已删除「${w.name}」`)
    await loadWatches()
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  }
}

/** 把关注区的 AOI 重新画到地图上并飞过去 */
function locateWatch(w: { aoiJson: string }) {
  try {
    const ring = JSON.parse(w.aoiJson) as number[][]
    if (!Array.isArray(ring) || ring.length < 3) return
    clearAoi()
    aoi.value = ring
    refreshAoi()
    const bounds = aoiBounds()
    viewer?.camera.flyTo({
      destination: Cartesian3.fromDegrees(
        (bounds.west + bounds.east) / 2,
        (bounds.south + bounds.north) / 2,
        4000
      ),
      duration: 1.2
    })
    viewer?.scene.requestRender()
  } catch {
    ElMessage.error('关注区坐标解析失败')
  }
}

// ---- 保存与历史 ----
async function saveResult() {
  if (!lastResult.value) return
  // 把 GeoJSON features 转成 Java 期望的外环坐标格式 List<List<List<Double>>>
  const rings: number[][][] = []
  for (const f of lastResult.value.features) {
    const g = f.geometry
    if (!g) continue
    if (g.type === 'Polygon') {
      rings.push(g.coordinates[0])
    } else if (g.type === 'MultiPolygon') {
      for (const poly of g.coordinates) rings.push(poly[0])
    }
  }
  try {
    // 直接保存到 Java extractions 表（进时序/分析/权限体系，不再用 localStorage）
    await extractionApi.save({
      projectId: projectStore.currentId!,
      name: saveName.value || `${classType.value}-${(lastResult.value.datetime || '').slice(0, 10)}`,
      classType: classType.value,
      features: rings,
      aoiJson: JSON.stringify(aoi.value),
      coveragePct: lastResult.value.coverage_pct,
      aoiAreaHa: ringAreaHa(aoi.value),
      acquisitionDate: lastResult.value.datetime,
      satellite: 'SENTINEL2'
    })
    saveName.value = ''
    ElMessage.success('已保存到影像库，可在变化分析中查看')
    // 刷新历史（从数据库读）
    await loadHistory()
  } catch (e: any) {
    ElMessage.error('保存失败：' + friendlyError(e))
  }
}

function showHistory(h: HistoryItem) {
  classType.value = h.classType
  aoi.value = [...h.aoi]
  lastResult.value = { ...lastResult.value, features: h.features, coverage_pct: h.coverage, datetime: h.datetime } as any
  resultColor.value = h.color
  renderResult(lastResult.value!)
  ElMessage.success(`已加载「${h.name}」`)
}

/** 是否有可复用的历史 AOI */
const lastAoiAvailable = computed(() => history.value.some((h) => (h.aoi?.length ?? 0) >= 3))

/**
 * 复用历史记录的 AOI：手圈两次的点位难免有偏差，
 * 而区域指纹是按顶点集合算的，点位一变就被视为"另一个区域"，
 * 会导致时序/对比匹配不上、面积被重复统计。这里直接复用上次的坐标。
 */
function reuseLastAoi() {
  const latest = history.value.find((h) => (h.aoi?.length ?? 0) >= 3)
  if (!latest) {
    ElMessage.warning('没有可复用的历史 AOI')
    return
  }
  finishDraw()
  aoi.value = latest.aoi.map((p) => [...p])
  // 重建顶点标记与多边形
  aoiPointEntities.forEach((e) => viewer?.entities.remove(e))
  aoiPointEntities = []
  aoi.value.forEach(([lng, lat]) => {
    aoiPointEntities.push(viewer!.entities.add({
      position: Cartesian3.fromDegrees(lng, lat),
      point: { pixelSize: 7, color: Color.fromCssColorString('#14b8a6'), outlineColor: Color.WHITE, outlineWidth: 2 }
    }))
  })
  refreshAoi()
  viewer?.scene.requestRender()
  ElMessage.success(`已复用「${latest.name}」的 AOI（${latest.datetime.slice(0, 10)}）`)
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

/** AOI 指纹：同一圈选区域的两次绘制视为同一区域（坐标容差 1e-6 度） */
function aoiKey(ring: number[][]): string {
  return ring
    .map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`)
    .sort()
    .join(';')
}

function startAnimation() {
  const items = playlist.value
  if (items.length < 1) {
    ElMessage.warning('请先勾选记录加入播放清单')
    return
  }
  // 时序播放必须是同一区域的多期变化，不同 AOI 混播没有意义
  const baseKey = aoiKey(items[0].aoi)
  const sameArea = items.filter((h) => aoiKey(h.aoi) === baseKey)
  if (sameArea.length < items.length) {
    ElMessage.warning(
      `播放清单里包含 ${items.length - sameArea.length} 条其他区域的记录，已自动排除；时序动画只在同一区域内比对`
    )
  }
  if (sameArea.length < 1) {
    ElMessage.error('没有可播放的记录')
    return
  }
  stopAnimation()
  animationItems = sameArea
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

async function showDiff() {
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
  // 空间求差要求两期落在同一区域，否则差集没有意义
  if (aoiKey(a.aoi) !== aoiKey(b.aoi)) {
    ElMessage.warning('两条记录不是同一区域，无法做空间求差；请选择同一 AOI 的两期结果')
    return
  }
  // 双色叠加：早=红 晚=蓝
  const early = a.datetime <= b.datetime ? a : b
  const late = a.datetime <= b.datetime ? b : a

  // 后端空间求差，生成热力图（新增=红、消失=绿、不变=灰）
  diffLoading.value = true
  try {
    const diff = await sentinelApi.diffHeatmap(early.features, late.features)
    heatmapResult.value = diff
    renderHeatmap(diff)
    heatmapVisible.value = true
    ElMessage.info(`红 = ${early.datetime.slice(0, 10)}（新增），绿 = ${late.datetime.slice(0, 10)} 前的区域（消失/复绿）`)
  } catch (e: any) {
    // 求差失败退回简单双色叠加
    ElMessage.warning('空间求差失败，退回双色叠加：' + friendlyError(e))
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
  } finally {
    diffLoading.value = false
  }
}

/** 渲染热力图：新增=红，消失=绿，不变=灰 */
function renderHeatmap(diff: DiffHeatmapResult) {
  clearResult()
  if (!viewer) return
  const drawGroup = (features: any[], color: string, alpha: number) => {
    for (const f of features) {
      const geom = f.geometry
      if (!geom) continue
      const coords = geom.type === 'Polygon' ? [geom.coordinates] : (geom.type === 'MultiPolygon' ? geom.coordinates : [])
      for (const poly of coords) {
        const outer = Array.isArray(poly[0]) && Array.isArray(poly[0][0]) ? poly[0] : poly
        resultEntities.push(viewer!.entities.add({
          polygon: {
            hierarchy: new PolygonHierarchy(outer.map(([lng, lat]: number[]) => Cartesian3.fromDegrees(lng, lat))),
            material: Color.fromCssColorString(color).withAlpha(alpha),
            height: 0, outline: true, outlineColor: Color.fromCssColorString(color)
          }
        }))
      }
    }
  }
  drawGroup(diff.added, '#ef4444', 0.55)      // 新增扰动 = 红
  drawGroup(diff.removed, '#22c55e', 0.55)    // 消失/复绿 = 绿
  drawGroup(diff.unchanged, '#9ca3af', 0.25)  // 不变 = 灰
  viewer.scene.requestRender()
}

function persistHistory() {
  // 已改为数据库持久化（extractions 表），此函数不再使用
}

// ---- 成果导出 ----
/** 导出 GeoJSON：把提取结果序列化成 FeatureCollection 下载 */
function exportGeoJson() {
  if (!lastResult.value) return
  const fc = {
    type: 'FeatureCollection',
    features: lastResult.value.features,
    metadata: {
      classType: lastResult.value.class,
      sceneId: lastResult.value.scene_id,
      datetime: lastResult.value.datetime,
      coveragePct: lastResult.value.coverage_pct,
      exportedAt: new Date().toISOString()
    }
  }
  downloadFile(
    `${classType.value}-${(lastResult.value.datetime || '').slice(0, 10)}.geojson`,
    JSON.stringify(fc, null, 2),
    'application/geo+json'
  )
  ElMessage.success('GeoJSON 已导出')
}

/** 导出 GeoTIFF：调 inference 生成（含 AOI 影像 + 掩膜） */
async function exportGeoTiff() {
  if (!lastResult.value || aoi.value.length < 3) {
    ElMessage.warning('暂无结果或 AOI 可导出')
    return
  }
  try {
    const res = await sentinelApi.exportGeoTiff({
      aoi: aoi.value,
      startDate: startDate.value,
      endDate: endDate.value,
      classType: classType.value,
      maxCloud: maxCloud.value
    })
    // base64 → blob 下载
    const byteChars = atob(res.tif_base64)
    const bytes = new Uint8Array(byteChars.length)
    for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
    const blob = new Blob([bytes], { type: 'image/tiff' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = res.filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('GeoTIFF 已导出')
  } catch (e: any) {
    ElMessage.error(friendlyError(e))
  }
}

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ---- 离线演示数据包 ----
/** 一键载入演示数据：用宁都河源默认 AOI 生成/读取离线演示包 */
async function loadDemo() {
  demoLoading.value = true
  // 默认演示 AOI（宁都河源样区）
  const demoAoi = [[116.014, 26.466], [116.030, 26.466], [116.030, 26.480], [116.014, 26.480]]
  try {
    busy.value = true
    busyText.value = '正在准备演示数据'
    busyHint.value = '首次生成需下载影像（约 1-10 分钟），之后从本地缓存秒读'
    // 先尝试生成（若已缓存会很快）
    const bundle = await sentinelApi.demoBundle({
      aoi: demoAoi,
      startDate: startDate.value,
      endDate: endDate.value,
      maxCloud: maxCloud.value
    })
    // 载入：设置 AOI + 真彩 + 各类结果
    aoi.value = demoAoi
    sceneInfo.value = {
      scene_id: bundle.sceneId,
      datetime: bundle.datetime,
      cloud_cover: bundle.cloudCover
    }
    // 真彩影像贴图
    const byteChars = atob(bundle.imageBase64)
    const bytes = new Uint8Array(byteChars.length)
    for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
    const blob = new Blob([bytes], { type: 'image/png' })
    const url = URL.createObjectURL(blob)
    const { width, height } = await readImageSize(url)
    if (clippedLayer) { viewer?.imageryLayers.remove(clippedLayer, true) }
    const bounds = aoiBounds()
    const rect = Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north)
    clippedLayer = viewer!.imageryLayers.addImageryProvider(
      new SingleTileImageryProvider({ url, rectangle: rect, tileWidth: width, tileHeight: height })
    )
    // 默认展示植被结果
    const veg = bundle.results?.VEGETATION
    if (veg) {
      classType.value = 'VEGETATION'
      lastResult.value = {
        class: 'VEGETATION',
        threshold: 0.25,
        coverage_pct: veg.coveragePct,
        feature_count: veg.featureCount,
        features: veg.features,
        scene_id: bundle.sceneId,
        datetime: bundle.datetime,
        cloud_cover: bundle.cloudCover
      }
      resultColor.value = '#22c55e'
      renderResult(lastResult.value)
    }
    refreshAoi()
    viewer?.scene.requestRender()
    ElMessage.success(`演示数据已载入：${bundle.sceneId}（${(bundle.datetime || '').slice(0, 10)}，含 ${Object.keys(bundle.results || {}).length} 类解译结果）`)
  } catch (e: any) {
    ElMessage.error('演示数据载入失败：' + friendlyError(e))
  } finally {
    demoLoading.value = false
    busy.value = false
  }
}

async function loadHistory() {
  // 从 Java extractions 表读历史记录（进时序/分析/权限体系）
  try {
    const list = await extractionApi.list(projectStore.currentId ?? undefined)
    history.value = list
      .filter((e) => e.featuresJson)   // 只保留有几何结果的
      .map((e) => ({
        id: String(e.id),
        name: e.name,
        classLabel: classOptions.find((c) => c.value === e.classType)?.label || e.classType,
        classType: e.classType,
        datetime: e.acquisitionDate || (e.year ? `${e.year}-01-01` : ''),
        coverage: e.coveragePct || 0,
        features: safeParseFeatures(e.featuresJson),
        aoi: safeParseAoi(e.aoiJson),
        color: classOptions.find((c) => c.value === e.classType)?.color || '#22c55e'
      }))
  } catch {
    history.value = []
  }
}

/** 把 extractions 表的 featuresJson 转回 GeoJSON Feature 列表（供渲染） */
function safeParseFeatures(json: string): any[] {
  try {
    const rings = JSON.parse(json)   // List<List<List<Double>>>
    if (!Array.isArray(rings)) return []
    return rings.map((ring: number[][], i: number) => ({
      type: 'Feature',
      properties: { id: i },
      geometry: { type: 'Polygon', coordinates: [ring] }
    }))
  } catch {
    return []
  }
}

function safeParseAoi(json?: string): number[][] {
  try {
    return json ? JSON.parse(json) : []
  } catch {
    return []
  }
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
  background: rgba(0,0,0,0.55); display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px; color: #fff;
}
.busy-mask .el-icon { font-size: 32px; }
.busy-title { font-size: 15px; font-weight: 600; }
.busy-steps { display: flex; gap: 18px; align-items: center; }
.busy-step { display: flex; align-items: center; gap: 5px; font-size: 12px; color: rgba(255,255,255,0.6); }
.busy-step .bs-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: rgba(255,255,255,0.35); transition: all 0.2s;
}
.busy-step.active { color: #fff; font-weight: 600; }
.busy-step.active .bs-dot { background: #14b8a6; box-shadow: 0 0 6px #14b8a6; }
.busy-step.done { color: #a7f3d0; }
.busy-step.done .bs-dot { background: #34d399; }
.busy-hint { font-size: 12px; color: rgba(255,255,255,0.7); max-width: 320px; text-align: center; line-height: 1.5; }

.step-card { padding: 2px 0; }
.step-disabled { opacity: 0.55; }

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
.evidence-hint { font-size: 11px; color: #a9aeb8; line-height: 1.5; margin-top: 6px; }
.method-note { font-size: 11px; color: #4e5969; line-height: 1.6; margin-top: 6px; }
.warn-note {
  margin-top: 8px; padding: 6px 8px; border-radius: 6px;
  background: #fffbeb; border: 1px solid #fde68a;
  font-size: 11px; color: #b45309; line-height: 1.6;
}

/* ---- 地形与安全指标 ---- */
.terrain-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.terrain-src { font-size: 10px; color: #a9aeb8; }
.terrain-kpi { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
.tk { background: #f6f8fa; border-radius: 8px; padding: 8px; text-align: center; }
.tk-num { font-size: 15px; font-weight: 700; color: #0d9488; }
.tk-num.warn { color: #ef4444; }
.tk-label { font-size: 11px; color: #86909c; margin-top: 2px; }
.slope-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; margin-bottom: 6px; }
.sb-seg { height: 100%; }
.slope-legend { display: flex; flex-wrap: wrap; gap: 8px; font-size: 11px; color: #4e5969; }
.sl-item { display: inline-flex; align-items: center; gap: 3px; }
.sl-item i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.terrain-note { margin-top: 8px; font-size: 11px; color: #4e5969; line-height: 1.6; }
.terrain-warn {
  margin-top: 6px; padding: 6px 8px; border-radius: 6px;
  background: #fffbeb; border: 1px solid #fde68a;
  font-size: 11px; color: #b45309; line-height: 1.6;
}

.compare-actions { display: flex; gap: 8px; margin-top: 8px; }

.diff-table { font-size: 13px; }
.diff-head, .diff-row {
  display: grid; grid-template-columns: 1.2fr 1fr 1fr 1fr;
  padding: 8px 6px; border-bottom: 1px solid #f0f0f0;
}
.diff-head { font-weight: 600; color: #1f2329; background: #fafbfc; border-radius: 6px 6px 0 0; }
.diff-row span { text-align: center; }

.heatmap-legend {
  display: flex; gap: 16px; align-items: center;
  padding: 8px 12px; background: #fafbfc; border-radius: 8px; margin-bottom: 12px;
}
.lg-item { display: flex; align-items: center; gap: 5px; font-size: 12px; color: #4e5969; }
.lg-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.watch-row { margin: 8px 0; }
.watch-list { margin-top: 8px; border-top: 1px dashed #eceef2; padding-top: 8px; }
.watch-item {
  border: 1px solid #f0f2f5; border-radius: 8px;
  padding: 8px 10px; margin-bottom: 6px; background: #fafbfc;
}
.w-line1 { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.w-name { font-weight: 600; color: #1f2329; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.w-tag {
  font-size: 11px; color: #0d9488; background: #e6f6f4;
  padding: 1px 6px; border-radius: 4px; flex-shrink: 0;
}
.w-meta { font-size: 11px; color: #86909c; flex-shrink: 0; }
.w-line2 { display: flex; gap: 10px; font-size: 11px; color: #86909c; margin-top: 3px; }
.w-area { color: #0d9488; font-weight: 600; }
.w-ops { display: flex; gap: 2px; margin-top: 4px; }
.batch-sum {
  margin-top: 10px; border-top: 1px dashed #eceef2; padding-top: 8px;
}
.bs-title { font-size: 12px; font-weight: 600; color: #4e5969; margin-bottom: 4px; }
.bs-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; padding: 3px 0; color: #4e5969;
}
.bs-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.bs-label { flex: 1; }
.bs-val { color: #0d9488; font-weight: 600; }
.bs-cnt { color: #a9aeb8; width: 52px; text-align: right; }
</style>

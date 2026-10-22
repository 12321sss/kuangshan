<template>
  <div class="cls-page">
    <!-- 参数条 -->
    <el-card shadow="never" class="op-card">
      <div class="op-bar">
        <div class="op-group">
          <el-radio-group v-model="source" size="small" @change="onSourceChange">
            <el-radio-button value="LOCAL">本地高清影像</el-radio-button>
            <el-radio-button value="SENTINEL2">在线 Sentinel-2</el-radio-button>
          </el-radio-group>

          <template v-if="source === 'LOCAL'">
            <span class="lbl">影像</span>
            <el-select v-model="imageryId" size="small" placeholder="选择影像库里的上传影像"
                       style="width: 240px" @change="onLocalImageryChange">
              <el-option v-for="m in localImageries" :key="m.id"
                         :label="`${m.name}（${m.acquisitionDate}）`" :value="m.id" />
            </el-select>
            <el-checkbox v-model="fullImage" label="整幅影像" border size="small" />
            <template v-if="!fullImage">
              <span class="lbl">兴趣区</span>
              <el-select v-model="aoiId" size="small" placeholder="从边界加载" style="width: 200px"
                         @change="refreshAoiOverlay">
                <el-option v-for="o in aoiOptions" :key="o.id" :label="`${o.name}（${o.areaHa} ha）`" :value="o.id" />
              </el-select>
            </template>
          </template>

          <template v-else>
            <span class="lbl">分析区</span>
            <el-select v-model="aoiId" size="small" placeholder="选择已导入的边界" style="width: 210px" @change="onAoiChange">
              <el-option v-for="o in aoiOptions" :key="o.id" :label="`${o.name}（${o.areaHa} ha）`" :value="o.id" />
            </el-select>
          </template>
          <template v-if="source === 'SENTINEL2'">
            <el-date-picker v-model="range" type="daterange" size="small" value-format="YYYY-MM-DD"
                            start-placeholder="起始" end-placeholder="结束" style="width: 230px" />
            <span class="lbl">云量</span>
            <el-input-number v-model="maxCloud" :min="1" :max="100" :step="5" size="small" style="width: 80px" />
            <el-radio-group v-model="combo" size="small" @change="onComboChange">
              <el-radio-button value="TRUE_COLOR">真彩</el-radio-button>
              <el-radio-button value="FALSE_COLOR">假彩(近红外)</el-radio-button>
            </el-radio-group>
          </template>
          <el-button size="small" :loading="loadingImg" @click="loadPreview">加载影像</el-button>
        </div>
      </div>
      <div v-if="!aoiOptions.length" class="warn-row">
        还没有可用的分析区：请先到「遥感解译 → 边界管理」导入矿权范围（SHP/GeoJSON/KML）
      </div>
    </el-card>

    <div class="main">
      <!-- 左：影像 + 选点 -->
      <el-card shadow="never" class="map-card">
        <template #header>
          <div class="card-head">
            <span>影像与样本点</span>
            <div class="head-right">
              <span class="card-hint">左键点选 · 滚轮缩放 · 右键拖动</span>
              <el-button link type="primary" size="small" :disabled="!image" @click="resetToNative">1:1</el-button>
              <el-button link type="primary" size="small" :disabled="!image" @click="fitToBox">适应窗口</el-button>
            </div>
          </div>
        </template>
        <div ref="boxRef" class="viewer" @wheel.prevent="onWheel" @contextmenu.prevent
             @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"
             @click="onClick">
          <div class="canvas-wrap" :style="wrapStyle">
            <img v-if="image" ref="imgRef" :src="'data:image/png;base64,' + image" class="view-img" @load="onImgLoad" />
            <!-- 兴趣区描边：提示"分类范围"与"影像范围"不是一回事 -->
            <svg v-if="image && aoiSvgPoints" class="aoi-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
              <polygon :points="aoiSvgPoints" fill="rgba(20,184,166,0.10)"
                       stroke="#14b8a6" stroke-width="1.5" vector-effect="non-scaling-stroke" />
            </svg>
            <div v-if="image" class="dots">
              <span v-for="(s, i) in samples" :key="i" class="dot"
                    :style="dotStyleOf(s)"
                    :title="`${classLabel(s.classType)} #${i + 1}`"></span>
            </div>
          </div>
          <div v-if="!image && !loadingImg" class="viewer-empty">
            选好分析区与日期后点「加载影像」，然后在图上点选样本
          </div>
          <div v-if="loadingImg" class="viewer-empty">影像加载中…（首次需下载瓦片，约 20-60 秒）</div>
          <div class="zoom-tip">{{ scale === 1 ? '1:1 原始像素' : '×' + scale.toFixed(1) }}</div>
        </div>

        <!-- 分辨率诊断：区域太小或影像太粗时，选点会很不准，必须提前说清 -->
        <div v-if="resHint" class="res-hint" :class="{ warn: resWarn }">
          <el-icon><WarningFilled v-if="resWarn" /><InfoFilled v-else /></el-icon>
          <span>{{ resHint }}</span>
        </div>
      </el-card>

      <!-- 右：样本与结果 -->
      <div class="side">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>样本采集 <b class="cnt">{{ samples.length }}</b> 个 · <b class="cnt">{{ sampleClassCount }}</b> 类</span>
              <div class="head-right">
                <el-button link type="primary" size="small" @click="pickSampleFile">导入</el-button>
                <el-dropdown size="small" trigger="click" @command="exportSamples">
                  <el-button link type="primary" size="small">导出</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="csv">导出 CSV（Excel 可改）</el-dropdown-item>
                      <el-dropdown-item command="geojson">导出 GeoJSON（GIS 可开）</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button link type="danger" size="small" :disabled="!samples.length" @click="samples = []">清空</el-button>
              </div>
            </div>
          </template>
          <input ref="sampleInput" type="file" accept=".csv,.json,.geojson" class="hidden-input"
                 @change="onSampleFile" />
          <div class="class-chips">
            <div v-for="c in classList" :key="c.value" class="chip"
                 :class="{ active: activeClass === c.value }"
                 @click="activeClass = c.value">
              <span class="chip-dot" :style="{ background: c.color }"></span>
              <span class="chip-name">{{ c.label }}</span>
              <span class="chip-count">{{ countOf(c.value) }}</span>
            </div>
          </div>
          <div class="sample-hint">
            当前选中：<b :style="{ color: classColor(activeClass) }">{{ classLabel(activeClass) }}</b>
            —— 在图上点击即可打点；每类建议 20-40 个，分散在各类图斑各处
          </div>
          <el-button type="primary" class="run-btn" :loading="classifying"
                     :disabled="!canRun" @click="runClassify">
            开始监督分类
          </el-button>
          <div class="run-hint">
            至少两类、每类 ≥8 个样本；首次需下载影像（1-4 分钟），之后有缓存会快很多
          </div>
        </el-card>

        <!-- 精度报告 -->
        <el-card v-if="result?.accuracy" shadow="never">
          <template #header>
            <div class="card-head">
              <span>精度评价</span>
              <span class="card-hint">{{ result.accuracy.split }} · 验证 {{ result.accuracy.validationCount }} 个</span>
            </div>
          </template>
          <div class="acc-kpi">
            <div class="kpi">
              <div class="kpi-num">{{ result.accuracy.overallAccuracy }}<span>%</span></div>
              <div class="kpi-lbl">总体精度 OA</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.accuracy.kappa }}</div>
              <div class="kpi-lbl">Kappa 系数</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.accuracy.oobScore ?? '—' }}<span v-if="result.accuracy.oobScore">%</span></div>
              <div class="kpi-lbl">袋外精度 OOB</div>
            </div>
          </div>
          <div class="mat-title">混淆矩阵（行=真值，列=预测）</div>
          <table class="cm">
            <thead>
              <tr>
                <th></th>
                <th v-for="n in result.accuracy.labelNames" :key="n">{{ n }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in result.accuracy.confusionMatrix" :key="i">
                <th>{{ result.accuracy.labelNames[i] }}</th>
                <td v-for="(v, j) in row" :key="j" :class="{ diag: i === j, err: i !== j && v > 0 }">{{ v }}</td>
              </tr>
            </tbody>
          </table>
        </el-card>

        <!-- 分类结果 -->
        <el-card v-if="result?.classes?.length" shadow="never">
          <template #header>
            <div class="card-head">
              <span>分类结果</span>
              <el-button size="small" type="success" :loading="saving" @click="saveAll">保存为解译记录</el-button>
            </div>
          </template>
          <el-table :data="result.classes" size="small">
            <el-table-column label="类别" min-width="110">
              <template #default="{ row }">
                <span class="cls-dot" :style="{ background: row.color }"></span>{{ row.label }}
              </template>
            </el-table-column>
            <el-table-column label="面积(ha)" width="88" align="right">
              <template #default="{ row }">{{ row.areaHa }}</template>
            </el-table-column>
            <el-table-column label="占比" width="70" align="right">
              <template #default="{ row }">{{ row.pctOfAoi }}%</template>
            </el-table-column>
            <el-table-column label="用户精度" width="86" align="right">
              <template #default="{ row }">{{ row.userAccuracy }}%</template>
            </el-table-column>
            <el-table-column label="制图精度" width="86" align="right">
              <template #default="{ row }">{{ row.producerAccuracy }}%</template>
            </el-table-column>
          </el-table>

          <el-button class="map-btn" @click="resultDialog = true">查看分类专题图</el-button>

          <div v-for="(w, i) in result.warnings" :key="i" class="warn-tip">· {{ w }}</div>
          <div class="disclaimer">{{ result.disclaimer }}</div>
        </el-card>
      </div>
    </div>

    <!-- 分类专题图：独立画布展示，右侧栏不再被拉长 -->
    <el-dialog v-model="resultDialog" title="分类专题图" width="70%" top="6vh">
      <div v-if="result" class="dlg-grid">
        <div class="dlg-figure">
          <img v-if="result.imageBase64" :src="'data:image/png;base64,' + result.imageBase64" class="dlg-img" />
          <div class="dlg-legend">
            <span v-for="c in result.classes" :key="c.classType" class="lg">
              <i :style="{ background: c.color }"></i>{{ c.label }}
            </span>
          </div>
        </div>
        <div class="dlg-side">
          <div class="sec-title">特征重要性</div>
          <div v-for="f in topFeatures" :key="f.name" class="imp-row">
            <span class="imp-name">{{ f.name }}</span>
            <div class="imp-bar"><i :style="{ width: f.importance * 4 + '%' }"></i></div>
            <span class="imp-val">{{ f.importance }}%</span>
          </div>
          <div class="sec-title">判别方法</div>
          <div class="dlg-method">{{ result.method }}</div>
          <div v-for="(w, i) in result.warnings" :key="i" class="warn-tip">· {{ w }}</div>
          <div class="disclaimer">{{ result.disclaimer }}</div>
        </div>
      </div>
    </el-dialog>

    <!-- 样本导入校验报告：先给结论再让人决定合并还是替换 -->
    <el-dialog v-model="importVisible" title="样本导入" width="520px">
      <template v-if="importResult">
        <div class="imp-line">
          共读取 <b>{{ importResult.total }}</b> 行：有效 <b class="ok">{{ importResult.valid }}</b>，
          重复像元 <b>{{ importResult.dup }}</b>，越界 <b>{{ importResult.out }}</b>，
          未知类别 <b>{{ importResult.unknown }}</b>
        </div>
        <div class="imp-line">按类：{{ importResult.byClassText }}</div>
        <el-alert v-if="importResult.shortText" type="warning" :closable="false" show-icon
                  :title="importResult.shortText" class="imp-warn" />
        <div v-if="importResult.errors?.length" class="imp-errs">
          <div v-for="(e, i) in importResult.errors.slice(0, 6)" :key="i">· {{ e }}</div>
          <div v-if="importResult.errors.length > 6">… 另有 {{ importResult.errors.length - 6 }} 条</div>
        </div>
      </template>
      <template #footer>
        <el-button size="small" @click="importVisible = false">取消</el-button>
        <el-button size="small" :disabled="!importResult?.valid" @click="applyImport('replace')">替换现有</el-button>
        <el-button size="small" type="primary" :disabled="!importResult?.valid" @click="applyImport('merge')">
          合并导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { WarningFilled, InfoFilled } from '@element-plus/icons-vue'
import { analysisApi, extractionApi, imageryApi } from '@/api'
import type { AoiOption, ClassifySample, SupervisedResult } from '@/api'
import { sentinelApi } from '@/api/sentinel'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

/** 七类地物：与方案表 6 编码一致 */
const classList = [
  { value: 'PIT', label: '露天采坑', color: '#787878' },
  { value: 'DUMP', label: '排土场', color: '#b08960' },
  { value: 'TAILINGS', label: '尾矿设施', color: '#e2dac4' },
  { value: 'BARE', label: '裸地扰动', color: '#c4a882' },
  { value: 'ROAD', label: '道路设施', color: '#fad65a' },
  { value: 'VEGETATION', label: '植被', color: '#4caf50' },
  { value: 'WATER', label: '水体', color: '#2182d6' }
]

/** 数据源：LOCAL 本地高清影像 / SENTINEL2 在线 */
const source = ref<'LOCAL' | 'SENTINEL2'>('LOCAL')
const localImageries = ref<Array<{ id: number; name: string; acquisitionDate: string; west: number; south: number; east: number; north: number }>>([])
const imageryId = ref<number | null>(null)
const fullImage = ref(true)
const resultDialog = ref(false)

// ---- 样本导入导出 ----
const sampleInput = ref<HTMLInputElement>()
const importVisible = ref(false)
const importResult = ref<any>(null)
const pendingImport = ref<ClassifySample[]>([])

/** 兴趣区描边：把 AOI 外环换算成 0-100 的图像百分比坐标 */
const aoiRing = computed<number[][]>(() => {
  const opt = aoiOptions.value.find((o) => o.id === aoiId.value)
  if (!opt) return []
  // 去掉闭合重复点
  const ring = opt.ring || []
  return ring.length > 2 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
    ? ring.slice(0, -1) : ring
})

const aoiSvgPoints = computed(() => {
  const b = bbox.value
  const ring = aoiRing.value
  if (!b || !ring.length) return ''
  return ring
    .map(([lng, lat]) => {
      const x = ((lng - b.west) / (b.east - b.west)) * 100
      const y = ((b.north - lat) / (b.north - b.south)) * 100
      return `${x.toFixed(3)},${y.toFixed(3)}`
    })
    .join(' ')
})

const sampleClassCount = computed(() => new Set(samples.value.map((s) => s.classType)).size)

function refreshAoiOverlay() {
  // 触发 computed 重算即可（SFC 里显式调用一次便于读代码）
  aoiSvgPoints.value
}

/** 当前应传给后端的 AOI：整幅模式传空，让后端按影像四至 */
function effectiveAoi(): number[][] {
  if (source.value === 'LOCAL') {
    if (fullImage.value) return []
    return aoiRing.value
  }
  return currentOption()?.ring || []
}

const aoiOptions = ref<AoiOption[]>([])
const aoiId = ref<number | null>(null)
const range = ref<[string, string]>([
  new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10),
  new Date().toISOString().slice(0, 10)
])
const maxCloud = ref(20)

const image = ref<string>('')
/** 显示组合：真彩便于认地物，假彩（近红外）便于区分植被与裸地 */
const combo = ref<'TRUE_COLOR' | 'FALSE_COLOR'>('TRUE_COLOR')
const bbox = ref<{ west: number; south: number; east: number; north: number } | null>(null)
const resWarn = ref(false)
const loadingImg = ref(false)
const imgNatural = ref<{ w: number; h: number }>({ w: 0, h: 0 })

const samples = ref<ClassifySample[]>([])
const activeClass = ref('VEGETATION')
const classifying = ref(false)
const saving = ref(false)
const result = ref<SupervisedResult | null>(null)

const boxRef = ref<HTMLDivElement>()
const imgRef = ref<HTMLImageElement>()
const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
const dragging = ref(false)
const dragStart = ref({ x: 0, y: 0, ox: 0, oy: 0 })

const wrapStyle = computed(() => ({
  transform: `translate(${offset.value.x}px, ${offset.value.y}px) scale(${scale.value})`
}))

const canRun = computed(() => {
  const codes = new Set(samples.value.map((s) => s.classType))
  return codes.size >= 2 && samples.value.length >= 16
})

/** 选影像后自动取预览，省一次点击 */
watch([imageryId, source], () => {
  if (source.value === 'LOCAL' && imageryId.value) loadLocalPreview()
})

const topFeatures = computed(() => (result.value?.featureImportance || []).slice(0, 8))

function classLabel(code: string) {
  return classList.find((c) => c.value === code)?.label || code
}
function classColor(code: string) {
  return classList.find((c) => c.value === code)?.color || '#888'
}
function countOf(code: string) {
  return samples.value.filter((s) => s.classType === code).length
}

/** 像元采样点 → 图上百分比位置（bbox 线性映射，与后端 clip 的窗口一致） */
/**
 * 样本点大小：**屏幕尺寸恒定**，不随影像缩放变化
 *
 * 之前点画在缩放容器里，容器放大 4 倍点就跟着放大 4 倍，小影像上直接把图盖满。
 * 这里用反向缩放（1/scale）抵消容器缩放，同时按影像边长自适应基准大小：
 * 小影像（几十像素）用 3px 点，大影像最多 10px。
 */
const dotBasePx = computed(() => {
  const n = Math.min(imgNatural.value.w || 0, imgNatural.value.h || 0)
  if (!n) return 7
  return Math.min(10, Math.max(4, n * 0.05))
})
const dotCounterScale = computed(() => Math.min(2.5, Math.max(0.2, 1 / scale.value)))

function dotStyleOf(s: ClassifySample) {
  const b = bbox.value
  const base = { width: `${dotBasePx.value}px`, height: `${dotBasePx.value}px`, background: classColor(s.classType) }
  if (!b) return { ...base, left: '0%', top: '0%' }
  const x = ((s.lng - b.west) / (b.east - b.west)) * 100
  const y = ((b.north - s.lat) / (b.north - b.south)) * 100
  return {
    ...base,
    left: `${x}%`,
    top: `${y}%`,
    // 抵消画布缩放，保证屏幕上看到的大小恒定
    transform: `translate(-50%, -50%) scale(${dotCounterScale.value})`
  }
}

async function loadLocalImageries() {
  const pid = projectStore.currentId
  if (!pid) return
  try {
    const rows = await imageryApi.list({ projectId: pid })
    localImageries.value = rows
      .filter((r) => r.source === 'UPLOAD' && r.filePath)
      .map((r) => ({
        id: r.id, name: r.name, acquisitionDate: r.acquisitionDate,
        west: r.west, south: r.south, east: r.east, north: r.north
      }))
    if (localImageries.value.length && !imageryId.value) {
      imageryId.value = localImageries.value[0].id
    }
  } catch {
    localImageries.value = []
  }
}

async function loadOptions() {
  const pid = projectStore.currentId
  if (!pid) return
  loadLocalImageries()
  try {
    const res = await analysisApi.aoiOptions(pid)
    aoiOptions.value = res.options || []
    if (aoiOptions.value.length && !aoiId.value) {
      // 优先选矿权范围
      const permit = aoiOptions.value.find((o) => o.boundaryType === 'PERMIT')
      aoiId.value = (permit || aoiOptions.value[0]).id
    }
  } catch {
    aoiOptions.value = []
  }
}

function currentOption() {
  return aoiOptions.value.find((o) => o.id === aoiId.value) || null
}

function onSourceChange() {
  image.value = ''
  samples.value = []
  result.value = null
  bbox.value = null
}

function currentImagery() {
  return localImageries.value.find((m) => m.id === imageryId.value) || null
}

/** 本地影像：从后端取预览图并按影像四至定位 */
async function loadLocalPreview() {
  const img = currentImagery()
  if (!img) {
    ElMessage.warning('请先选择影像')
    return
  }
  loadingImg.value = true
  try {
    const res = await imageryApi.preview(img.id)
    if (res.error || !res.previewBase64) {
      ElMessage.error(res.error || '预览图生成失败')
      return
    }
    image.value = res.previewBase64
    bbox.value = {
      west: img.west, south: img.south, east: img.east, north: img.north
    }
    scale.value = 1
    offset.value = { x: 0, y: 0 }
  } catch (e: any) {
    ElMessage.error(e?.message || '预览加载失败')
  } finally {
    loadingImg.value = false
  }
}

function onLocalImageryChange() {
  image.value = ''
  result.value = null
  bbox.value = null
  loadLocalPreview()
}

function onAoiChange() {
  image.value = ''
  samples.value = []
  result.value = null
  bbox.value = null
}

async function loadPreview() {
  if (source.value === 'LOCAL') {
    await loadLocalPreview()
    return
  }
  const opt = currentOption()
  if (!opt) {
    ElMessage.warning('请先选择分析区')
    return
  }
  loadingImg.value = true
  try {
    const res = await sentinelApi.preview(opt.ring, range.value[0], range.value[1], maxCloud.value, combo.value)
    image.value = res.image_base64
    const lngs = opt.ring.map((p) => p[0])
    const lats = opt.ring.map((p) => p[1])
    bbox.value = {
      west: Math.min(...lngs), east: Math.max(...lngs),
      south: Math.min(...lats), north: Math.max(...lats)
    }
    scale.value = 1
    offset.value = { x: 0, y: 0 }
    ElMessage.success('影像已加载，可以开始点选样本')
  } catch (e: any) {
    ElMessage.error(e?.message || '影像加载失败')
  } finally {
    loadingImg.value = false
  }
}

async function onImgLoad() {
  const el = imgRef.value
  if (!el) return
  imgNatural.value = { w: el.naturalWidth, h: el.naturalHeight }
  await nextTick()
  // 默认按原始分辨率 1:1 显示（1 影像像元 = 1 屏幕像素），不做任何拉伸
  resetToNative()
}

/** 恢复 1:1 原始像素显示并居中（比容器大时左上对齐，靠右键拖动看其余部分） */
function resetToNative() {
  const box = boxRef.value?.getBoundingClientRect()
  const img = imgRef.value
  scale.value = 1
  if (!box || !img) return
  offset.value = {
    x: img.naturalWidth <= box.width ? (box.width - img.naturalWidth) / 2 : 0,
    y: img.naturalHeight <= box.height ? (box.height - img.naturalHeight) / 2 : 0
  }
}

/** 让影像铺满可视区（可选，默认不用）：把整幅图缩放到可视区内 */
function fitToBox() {
  const box = boxRef.value?.getBoundingClientRect()
  const img = imgRef.value
  if (!box || !img || !img.naturalWidth) return
  const s = Math.min((box.width - 24) / img.naturalWidth, (box.height - 24) / img.naturalHeight)
  scale.value = Math.max(0.2, Math.min(12, s))
  offset.value = {
    x: (box.width - img.naturalWidth * scale.value) / 2,
    y: (box.height - img.naturalHeight * scale.value) / 2
  }
}

function onComboChange() {
  if (image.value) loadPreview()
}

/** 分辨率诊断：像素数太少时选点没有意义，要明确告诉用户并给替代方案 */
const resHint = computed(() => {
  const b = bbox.value
  const nat = imgNatural.value
  if (!b || !nat.w || !nat.h) return ''
  const lat0 = (b.south + b.north) / 2
  const metersX = (b.east - b.west) * 111320 * Math.cos((lat0 * Math.PI) / 180)
  const mPerPx = metersX / nat.w
  const wPx = nat.w
  const hPx = nat.h
  resWarn.value = wPx < 60 || hPx < 60
  if (resWarn.value) {
    return `原始分辨率 ${wPx}×${hPx} 像素，每像素约 ${mPerPx.toFixed(1)} m，已按 1:1 显示。区域太小，选点会很粗——建议导入更大范围的边界（如整个矿区），或改用更高分辨率影像。注意：放大只是把像元画大，不会增加细节。`
  }
  return `原始分辨率 ${wPx}×${hPx} 像素，每像素约 ${mPerPx.toFixed(1)} m，已按 1:1 显示。样本点请分散在各类图斑内部，避开边缘 2~3 个像元。`
})

// ---- 缩放与平移 ----
function onWheel(e: WheelEvent) {
  if (!image.value) return
  const delta = e.deltaY < 0 ? 1.2 : 1 / 1.2
  const next = Math.min(12, Math.max(0.2, scale.value * delta))
  const box = boxRef.value?.getBoundingClientRect()
  if (!box) return
  const mx = e.clientX - box.left
  const my = e.clientY - box.top
  // 以光标为锚点缩放：先把光标处的图像坐标固定住
  const k = next / scale.value
  offset.value = {
    x: mx - (mx - offset.value.x) * k,
    y: my - (my - offset.value.y) * k
  }
  scale.value = next
}

function onDown(e: MouseEvent) {
  // 右键或中键拖动平移；左键留给打点
  if (e.button !== 2 && e.button !== 1) return
  dragging.value = true
  dragStart.value = { x: e.clientX, y: e.clientY, ox: offset.value.x, oy: offset.value.y }
}

function onMove(e: MouseEvent) {
  if (!dragging.value) return
  offset.value = {
    x: dragStart.value.ox + (e.clientX - dragStart.value.x),
    y: dragStart.value.oy + (e.clientY - dragStart.value.y)
  }
}

function onUp() {
  dragging.value = false
}

function onClick(e: MouseEvent) {
  if (!image.value || !bbox.value || dragging.value) return
  const el = imgRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const x = (e.clientX - rect.left) / rect.width
  const y = (e.clientY - rect.top) / rect.height
  if (x < 0 || x > 1 || y < 0 || y > 1) return
  const b = bbox.value
  const lng = b.west + x * (b.east - b.west)
  const lat = b.north - y * (b.north - b.south)
  samples.value = [...samples.value, { classType: activeClass.value, lng: +lng.toFixed(7), lat: +lat.toFixed(7) }]
}

async function runClassify() {
  if (source.value === 'LOCAL') {
    await runClassifyLocal()
    return
  }
  const opt = currentOption()
  if (!opt) return
  classifying.value = true
  result.value = null
  try {
    const res = await analysisApi.classifySupervised({
      projectId: projectStore.currentId!,
      aoi: opt.ring,
      samples: samples.value,
      start: range.value[0],
      end: range.value[1],
      maxCloud: maxCloud.value,
      minSamples: 8
    })
    result.value = res
    ElMessage.success(`分类完成：OA ${res.accuracy?.overallAccuracy}% · Kappa ${res.accuracy?.kappa}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '监督分类失败')
  } finally {
    classifying.value = false
  }
}

async function runClassifyLocal() {
  const img = currentImagery()
  if (!img) {
    ElMessage.warning('请先选择影像')
    return
  }
  classifying.value = true
  result.value = null
  try {
    const res = await analysisApi.classifyLocal({
      projectId: projectStore.currentId!,
      imageryId: img.id,
      // 整幅模式不传 AOI（后端按影像四至）；否则用当前兴趣区
      aoi: effectiveAoi(),
      samples: samples.value,
      minSamples: 8
    })
    result.value = res
    ElMessage.success(`分类完成：OA ${res.accuracy?.overallAccuracy}% · Kappa ${res.accuracy?.kappa}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '本地影像分类失败')
  } finally {
    classifying.value = false
  }
}

// ------------------------------------------------------------------
// 样本导入导出（纯前端，不经过服务器：样本是临时分析产物）
// ------------------------------------------------------------------

const CLASS_ALIAS: Record<string, string> = {
  采坑: 'PIT', 露天采坑: 'PIT', 排土场: 'DUMP', 废石堆: 'DUMP',
  尾矿: 'TAILINGS', 尾矿设施: 'TAILINGS', 裸地: 'BARE', 扰动区: 'BARE',
  道路: 'ROAD', 植被: 'VEGETATION', 水体: 'WATER'
}
const VALID_CLASSES = ['PIT', 'DUMP', 'TAILINGS', 'BARE', 'ROAD', 'VEGETATION', 'WATER']

function normalizeClass(raw: string): string | null {
  const t = String(raw || '').trim()
  if (!t) return null
  const upper = t.toUpperCase()
  if (VALID_CLASSES.includes(upper)) return upper
  return CLASS_ALIAS[t] || null
}

function pickSampleFile() {
  sampleInput.value?.click()
}

function onSampleFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const text = String(reader.result || '')
      const parsed = file.name.toLowerCase().endsWith('.csv')
        ? parseSampleCsv(text)
        : parseSampleGeoJson(text)
      importResult.value = parsed
      pendingImport.value = parsed.points
      importVisible.value = true
    } catch (err: any) {
      ElMessage.error(err?.message || '文件解析失败')
    } finally {
      input.value = ''
    }
  }
  reader.readAsText(file, 'utf-8')
}

/** CSV：表头容错（class/type/类型，lng/lon/x/经度，lat/y/纬度），# 开头为注释 */
function parseSampleCsv(text: string) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith('#'))
  if (!lines.length) throw new Error('文件为空或只有注释行')
  const header = lines[0].split(',').map((h) => h.trim().toLowerCase())
  const find = (...keys: string[]) => header.findIndex((h) => keys.includes(h))
  const iCls = find('classtype', 'class', 'type', '类型', '类别')
  const iLng = find('lng', 'lon', 'x', '经度')
  const iLat = find('lat', 'y', '纬度')
  if (iCls < 0 || iLng < 0 || iLat < 0) {
    throw new Error('表头缺少必要列：需要 classType、lng、lat（或中文「类型/经度/纬度」）')
  }

  const points: ClassifySample[] = []
  const errors: string[] = []
  let dup = 0
  let out = 0
  let unknown = 0
  const seen = new Set<string>()
  const b = bbox.value

  for (let n = 1; n < lines.length; n++) {
    const cols = lines[n].split(',')
    const cls = normalizeClass(cols[iCls] || '')
    const lng = Number(cols[iLng])
    const lat = Number(cols[iLat])
    if (!cls) {
      unknown++
      errors.push(`第 ${n + 1} 行：类别「${(cols[iCls] || '').trim()}」无法识别`)
      continue
    }
    if (!isFinite(lng) || !isFinite(lat)) {
      unknown++
      errors.push(`第 ${n + 1} 行：经纬度不是数字`)
      continue
    }
    if (Math.abs(lng) > 180 || Math.abs(lat) > 90) {
      out++
      errors.push(`第 ${n + 1} 行：${lng},${lat} 不像经纬度（可能是投影坐标，请先转 WGS84）`)
      continue
    }
    if (b && (lng < b.west || lng > b.east || lat < b.south || lat > b.north)) {
      out++
      errors.push(`第 ${n + 1} 行：落在影像范围外`)
      continue
    }
    const key = `${lng.toFixed(6)},${lat.toFixed(6)}`
    if (seen.has(key)) {
      dup++
      continue
    }
    seen.add(key)
    points.push({ classType: cls, lng: +lng.toFixed(7), lat: +lat.toFixed(7) })
  }

  return summarizeImport(lines.length - 1, points, { dup, out, unknown, errors })
}

/** GeoJSON：取 Point 要素，属性里认 classType/class/type */
function parseSampleGeoJson(text: string) {
  const obj = JSON.parse(text)
  const feats: any[] = obj.type === 'FeatureCollection' ? obj.features || [] : [obj]
  const points: ClassifySample[] = []
  const errors: string[] = []
  let unknown = 0
  let out = 0
  let dup = 0
  const seen = new Set<string>()
  const b = bbox.value

  feats.forEach((f, i) => {
    const geom = f.geometry || f
    if (geom?.type !== 'Point') return
    const [lng, lat] = geom.coordinates || []
    const props = f.properties || {}
    const cls = normalizeClass(props.classType || props.class || props.type || '')
    if (!cls) {
      unknown++
      errors.push(`第 ${i + 1} 个要素：缺少类别属性`)
      return
    }
    if (Math.abs(lng) > 180 || Math.abs(lat) > 90) {
      out++
      errors.push(`第 ${i + 1} 个要素：坐标不像经纬度`)
      return
    }
    if (b && (lng < b.west || lng > b.east || lat < b.south || lat > b.north)) {
      out++
      errors.push(`第 ${i + 1} 个要素：落在影像范围外`)
      return
    }
    const key = `${lng.toFixed(6)},${lat.toFixed(6)}`
    if (seen.has(key)) {
      dup++
      return
    }
    seen.add(key)
    points.push({ classType: cls, lng, lat })
  })

  return summarizeImport(feats.length, points, { dup, out, unknown, errors })
}

function summarizeImport(total: number, points: ClassifySample[], extra: {
  dup: number; out: number; unknown: number; errors: string[]
}) {
  const counts: Record<string, number> = {}
  for (const p of points) counts[p.classType] = (counts[p.classType] || 0) + 1
  const byClassText = Object.keys(counts).length
    ? Object.entries(counts).map(([k, v]) => `${classLabel(k)} ${v}`).join('、')
    : '无有效点'
  const short = Object.entries(counts).filter(([, v]) => v < 8)
  return {
    total,
    valid: points.length,
    dup: extra.dup,
    out: extra.out,
    unknown: extra.unknown,
    errors: extra.errors,
    byClassText,
    shortText: short.length
      ? `样本量偏少：${short.map(([k, v]) => `${classLabel(k)} ${v}`).join('、')}（每类建议 ≥8）`
      : '',
    points
  }
}

function applyImport(mode: 'merge' | 'replace') {
  const incoming = pendingImport.value || []
  if (mode === 'replace') {
    samples.value = incoming.slice()
  } else {
    const seen = new Set(samples.value.map((s) => `${s.lng},${s.lat}`))
    const add = incoming.filter((p) => !seen.has(`${p.lng},${p.lat}`))
    samples.value = [...samples.value, ...add]
  }
  importVisible.value = false
  ElMessage.success(`已${mode === 'replace' ? '替换' : '合并'}导入，当前共 ${samples.value.length} 个样本`)
}

function exportSamples(kind: 'csv' | 'geojson') {
  if (!samples.value.length) {
    ElMessage.warning('还没有样本可导出')
    return
  }
  const img = currentImagery()
  const ring = aoiRing.value
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const base = `样本_${img?.name?.replace(/\.[^.]+$/, '') || '区域'}_${stamp}`

  if (kind === 'csv') {
    const head = [
      '# schema=v1',
      `# imagery=${img?.name || ''}`,
      ring.length ? `# aoi=${ring.map((p) => p.join(',')).join(';')}` : '# aoi=整幅影像',
      `# exported=${new Date().toISOString()}`,
      'classType,lng,lat,note'
    ].join('\n')
    const body = samples.value.map((s) => `${s.classType},${s.lng},${s.lat},`).join('\n')
    // BOM 让 Excel 直接打开不乱码
    download(`${base}.csv`, '\ufeff' + head + '\n' + body, 'text/csv;charset=utf-8')
  } else {
    const fc = {
      type: 'FeatureCollection',
      features: samples.value.map((s, i) => ({
        type: 'Feature',
        properties: { classType: s.classType, index: i + 1 },
        geometry: { type: 'Point', coordinates: [s.lng, s.lat] }
      }))
    }
    download(`${base}.geojson`, JSON.stringify(fc, null, 2), 'application/geo+json')
  }
  ElMessage.success(`已导出 ${samples.value.length} 个样本`)
}

function download(name: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** 各类分别落一条解译记录，走既有的时序/风险/报告链路 */
async function saveAll() {
  const res = result.value
  const opt = currentOption()
  if (!res?.classes || !opt) return
  saving.value = true
  let saved = 0
  try {
    const areaHa = opt.areaHa || 1
    for (const c of res.classes) {
      const feats = res.features?.[c.classType] || []
      if (!feats.length || c.areaHa <= 0) continue
      const rings = feats.map((f: any) => f.geometry.coordinates[0] as number[][])
      await extractionApi.save({
        projectId: projectStore.currentId!,
        name: `${c.label}-监督分类`,
        classType: c.classType,
        features: rings,
        aoiJson: JSON.stringify(opt.ring),
        coveragePct: c.pctOfAoi,
        aoiAreaHa: areaHa,
        acquisitionDate: (res.scene?.datetime || range.value[1]).slice(0, 10),
        satellite: source.value === 'LOCAL'
          ? (currentImagery()?.name?.includes('GF7') ? 'GF7' : 'GF2')
          : 'SENTINEL2',
        // 标记解译方法：叠加分析要按方法区分"分类结果"与"指数结果"
        method: 'SUPERVISED',
        accuracyJson: JSON.stringify({
          overallAccuracy: res.accuracy?.overallAccuracy,
          kappa: res.accuracy?.kappa,
          oobScore: res.accuracy?.oobScore,
          split: res.accuracy?.split,
          sampleCount: res.accuracy?.sampleCount,
          confusionMatrix: res.accuracy?.confusionMatrix,
          labels: res.accuracy?.labels
        })
      })
      saved++
    }
    ElMessage.success(`已保存 ${saved} 个类别的解译记录，可用于时序与风险评估`)
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadOptions)
watch(() => projectStore.currentId, () => {
  aoiId.value = null
  onAoiChange()
  loadOptions()
})
</script>

<style scoped>
.cls-page { display: flex; flex-direction: column; gap: 12px; }
.op-card :deep(.el-card__body) { padding: 10px 14px; }
.op-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.op-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lbl { font-size: 12px; color: #6b7280; }
.warn-row { margin-top: 8px; font-size: 12px; color: #b45309; }

.main { display: grid; grid-template-columns: 1fr 430px; gap: 12px; align-items: start; }
@media (max-width: 1400px) { .main { grid-template-columns: 1fr; } }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.head-right { display: flex; align-items: center; gap: 6px; }
.card-hint { font-size: 11px; color: #a9aeb8; }

.map-card :deep(.el-card__body) { padding: 8px; }
.viewer {
  position: relative; height: 620px; overflow: hidden;
  background: #1b1f24; border-radius: 6px; cursor: crosshair;
}
.canvas-wrap { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
.view-img { display: block; max-width: none; user-select: none; -webkit-user-drag: none; image-rendering: pixelated; }
.dots { position: absolute; inset: 0; pointer-events: none; }
.dot {
  position: absolute; border-radius: 50%;
  /* 宽高与 transform 由 dotStyleOf 动态给定（屏幕尺寸恒定） */
  box-shadow: 0 0 0 1px #fff;
}
.viewer-empty {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #9aa3ad; font-size: 13px; text-align: center; padding: 0 40px; line-height: 1.7;
}
.zoom-tip {
  position: absolute; right: 8px; bottom: 8px; padding: 2px 6px;
  background: rgba(0, 0, 0, 0.45); color: #fff; font-size: 11px; border-radius: 4px;
}

.res-hint {
  display: flex; align-items: flex-start; gap: 6px;
  margin-top: 8px; padding: 7px 9px; border-radius: 6px;
  background: #f0fdfa; border: 1px solid #ccfbf1;
  font-size: 11px; color: #0f766e; line-height: 1.6;
}
.res-hint.warn { background: #fffbeb; border-color: #fde68a; color: #b45309; }
.res-hint :deep(.el-icon) { margin-top: 2px; }

.side { display: flex; flex-direction: column; gap: 12px; }
.class-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: flex; align-items: center; gap: 5px; padding: 4px 8px;
  border: 1px solid #e5e7eb; border-radius: 14px; font-size: 12px; cursor: pointer;
  color: #4b5563; background: #fff;
}
.chip.active { border-color: #0d9488; background: #f0fdfa; color: #0f766e; font-weight: 600; }
.chip-dot { width: 8px; height: 8px; border-radius: 50%; }
.chip-count { color: #9ca3af; font-size: 11px; }
.sample-hint { font-size: 11px; color: #909399; line-height: 1.7; margin: 10px 0; }
.run-btn { width: 100%; }
.run-hint { font-size: 11px; color: #a9aeb8; line-height: 1.6; margin-top: 6px; }

.acc-kpi { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.kpi { background: #f6f8fa; border-radius: 8px; padding: 10px 6px; text-align: center; }
.kpi-num { font-size: 20px; font-weight: 700; color: #0d9488; }
.kpi-num span { font-size: 12px; font-weight: 400; margin-left: 1px; }
.kpi-lbl { font-size: 11px; color: #6b7280; margin-top: 2px; }

.mat-title { font-size: 12px; color: #4b5563; margin: 6px 0; }
.cm { width: 100%; border-collapse: collapse; font-size: 11px; }
.cm th, .cm td { border: 1px solid #eef0f3; padding: 3px 4px; text-align: center; }
.cm th { background: #f8fafb; color: #4b5563; font-weight: 500; }
.cm td.diag { background: #e8f5e9; color: #1b5e20; font-weight: 600; }
.cm td.err { background: #fff3e0; color: #b45309; }

.cls-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; }
.sec-title { font-size: 12px; color: #4b5563; margin: 12px 0 6px; }
.imp-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.imp-name { width: 80px; font-size: 11px; color: #6b7280; }
.imp-bar { flex: 1; height: 7px; background: #f0f2f5; border-radius: 4px; overflow: hidden; }
.imp-bar i { display: block; height: 100%; background: #0d9488; }
.imp-val { width: 38px; text-align: right; font-size: 11px; color: #374151; }
.cls-img { width: 100%; border: 1px solid #eef0f3; border-radius: 6px; image-rendering: pixelated; }
.map-btn { width: 100%; margin-top: 10px; }
.cnt { color: #0d9488; }
.hidden-input { display: none; }
.aoi-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.imp-line { font-size: 12px; color: #374151; line-height: 1.9; }
.imp-line .ok { color: #2e7d32; }
.imp-warn { margin-top: 8px; border-radius: 6px; }
.imp-errs { margin-top: 8px; font-size: 11px; color: #b45309; line-height: 1.7; max-height: 120px; overflow-y: auto; }
.dlg-grid { display: grid; grid-template-columns: 1fr 240px; gap: 14px; align-items: start; }
.dlg-figure { min-width: 0; }
.dlg-img { width: 100%; max-height: 68vh; object-fit: contain; image-rendering: pixelated; }
.dlg-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 8px; }
.lg { display: flex; align-items: center; gap: 5px; font-size: 12px; color: #4b5563; }
.lg i { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
.dlg-method { font-size: 11px; color: #6b7280; line-height: 1.6; margin-bottom: 6px; }
.warn-tip { font-size: 11px; color: #b45309; line-height: 1.6; margin-top: 4px; }
.disclaimer { font-size: 10px; color: #a9aeb8; line-height: 1.6; margin-top: 8px; }
</style>

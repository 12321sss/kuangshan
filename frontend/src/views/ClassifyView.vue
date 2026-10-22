<template>
  <div class="cls-page">
    <!-- 参数条 -->
    <el-card shadow="never" class="op-card">
      <div class="op-bar">
        <div class="op-group">
          <span class="lbl">分析区</span>
          <el-select v-model="aoiId" size="small" placeholder="选择已导入的边界" style="width: 210px" @change="onAoiChange">
            <el-option v-for="o in aoiOptions" :key="o.id" :label="`${o.name}（${o.areaHa} ha）`" :value="o.id" />
          </el-select>
          <el-date-picker v-model="range" type="daterange" size="small" value-format="YYYY-MM-DD"
                          start-placeholder="起始" end-placeholder="结束" style="width: 230px" />
          <span class="lbl">云量</span>
          <el-input-number v-model="maxCloud" :min="1" :max="100" :step="5" size="small" style="width: 80px" />
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
            <span>真彩影像与样本点</span>
            <span class="card-hint">左键点选样本 · 滚轮缩放 · 右键拖动平移</span>
          </div>
        </template>
        <div ref="boxRef" class="viewer" @wheel.prevent="onWheel" @contextmenu.prevent
             @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"
             @click="onClick">
          <div class="canvas-wrap" :style="wrapStyle">
            <img v-if="image" ref="imgRef" :src="'data:image/png;base64,' + image" class="view-img" @load="onImgLoad" />
            <div v-if="image" class="dots">
              <span v-for="(s, i) in samples" :key="i" class="dot"
                    :style="{ left: dotStyle(s).left, top: dotStyle(s).top, background: classColor(s.classType) }"
                    :title="`${classLabel(s.classType)} #${i + 1}`"></span>
            </div>
          </div>
          <div v-if="!image && !loadingImg" class="viewer-empty">
            选好分析区与日期后点「加载影像」，然后在图上点选样本
          </div>
          <div v-if="loadingImg" class="viewer-empty">影像加载中…（首次需下载瓦片，约 20-60 秒）</div>
          <div class="zoom-tip">×{{ scale.toFixed(1) }}</div>
        </div>
      </el-card>

      <!-- 右：样本与结果 -->
      <div class="side">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>样本采集</span>
              <el-button link type="danger" size="small" :disabled="!samples.length" @click="samples = []">清空</el-button>
            </div>
          </template>
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

          <div class="sec-title">特征重要性</div>
          <div v-for="f in topFeatures" :key="f.name" class="imp-row">
            <span class="imp-name">{{ f.name }}</span>
            <div class="imp-bar"><i :style="{ width: f.importance * 4 + '%' }"></i></div>
            <span class="imp-val">{{ f.importance }}%</span>
          </div>

          <div class="sec-title">分类图</div>
          <img v-if="result.imageBase64" :src="'data:image/png;base64,' + result.imageBase64" class="cls-img" />

          <div v-for="(w, i) in result.warnings" :key="i" class="warn-tip">· {{ w }}</div>
          <div class="disclaimer">{{ result.disclaimer }}</div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi, extractionApi } from '@/api'
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

const aoiOptions = ref<AoiOption[]>([])
const aoiId = ref<number | null>(null)
const range = ref<[string, string]>([
  new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10),
  new Date().toISOString().slice(0, 10)
])
const maxCloud = ref(20)

const image = ref<string>('')
const bbox = ref<{ west: number; south: number; east: number; north: number } | null>(null)
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
function dotStyle(s: ClassifySample) {
  const b = bbox.value
  if (!b) return { left: '0%', top: '0%' }
  const x = ((s.lng - b.west) / (b.east - b.west)) * 100
  const y = ((b.north - s.lat) / (b.north - b.south)) * 100
  return { left: `${x}%`, top: `${y}%` }
}

async function loadOptions() {
  const pid = projectStore.currentId
  if (!pid) return
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

function onAoiChange() {
  image.value = ''
  samples.value = []
  result.value = null
  bbox.value = null
}

async function loadPreview() {
  const opt = currentOption()
  if (!opt) {
    ElMessage.warning('请先选择分析区')
    return
  }
  loadingImg.value = true
  try {
    const res = await sentinelApi.preview(opt.ring, range.value[0], range.value[1], maxCloud.value, 'TRUE_COLOR')
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

function onImgLoad() {
  const el = imgRef.value
  if (el) imgNatural.value = { w: el.naturalWidth, h: el.naturalHeight }
}

// ---- 缩放与平移 ----
function onWheel(e: WheelEvent) {
  if (!image.value) return
  const delta = e.deltaY < 0 ? 1.2 : 1 / 1.2
  const next = Math.min(10, Math.max(1, scale.value * delta))
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
        satellite: 'SENTINEL2'
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
  position: absolute; width: 9px; height: 9px; border-radius: 50%;
  transform: translate(-50%, -50%); box-shadow: 0 0 0 1.5px #fff;
}
.viewer-empty {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #9aa3ad; font-size: 13px; text-align: center; padding: 0 40px; line-height: 1.7;
}
.zoom-tip {
  position: absolute; right: 8px; bottom: 8px; padding: 2px 6px;
  background: rgba(0, 0, 0, 0.45); color: #fff; font-size: 11px; border-radius: 4px;
}

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
.warn-tip { font-size: 11px; color: #b45309; line-height: 1.6; margin-top: 4px; }
.disclaimer { font-size: 10px; color: #a9aeb8; line-height: 1.6; margin-top: 8px; }
</style>

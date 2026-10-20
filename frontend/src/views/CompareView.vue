<template>
  <div class="cmp-page">
    <!-- 控制栏 -->
    <el-card shadow="never" class="ctrl-card">
      <div class="ctrl-row">
        <span class="ctrl-label">对比期次</span>
        <el-select v-model="earlyId" size="small" style="width: 220px" placeholder="选择早期记录">
          <el-option v-for="r in recordOptions" :key="'e' + r.id" :label="`${r.date} · ${r.classLabel}`" :value="r.id" />
        </el-select>
        <span class="ctrl-vs">VS</span>
        <el-select v-model="lateId" size="small" style="width: 220px" placeholder="选择晚期记录">
          <el-option v-for="r in recordOptions" :key="'l' + r.id" :label="`${r.date} · ${r.classLabel}`" :value="r.id" />
        </el-select>
        <el-button size="small" type="primary" :loading="loading" :disabled="!earlyId || !lateId" @click="loadImages">
          载入对比
        </el-button>
        <el-radio-group v-model="mode" size="small" style="margin-left: auto">
          <el-radio-button value="slider">滑块对比</el-radio-button>
          <el-radio-button value="side">并排对比</el-radio-button>
        </el-radio-group>
      </div>
      <div class="ctrl-hint">
        影像来自平台的 Sentinel-2 在线检索（同一 AOI、不同拍摄日期），用于直观查看矿区地表变化。
      </div>
    </el-card>

    <el-empty v-if="recordOptions.length < 2" description="至少需要两条解译记录才能做双期对比">
      <el-button type="primary" size="small" @click="$router.push('/remote-extract')">去遥感提取</el-button>
    </el-empty>

    <template v-else>
      <!-- 滑块对比 -->
      <el-card v-if="mode === 'slider'" shadow="never" class="view-card">
        <template #header>
          <div class="vc-head">
            <span>{{ earlyLabel }}</span>
            <span class="vc-vs">|</span>
            <span>{{ lateLabel }}</span>
          </div>
        </template>
        <div v-if="!earlyImg || !lateImg" class="placeholder">
          <el-icon :size="34"><Picture /></el-icon>
          <div>选择两期记录后点「载入对比」</div>
        </div>
        <div v-else class="slider-wrap" ref="sliderRef" @mousedown="startDrag" @touchstart.prevent="startDrag">
          <!-- 晚期影像铺满作为底图 -->
          <img :src="lateImg" class="slider-img base" alt="晚期影像" />
          <!-- 早期影像按滑块位置裁切 -->
          <div class="slider-top" :style="{ clipPath: `inset(0 ${100 - sliderPct}% 0 0)` }">
            <img :src="earlyImg" class="slider-img" alt="早期影像" />
          </div>
          <!-- 分隔线与把手 -->
          <div class="slider-line" :style="{ left: sliderPct + '%' }">
            <div class="slider-handle">
              <span>‹</span><span>›</span>
            </div>
          </div>
          <div class="slider-tag left">早期 {{ earlyLabel }}</div>
          <div class="slider-tag right">晚期 {{ lateLabel }}</div>
        </div>
      </el-card>

      <!-- 并排对比 -->
      <div v-else class="side-wrap">
        <el-card shadow="never" class="side-card">
          <template #header><span>{{ earlyLabel }}</span></template>
          <div v-if="!earlyImg" class="placeholder"><div>载入后显示</div></div>
          <img v-else :src="earlyImg" class="side-img" alt="早期影像" />
        </el-card>
        <el-card shadow="never" class="side-card">
          <template #header><span>{{ lateLabel }}</span></template>
          <div v-if="!lateImg" class="placeholder"><div>载入后显示</div></div>
          <img v-else :src="lateImg" class="side-img" alt="晚期影像" />
        </el-card>
      </div>

      <!-- 两期统计对比 -->
      <el-card v-if="earlyRec && lateRec" shadow="never" class="stat-card">
        <template #header><span>两期解译统计对比</span></template>
        <div class="stat-grid">
          <div class="stat-item">
            <div class="si-label">{{ earlyRec.date }} · {{ earlyRec.classLabel }}</div>
            <div class="si-num">{{ earlyRec.coverage.toFixed(2) }}%</div>
            <div class="si-sub">覆盖率</div>
          </div>
          <div class="stat-item">
            <div class="si-label">{{ lateRec.date }} · {{ lateRec.classLabel }}</div>
            <div class="si-num">{{ lateRec.coverage.toFixed(2) }}%</div>
            <div class="si-sub">覆盖率</div>
          </div>
          <div class="stat-item">
            <div class="si-label">变化量</div>
            <div class="si-num" :style="{ color: delta >= 0 ? '#ef4444' : '#22c55e' }">
              {{ delta >= 0 ? '+' : '' }}{{ delta.toFixed(2) }}%
            </div>
            <div class="si-sub">{{ delta >= 0 ? '增长' : '减少' }}</div>
          </div>
        </div>
        <div class="stat-note">
          提示：更精确的空间变化请用「遥感提取」页的对比差异功能（后端做多边形空间求差，区分新增/消失区域）。
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Picture } from '@element-plus/icons-vue'
import { extractionApi } from '@/api'
import { sentinelApi } from '@/api/sentinel'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

interface RecOption {
  id: number
  date: string
  classType: string
  classLabel: string
  coverage: number
  aoi: number[][]
}

const CLASS_LABEL: Record<string, string> = {
  PIT: '采坑', DUMP: '排土场', TAILINGS: '尾矿库', BARE: '裸地扰动',
  VEGETATION: '植被', WATER: '水体', ROAD: '道路设施', BUILDING: '建筑', MOUNTAIN: '山体'
}

const records = ref<RecOption[]>([])
const earlyId = ref<number | null>(null)
const lateId = ref<number | null>(null)
const mode = ref<'slider' | 'side'>('slider')
const loading = ref(false)
const earlyImg = ref('')
const lateImg = ref('')
const sliderPct = ref(50)

const recordOptions = computed(() =>
  [...records.value].sort((a, b) => a.date.localeCompare(b.date))
)

const earlyRec = computed(() => records.value.find((r) => r.id === earlyId.value) || null)
const lateRec = computed(() => records.value.find((r) => r.id === lateId.value) || null)
const earlyLabel = computed(() => (earlyRec.value ? earlyRec.value.date : '早期'))
const lateLabel = computed(() => (lateRec.value ? lateRec.value.date : '晚期'))
const delta = computed(() => {
  if (!earlyRec.value || !lateRec.value) return 0
  return lateRec.value.coverage - earlyRec.value.coverage
})

async function loadRecords() {
  try {
    const list = await extractionApi.list(projectStore.currentId ?? undefined)
    records.value = list
      .filter((e) => e.aoiJson && e.acquisitionDate)
      .map((e) => ({
        id: e.id,
        date: String(e.acquisitionDate).slice(0, 10),
        classType: e.classType,
        classLabel: CLASS_LABEL[e.classType] || e.classType,
        coverage: e.coveragePct || 0,
        aoi: safeParse(e.aoiJson)
      }))
      .filter((r) => r.aoi.length >= 3)
    // 默认选最早与最晚
    const sorted = recordOptions.value
    if (sorted.length >= 2) {
      earlyId.value = sorted[0].id
      lateId.value = sorted[sorted.length - 1].id
    }
  } catch (e: any) {
    ElMessage.error('加载记录失败：' + e.message)
  }
}

function safeParse(json?: string): number[][] {
  try {
    const v = json ? JSON.parse(json) : []
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

async function loadImages() {
  if (!earlyRec.value || !lateRec.value) return
  if (earlyRec.value.aoi.length < 3 || lateRec.value.aoi.length < 3) {
    ElMessage.warning('记录缺少 AOI 范围，无法加载影像')
    return
  }
  // 影像对比必须是同一区域的前后两期，不同 AOI 没法对齐
  const key = (r: number[][]) => r.map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`).sort().join(';')
  if (key(earlyRec.value.aoi) !== key(lateRec.value.aoi)) {
    ElMessage.warning('所选两期不是同一区域，请选择同一 AOI 的不同日期记录')
    return
  }
  loading.value = true
  try {
    // 两期影像并行拉取（同一 AOI 不同日期），返回 base64 → DataURL 供 <img> 直接显示
    const [a, b] = await Promise.all([
      fetchPreviewDataUrl(earlyRec.value.aoi, earlyRec.value.date),
      fetchPreviewDataUrl(lateRec.value.aoi, lateRec.value.date)
    ])
    earlyImg.value = a
    lateImg.value = b
    ElMessage.success('两期影像已载入，拖动中间滑块对比')
  } catch (e: any) {
    ElMessage.error('影像加载失败：' + (e.message || ''))
  } finally {
    loading.value = false
  }
}

/** 拉取某一天的 AOI 真彩预览，返回可直接用于 <img src> 的 data URL */
async function fetchPreviewDataUrl(aoi: number[][], date: string): Promise<string> {
  // 用拍摄日期前后各 15 天做检索窗口，尽量命中该期影像
  const d = new Date(date)
  const fmt = (x: Date) => x.toISOString().slice(0, 10)
  const start = new Date(d.getTime() - 15 * 86400000)
  const end = new Date(d.getTime() + 15 * 86400000)
  const res = await sentinelApi.preview(aoi, fmt(start), fmt(end), 60)
  return `data:image/png;base64,${res.image_base64}`
}

// ---- 滑块拖动 ----
const sliderRef = ref<HTMLDivElement>()
let dragging = false

function startDrag(e: MouseEvent | TouchEvent) {
  dragging = true
  updateByEvent(e)
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
  window.addEventListener('touchmove', onDrag, { passive: false })
  window.addEventListener('touchend', endDrag)
}

function onDrag(e: MouseEvent | TouchEvent) {
  if (!dragging) return
  e.preventDefault?.()
  updateByEvent(e)
}

function updateByEvent(e: MouseEvent | TouchEvent) {
  const el = sliderRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const clientX = 'touches' in e ? (e.touches[0]?.clientX ?? 0) : e.clientX
  const pct = ((clientX - rect.left) / rect.width) * 100
  sliderPct.value = Math.min(100, Math.max(0, pct))
}

function endDrag() {
  dragging = false
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', endDrag)
  window.removeEventListener('touchmove', onDrag)
  window.removeEventListener('touchend', endDrag)
}

onMounted(loadRecords)
onBeforeUnmount(endDrag)
</script>

<style scoped>
.cmp-page { display: flex; flex-direction: column; gap: 12px; }

.ctrl-card { border: 1px solid #eceef2; border-radius: 10px; }
.ctrl-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ctrl-label { font-size: 13px; color: #4e5969; }
.ctrl-vs { font-size: 12px; color: #a9aeb8; font-weight: 700; }
.ctrl-hint { margin-top: 8px; font-size: 12px; color: #a9aeb8; }

.view-card { border: 1px solid #eceef2; border-radius: 10px; }
.vc-head { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; }
.vc-vs { color: #a9aeb8; font-weight: 400; }

.placeholder {
  height: 320px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  color: #a9aeb8; font-size: 13px; background: #fafbfc; border-radius: 8px;
}

/* 滑块对比容器 */
.slider-wrap {
  position: relative; width: 100%; height: 480px;
  border-radius: 8px; overflow: hidden; background: #0f172a;
  cursor: ew-resize; user-select: none;
}
.slider-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.slider-top { position: absolute; inset: 0; }
.slider-line {
  position: absolute; top: 0; bottom: 0; width: 2px;
  background: #fff; box-shadow: 0 0 6px rgba(0, 0, 0, 0.5);
  transform: translateX(-1px);
}
.slider-handle {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 34px; height: 34px; border-radius: 50%;
  background: #fff; color: #0d9488;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; gap: 2px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
}
.slider-tag {
  position: absolute; bottom: 10px; padding: 4px 10px;
  background: rgba(0, 0, 0, 0.55); color: #fff;
  font-size: 12px; border-radius: 12px; pointer-events: none;
}
.slider-tag.left { left: 10px; }
.slider-tag.right { right: 10px; }

/* 并排 */
.side-wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.side-card { border: 1px solid #eceef2; border-radius: 10px; }
.side-img { width: 100%; height: 380px; object-fit: cover; border-radius: 8px; display: block; }

/* 统计 */
.stat-card { border: 1px solid #eceef2; border-radius: 10px; }
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.stat-item { background: #f6f8fa; border-radius: 10px; padding: 14px; text-align: center; }
.si-label { font-size: 12px; color: #86909c; }
.si-num { font-size: 26px; font-weight: 700; color: #0d9488; margin: 6px 0 2px; }
.si-sub { font-size: 11px; color: #a9aeb8; }
.stat-note { margin-top: 12px; font-size: 12px; color: #a9aeb8; line-height: 1.6; }

@media (max-width: 900px) {
  .side-wrap { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: 1fr; }
  .slider-wrap { height: 320px; }
  .side-img { height: 260px; }
}
</style>

<template>
  <div class="terrain-page">
    <!-- ============ 数据源 ============ -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="head">
          <div>
            <span class="head-title">地形与边坡分析</span>
            <span class="head-sub">基于 DEM 计算坡度、坡向、低洼汇水，为边坡安全评估提供地形底数</span>
          </div>
          <el-tag size="small" effect="plain" type="info">约 10m 分辨率</el-tag>
        </div>
      </template>

      <div class="src-row">
        <div class="src-item">
          <label>AOI 来源</label>
          <el-select v-model="sourceType" size="default" style="width: 160px" @change="onSourceChange">
            <el-option label="我的关注区" value="watch" />
            <el-option label="手动输入坐标" value="manual" />
            <el-option label="最近一次圈选" value="last" />
          </el-select>
        </div>

        <div v-if="sourceType === 'watch'" class="src-item grow">
          <label>选择关注区</label>
          <el-select v-model="selectedWatchId" placeholder="请选择已保存的监测区域" style="width: 100%">
            <el-option
              v-for="w in watches"
              :key="w.id"
              :label="`${w.name}（${w.periodCount} 期）`"
              :value="w.id"
            />
          </el-select>
          <div v-if="!watches.length" class="hint">
            还没有关注区。先在「遥感提取」页圈选并保存为关注区，之后就能在这里直接分析。
          </div>
        </div>

        <div v-else-if="sourceType === 'manual'" class="src-item grow">
          <label>坐标（每行一个 lng,lat）</label>
          <el-input
            v-model="manualCoords"
            type="textarea"
            :rows="3"
            placeholder="116.014,26.466&#10;116.030,26.466&#10;116.030,26.480&#10;116.014,26.480"
          />
        </div>

        <div class="src-item">
          <label>DEM 缩放</label>
          <el-select v-model="zoom" style="width: 130px">
            <el-option label="14（约 9.6m）" :value="14" />
            <el-option label="15（约 4.8m）" :value="15" />
          </el-select>
        </div>

        <el-button type="primary" :loading="loading" :disabled="!aoiValid" @click="runAnalyze">
          开始分析
        </el-button>
      </div>

      <div v-if="loading" class="loading-hint">
        正在读取高程瓦片并计算坡度，首次约 10–30 秒（之后有本地缓存）
      </div>
    </el-card>

    <!-- ============ 空状态 ============ -->
    <el-card v-if="!result && !loading" shadow="never" class="panel">
      <el-empty description="还没有分析结果" :image-size="100">
        <div class="empty-hint">
          选择或输入 AOI 后点「开始分析」，将得到高程统计、坡度分级与低洼汇水筛查结果。
        </div>
      </el-empty>
    </el-card>

    <!-- ============ 结果 ============ -->
    <template v-if="result">
      <div class="result-grid">
        <!-- 坡度专题图 -->
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="head">
              <span class="head-title">坡度分级专题图</span>
              <span class="head-sub">
                {{ result.grid.width }}×{{ result.grid.height }} 栅格 · {{ result.grid.mPerPixel }}m/像元
              </span>
            </div>
          </template>
          <img
            v-if="result.slopeImageBase64"
            :src="'data:image/png;base64,' + result.slopeImageBase64"
            class="slope-img"
            alt="坡度分级图"
          />
          <div class="legend">
            <span v-for="l in result.legend" :key="l.label" class="lg-item">
              <i :style="{ background: l.color }"></i>{{ l.label }}
            </span>
          </div>
        </el-card>

        <!-- 关键指标 -->
        <el-card shadow="never" class="panel">
          <template #header><span class="head-title">地形指标</span></template>
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi-num">{{ result.summary.elevMin }}–{{ result.summary.elevMax }}</div>
              <div class="kpi-label">高程范围(m)</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.summary.reliefM }}</div>
              <div class="kpi-label">地形起伏(m)</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.summary.slopeMean }}°</div>
              <div class="kpi-label">平均坡度</div>
            </div>
            <div class="kpi">
              <div class="kpi-num" :class="{ warn: result.summary.steepPct > 15 }">
                {{ result.summary.steepPct }}%
              </div>
              <div class="kpi-label">陡坡(≥15°)占比</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.summary.slopeP90 }}°</div>
              <div class="kpi-label">坡度 P90</div>
            </div>
            <div class="kpi">
              <div class="kpi-num" :class="{ warn: result.pond.areaPct > 3 }">
                {{ result.pond.areaPct }}%
              </div>
              <div class="kpi-label">低洼汇水占比</div>
            </div>
          </div>
          <div class="pond-note">{{ result.pond.note }}</div>
        </el-card>
      </div>

      <!-- 坡度分级明细 -->
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="head">
            <span class="head-title">坡度分级分布</span>
            <span class="head-sub">陡坡与极陡占比是边坡安全的关键输入</span>
          </div>
        </template>
        <div class="dist-bar">
          <div
            v-for="d in result.summary.distribution"
            :key="d.label"
            class="dist-seg"
            :style="{ width: d.pct + '%', background: colorOf(d.label) }"
            :title="`${d.label} ${d.pct}%`"
          ></div>
        </div>
        <el-table :data="result.summary.distribution" size="small" class="dist-table">
          <el-table-column label="坡度区间" min-width="140">
            <template #default="{ row }">
              <span class="cls-dot" :style="{ background: colorOf(row.label) }"></span>{{ row.label }}
            </template>
          </el-table-column>
          <el-table-column prop="pct" label="面积占比(%)" width="130" />
          <el-table-column label="安全含义" min-width="240">
            <template #default="{ row }">{{ meaningOf(row.label) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 精度与口径 -->
      <el-card shadow="never" class="panel note-panel">
        <el-icon class="note-icon"><InfoFilled /></el-icon>
        <div>
          <div class="note-title">数据来源与精度边界</div>
          <div class="note-line">数据源：{{ result.precision.source }}</div>
          <div class="note-line">地面分辨率：约 {{ result.precision.groundResolutionM }} m</div>
          <div class="note-line warn-text">{{ result.precision.limitation }}</div>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { aoiWatchApi } from '@/api'
import { terrainApi } from '@/api/sentinel'
import type { TerrainResult } from '@/api/sentinel'
import { useProjectStore } from '@/stores/project'

/** 关注区列表项（只用到 id/name/aoiJson/期数） */
interface WatchItem {
  id: number
  name: string
  aoiJson: string
  periodCount: number
}

const projectStore = useProjectStore()

const sourceType = ref<'watch' | 'manual' | 'last'>('watch')
const watches = ref<WatchItem[]>([])
const selectedWatchId = ref<number>()
const manualCoords = ref('')
const zoom = ref(14)

const loading = ref(false)
const result = ref<TerrainResult | null>(null)

/** 解析手输坐标：每行 "lng,lat" */
function parseManualCoords(text: string): number[][] {
  const out: number[][] = []
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim()
    if (!t) continue
    const parts = t.split(/[,，\s]+/).map(Number)
    if (parts.length >= 2 && parts.every((n) => Number.isFinite(n))) {
      out.push([parts[0], parts[1]])
    }
  }
  return out
}

/** 当前选中的 AOI（环） */
const currentAoi = computed<number[][]>(() => {
  if (sourceType.value === 'watch') {
    const w = watches.value.find((x) => x.id === selectedWatchId.value)
    if (!w?.aoiJson) return []
    try {
      const arr = JSON.parse(w.aoiJson)
      return Array.isArray(arr) ? arr : []
    } catch {
      return []
    }
  }
  if (sourceType.value === 'manual') return parseManualCoords(manualCoords.value)
  // 最近一次圈选：从 localStorage 取（遥感提取页保存）
  try {
    const raw = localStorage.getItem('last_aoi')
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
})

const aoiValid = computed(() => currentAoi.value.length >= 3)

function onSourceChange() {
  result.value = null
}

async function loadWatches() {
  try {
    const pid = projectStore.currentId ?? undefined
    watches.value = (await aoiWatchApi.list(pid)) as unknown as WatchItem[]
    if (!selectedWatchId.value && watches.value.length) {
      selectedWatchId.value = watches.value[0].id
    }
  } catch {
    watches.value = []
  }
}

async function runAnalyze() {
  const aoi = currentAoi.value
  if (aoi.length < 3) {
    ElMessage.warning('AOI 至少需要 3 个点')
    return
  }
  loading.value = true
  try {
    result.value = await terrainApi.analyze(aoi, zoom.value, true)
    ElMessage.success(
      `分析完成：起伏 ${result.value.summary.reliefM}m，平均坡度 ${result.value.summary.slopeMean}°，` +
      `陡坡占比 ${result.value.summary.steepPct}%`
    )
  } catch (e: any) {
    ElMessage.error(e?.message || '地形分析失败，请确认解译服务已启动')
  } finally {
    loading.value = false
  }
}

/** 坡度分级配色（与后端 PNG 一致） */
function colorOf(label: string): string {
  if (label.includes('<2')) return '#4caf50'
  if (label.includes('2-6')) return '#aed581'
  if (label.includes('6-15')) return '#ffd54f'
  if (label.includes('15-25')) return '#ff9800'
  return '#d32f2f'
}

/** 每个坡度区间的安全含义，帮助非专业人员理解 */
function meaningOf(label: string): string {
  if (label.includes('<2')) return '近似平坦，排水条件好，基本无重力侵蚀风险'
  if (label.includes('2-6')) return '缓坡，常规排水即可，无需专门防护'
  if (label.includes('6-15')) return '缓陡坡，需关注坡面汇水与排水沟设置'
  if (label.includes('15-25')) return '陡坡，易发生面蚀与浅层滑塌，建议核查截排水'
  return '极陡，滑坡与崩塌敏感区，须现场核查边坡形态与支护'
}

onMounted(loadWatches)
watch(() => projectStore.currentId, () => {
  selectedWatchId.value = undefined
  result.value = null
  loadWatches()
})
</script>

<style scoped>
.terrain-page { display: flex; flex-direction: column; gap: 14px; }
.panel { border: 1px solid #eceef2; border-radius: 10px; }

.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.head-title { font-size: 14px; font-weight: 700; color: #1d2129; }
.head-sub { font-size: 12px; color: #86909c; margin-left: 8px; font-weight: 400; }

/* 数据源行：横向排列，不挤 */
.src-row { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; }
.src-item { display: flex; flex-direction: column; gap: 5px; }
.src-item.grow { flex: 1; min-width: 240px; }
.src-item label { font-size: 12px; color: #86909c; }
.hint { font-size: 11px; color: #a9aeb8; line-height: 1.6; }
.loading-hint { margin-top: 10px; font-size: 12px; color: #0d9488; }
.empty-hint { font-size: 12px; color: #86909c; line-height: 1.8; }

.result-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
.slope-img {
  width: 100%; border-radius: 8px; border: 1px solid #eceef2;
  image-rendering: pixelated;
}
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 12px; color: #4e5969; }
.lg-item { display: inline-flex; align-items: center; gap: 5px; }
.lg-item i { width: 10px; height: 10px; border-radius: 2px; }

.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.kpi { background: #f6f8fa; border-radius: 8px; padding: 10px; text-align: center; }
.kpi-num { font-size: 17px; font-weight: 700; color: #0d9488; }
.kpi-num.warn { color: #ef4444; }
.kpi-label { font-size: 11px; color: #86909c; margin-top: 3px; }
.pond-note { margin-top: 10px; font-size: 11px; color: #86909c; line-height: 1.7; }

.dist-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; margin-bottom: 12px; }
.dist-seg { height: 100%; }
.dist-table { margin-top: 4px; }
.cls-dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; }

.note-panel :deep(.el-card__body) { display: flex; gap: 10px; align-items: flex-start; }
.note-icon { color: #0ea5e9; font-size: 18px; margin-top: 2px; flex-shrink: 0; }
.note-title { font-size: 12px; font-weight: 700; color: #1d2129; margin-bottom: 5px; }
.note-line { font-size: 12px; color: #4e5969; line-height: 1.8; }
.note-line.warn-text { color: #b45309; }

@media (max-width: 1280px) {
  .result-grid { grid-template-columns: 1fr; }
}
</style>

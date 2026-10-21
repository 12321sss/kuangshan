<template>
  <div class="eco-page">
    <!-- ============ 参数 ============ -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="head">
          <div>
            <span class="head-title">生态质量指数 RSEI</span>
            <span class="head-sub">绿度 + 湿度 + 干度三因子 PCA 合成，反映矿区生态综合状况</span>
          </div>
          <el-tag size="small" effect="plain" type="info">需拉取 6 个波段</el-tag>
        </div>
      </template>

      <div class="src-row">
        <div class="src-item">
          <label>AOI 来源</label>
          <el-select v-model="sourceType" style="width: 150px" @change="onSourceChange">
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
          <label>起始日期</label>
          <el-date-picker v-model="startDate" type="date" value-format="YYYY-MM-DD" style="width: 145px" />
        </div>
        <div class="src-item">
          <label>结束日期</label>
          <el-date-picker v-model="endDate" type="date" value-format="YYYY-MM-DD" style="width: 145px" />
        </div>
        <div class="src-item">
          <label>最大云量(%)</label>
          <el-input-number v-model="maxCloud" :min="0" :max="100" :step="10" style="width: 120px" />
        </div>

        <el-button type="primary" :loading="loading" :disabled="!aoiValid" @click="runRsei">
          计算 RSEI
        </el-button>
      </div>

      <div v-if="loading" class="loading-hint">
        正在检索影像并下载 6 个波段（含短波红外），首次约 1–3 分钟
      </div>
      <div v-if="!watches.length && sourceType === 'watch'" class="hint">
        还没有关注区。先在「遥感提取」页圈选并保存为关注区，之后就能在这里直接分析。
      </div>
    </el-card>

    <!-- ============ 空状态 ============ -->
    <el-card v-if="!result && !loading" shadow="never" class="panel">
      <el-empty description="还没有计算结果" :image-size="100">
        <div class="empty-hint">
          选择或输入 AOI 与时间范围后点「计算 RSEI」，并与去年同期做对比。
        </div>
      </el-empty>
    </el-card>

    <!-- ============ 结果 ============ -->
    <template v-if="result">
      <div class="result-grid">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="head">
              <span class="head-title">RSEI 分级图</span>
              <span class="head-sub">{{ (result.datetime || '').slice(0, 10) }}</span>
            </div>
          </template>
          <img
            v-if="result.imageBase64"
            :src="'data:image/png;base64,' + result.imageBase64"
            class="rsei-img"
            alt="RSEI 分级图"
          />
          <div class="legend">
            <span v-for="l in result.levels" :key="l.label" class="lg-item">
              <i :style="{ background: l.color }"></i>{{ l.label }}
            </span>
          </div>
        </el-card>

        <el-card shadow="never" class="panel">
          <template #header><span class="head-title">关键指标</span></template>
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi-num">{{ result.mean }}</div>
              <div class="kpi-label">RSEI 均值</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">
                {{ result.explainRatio ? (result.explainRatio * 100).toFixed(1) + '%' : '-' }}
              </div>
              <div class="kpi-label">PC1 解释率</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.cloudCover }}%</div>
              <div class="kpi-label">影像云量</div>
            </div>
            <div class="kpi">
              <div class="kpi-num small">{{ result.precision.resolution }}</div>
              <div class="kpi-label">分辨率</div>
            </div>
          </div>

          <!-- 分级占比条 -->
          <div class="level-bar">
            <div
              v-for="l in result.levels"
              :key="l.label"
              class="lb-seg"
              :style="{ width: l.pct + '%', background: l.color }"
              :title="`${l.label} ${l.pct}%`"
            ></div>
          </div>
          <div class="level-list">
            <span v-for="l in result.levels" :key="l.label" class="lv-item">
              {{ l.label }} {{ l.pct }}%
            </span>
          </div>

          <!-- PC1 载荷：说明哪一项主导本区生态 -->
          <div class="weight-block">
            <div class="wb-title">PC1 载荷（哪一项主导本区生态状况）</div>
            <div v-for="(w, i) in result.pc1Weight" :key="i" class="wb-row">
              <span class="wb-label">{{ result.weightLabels[i] }}</span>
              <div class="wb-track">
                <div class="wb-fill" :style="{ width: Math.min(Math.abs(w) * 100, 100) + '%' }"></div>
              </div>
              <span class="wb-val">{{ w }}</span>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 两期对比 -->
      <el-card v-if="result.compare" shadow="never" class="panel">
        <template #header>
          <div class="head">
            <span class="head-title">与 {{ (result.compare.datetime || '').slice(0, 10) }} 对比</span>
            <el-tag size="small" :type="deltaType">{{ result.compare.verdict }}</el-tag>
          </div>
        </template>
        <div class="cmp-row">
          <div class="cmp-kpi">
            <div class="cmp-num">{{ result.compare.earlyMean }}</div>
            <div class="cmp-label">上期均值</div>
          </div>
          <div class="cmp-arrow">→</div>
          <div class="cmp-kpi">
            <div class="cmp-num" :class="{ up: result.compare.deltaMean > 0, down: result.compare.deltaMean < 0 }">
              {{ result.compare.lateMean }}
            </div>
            <div class="cmp-label">本期均值</div>
          </div>
          <div class="cmp-kpi">
            <div class="cmp-num" :class="{ up: result.compare.deltaMean > 0, down: result.compare.deltaMean < 0 }">
              {{ result.compare.deltaMean > 0 ? '+' : '' }}{{ result.compare.deltaMean }}
            </div>
            <div class="cmp-label">变化量</div>
          </div>
        </div>
        <div class="cmp-bar">
          <div class="cb-seg improved" :style="{ width: result.compare.improvedPct + '%' }"
               :title="`改善 ${result.compare.improvedPct}%`"></div>
          <div class="cb-seg stable" :style="{ width: result.compare.stablePct + '%' }"
               :title="`稳定 ${result.compare.stablePct}%`"></div>
          <div class="cb-seg degraded" :style="{ width: result.compare.degradedPct + '%' }"
               :title="`退化 ${result.compare.degradedPct}%`"></div>
        </div>
        <div class="cmp-legend">
          <span><i class="dt improved"></i>改善 {{ result.compare.improvedPct }}%</span>
          <span><i class="dt stable"></i>稳定 {{ result.compare.stablePct }}%</span>
          <span><i class="dt degraded"></i>退化 {{ result.compare.degradedPct }}%</span>
        </div>
        <div class="cmp-note">{{ result.compare.note }}</div>
      </el-card>

      <!-- 精度与口径 -->
      <el-card shadow="never" class="panel note-panel">
        <el-icon class="note-icon"><InfoFilled /></el-icon>
        <div>
          <div class="note-title">方法说明与口径</div>
          <div class="note-line">{{ result.formula && result.formula.info }}</div>
          <div class="note-line warn-text">{{ result.precision.limitation }}</div>
          <div class="note-line">参考：{{ result.reference }}</div>
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
import { ecologyApi } from '@/api/sentinel'
import type { RseiResult } from '@/api/sentinel'
import { useProjectStore } from '@/stores/project'

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

/** 默认时间窗：近半年 */
const today = new Date()
const endDate = ref(today.toISOString().slice(0, 10))
const startDate = ref(new Date(today.getTime() - 180 * 86400000).toISOString().slice(0, 10))
const maxCloud = ref(30)

const loading = ref(false)
const result = ref<RseiResult | null>(null)

function parseManualCoords(text: string): number[][] {
  const out: number[][] = []
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim()
    if (!t) continue
    const parts = t.split(/[,，\s]+/).map(Number)
    if (parts.length >= 2 && parts.every((n) => Number.isFinite(n))) out.push([parts[0], parts[1]])
  }
  return out
}

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
  try {
    const raw = localStorage.getItem('last_aoi')
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
})

const aoiValid = computed(() => currentAoi.value.length >= 3)

/** 对比结论的标签颜色：改善绿、退化红、持平灰 */
const deltaType = computed<'success' | 'danger' | 'info'>(() => {
  const d = result.value?.compare?.deltaMean ?? 0
  if (d > 0.02) return 'success'
  if (d < -0.02) return 'danger'
  return 'info'
})

function onSourceChange() {
  result.value = null
}

/** 把日期往前推一年，用于同期对比（避免季节差异被误判为变化） */
function shiftYear(dateStr: string, delta: number): string {
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return dateStr
  d.setFullYear(d.getFullYear() + delta)
  return d.toISOString().slice(0, 10)
}

async function loadWatches() {
  try {
    watches.value = (await aoiWatchApi.list(projectStore.currentId ?? undefined)) as unknown as WatchItem[]
    if (!selectedWatchId.value && watches.value.length) selectedWatchId.value = watches.value[0].id
  } catch {
    watches.value = []
  }
}

async function runRsei() {
  const aoi = currentAoi.value
  if (aoi.length < 3) {
    ElMessage.warning('AOI 至少需要 3 个点')
    return
  }
  loading.value = true
  try {
    result.value = await ecologyApi.rsei({
      aoi,
      startDate: startDate.value,
      endDate: endDate.value,
      maxCloud: maxCloud.value,
      withImage: true,
      // 对比期取去年同期：同季节比较才能排除物候影响
      compareStart: shiftYear(startDate.value, -1),
      compareEnd: shiftYear(endDate.value, -1)
    })
    ElMessage.success(`RSEI 均值 ${result.value.mean}`)
  } catch (e: any) {
    ElMessage.error(e?.message || 'RSEI 计算失败，请确认解译服务已启动')
  } finally {
    loading.value = false
  }
}

onMounted(loadWatches)
watch(() => projectStore.currentId, () => {
  selectedWatchId.value = undefined
  result.value = null
  loadWatches()
})
</script>

<style scoped>
.eco-page { display: flex; flex-direction: column; gap: 14px; }
.panel { border: 1px solid #eceef2; border-radius: 10px; }

.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.head-title { font-size: 14px; font-weight: 700; color: #1d2129; }
.head-sub { font-size: 12px; color: #86909c; margin-left: 8px; font-weight: 400; }

.src-row { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; }
.src-item { display: flex; flex-direction: column; gap: 5px; }
.src-item.grow { flex: 1; min-width: 220px; }
.src-item label { font-size: 12px; color: #86909c; }
.hint { margin-top: 8px; font-size: 11px; color: #a9aeb8; line-height: 1.6; }
.loading-hint { margin-top: 10px; font-size: 12px; color: #0d9488; }
.empty-hint { font-size: 12px; color: #86909c; line-height: 1.8; }

.result-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; }
.rsei-img { width: 100%; border-radius: 8px; border: 1px solid #eceef2; image-rendering: pixelated; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 12px; color: #4e5969; }
.lg-item { display: inline-flex; align-items: center; gap: 5px; }
.lg-item i { width: 10px; height: 10px; border-radius: 2px; }

.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.kpi { background: #f6f8fa; border-radius: 8px; padding: 10px; text-align: center; }
.kpi-num { font-size: 17px; font-weight: 700; color: #0d9488; }
.kpi-num.small { font-size: 13px; }
.kpi-label { font-size: 11px; color: #86909c; margin-top: 3px; }

.level-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; margin: 14px 0 8px; }
.lb-seg { height: 100%; }
.level-list { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: #4e5969; }
.lv-item { white-space: nowrap; }

.weight-block { margin-top: 14px; }
.wb-title { font-size: 12px; font-weight: 600; color: #1d2129; margin-bottom: 8px; }
.wb-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.wb-label { font-size: 11px; color: #4e5969; width: 64px; flex-shrink: 0; }
.wb-track { flex: 1; height: 6px; background: #f0f2f5; border-radius: 3px; overflow: hidden; }
.wb-fill { height: 100%; background: #0d9488; border-radius: 3px; }
.wb-val { font-size: 11px; color: #86909c; width: 48px; text-align: right; }

.cmp-row { display: flex; align-items: center; gap: 18px; margin-bottom: 14px; flex-wrap: wrap; }
.cmp-kpi { text-align: center; min-width: 80px; }
.cmp-num { font-size: 20px; font-weight: 700; color: #1d2129; }
.cmp-num.up { color: #22c55e; }
.cmp-num.down { color: #ef4444; }
.cmp-label { font-size: 11px; color: #86909c; margin-top: 2px; }
.cmp-arrow { font-size: 18px; color: #c9cdd4; }

.cmp-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; }
.cb-seg { height: 100%; }
.cb-seg.improved, .dt.improved { background: #22c55e; }
.cb-seg.stable, .dt.stable { background: #cbd5e1; }
.cb-seg.degraded, .dt.degraded { background: #ef4444; }
.cmp-legend { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: #4e5969; }
.cmp-legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; }
.cmp-note { margin-top: 10px; font-size: 11px; color: #86909c; line-height: 1.7; }

.note-panel :deep(.el-card__body) { display: flex; gap: 10px; align-items: flex-start; }
.note-icon { color: #0ea5e9; font-size: 18px; margin-top: 2px; flex-shrink: 0; }
.note-title { font-size: 12px; font-weight: 700; color: #1d2129; margin-bottom: 5px; }
.note-line { font-size: 12px; color: #4e5969; line-height: 1.8; }
.note-line.warn-text { color: #b45309; }

@media (max-width: 1280px) {
  .result-grid { grid-template-columns: 1fr; }
}
</style>

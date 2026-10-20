<template>
  <div v-loading="loading">
    <el-alert :type="hasData ? 'info' : 'warning'" :closable="false" class="notice">
      <template #title>
        <template v-if="hasData">
          面积数据来自<b>真实解译结果</b>按影像拍摄日期累计，可追溯到每次提取记录。
          预测为<b>趋势外推（带不确定性区间）</b>，不是实测值；
          「持续复绿」不等于「生态修复成功」。
        </template>
        <template v-else>
          当前项目还没有真实提取记录，本页暂无数据。
          请先到<b>在线提取</b>页对影像执行解译。
        </template>
      </template>
    </el-alert>

    <!-- 筛选 + 粒度 + 操作 -->
    <div class="filter-row">
      <div class="filter-left">
        <span class="filter-label">地物类型</span>
        <!-- 下拉而非按钮组：9 类地物全列出，窄屏也不会挤 -->
        <el-select
          v-model="classFilter"
          size="small"
          style="width: 160px"
          placeholder="全部地物"
          @change="reload"
        >
          <el-option label="全部地物" value="" />
          <el-option
            v-for="c in classOptions"
            :key="c.value"
            :label="c.label"
            :value="c.value"
          >
            <span class="opt-dot" :style="{ background: c.color }"></span>
            <span>{{ c.label }}</span>
          </el-option>
        </el-select>
        <span class="filter-label">统计粒度</span>
        <el-radio-group v-model="periodMode" size="small" @change="reload">
          <el-radio-button value="month">按月</el-radio-button>
          <el-radio-button value="year">按年</el-radio-button>
        </el-radio-group>
      </div>
      <div class="filter-right">
        <el-tooltip content="按面积环比增幅检测突变，超过 20% 自动生成趋势告警" placement="top">
          <el-button size="small" type="warning" plain :loading="checkingTrends" @click="doCheckTrends">
            检测面积突变
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <div class="panel-row">
      <!-- 面积时序 -->
      <el-card shadow="never" class="panel">
        <template #header>
          <span>地物面积时序变化</span>
          <span class="unit-note">单位：平方千米（km²）</span>
        </template>
        <div v-if="hasData" ref="areaChartRef" class="chart"></div>
        <el-empty v-else description="还没有解译数据，无法生成时序图" :image-size="90">
          <el-button type="primary" size="small" @click="$router.push('/remote-extract')">去遥感提取</el-button>
        </el-empty>
        <!-- 数据缺口提示：中间缺月不一定是系统漏采，多半是该时段无无云影像 -->
        <div v-if="dataGaps.length > 0" class="gap-note">
          <el-icon><Warning /></el-icon>
          <span>
            数据缺口：{{ dataGaps.map((g) => `${g.from} ~ ${g.to} 缺 ${g.months} 个月`).join('；') }}
            —— 通常为该时段没有符合云量要求的影像，可在遥感提取页放宽云量阈值补采。
          </span>
        </div>
      </el-card>

      <!-- 地物构成：按指定期次查看（存量指标，不做跨期累加） -->
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="pie-head">
            <span>地物构成（{{ piePeriodLabel }}）</span>
            <el-select
              v-model="piePeriod"
              size="small"
              style="width: 140px"
              placeholder="最新一期"
              @change="renderPie"
            >
              <el-option label="最新一期" value="" />
              <el-option v-for="r in series" :key="r.date" :label="r.date" :value="r.date" />
            </el-select>
          </div>
        </template>
        <div v-if="hasSummary" ref="pieChartRef" class="chart"></div>
        <el-empty v-else description="该期没有解译数据" :image-size="90">
          <el-button type="primary" size="small" @click="$router.push('/remote-extract')">去遥感提取</el-button>
        </el-empty>
        <div v-if="hasSummary" class="pie-note">
          同一区域内多次提取只取最新一次，不重复累加；切换期次可查看不同年月的实际地物格局。
        </div>
      </el-card>
    </div>

    <!-- 采坑预测（口径敏感，单独成卡并显式标注） -->
    <el-card v-if="forecast && !forecast.insufficient" shadow="never" class="panel">
      <template #header>
        <span>采坑扩张趋势外推</span>
        <span class="unit-note">单位：平方千米（km²）</span>
      </template>
      <el-alert type="warning" :closable="false" class="forecast-note">
        <template #title>
          <b>{{ forecast.method }}</b> ——{{ forecast.disclaimer }}
        </template>
      </el-alert>
      <el-table :data="forecast.forecast" stripe size="small">
        <el-table-column prop="date" label="外推日期" width="120" />
        <el-table-column label="面积中值(km²)" width="120">
          <template #default="{ row }">{{ haToKm2(row.areaHa) }}</template>
        </el-table-column>
        <el-table-column label="下限(km²)" width="110">
          <template #default="{ row }">{{ haToKm2(row.lowerHa) }}</template>
        </el-table-column>
        <el-table-column label="上限(km²)" width="110">
          <template #default="{ row }">{{ haToKm2(row.upperHa) }}</template>
        </el-table-column>
        <el-table-column label="不确定度(±km²)" width="130">
          <template #default="{ row }">
            <span class="uncertain">{{ haToKm2(row.uncertaintyHa) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 明细表 -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="detail-head">
          <span>时序明细（{{ periodMode === 'month' ? '按月' : '按年' }}聚合）</span>
          <span v-if="seriesNote" class="detail-note">{{ seriesNote }}</span>
          <el-button
            size="small"
            style="margin-left: auto"
            :disabled="!hasData"
            :loading="exporting"
            @click="exportAllGeoJson"
          >
            导出全部 GeoJSON
          </el-button>
        </div>
      </template>
      <el-table :data="series" stripe size="small" empty-text="暂无提取记录">
        <el-table-column label="统计期" width="120">
          <template #default="{ row }">{{ row.date }}</template>
        </el-table-column>
        <el-table-column label="记录数" width="90">
          <template #default="{ row }">{{ row.recordCount ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="合计面积(km²)" width="130"><template #default="{ row }">{{ haToKm2(row.totalAreaHa) }}</template></el-table-column>
        <el-table-column label="较上期变化(km²)" width="140">
          <template #default="{ row }">
            <span :style="{ color: row.changeHa > 0 ? '#ef4444' : row.changeHa < 0 ? '#22c55e' : '' }">
              {{ row.changeHa > 0 ? '+' : '' }}{{ haToKm2(row.changeHa) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="分类构成" min-width="240">
          <template #default="{ row }">
            <el-tag
              v-for="(area, cls) in row.byClass"
              :key="cls"
              size="small"
              class="cls-tag"
              :style="{ background: classColor(cls), color: '#fff', border: 'none' }"
            >
              {{ classLabel(cls) }} {{ haToKm2(area) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 单区域体检：一块地的全类型历年变化，回答"这块地到底怎么变的" -->
    <el-card shadow="never" class="panel" v-loading="profileLoading">
      <template #header>
        <div class="detail-head">
          <span>单区域体检（同一块地的全类型变化）</span>
          <span class="detail-note">自动选取记录最多的区域</span>
        </div>
      </template>
      <div v-if="!profile || !profile.signature" class="empty-block">
        还没有可用于体检的区域数据。在遥感提取页圈选并保存至少两期后即可查看。
      </div>
      <template v-else>
        <div class="profile-kpi">
          <div class="pk">
            <div class="pk-num">{{ profile.classCount ?? 0 }}</div>
            <div class="pk-label">涉及地物类型</div>
          </div>
          <div class="pk">
            <div class="pk-num">{{ profile.recordCount ?? 0 }}</div>
            <div class="pk-label">解译记录数</div>
          </div>
          <div class="pk">
            <div class="pk-num">{{ haToKm2(profile.totalAreaHa) }}</div>
            <div class="pk-label">当前总面积(km²)</div>
          </div>
        </div>
        <el-table :data="profile.classes" size="small" stripe>
          <el-table-column label="地物类型" width="130">
            <template #default="{ row }">
              <span class="cls-dot" :style="{ background: classColor(row.classType) }"></span>
              {{ classLabel(row.classType) }}
            </template>
          </el-table-column>
          <el-table-column label="最新面积(km²)" width="140">
            <template #default="{ row }">{{ haToKm2(row.latestAreaHa) }}</template>
          </el-table-column>
          <el-table-column label="最近观测" width="120">
            <template #default="{ row }">{{ row.latestDate || '-' }}</template>
          </el-table-column>
          <el-table-column label="历史期数" width="100">
            <template #default="{ row }">{{ row.periodCount }}</template>
          </el-table-column>
          <el-table-column label="变化轨迹(km²)" min-width="240">
            <template #default="{ row }">
              <span v-if="row.periodCount <= 1" class="muted">仅一期，无法看趋势</span>
              <span v-else class="track">
                <template v-for="(p, i) in row.series" :key="p.date">
                  <span class="track-item">{{ p.date }}: {{ haToKm2(p.areaHa) }}</span>
                  <span v-if="i < row.series.length - 1" class="track-arrow">→</span>
                </template>
              </span>
            </template>
          </el-table-column>
        </el-table>
        <div class="profile-note">{{ profile.note }}</div>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Warning } from '@element-plus/icons-vue'
import { analysisApi, extractionApi } from '@/api'
import { haToKm2, haToKm2Num } from '@/utils/format'
import { useProjectStore } from '@/stores/project'
import type { AreaTimeseriesRow, ChangeSummary, PitForecastResult } from '@/api/types'

const projectStore = useProjectStore()
const loading = ref(false)
const classFilter = ref('')
const checkingTrends = ref(false)
/** 聚合粒度：按月（默认）/ 按年 */
const periodMode = ref<'month' | 'year'>('month')
/** 饼图查看的期次：空字符串表示最新一期 */
const piePeriod = ref('')
/** 后端返回的口径说明（同区域重复提取不累加） */
const seriesNote = ref('')

const series = ref<AreaTimeseriesRow[]>([])
const summary = ref<ChangeSummary | null>(null)
const forecast = ref<PitForecastResult | null>(null)

const areaChartRef = ref<HTMLDivElement>()
const pieChartRef = ref<HTMLDivElement>()
let areaChart: echarts.ECharts | undefined
let pieChart: echarts.ECharts | undefined

const hasData = computed(() => series.value.length > 0)

/** 最新一期（series 由后端按期升序返回，取最后一条） */
const latestRow = computed<AreaTimeseriesRow | null>(() =>
  series.value.length > 0 ? series.value[series.value.length - 1] : null
)
/** 当前饼图选中的期次（未选则用最新一期） */
const selectedRow = computed<AreaTimeseriesRow | null>(() => {
  if (!piePeriod.value) return latestRow.value
  return series.value.find((r) => r.date === piePeriod.value) || latestRow.value
})
const piePeriodLabel = computed(() => selectedRow.value?.date || '暂无数据')
/** 选中期次的各地物面积（存量，不跨期累加） */
const pieClasses = computed<Array<{ classType: string; totalAreaHa: number }>>(() => {
  const row = selectedRow.value
  if (!row) return []
  return Object.entries(row.byClass || {}).map(([classType, ha]) => ({
    classType,
    totalAreaHa: Number(ha) || 0
  }))
})
const hasSummary = computed(() => pieClasses.value.length > 0)

/**
 * 数据缺口检测：按月模式下，相邻两期间隔超过 1 个月即视为缺口。
 * 缺口通常是该时段没有满足云量要求的影像，需明确告知用户而不是让图看起来"连续"。
 */
const dataGaps = computed(() => {
  if (periodMode.value !== 'month' || series.value.length < 2) return []
  const gaps: Array<{ from: string; to: string; months: number }> = []
  for (let i = 1; i < series.value.length; i++) {
    const prev = series.value[i - 1].date
    const cur = series.value[i].date
    const p = prev.split('-').map(Number)
    const c = cur.split('-').map(Number)
    if (p.length < 2 || c.length < 2) continue
    const diff = (c[0] - p[0]) * 12 + (c[1] - p[1])
    if (diff > 1) gaps.push({ from: prev, to: cur, months: diff - 1 })
  }
  return gaps
})

// ---- 单区域体检 ----
const profile = ref<Awaited<ReturnType<typeof analysisApi.aoiProfile>> | null>(null)
const profileLoading = ref(false)
async function loadProfile() {
  profileLoading.value = true
  try {
    profile.value = await analysisApi.aoiProfile(projectStore.currentId ?? undefined)
  } catch {
    profile.value = null
  } finally {
    profileLoading.value = false
  }
}

// ---- 批量导出全部解译结果 ----
const exporting = ref(false)

/**
 * 把当前项目的全部解译记录导出为一个 GeoJSON FeatureCollection。
 * 客户要拿数据进 ArcGIS/QGIS 时，一条条导出太麻烦，这里一次全给。
 * 每条要素带上类型、日期、面积、AOI 等属性，便于二次分析。
 */
async function exportAllGeoJson() {
  exporting.value = true
  try {
    const list = await extractionApi.list(projectStore.currentId ?? undefined)
    const features: any[] = []
    for (const e of list) {
      if (!e.featuresJson) continue
      let rings: number[][][] = []
      try {
        rings = JSON.parse(e.featuresJson)
      } catch {
        continue
      }
      if (!Array.isArray(rings)) continue
      rings.forEach((ring, i) => {
        features.push({
          type: 'Feature',
          properties: {
            recordId: e.id,
            name: e.name,
            classType: e.classType,
            classLabel: classLabel(e.classType),
            acquisitionDate: e.acquisitionDate || null,
            areaHa: e.extractAreaHa,
            coveragePct: e.coveragePct,
            splitIndex: i
          },
          geometry: { type: 'Polygon', coordinates: [ring] }
        })
      })
    }
    if (features.length === 0) {
      ElMessage.warning('没有可导出的几何数据')
      return
    }
    const fc = {
      type: 'FeatureCollection',
      features,
      metadata: {
        projectId: projectStore.currentId,
        exportedAt: new Date().toISOString(),
        recordCount: list.length,
        featureCount: features.length,
        note: '面积口径为潜在水土流失风险筛查结果；同一区域重复解译不累加。'
      }
    }
    const blob = new Blob([JSON.stringify(fc, null, 2)], { type: 'application/geo+json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `解译结果全部导出-${new Date().toISOString().slice(0, 10)}.geojson`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${list.length} 条记录的 ${features.length} 个要素`)
  } catch (e: any) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

const CLASS_LABEL: Record<string, string> = {
  PIT: '采坑', BARE: '裸地扰动', VEGETATION: '植被',
  WATER: '水体', DUMP: '排土场', TAILINGS: '尾矿库', ROAD: '道路设施',
  BUILDING: '建筑', MOUNTAIN: '山体'
}
const CLASS_COLOR: Record<string, string> = {
  PIT: '#ef4444', BARE: '#a8a29e', VEGETATION: '#22c55e',
  WATER: '#3b82f6', DUMP: '#f59e0b', TAILINGS: '#8b5cf6', ROAD: '#64748b',
  BUILDING: '#f97316', MOUNTAIN: '#6b7280'
}
function classLabel(c: string) {
  return CLASS_LABEL[c] || c
}
function classColor(c: string) {
  return CLASS_COLOR[c] || '#888'
}

/** 筛选下拉的完整 9 类地物（与后端解译类型对齐，含建筑/山体） */
const classOptions = [
  { value: 'PIT', label: '采坑', color: '#ef4444' },
  { value: 'DUMP', label: '排土场', color: '#f59e0b' },
  { value: 'TAILINGS', label: '尾矿库', color: '#8b5cf6' },
  { value: 'BARE', label: '裸地扰动', color: '#a8a29e' },
  { value: 'VEGETATION', label: '植被', color: '#22c55e' },
  { value: 'WATER', label: '水体', color: '#3b82f6' },
  { value: 'ROAD', label: '道路设施', color: '#64748b' },
  { value: 'BUILDING', label: '建筑', color: '#f97316' },
  { value: 'MOUNTAIN', label: '山体', color: '#6b7280' }
]

async function reload() {
  loading.value = true
  const pid = projectStore.currentId ?? undefined
  try {
    const [ts, sum] = await Promise.all([
      analysisApi.areaTimeseries({
        projectId: pid,
        classType: classFilter.value || undefined,
        granularity: periodMode.value
      }),
      analysisApi.changeSummary(pid)
    ])
    // 新口径：后端返回 { granularity, rows, note }
    series.value = ts.rows || []
    seriesNote.value = ts.note || ''
    summary.value = sum
    // 切换粒度后原选中期次可能已不存在，回落到最新一期
    if (piePeriod.value && !series.value.some((r) => r.date === piePeriod.value)) {
      piePeriod.value = ''
    }
    // 预测只在未筛选类别时给出（采坑预测是专门口径）
    if (!classFilter.value) {
      try {
        forecast.value = await analysisApi.pitForecast(pid)
      } catch {
        forecast.value = null
      }
    } else {
      forecast.value = null
    }
    renderArea()
    renderPie()
    loadProfile()
  } catch (e: any) {
    series.value = []
    summary.value = null
    forecast.value = null
  } finally {
    loading.value = false
  }
}

/** 检测面积突变：环比超阈值生成趋势告警 */
async function doCheckTrends() {
  checkingTrends.value = true
  try {
    const res = await analysisApi.checkTrends(projectStore.currentId ?? undefined)
    if (res.triggered && res.triggered.length > 0) {
      ElMessage.warning(res.message)
    } else {
      ElMessage.info(res.message)
    }
  } catch (e: any) {
    ElMessage.error(e.message || '检测失败')
  } finally {
    checkingTrends.value = false
  }
}

function renderArea() {
  // v-if 控制图表容器：有数据才渲染，等 DOM 更新后再初始化 echarts
  nextTick(() => {
    const el = areaChartRef.value
    if (!el) return
    // 容器被 v-if 重建后旧实例绑在已销毁的 DOM 上，需要 dispose 重建
    if (!areaChart || areaChart.getDom() !== el) {
      areaChart?.dispose()
      areaChart = echarts.init(el)
    }
    const dates = series.value.map((r) => r.date)
    // 多类别堆叠
    const classes = new Set<string>()
    series.value.forEach((r) => Object.keys(r.byClass).forEach((c) => classes.add(c)))
    const seriesArr = [...classes].map((c) => ({
      name: classLabel(c),
      type: 'bar',
      stack: 'total',
      itemStyle: { color: classColor(c) },
      data: series.value.map((r) => haToKm2Num(r.byClass[c]))
    }))
    areaChart.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: [...classes].map(classLabel) },
      grid: { left: 50, right: 20, top: 40, bottom: 35 },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value', name: 'km²' },
      series: seriesArr.length ? seriesArr : [{ type: 'bar', data: [] }]
    }, true)
  })
}

function renderPie() {
  nextTick(() => {
    const el = pieChartRef.value
    if (!el) return
    if (!pieChart || pieChart.getDom() !== el) {
      pieChart?.dispose()
      pieChart = echarts.init(el)
    }
    // 存量口径：默认用最新一期构成；切到累计时用历史各期之和
    const classes = pieClasses.value
    pieChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} km² ({d}%)' },
      legend: { orient: 'vertical', right: 10, top: 'center' },
      series: [{
        type: 'pie',
        radius: ['40%', '65%'],
        label: { formatter: '{b}\n{c} km²' },
        data: classes.map((c) => ({
          name: classLabel(c.classType),
          value: haToKm2Num(c.totalAreaHa),
          itemStyle: { color: classColor(c.classType) }
        }))
      }]
    }, true)
  })
}

watch(() => projectStore.currentId, () => reload())

onMounted(() => {
  reload()
  window.addEventListener('resize', handleResize)
})

function handleResize() {
  areaChart?.resize()
  pieChart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  areaChart?.dispose()
  pieChart?.dispose()
})
</script>

<style scoped>
.notice {
  margin-bottom: 12px;
}
.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.filter-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.filter-label { font-size: 12px; color: #86909c; }
.filter-right { display: flex; align-items: center; gap: 8px; }
.opt-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 7px; vertical-align: middle;
}

.pie-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.pie-note { margin-top: 8px; font-size: 11px; color: #a9aeb8; line-height: 1.5; }
.detail-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.detail-note { font-size: 11px; color: #a9aeb8; font-weight: 400; }

/* 数据缺口提示 */
.gap-note {
  display: flex; align-items: flex-start; gap: 6px;
  margin-top: 10px; padding: 8px 10px;
  background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
  font-size: 12px; color: #b45309; line-height: 1.6;
}

/* 单区域体检 */
.profile-kpi { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; }
.pk { background: #f6f8fa; border-radius: 10px; padding: 12px; text-align: center; }
.pk-num { font-size: 22px; font-weight: 700; color: #0d9488; }
.pk-label { font-size: 12px; color: #86909c; margin-top: 2px; }
.cls-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.muted { color: #a9aeb8; font-size: 12px; }
.track { font-size: 12px; color: #4e5969; line-height: 1.8; }
.track-item { white-space: nowrap; }
.track-arrow { color: #c9cdd4; margin: 0 6px; }
.profile-note { margin-top: 10px; font-size: 11px; color: #a9aeb8; line-height: 1.5; }
.empty-block { padding: 16px 0; font-size: 13px; color: #86909c; }
.panel-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}
.chart {
  height: 300px;
}
.unit-note {
  float: right;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.forecast-note {
  margin-bottom: 10px;
}
.uncertain {
  color: var(--el-color-warning);
}
.cls-tag {
  margin-right: 4px;
}
@media (max-width: 1100px) {
  .panel-row {
    grid-template-columns: 1fr;
  }
}
</style>
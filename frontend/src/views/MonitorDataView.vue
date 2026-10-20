<template>
  <div v-loading="loading">
    <!-- 站点统计卡片 -->
    <div class="stat-grid">
      <div v-for="c in cards" :key="c.label" class="stat-card">
        <div class="stat-icon" :style="{ background: c.bg }">
          <el-icon :size="20" :color="c.color"><component :is="c.icon" /></el-icon>
        </div>
        <div>
          <div class="stat-label">{{ c.label }}</div>
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
        </div>
      </div>
    </div>

    <!-- 过滤栏 -->
    <el-card shadow="never" class="panel">
      <div class="filter-bar">
        <el-select v-model="stationId" size="default" style="width: 220px" @change="loadData">
          <el-option v-for="s in gnssStations" :key="s.id" :label="s.stationName" :value="s.id" />
        </el-select>
        <el-radio-group v-model="hours" @change="loadData">
          <el-radio-button :value="24">今天</el-radio-button>
          <el-radio-button :value="72">近3天</el-radio-button>
          <el-radio-button :value="168">近7天</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :icon="Search" @click="loadData">查询</el-button>
        <el-button :icon="Download" @click="onExport">导出</el-button>
        <el-checkbox v-model="showThreshold" @change="renderChart">加载预警线</el-checkbox>
      </div>
    </el-card>

    <!-- 多分量位移曲线 -->
    <el-card shadow="never" class="panel">
      <template #header>
        <span>地表位移（{{ currentStationName }}）</span>
        <span class="unit-note">单位：mm · 模拟数据</span>
      </template>
      <div ref="chartRef" class="chart"></div>
    </el-card>

    <!-- 统计表 -->
    <el-card shadow="never" class="panel">
      <el-table :data="statRows" stripe>
        <el-table-column prop="name" label="监测属性" min-width="140" />
        <el-table-column prop="mean" label="均值" min-width="110" />
        <el-table-column prop="max" label="最大值" min-width="110" />
        <el-table-column prop="min" label="最小值" min-width="110" />
        <el-table-column prop="std" label="标准差" min-width="110" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Search, Download, Monitor, CircleCheck, WarningFilled, Tools } from '@element-plus/icons-vue'
import { sensorApi, stationApi } from '@/api'
import { useProjectStore } from '@/stores/project'
import type { DisplacementSeries, Station } from '@/api/types'

const projectStore = useProjectStore()

const loading = ref(true)
const stations = ref<Station[]>([])
const stationId = ref('')
const hours = ref(24)
const showThreshold = ref(true)
const series = ref<DisplacementSeries | null>(null)

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | undefined

// 站点与传感器通过 station.sensorId 直接关联（数据库外键口径）
const gnssStations = computed(() => stations.value.filter((s) => s.stationType.includes('GNSS') && s.sensorId))
const currentStationName = computed(
  () => stations.value.find((s) => s.id === stationId.value)?.stationName || ''
)

const cards = computed(() => {
  const total = stations.value.length
  const normal = stations.value.filter((s) => s.workStatus === 'NORMAL').length
  const abnormal = stations.value.filter((s) => s.workStatus === 'ABNORMAL').length
  const maintain = stations.value.filter((s) => s.workStatus === 'MAINTAIN').length
  return [
    { label: '站点总数', value: total, icon: Monitor, color: '#0d9488', bg: '#e6f6f4' },
    { label: '正常总数', value: normal, icon: CircleCheck, color: '#22c55e', bg: '#eafaf0' },
    { label: '异常总数', value: abnormal, icon: WarningFilled, color: '#ef4444', bg: '#fdecec' },
    { label: '维护总数', value: maintain, icon: Tools, color: '#f59e0b', bg: '#fef6e6' }
  ]
})

interface StatRow { name: string; mean: string; max: string; min: string; std: string }

const statRows = computed<StatRow[]>(() => {
  if (!series.value) return []
  const defs = [
    { key: 'x' as const, name: 'X位移(mm)' },
    { key: 'y' as const, name: 'Y位移(mm)' },
    { key: 'z' as const, name: 'Z位移(mm)' },
    { key: 'total' as const, name: '合位移(mm)' }
  ]
  return defs.map((d) => {
    const values = series.value![d.key].map((p) => p.value)
    const mean = values.reduce((a, b) => a + b, 0) / values.length
    const std = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length)
    return {
      name: d.name,
      mean: mean.toFixed(4),
      max: Math.max(...values).toFixed(2),
      min: Math.min(...values).toFixed(2),
      std: std.toFixed(4)
    }
  })
})

function fmtTime(t: string) {
  return hours.value <= 24 ? t.slice(11, 16) : t.slice(5, 13).replace('T', ' ')
}

function renderChart() {
  if (!series.value) return
  if (!chart && chartRef.value) {
    chart = echarts.init(chartRef.value)
  }
  const s = series.value
  const markLine = showThreshold.value
    ? {
        silent: true, symbol: 'none',
        lineStyle: { type: 'dashed' as const },
        data: [
          { yAxis: 5, lineStyle: { color: '#eab308' }, label: { formatter: '黄色预警 5mm', fontSize: 10 } },
          { yAxis: 10, lineStyle: { color: '#f97316' }, label: { formatter: '橙色预警 10mm', fontSize: 10 } },
          { yAxis: 20, lineStyle: { color: '#ef4444' }, label: { formatter: '红色预警 20mm', fontSize: 10 } }
        ]
      }
    : undefined
  chart?.setOption({
    grid: { left: 50, right: 20, top: 40, bottom: 56 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['X位移', 'Y位移', 'Z位移', '合位移'], top: 4, textStyle: { fontSize: 12 } },
    dataZoom: [{ type: 'slider', height: 18, bottom: 8 }],
    xAxis: { type: 'category', data: s.total.map((p) => fmtTime(p.time)), axisLabel: { fontSize: 11, color: '#86909c' } },
    yAxis: { type: 'value', name: 'mm', splitLine: { lineStyle: { color: '#f0f0f0' } } },
    series: [
      { name: 'X位移', type: 'line', data: s.x.map((p) => p.value), smooth: true, symbol: 'none', lineStyle: { width: 1.6 } },
      { name: 'Y位移', type: 'line', data: s.y.map((p) => p.value), smooth: true, symbol: 'none', lineStyle: { width: 1.6 } },
      { name: 'Z位移', type: 'line', data: s.z.map((p) => p.value), smooth: true, symbol: 'none', lineStyle: { width: 1.6 } },
      { name: '合位移', type: 'line', data: s.total.map((p) => p.value), smooth: true, symbol: 'none', lineStyle: { width: 2.4, color: '#ef4444' }, markLine }
    ]
  }, true)
}

async function loadData() {
  if (!stationId.value) return
  const sensorId = stations.value.find((s) => s.id === stationId.value)?.sensorId
  if (!sensorId) return
  try {
    series.value = await sensorApi.displacement(sensorId, hours.value)
    renderChart()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

/** 导出当前监测数据为 CSV（前端直接生成，含 BOM 保证 Excel 中文不乱码） */
function onExport() {
  if (!series.value) {
    ElMessage.warning('暂无数据可导出，请先查询')
    return
  }
  // 收集所有分量的时间轴与数值
  const keys = Object.keys(series.value)
  if (keys.length === 0) {
    ElMessage.warning('暂无数据可导出')
    return
  }
  const timeSet = new Set<string>()
  keys.forEach((k) => (series.value![k] || []).forEach((p) => timeSet.add(String(p.time))))
  const times = [...timeSet].sort()

  // 时间 -> 各分量值
  const lookup: Record<string, Record<string, number>> = {}
  keys.forEach((k) => {
    (series.value![k] || []).forEach((p) => {
      const t = String(p.time)
      lookup[t] ??= {}
      lookup[t][k] = p.value
    })
  })

  const header = ['时间', ...keys.map(multiLabel)].join(',')
  const rows = times.map((t) => [t, ...keys.map((k) => lookup[t]?.[k] ?? '')].join(','))
  const csv = '\uFEFF' + header + '\n' + rows.join('\n')

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${currentStationName.value || 'GNSS'}-位移-${hours.value}h.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${times.length} 条记录`)
}

/** 位移分量编码转中文列名 */
function multiLabel(k: string) {
  return { x: 'X位移(mm)', y: 'Y位移(mm)', z: 'Z位移(mm)', total: '合位移(mm)', dx: 'X位移(mm)', dy: 'Y位移(mm)', dz: 'Z位移(mm)' }[k] || k
}

function resize() { chart?.resize() }

onMounted(async () => {
  await loadStations()
  window.addEventListener('resize', resize)
})

async function loadStations() {
  loading.value = true
  try {
    stations.value = await stationApi.list(projectStore.currentId)
    stationId.value = gnssStations.value[0]?.id || ''
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

// 切换工程 -> 重新拉站点与曲线
watch(() => projectStore.currentId, loadStations)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<style scoped>
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 14px; }

.stat-card {
  background: #fff; border: 1px solid #eceef2; border-radius: 10px;
  padding: 16px 18px; display: flex; align-items: center; gap: 14px;
}

.stat-icon {
  width: 44px; height: 44px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
}

.stat-label { font-size: 13px; color: #86909c; }
.stat-value { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }

.panel { border: 1px solid #eceef2; border-radius: 10px; margin-bottom: 14px; }

.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

.unit-note { font-size: 12px; color: #a9aeb8; margin-left: 10px; font-weight: 400; }

.chart { height: 340px; }
</style>

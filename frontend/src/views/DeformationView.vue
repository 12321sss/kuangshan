<template>
  <div class="deformation-page">
    <!-- 顶部操作条 -->
    <el-card shadow="never" class="op-card">
      <div class="op-row">
        <div class="op-left">
          <span class="op-title">形变监测（InSAR）</span>
          <span class="op-sub">
            基于 NISAR / Sentinel-1 干涉雷达，反演地表形变速率场；升降轨联合可解垂直与东西向位移
          </span>
        </div>
        <div class="op-right">
          <el-button :loading="submitting" @click="submitAnalysis">发起分析</el-button>
          <el-button :loading="loading" @click="load">刷新结果</el-button>
        </div>
      </div>
    </el-card>

    <!-- 加载失败 -->
    <el-card v-if="error" shadow="never" class="empty-card">
      <el-alert :title="error" type="warning" :closable="false" show-icon />
    </el-card>

    <!-- 无结果 -->
    <el-card v-else-if="!loading && !fusion && tracks.length === 0" shadow="never" class="empty-card">
      <el-empty description="还没有形变分析结果" :image-size="110">
        <div class="empty-hint">
          形变结果由雷达数据处理产出（SBAS 反演 → 趋势分析）。<br />
          当前尚未产出结果，或 inference 服务未启动。
        </div>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- ==================== 升降轨联合 ==================== -->
      <template v-if="fusion">
        <el-card shadow="never" class="sec-card">
          <div class="sec-head">
            <span class="sec-title">升降轨联合（垂直 + 东西向）</span>
            <span class="sec-meta">
              降轨 track {{ fusion.descTrack }} × 升轨 track {{ fusion.ascTrack }} ·
              {{ fusion.solvedPixels }} 像元可解
            </span>
          </div>

          <!-- 几何条件说明 -->
          <el-alert type="success" :closable="false" class="geo-alert">
            <template #title>
              单轨 InSAR 只能测「视线向(LOS)」，联合升降轨才能解出垂直(V)与东西(E)分量——这才是「沉降量」的物理含义。南北向因轨道近极地不可解。
            </template>
          </el-alert>

          <div class="chart-grid">
            <div class="chart-block">
              <div ref="vertChart" class="chart-box"></div>
              <div class="chart-cap">垂直形变速率（正值=抬升 / 负值=沉降，mm/yr）</div>
            </div>
            <div class="chart-block">
              <div ref="eastChart" class="chart-box"></div>
              <div class="chart-cap">东西向形变速率（正值=向东，mm/yr）</div>
            </div>
          </div>

          <el-table :data="fusionStats" size="small" border class="stat-table">
            <el-table-column prop="name" label="分量" width="120" />
            <el-table-column prop="median" label="中位 (mm/yr)" />
            <el-table-column prop="p5" label="P5" />
            <el-table-column prop="p95" label="P95" />
            <el-table-column prop="range" label="极值" />
          </el-table>
        </el-card>
      </template>

      <!-- ==================== 单轨趋势 ==================== -->
      <template v-for="(t, i) in tracks" :key="i">
        <el-card shadow="never" class="sec-card">
          <div class="sec-head">
            <span class="sec-title">单轨形变趋势 · track {{ t.track }}</span>
            <span class="sec-meta">
              信噪比 {{ t.snr }}（{{ t.reliable ? '可靠' : '不足，加速度仅供参考' }}）·
              {{ t.generatedAt }}
            </span>
          </div>

          <!-- 趋势研判 -->
          <div class="verdict-bar" :class="'v-' + (t.verdict?.confidence || 'medium')">
            <b>趋势研判：{{ t.verdict?.type || '—' }}</b>
            <span class="verdict-basis">{{ t.verdict?.basis || '' }}</span>
          </div>

          <div class="chart-grid">
            <div class="chart-block">
              <div :ref="el => setChartRef('vel' + i, el)" class="chart-box"></div>
              <div class="chart-cap">速率场（mm/yr，负=远离卫星/沉降）</div>
            </div>
            <div class="chart-block">
              <div :ref="el => setChartRef('acc' + i, el)" class="chart-box"></div>
              <div class="chart-cap">加速度场（mm/yr²，正值=加速）</div>
            </div>
          </div>

          <!-- 危险测点 -->
          <div class="hotspots">
            <div class="hs-title">危险测点（按风险排序，前 {{ t.hotspots?.length || 0 }} 处）</div>
            <el-table :data="t.hotspots" size="small" border>
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="位置(lng,lat)" width="200">
                <template #default="{ row }">
                  {{ row.x?.toFixed(4) }}, {{ row.y?.toFixed(4) }}
                </template>
              </el-table-column>
              <el-table-column label="速率(mm/yr)">
                <template #default="{ row }">{{ row.velocity?.toFixed(1) }}</template>
              </el-table-column>
              <el-table-column label="加速度(mm/yr²)">
                <template #default="{ row }">{{ row.acceleration?.toFixed(1) }}</template>
              </el-table-column>
              <el-table-column label="外推失稳(天)">
                <template #default="{ row }">
                  {{ row.tfDays != null ? row.tfDays + ' 天' : '数据不足' }}
                </template>
              </el-table-column>
              <el-table-column prop="severityLabel" label="速度分级" width="100" />
            </el-table>
          </div>
        </el-card>
      </template>

      <!-- 口径说明 -->
      <el-card shadow="never" class="disclaimer-card">
        <div class="disclaimer-title">口径与局限（重要）</div>
        <ul class="disclaimer-list">
          <li>本结果为「潜在形变风险筛查」，非边坡稳定性评价，<b>不给安全系数</b>。</li>
          <li>观测期仅 3 个月，<b>速率可用、加速度不可信</b>（信噪比 &lt; 0.3），失稳外推已按口径清空，不输出假预警。</li>
          <li>空间噪声较大（P5~P95 跨度远大于中位值），逐像元数值仅供参考，趋势以中位统计为准。</li>
          <li>单轨为 LOS 视线向，非垂直沉降；判定须结合边坡单元、现场勘察与多源数据复核。</li>
        </ul>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { deformationApi } from '@/api'
import type { DeformationResults, DeformationFusionResult, DeformationTrackResult } from '@/api/types'

const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fusion = ref<DeformationFusionResult | null>(null)
const tracks = ref<DeformationTrackResult[]>([])

const fusionStats = ref<Array<{ name: string; median: string; p5: string; p95: string; range: string }>>([])

const chartRefs = new Map<string, HTMLElement>()
const charts = new Map<string, echarts.ECharts>()

function setChartRef(key: string, el: any) {
  if (el) chartRefs.set(key, el)
}

/** 二维场 → ECharts heatmap 数据 [x, y, value] */
function toHeatData(field: (number | null)[][]): number[][] {
  const data: number[][] = []
  for (let y = 0; y < field.length; y++) {
    for (let x = 0; x < (field[y]?.length || 0); x++) {
      const v = field[y][x]
      if (v != null && Number.isFinite(v)) data.push([x, y, v])
    }
  }
  return data
}

/** 渲染热力图（蓝→白→红，P5~P95 自适应） */
function renderHeat(key: string, field: (number | null)[][], unit: string) {
  const el = chartRefs.get(key)
  if (!el) return
  if (!charts.has(key)) charts.set(key, echarts.init(el))
  const chart = charts.get(key)!

  const vals = toHeatData(field).map(d => d[2])
  const p5 = percentile(vals, 5)
  const p95 = percentile(vals, 95)
  const h = field.length
  const w = field[0]?.length || 0

  chart.setOption({
    animation: false,
    grid: { left: 10, right: 10, top: 10, bottom: 30 },
    xAxis: { type: 'category', show: false },
    yAxis: { type: 'category', show: false, inverse: true },
    visualMap: {
      min: p5, max: p95, calculable: false, show: false,
      inRange: { color: ['#2563eb', '#93c5fd', '#f8fafc', '#fca5a5', '#dc2626'] }
    },
    tooltip: {
      formatter: (p: any) => `${p.value[2]} ${unit}`
    },
    series: [{
      type: 'heatmap',
      data: toHeatData(field),
      itemStyle: { borderWidth: 0.5, borderColor: 'rgba(0,0,0,0.05)' }
    }]
  })
}

function percentile(sortedVals: number[], p: number): number {
  if (!sortedVals.length) return 0
  const s = [...sortedVals].sort((a, b) => a - b)
  const idx = Math.min(s.length - 1, Math.max(0, Math.floor((p / 100) * (s.length - 1))))
  return s[idx]
}

async function submitAnalysis() {
  submitting.value = true
  try {
    const projectId = 1  // demo 项目，后续接项目上下文
    await deformationApi.submit({ projectId, taskType: 'trend', track: 18 })
    ElMessage.success('形变分析任务已提交，完成后会收到通知，可先去处理其它工作')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '发起分析失败')
  } finally {
    submitting.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 项目 id 从 store 取；这里先传 1（demo 项目），后续接项目上下文
    const projectId = 1
    const data: DeformationResults = await deformationApi.results(projectId)
    fusion.value = data.fusion
    tracks.value = data.tracks || []

    if (data.fusion) {
      const f = data.fusion
      fusionStats.value = [
        { name: '垂直分量 V', median: f.vertical.median.toFixed(1), p5: f.vertical.p5.toFixed(1), p95: f.vertical.p95.toFixed(1), range: `${f.vertical.min.toFixed(0)} ~ ${f.vertical.max.toFixed(0)}` },
        { name: '东西分量 E', median: f.eastWest.median.toFixed(1), p5: f.eastWest.p5.toFixed(1), p95: f.eastWest.p95.toFixed(1), range: `${f.eastWest.min.toFixed(0)} ~ ${f.eastWest.max.toFixed(0)}` }
      ]
      await nextTick()
      renderHeat('vertChart', f.verticalField, 'mm/yr')
      renderHeat('eastChart', f.eastWestField, 'mm/yr')
    }

    await nextTick()
    tracks.value.forEach((t, i) => {
      renderHeat('vel' + i, t.velocityField, 'mm/yr')
      renderHeat('acc' + i, t.accelerationField, 'mm/yr²')
    })
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || '读取形变结果失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.deformation-page { padding: 4px; }
.op-card { margin-bottom: 12px; }
.op-row { display: flex; align-items: center; justify-content: space-between; }
.op-title { font-size: 17px; font-weight: 600; color: #1e3a8a; }
.op-sub { margin-left: 12px; font-size: 12px; color: #6b7280; }
.empty-card { margin: 16px 0; }
.empty-hint { font-size: 13px; color: #6b7280; margin-bottom: 10px; }
.sec-card { margin-bottom: 14px; }
.sec-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.sec-title { font-size: 15px; font-weight: 600; color: #1e3a8a; }
.sec-meta { font-size: 12px; color: #6b7280; }
.geo-alert { margin-bottom: 12px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
.chart-box { height: 300px; width: 100%; }
.chart-cap { font-size: 12px; color: #6b7280; margin-top: 6px; text-align: center; }
.stat-table { margin-top: 8px; }
.verdict-bar { padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-size: 14px; }
.verdict-basis { display: block; font-size: 12px; color: #6b7280; margin-top: 4px; }
.v-high { background: #fee2e2; color: #991b1b; }
.v-medium { background: #fef3c7; color: #92400e; }
.v-low { background: #e5e7eb; color: #374151; }
.hotspots { margin-top: 10px; }
.hs-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #374151; }
.disclaimer-card { margin-top: 4px; background: #fef2f2; }
.disclaimer-title { font-weight: 600; color: #991b1b; margin-bottom: 8px; }
.disclaimer-list { margin: 0; padding-left: 18px; font-size: 13px; color: #7f1d1d; line-height: 1.8; }
</style>

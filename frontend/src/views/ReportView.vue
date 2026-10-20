<template>
  <div v-loading="loading">
    <el-alert type="info" :closable="false" class="notice">
      <template #title>
        报告基于<b>真实解译结果</b>与传感器数据自动生成，数据可追溯到每次提取记录。
        输出口径为「潜在水土流失风险筛查」，非实测侵蚀量。
      </template>
    </el-alert>

    <el-card shadow="never" class="panel">
      <template #header><span>报告预览（生成前数据概览）</span></template>

      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-num">{{ summary.totalRecords }}</div>
          <div class="stat-label">解译记录数</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ series.length }}</div>
          <div class="stat-label">时序期数</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ sensorOnline }}</div>
          <div class="stat-label">在线设备</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" :class="{ warn: sensorAlarm > 0 }">{{ sensorAlarm }}</div>
          <div class="stat-label">未处理告警</div>
        </div>
      </div>

      <div v-if="!summary.totalRecords" class="empty-tip">
        当前项目还没有解译记录，报告内容会为空。请先到「遥感解译」模块完成至少一次提取。
      </div>

      <div v-else class="preview">
        <div class="preview-item">
          <span class="label">地物构成</span>
          <el-tag
            v-for="c in summary.classes"
            :key="c.classType"
            size="small"
            class="cls-tag"
          >
            {{ classLabel(c.classType) }} {{ haToKm2(c.totalAreaHa) }} km²
          </el-tag>
        </div>
        <div class="preview-item">
          <span class="label">时序变化</span>
          <span>{{ series.length }} 期（{{ series[0]?.date }} → {{ series[series.length - 1]?.date }}）</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="panel">
      <template #header><span>生成报告</span></template>

      <!-- 模板选择 + 矿区基本信息 -->
      <el-form label-width="90px" class="report-form">
        <el-form-item label="报告模板">
          <el-radio-group v-model="template">
            <el-radio-button value="default">标准版</el-radio-button>
            <el-radio-button value="simple">简洁版</el-radio-button>
            <el-radio-button value="detailed">详细版</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="矿区名称">
          <el-input v-model="mineInfo.name" placeholder="如：宁都河源锂矿" />
        </el-form-item>
        <el-form-item label="矿权位置">
          <el-input v-model="mineInfo.location" placeholder="如：江西省赣州市宁都县" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="mineInfo.manager" placeholder="如：张三" />
        </el-form-item>
        <el-form-item label="安全评估">
          <div>
            <el-checkbox v-model="includeSafety">
              包含安全风险评估章节（五维评分 + 越界检测 + 热点清单）
            </el-checkbox>
            <div class="include-hint">勾选后生成前会实时跑一次评估，约需 10–30 秒</div>
          </div>
        </el-form-item>
      </el-form>

      <div class="gen-row">
        <el-button
          type="primary"
          :loading="generating"
          :disabled="!summary.totalRecords"
          @click="doGenerate"
        >
          生成 Word 报告
        </el-button>
        <span class="gen-hint">
          {{ summary.totalRecords ? '将生成 .docx 文件，可直接下载' : '请先完成至少一次解译提取' }}
        </span>
      </div>
    </el-card>

    <!-- 历史报告列表 -->
    <el-card shadow="never" class="panel">
      <template #header><span>历史报告</span></template>
      <div v-if="reportHistory.length === 0" class="empty-tip">暂无历史报告，生成后这里会记录</div>
      <el-table v-else :data="reportHistory" size="small">
        <el-table-column prop="name" label="报告名称" min-width="200" />
        <el-table-column prop="templateLabel" label="模板" width="90" />
        <el-table-column prop="generatedAt" label="生成时间" width="170" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="reDownload(row)">下载</el-button>
            <el-popconfirm title="删除这条记录？" @confirm="removeHistory(row)">
              <template #reference>
                <el-button size="small" text type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi, overviewApi } from '@/api'
import { reportApi } from '@/api/sentinel'
import { useProjectStore } from '@/stores/project'
import { haToKm2 } from '@/utils/format'
import type { AreaTimeseriesRow, ChangeSummary, PitForecastResult } from '@/api/types'

const projectStore = useProjectStore()
const loading = ref(false)
const generating = ref(false)

const template = ref<'default' | 'simple' | 'detailed'>('default')
const mineInfo = ref({
  name: '',
  location: '',
  manager: ''
})

const series = ref<AreaTimeseriesRow[]>([])
const summary = ref<ChangeSummary>({ totalRecords: 0, classes: [], note: '' })
const forecast = ref<PitForecastResult | null>(null)
const sensorOnline = ref(0)
const sensorAlarm = ref(0)

interface ReportHistoryItem {
  id: string
  name: string
  template: string
  templateLabel: string
  generatedAt: string
  mineName: string
  location: string
  manager: string
}
const reportHistory = ref<ReportHistoryItem[]>([])
/** 是否在报告中包含安全风险评估章节 */
const includeSafety = ref(false)

const TEMPLATE_LABEL: Record<string, string> = { default: '标准版', simple: '简洁版', detailed: '详细版' }

const CLASS_LABEL: Record<string, string> = {
  PIT: '采坑', BARE: '裸地扰动', VEGETATION: '植被',
  WATER: '水体', DUMP: '排土场', TAILINGS: '尾矿库', ROAD: '道路设施',
  BUILDING: '建筑', MOUNTAIN: '山体'
}
function classLabel(c: string) {
  return CLASS_LABEL[c] || c
}

async function loadData() {
  loading.value = true
  const pid = projectStore.currentId ?? undefined
  try {
    const [ts, sum, ov] = await Promise.all([
      analysisApi.areaTimeseries({ projectId: pid }),
      analysisApi.changeSummary(pid),
      overviewApi.stats(pid)
    ])
    series.value = ts.rows || []
    summary.value = sum
    sensorOnline.value = ov.sensorOnline ?? 0
    sensorAlarm.value = ov.sensorAlarm ?? 0
    try {
      forecast.value = await analysisApi.pitForecast(pid)
    } catch {
      forecast.value = null
    }
    // 默认矿区信息取当前项目
    mineInfo.value.name = projectStore.current?.name || ''
    mineInfo.value.location = projectStore.current?.region || ''
  } catch (e: any) {
    ElMessage.error('数据加载失败：' + (e.message || ''))
  } finally {
    loading.value = false
  }
}

/** 实际生成并下载 docx（复用下载逻辑） */
async function downloadReport(projectName: string): Promise<void> {
  // 勾选时先生成安全评估（含 DEM 读取，约 10-30 秒），把结果并入报告
  let safety: any = null
  if (includeSafety.value) {
    try {
      safety = await analysisApi.safetyEvaluate(projectStore.currentId ?? undefined, true)
      if (!safety?.available) {
        ElMessage.warning('安全评估数据不足，报告将不包含该章节')
        safety = null
      }
    } catch (e: any) {
      ElMessage.warning('安全评估失败，报告将不包含该章节：' + (e.message || ''))
      safety = null
    }
  }

  const res = await reportApi.generate({
    projectName,
    timeseries: series.value,
    summary: summary.value.classes,
    forecast: forecast.value || {},
    sensorOnline: sensorOnline.value,
    sensorAlarm: sensorAlarm.value,
    safety
  })
  const byteChars = atob(res.docx_base64)
  const bytes = new Uint8Array(byteChars.length)
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = res.filename
  a.click()
  URL.revokeObjectURL(url)
}

async function doGenerate() {
  generating.value = true
  try {
    const name = mineInfo.value.name || projectStore.current?.name || '默认项目'
    await downloadReport(name)
    // 记录到历史
    const item: ReportHistoryItem = {
      id: Date.now().toString(),
      name: `矿山监测报告-${name}`,
      template: template.value,
      templateLabel: TEMPLATE_LABEL[template.value],
      generatedAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      mineName: mineInfo.value.name,
      location: mineInfo.value.location,
      manager: mineInfo.value.manager
    }
    reportHistory.value.unshift(item)
    persistHistory()
    ElMessage.success('报告已生成并开始下载')
  } catch (e: any) {
    ElMessage.error('报告生成失败：' + (e.message || ''))
  } finally {
    generating.value = false
  }
}

async function reDownload(row: ReportHistoryItem) {
  try {
    await downloadReport(row.mineName || projectStore.current?.name || '默认项目')
    ElMessage.success('报告已重新生成并下载')
  } catch (e: any) {
    ElMessage.error('下载失败：' + (e.message || ''))
  }
}

function removeHistory(row: ReportHistoryItem) {
  reportHistory.value = reportHistory.value.filter((h) => h.id !== row.id)
  persistHistory()
}

function persistHistory() {
  localStorage.setItem('rs_report_history', JSON.stringify(reportHistory.value))
}

function loadHistory() {
  try {
    const raw = localStorage.getItem('rs_report_history')
    if (raw) reportHistory.value = JSON.parse(raw)
  } catch { /* ignore */ }
}

onMounted(() => {
  loadHistory()
  loadData()
})
</script>

<style scoped>
.include-hint { font-size: 11px; color: #a9aeb8; line-height: 1.6; margin-top: 2px; }
.notice {
  margin-bottom: 12px;
}
.panel {
  margin-bottom: 12px;
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: var(--el-fill-color-light);
  border-radius: 10px;
  padding: 16px;
  text-align: center;
}
.stat-num {
  font-size: 28px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.stat-num.warn {
  color: var(--el-color-danger);
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.empty-tip {
  color: var(--el-color-warning);
  font-size: 13px;
  padding: 8px 0;
}
.preview-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
}
.preview-item .label {
  color: var(--el-text-color-secondary);
  width: 80px;
  flex-shrink: 0;
}
.cls-tag {
  margin-right: 4px;
}
.gen-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.gen-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.report-form {
  max-width: 520px;
  margin-bottom: 12px;
}
</style>
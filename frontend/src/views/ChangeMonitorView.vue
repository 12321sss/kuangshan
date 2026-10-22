<template>
  <div class="mon-page">
    <!-- 参数条 -->
    <el-card shadow="never" class="op-card">
      <div class="op-bar">
        <div class="op-group">
          <span class="lbl">分析区</span>
          <el-select v-model="aoiId" size="small" placeholder="选择已导入的边界" style="width: 220px">
            <el-option v-for="o in aoiOptions" :key="o.id" :label="`${o.name}（${o.areaHa} ha）`" :value="o.id" />
          </el-select>
          <span class="lbl">云量上限</span>
          <el-input-number v-model="maxCloud" :min="1" :max="100" :step="5" size="small" style="width: 80px" />
        </div>
      </div>
      <div v-if="!aoiOptions.length" class="warn-row">
        还没有可用的分析区：请先到「遥感解译 → 边界管理」导入矿权范围
      </div>
    </el-card>

    <div class="grid">
      <!-- L1 可用性 -->
      <el-card shadow="never" v-loading="loadingAvail">
        <template #header>
          <div class="card-head">
            <span>① 影像可用性检查</span>
            <span class="card-hint">先确认「有没有影像」再谈「有没有变化」</span>
          </div>
        </template>
        <div class="row">
          <span class="lbl">往前看</span>
          <el-input-number v-model="days" :min="7" :max="365" :step="7" size="small" style="width: 90px" />
          <span class="unit">天</span>
          <el-button size="small" type="primary" plain :loading="loadingAvail" @click="runAvailability">检查</el-button>
        </div>
        <template v-if="avail">
          <div class="avail-head">
            <el-tag :type="availTag(avail.level)" size="small">{{ avail.level }}</el-tag>
            <span class="avail-msg">{{ avail.message }}</span>
          </div>
          <div class="avail-advice">{{ avail.advice }}</div>
          <el-table v-if="avail.scenes.length" :data="avail.scenes" size="small" max-height="220" class="mt8">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column label="云量" width="80">
              <template #default="{ row }">{{ row.cloudCover }}%</template>
            </el-table-column>
            <el-table-column prop="platform" label="平台" width="100" />
            <el-table-column label="ID" min-width="180">
              <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
            </el-table-column>
          </el-table>
          <div class="note">{{ avail.note }}</div>
        </template>
        <el-empty v-else description="还没有检查" :image-size="60" />
      </el-card>

      <!-- L2 突变检测 -->
      <el-card shadow="never" v-loading="loadingChange">
        <template #header>
          <div class="card-head">
            <span>② 两期突变检测</span>
            <span class="card-hint">只找可疑斑块，不做面积趋势（周尺度测不准）</span>
          </div>
        </template>
        <div class="row">
          <span class="lbl">第一期</span>
          <el-date-picker v-model="range1" type="daterange" size="small" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" style="width: 220px" />
        </div>
        <div class="row">
          <span class="lbl">第二期</span>
          <el-date-picker v-model="range2" type="daterange" size="small" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" style="width: 220px" />
        </div>
        <div class="row">
          <span class="lbl">最小斑块</span>
          <el-input-number v-model="minAreaHa" :min="0.05" :max="10" :step="0.1" :precision="2" size="small" style="width: 96px" />
          <span class="unit">ha</span>
          <el-button size="small" type="primary" :loading="loadingChange" @click="runChange">开始检测</el-button>
        </div>
        <div class="run-hint">首次检测需下载两期影像（1-4 分钟），之后同一景会命中磁盘缓存</div>

        <template v-if="change">
          <div class="conclusion">{{ change.conclusion }}</div>
          <div class="period-row">
            <span>第一期 <b>{{ change.periods.first.datetime }}</b>（云量 {{ change.periods.first.cloudCover }}%）</span>
            <span>第二期 <b>{{ change.periods.second.datetime }}</b>（云量 {{ change.periods.second.cloudCover }}%）</span>
          </div>

          <div class="event-grid">
            <div v-for="e in change.events" :key="e.type" class="ev-card">
              <div class="ev-head">
                <span class="ev-dot" :style="{ background: e.color }"></span>
                <span class="ev-label">{{ e.label }}</span>
                <span class="ev-count">{{ e.count }} 处</span>
              </div>
              <div class="ev-area">{{ e.totalAreaHa }} ha</div>
              <div v-if="e.patches.length" class="ev-patch">
                <el-popover placement="top" :width="320" trigger="hover">
                  <template #reference>
                    <span class="patch-link">查看点位</span>
                  </template>
                  <div v-for="(p, i) in e.patches.slice(0, 8)" :key="i" class="patch-item">
                    <span class="mono">{{ p.lng }}, {{ p.lat }}</span>
                    <span>{{ p.areaHa }} ha</span>
                    <el-button link type="primary" size="small" @click="copyCoord(p)">复制</el-button>
                  </div>
                </el-popover>
              </div>
            </div>
          </div>

          <div v-if="change.imageBase64" class="img-wrap">
            <img :src="'data:image/png;base64,' + change.imageBase64" class="chg-img" />
            <div class="legend">
              <span v-for="l in change.legend" :key="l.label" class="lg">
                <i :style="{ background: l.color }"></i>{{ l.label }}
              </span>
            </div>
          </div>

          <div v-for="(w, i) in change.warnings" :key="i" class="warn-tip">· {{ w }}</div>
          <div class="disclaimer">{{ change.disclaimer }}</div>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi } from '@/api'
import type { AoiOption, AvailabilityResult, ChangeEventsResult } from '@/api'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const aoiOptions = ref<AoiOption[]>([])
const aoiId = ref<number | null>(null)
const maxCloud = ref(20)

const days = ref(30)
const avail = ref<AvailabilityResult | null>(null)
const loadingAvail = ref(false)

const today = new Date().toISOString().slice(0, 10)
const range1 = ref<[string, string]>([
  new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10),
  new Date(Date.now() - 40 * 86400000).toISOString().slice(0, 10)
])
const range2 = ref<[string, string]>([
  new Date(Date.now() - 35 * 86400000).toISOString().slice(0, 10),
  today
])
const minAreaHa = ref(0.5)
const change = ref<ChangeEventsResult | null>(null)
const loadingChange = ref(false)

const currentRing = computed(() => aoiOptions.value.find((o) => o.id === aoiId.value)?.ring)

function availTag(level: string) {
  if (level === '充足') return 'success'
  if (level === '偏少') return 'warning'
  return 'danger'
}

async function loadOptions() {
  const pid = projectStore.currentId
  if (!pid) return
  try {
    const res = await analysisApi.aoiOptions(pid)
    aoiOptions.value = res.options || []
    if (aoiOptions.value.length && !aoiId.value) {
      const permit = aoiOptions.value.find((o) => o.boundaryType === 'PERMIT')
      aoiId.value = (permit || aoiOptions.value[0]).id
    }
  } catch {
    aoiOptions.value = []
  }
}

async function runAvailability() {
  if (!projectStore.currentId) return
  loadingAvail.value = true
  try {
    avail.value = await analysisApi.monitorAvailability({
      projectId: projectStore.currentId,
      aoi: currentRing.value,
      days: days.value,
      maxCloud: maxCloud.value
    })
  } catch (e: any) {
    ElMessage.error(e?.message || '可用性检查失败')
  } finally {
    loadingAvail.value = false
  }
}

async function runChange() {
  if (!projectStore.currentId) return
  if (!range1.value || !range2.value) {
    ElMessage.warning('两期日期都要选')
    return
  }
  loadingChange.value = true
  change.value = null
  try {
    change.value = await analysisApi.changeEvents({
      projectId: projectStore.currentId,
      aoi: currentRing.value,
      d1Start: range1.value[0],
      d1End: range1.value[1],
      d2Start: range2.value[0],
      d2End: range2.value[1],
      maxCloud: maxCloud.value,
      minAreaHa: minAreaHa.value,
      withImage: true
    })
    ElMessage.success(change.value.conclusion)
  } catch (e: any) {
    ElMessage.error(e?.message || '突变检测失败')
  } finally {
    loadingChange.value = false
  }
}

async function copyCoord(p: { lng: number; lat: number }) {
  try {
    await navigator.clipboard.writeText(`${p.lng},${p.lat}`)
    ElMessage.success('坐标已复制，可直接粘到地图或汇报材料')
  } catch {
    ElMessage.warning(`坐标：${p.lng}, ${p.lat}`)
  }
}

onMounted(loadOptions)
watch(() => projectStore.currentId, () => {
  aoiId.value = null
  avail.value = null
  change.value = null
  loadOptions()
})
</script>

<style scoped>
.mon-page { display: flex; flex-direction: column; gap: 12px; }
.op-card :deep(.el-card__body) { padding: 10px 14px; }
.op-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.op-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lbl { font-size: 12px; color: #6b7280; }
.unit { font-size: 12px; color: #a9aeb8; }
.warn-row { margin-top: 8px; font-size: 12px; color: #b45309; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
@media (max-width: 1300px) { .grid { grid-template-columns: 1fr; } }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-hint { font-size: 11px; color: #a9aeb8; }
.row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.mt8 { margin-top: 8px; }

.avail-head { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
.avail-msg { font-size: 12px; color: #303133; line-height: 1.6; }
.avail-advice { font-size: 12px; color: #0f766e; line-height: 1.6; padding: 6px 8px; background: #f0fdfa; border-radius: 6px; }
.note { font-size: 11px; color: #a9aeb8; margin-top: 8px; line-height: 1.6; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #6b7280; }

.run-hint { font-size: 11px; color: #a9aeb8; margin-top: 2px; }
.conclusion { font-size: 13px; color: #1f2937; line-height: 1.7; padding: 8px 10px; background: #f6f8fa; border-radius: 8px; margin: 8px 0; }
.period-row { display: flex; gap: 16px; font-size: 11px; color: #6b7280; flex-wrap: wrap; }

.event-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 10px 0; }
.ev-card { border: 1px solid #eef0f3; border-radius: 8px; padding: 8px 10px; }
.ev-head { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #374151; }
.ev-dot { width: 8px; height: 8px; border-radius: 2px; }
.ev-label { flex: 1; }
.ev-count { color: #6b7280; font-size: 11px; }
.ev-area { font-size: 16px; font-weight: 600; color: #111827; margin-top: 2px; }
.ev-patch { margin-top: 2px; }
.patch-link { font-size: 11px; color: #0d9488; cursor: pointer; }
.patch-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 11px; padding: 2px 0; }

.img-wrap { margin-top: 8px; }
.chg-img { width: 100%; border: 1px solid #eef0f3; border-radius: 6px; image-rendering: pixelated; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-top: 6px; }
.lg { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #6b7280; }
.lg i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.warn-tip { font-size: 11px; color: #b45309; line-height: 1.6; margin-top: 4px; }
.disclaimer { font-size: 10px; color: #a9aeb8; line-height: 1.6; margin-top: 8px; }
</style>

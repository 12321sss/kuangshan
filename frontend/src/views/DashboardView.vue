<template>
  <div v-loading="loading">
    <!-- 演示入口：一键走完整个平台主线，避免现场手忙脚乱 -->
    <div class="demo-bar">
      <div class="db-left">
        <div class="db-title">演示模式</div>
        <div class="db-sub">一键按顺序走完「遥感提取 → 变化分析 → 告警 → 报告」，适合给客户做完整展示</div>
      </div>
      <div class="db-right">
        <el-button v-if="!demoRunning" type="primary" @click="startDemo">▶ 开始演示</el-button>
        <template v-else>
          <span class="db-step">{{ demoStepText }}</span>
          <el-button size="small" @click="stopDemo">结束演示</el-button>
        </template>
      </div>
    </div>

    <!-- 指标卡片 -->
    <div class="stat-grid">
      <div v-for="card in cards" :key="card.label" class="stat-card">
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value" :style="{ color: card.color }">
          {{ card.value }}<span class="stat-unit">{{ card.unit }}</span>
        </div>
        <div class="stat-foot">{{ card.foot }}</div>
      </div>
    </div>

    <!-- 快捷入口：把高频操作集中一行，减少找菜单的成本 -->
    <div class="quick-links">
      <span class="ql-title">快捷入口</span>
      <div
        v-for="q in quickLinks"
        :key="q.path"
        class="ql-item"
        @click="router.push(q.path)"
      >
        <el-icon><component :is="q.icon" /></el-icon>
        <span>{{ q.label }}</span>
      </div>
    </div>

    <div class="panel-row">
      <!-- 传感器曲线 -->
      <el-card class="panel chart-panel" shadow="never">
        <template #header>
          <div class="panel-head">
            <span>排土场北坡位移（DISP-03 · 告警设备）</span>
            <el-radio-group v-model="hours" size="small" @change="loadChart">
              <el-radio-button :value="24">24h</el-radio-button>
              <el-radio-button :value="72">72h</el-radio-button>
              <el-radio-button :value="168">7天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div ref="chartRef" class="chart"></div>
      </el-card>

      <!-- 告警与任务 -->
      <el-card class="panel side-panel" shadow="never">
        <template #header><span>当前告警</span></template>
        <div v-if="alarms.length === 0" class="empty">暂无告警</div>
        <div v-for="s in alarms" :key="s.id" class="alarm-item">
          <el-tag type="danger" size="small">告警</el-tag>
          <div class="alarm-info">
            <div class="alarm-name">{{ s.name }}</div>
            <div class="alarm-detail">{{ s.latestValue }} {{ s.unit }} · 超阈值</div>
          </div>
        </div>
        <el-divider />
        <div class="sub-title">最新任务</div>
        <div v-for="t in recentTasks" :key="t.id" class="task-item">
          <span class="task-name">{{ t.name }}</span>
          <el-tag :type="taskTagType(t.status)" size="small">{{ taskStatusLabel(t.status) }}</el-tag>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { MapLocation, Cpu, DataLine, Bell, Document, Odometer } from '@element-plus/icons-vue'
import { overviewApi, sensorApi, taskApi } from '@/api'
import { useProjectStore } from '@/stores/project'
import type { InterpretTask, OverviewStats, Sensor } from '@/api/types'

const projectStore = useProjectStore()
const router = useRouter()

// ---- 演示剧本：按顺序自动走完平台主线，适合现场给客户展示 ----
const DEMO_STEPS = [
  { path: '/remote-extract', title: '第 1 步 · 遥感提取（圈 AOI → 解译）' },
  { path: '/analysis', title: '第 2 步 · 变化分析（面积时序 + 检测突变）' },
  { path: '/warning/alarms', title: '第 3 步 · 告警日志（闭环处理）' },
  { path: '/report', title: '第 4 步 · 报告生成（选模板出 Word）' }
]
const demoRunning = ref(false)
const demoIndex = ref(0)
const demoStepText = computed(() => DEMO_STEPS[demoIndex.value]?.title || '')
let demoTimer: ReturnType<typeof setInterval> | undefined

function startDemo() {
  demoRunning.value = true
  demoIndex.value = 0
  ElMessage.info('演示开始：将依次展示遥感提取 → 变化分析 → 告警 → 报告')
  router.push(DEMO_STEPS[0].path)
  demoTimer = setInterval(() => {
    demoIndex.value += 1
    if (demoIndex.value >= DEMO_STEPS.length) {
      stopDemo()
      ElMessage.success('演示流程已完成')
      return
    }
    router.push(DEMO_STEPS[demoIndex.value].path)
  }, 12000)
}

function stopDemo() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = undefined }
  demoRunning.value = false
  demoIndex.value = 0
}

const loading = ref(true)
const stats = ref<OverviewStats | null>(null)
const sensors = ref<Sensor[]>([])
const tasks = ref<InterpretTask[]>([])
const hours = ref(24)

const chartRef = ref<HTMLDivElement>()
// 图表实例：用普通 let + 类型标注，避免 SFC 编译期对 ref<命名空间.类型>() 泛型写法的解析问题
let chart: echarts.ECharts | undefined

const cards = computed(() => [
  { label: '影像库', value: stats.value?.imageCount ?? '-', unit: ' 景', color: '#2f54eb', foot: '已入库影像' },
  { label: '运行中任务', value: stats.value?.taskRunning ?? '-', unit: ' 个', color: '#0ea5e9', foot: '解译任务' },
  { label: '在线传感器', value: stats.value?.sensorOnline ?? '-', unit: ' 台', color: '#22c55e', foot: 'IoT 设备在线' },
  { label: '当前告警', value: stats.value?.sensorAlarm ?? '-', unit: ' 条', color: '#ef4444', foot: '位移计阈值告警' }
])

/** 快捷入口：覆盖"看数据 / 做解译 / 查变化 / 处理告警 / 出报告 / 查健康"主线 */
const quickLinks = [
  { label: 'GIS 大屏', path: '/screen', icon: MapLocation },
  { label: '遥感提取', path: '/remote-extract', icon: Cpu },
  { label: '变化分析', path: '/analysis', icon: DataLine },
  { label: '告警闭环', path: '/warning/alarms', icon: Bell },
  { label: '生成报告', path: '/report', icon: Document },
  { label: '系统健康', path: '/platform/health', icon: Odometer }
]

const alarms = computed(() => sensors.value.filter((s) => s.status === 'ALARM'))
const recentTasks = computed(() => tasks.value.slice(0, 4))

function taskTagType(status: InterpretTask['status']) {
  return { SUCCESS: 'success', RUNNING: 'primary', PENDING: 'info', FAILED: 'danger' }[status] as any
}
function taskStatusLabel(status: InterpretTask['status']) {
  return { SUCCESS: '完成', RUNNING: '运行中', PENDING: '排队中', FAILED: '失败' }[status]
}

async function loadChart() {
  try {
    // 取当前项目第一台位移计；没有位移计就取第一台设备
    const target = sensors.value.find((s) => s.type === 'DISP') || sensors.value[0]
    if (!target) return
    const data = await sensorApi.data(target.id, hours.value)
    if (!chart && chartRef.value) {
      chart = echarts.init(chartRef.value)
    }
    chart?.setOption({
      grid: { left: 44, right: 16, top: 30, bottom: 28 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: data.map((p) => p.time.slice(5, 13).replace('T', ' ')),
        axisLabel: { fontSize: 11, color: '#86909c' }
      },
      yAxis: {
        type: 'value', name: 'mm',
        axisLabel: { fontSize: 11, color: '#86909c' },
        splitLine: { lineStyle: { color: '#f0f0f0' } }
      },
      series: [{
        type: 'line',
        data: data.map((p) => p.value),
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#ef4444', width: 2 },
        areaStyle: { color: 'rgba(239,68,68,0.08)' },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#f59e0b', type: 'dashed' },
          data: [{ yAxis: 6, label: { formatter: '告警阈值 6mm', fontSize: 11 } }]
        }
      }]
    }, true)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  try {
    const [s, sensorList, taskList] = await Promise.all([
      overviewApi.stats(projectStore.currentId),
      sensorApi.list(projectStore.currentId),
      taskApi.list(projectStore.currentId)
    ])
    stats.value = s
    sensors.value = sensorList
    tasks.value = taskList
    await loadChart()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
  window.addEventListener('resize', resize)
})

// 切换工程 -> 全量刷新
watch(() => projectStore.currentId, async () => {
  loading.value = true
  try {
    const [s, sensorList, taskList] = await Promise.all([
      overviewApi.stats(projectStore.currentId),
      sensorApi.list(projectStore.currentId),
      taskApi.list(projectStore.currentId)
    ])
    stats.value = s
    sensors.value = sensorList
    tasks.value = taskList
    await loadChart()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
})

function resize() { chart?.resize() }

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  if (demoTimer) clearInterval(demoTimer)   // 离开页面时停掉演示定时器
})
</script>

<style scoped>
/* ---- 演示模式条 ---- */
.demo-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: linear-gradient(90deg, #f0fdfa 0%, #ecfeff 100%);
  border: 1px solid #ccfbf1;
  border-radius: 10px; padding: 12px 16px; margin-bottom: 12px;
}
.db-title { font-size: 14px; font-weight: 700; color: #0d9488; }
.db-sub { font-size: 12px; color: #5e8a85; margin-top: 3px; }
.db-right { display: flex; align-items: center; gap: 10px; }
.db-step { font-size: 12px; color: #0d9488; font-weight: 600; }

/* 快捷入口 */
.quick-links {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 12px; padding: 10px 14px;
  background: #fff; border: 1px solid #eceef2; border-radius: 10px;
}
.ql-title { font-size: 12px; color: #86909c; margin-right: 4px; }
.ql-item {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: 16px;
  background: #f2f7f6; color: #0d9488;
  font-size: 12px; cursor: pointer; transition: all 0.15s;
}
.ql-item:hover { background: #ccfbf1; transform: translateY(-1px); }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  background: #fff;
  border: 1px solid #eceef2;
  border-radius: 10px;
  padding: 18px 20px;
}

.stat-label { font-size: 13px; color: #86909c; }
.stat-value { font-size: 30px; font-weight: 700; margin: 8px 0 4px; font-variant-numeric: tabular-nums; }
.stat-unit { font-size: 13px; font-weight: 400; color: #86909c; }
.stat-foot { font-size: 12px; color: #a9aeb8; }

.panel-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}

.panel { border: 1px solid #eceef2; border-radius: 10px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.chart { height: 320px; }

.empty { color: #a9aeb8; font-size: 13px; padding: 8px 0; }

.alarm-item { display: flex; align-items: center; gap: 10px; padding: 8px 0; }
.alarm-name { font-size: 13px; font-weight: 600; }
.alarm-detail { font-size: 12px; color: #ef4444; }

.sub-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.task-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 0; font-size: 13px;
}
.task-name {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 220px; color: #4e5969;
}
</style>

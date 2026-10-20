<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>告警日志</span>
        <div class="head-filters">
          <el-radio-group v-model="levelFilter" size="small">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="RED">红色</el-radio-button>
            <el-radio-button value="ORANGE">橙色</el-radio-button>
            <el-radio-button value="YELLOW">黄色</el-radio-button>
            <el-radio-button value="BLUE">蓝色</el-radio-button>
          </el-radio-group>
        </div>
      </div>
    </template>
    <el-table :data="filtered" stripe>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag :color="levelColor(row.level)" style="color:#fff;border:none" size="small">
            {{ levelLabel(row.level) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sensorName" label="监测设备" min-width="160" />
      <el-table-column prop="indicator" label="指标" width="110" />
      <el-table-column label="数值 / 阈值" width="150">
        <template #default="{ row }">
          <span :style="{ color: levelColor(row.level), fontWeight: 600 }">{{ row.value }}</span>
          <span class="threshold"> / {{ row.threshold }} {{ row.unit }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="触发时间" width="170">
        <template #default="{ row }">{{ row.createdAt.replace('T', ' ').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'UNACK' ? 'danger' : row.status === 'ACKED' ? 'warning' : 'success'" size="small" effect="plain">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="处理" min-width="150">
        <template #default="{ row }">
          <span v-if="row.handledBy" class="handled-info">{{ row.handledBy }} · {{ row.handleComment || '已处理' }}</span>
          <span v-else class="done-text">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button v-if="row.status === 'UNACK' && canAck" size="small" type="primary" @click="onAck(row)">确认</el-button>
          <el-button v-if="row.status !== 'RESOLVED' && canAck" size="small" type="success" @click="onResolveOpen(row)">处理关闭</el-button>
          <span v-else-if="row.status === 'UNACK' && !canAck" class="done-text">待确认</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 闭环处理弹窗 -->
    <el-dialog v-model="resolveVisible" title="告警闭环处理" width="440px">
      <el-form v-if="resolving" label-width="80px">
        <el-form-item label="告警">
          <span>{{ resolving.sensorName }} · {{ resolving.indicator }}（{{ resolving.value }}{{ resolving.unit }}）</span>
        </el-form-item>
        <el-form-item label="处理人" required>
          <el-input v-model="resolveForm.handledBy" placeholder="填写处理人姓名" />
        </el-form-item>
        <el-form-item label="处理意见" required>
          <el-input v-model="resolveForm.handleComment" type="textarea" :rows="3" placeholder="描述处置措施与结论" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resolveVisible = false">取消</el-button>
        <el-button type="primary" :loading="resolvingLoading" @click="onResolve">确认关闭</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { alarmApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { Alarm, AlarmLevel, AlarmStatus } from '@/api/types'

const auth = useAuthStore()
const projectStore = useProjectStore()
// 确认告警需 管理员/项目管理员/分析师；观察员只读
const canAck = computed(() => ['ADMIN', 'MANAGER', 'ANALYST'].includes(auth.user?.role || ''))

const loading = ref(true)
const alarms = ref<Alarm[]>([])
const levelFilter = ref('')
const resolveVisible = ref(false)
const resolving = ref<Alarm | null>(null)
const resolvingLoading = ref(false)
const resolveForm = ref({ handledBy: '', handleComment: '' })

const filtered = computed(() =>
  levelFilter.value ? alarms.value.filter((a) => a.level === levelFilter.value) : alarms.value
)

function levelColor(level: AlarmLevel) {
  return { RED: '#ef4444', ORANGE: '#f97316', YELLOW: '#eab308', BLUE: '#3b82f6' }[level]
}
function levelLabel(level: AlarmLevel) {
  return { RED: '红色', ORANGE: '橙色', YELLOW: '黄色', BLUE: '蓝色' }[level]
}
function statusLabel(s: AlarmStatus) {
  return { UNACK: '未确认', ACKED: '已确认', RESOLVED: '已解除' }[s]
}

async function load() {
  loading.value = true
  try {
    alarms.value = await alarmApi.list(projectStore.currentId)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

// 切换工程 -> 重新拉取
watch(() => projectStore.currentId, load)

async function onAck(row: Alarm) {
  try {
    await alarmApi.ack(row.id)
    ElMessage.success('告警已确认')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

function onResolveOpen(row: Alarm) {
  resolving.value = row
  resolveForm.value = { handledBy: auth.user?.displayName || '', handleComment: '' }
  resolveVisible.value = true
}

async function onResolve() {
  if (!resolving.value) return
  if (!resolveForm.value.handledBy || !resolveForm.value.handleComment) {
    ElMessage.warning('请填写处理人和处理意见')
    return
  }
  resolvingLoading.value = true
  try {
    await alarmApi.resolve(resolving.value.id, resolveForm.value.handledBy, resolveForm.value.handleComment)
    ElMessage.success('告警已闭环关闭')
    resolveVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    resolvingLoading.value = false
  }
}
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.threshold { color: #a9aeb8; font-size: 12px; }
.done-text { color: #a9aeb8; font-size: 12px; }
.handled-info { color: #4e5969; font-size: 12px; }
</style>

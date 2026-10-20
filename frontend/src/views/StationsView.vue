<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>站点监控 · {{ projectStore.current?.name || '全部项目' }}</span>
        <div class="head-actions">
          <el-button :icon="Download" @click="onExport">导出</el-button>
          <el-button v-if="auth.hasAction('action:station-manage')" type="primary" :icon="Plus" @click="onCreate">新增站点</el-button>
        </div>
      </div>
    </template>

    <!-- 统计卡片 -->
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

    <!-- 站点表 -->
    <el-table :data="stations" stripe>
      <el-table-column prop="projectNo" label="工程编号" width="90" />
      <el-table-column prop="region" label="地区" min-width="140" show-overflow-tooltip />
      <el-table-column prop="stationName" label="站点名称" min-width="150" show-overflow-tooltip />
      <el-table-column prop="stationType" label="站点类型" min-width="140" show-overflow-tooltip />
      <el-table-column label="站点工作状态" width="105">
        <template #default="{ row }">
          <el-tag :type="workStatusTag(row.workStatus)" size="small">{{ workStatusLabel(row.workStatus) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="lastMonitorAt" label="最后监测" width="150" />
      <el-table-column prop="deviceSn" label="设备机身号" width="110" />
      <el-table-column prop="deviceModel" label="设备型号" width="95" />
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="onDetail(row)">详情</el-button>
          <template v-if="auth.hasAction('action:station-manage')">
            <el-button size="small" text type="primary" @click="onEdit(row)">编辑</el-button>
            <el-popconfirm title="确定删除该站点？" @confirm="onDelete(row)">
              <template #reference>
                <el-button size="small" text type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="isCreate ? '新增站点' : '编辑站点'" width="520px">
      <el-form v-if="editing" label-width="96px">
        <el-form-item label="站点编号" required>
          <el-input v-model="editing.id" :disabled="!isCreate" placeholder="如 S14" />
        </el-form-item>
        <el-form-item label="站点名称" required>
          <el-input v-model="editing.stationName" />
        </el-form-item>
        <el-form-item label="站点类型">
          <el-select v-model="editing.stationType" style="width: 100%">
            <el-option value="GNSS 地表位移监测站" label="GNSS 地表位移监测站" />
            <el-option value="一体化雨量监测站" label="一体化雨量监测站" />
            <el-option value="土壤含水率监测站" label="土壤含水率监测站" />
            <el-option value="水位监测站" label="水位监测站" />
          </el-select>
        </el-form-item>
        <el-form-item label="工作状态">
          <el-radio-group v-model="editing.workStatus">
            <el-radio-button value="NORMAL">正常</el-radio-button>
            <el-radio-button value="ABNORMAL">异常</el-radio-button>
            <el-radio-button value="MAINTAIN">维护</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="关联传感器">
          <el-select v-model="editing.sensorId" clearable placeholder="选择传感器数据源" style="width: 100%">
            <el-option v-for="s in sensors" :key="s.id" :label="`${s.name}（${s.id}）`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备机身号"><el-input v-model="editing.deviceSn" /></el-form-item>
        <el-form-item label="设备型号"><el-input v-model="editing.deviceModel" /></el-form-item>
        <el-form-item label="固件版本"><el-input v-model="editing.firmware" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="current?.stationName" size="380px">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="站点编号">{{ current.id }}</el-descriptions-item>
        <el-descriptions-item label="工程编号">{{ current.projectNo }}</el-descriptions-item>
        <el-descriptions-item label="地区">{{ current.region }}</el-descriptions-item>
        <el-descriptions-item label="站点类型">{{ current.stationType }}</el-descriptions-item>
        <el-descriptions-item label="关联传感器">{{ current.sensorId || '未关联' }}</el-descriptions-item>
        <el-descriptions-item label="首次监测">{{ current.firstMonitorAt }}</el-descriptions-item>
        <el-descriptions-item label="最后监测">{{ current.lastMonitorAt }}</el-descriptions-item>
        <el-descriptions-item label="设备机身号">{{ current.deviceSn }}</el-descriptions-item>
        <el-descriptions-item label="设备型号">{{ current.deviceModel }}</el-descriptions-item>
        <el-descriptions-item label="固件版本">{{ current.firmware }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Monitor, CircleCheck, WarningFilled, Tools, Plus } from '@element-plus/icons-vue'
import { sensorApi, stationApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { Sensor, Station } from '@/api/types'

const auth = useAuthStore()
const projectStore = useProjectStore()

const loading = ref(true)
const saving = ref(false)
const stations = ref<Station[]>([])
const sensors = ref<Sensor[]>([])
const dialogVisible = ref(false)
const drawerVisible = ref(false)
const isCreate = ref(true)
const editing = ref<Partial<Station> | null>(null)
const current = ref<Station | null>(null)

const cards = computed(() => [
  { label: '站点总数', value: stations.value.length, icon: Monitor, color: '#0d9488', bg: '#e6f6f4' },
  { label: '正常总数', value: stations.value.filter((s) => s.workStatus === 'NORMAL').length, icon: CircleCheck, color: '#22c55e', bg: '#eafaf0' },
  { label: '异常总数', value: stations.value.filter((s) => s.workStatus === 'ABNORMAL').length, icon: WarningFilled, color: '#ef4444', bg: '#fdecec' },
  { label: '维护总数', value: stations.value.filter((s) => s.workStatus === 'MAINTAIN').length, icon: Tools, color: '#f59e0b', bg: '#fef6e6' }
])

function workStatusTag(s: Station['workStatus']) {
  return { NORMAL: 'success', ABNORMAL: 'danger', MAINTAIN: 'warning' }[s] as any
}
function workStatusLabel(s: Station['workStatus']) {
  return { NORMAL: '正常', ABNORMAL: '异常', MAINTAIN: '维护' }[s]
}

async function load() {
  loading.value = true
  try {
    ;[stations.value, sensors.value] = await Promise.all([
      stationApi.list(projectStore.currentId),
      sensorApi.list(projectStore.currentId)
    ])
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onCreate() {
  isCreate.value = true
  editing.value = {
    id: '', stationName: '', stationType: 'GNSS 地表位移监测站', workStatus: 'NORMAL',
    projectId: projectStore.currentId, region: projectStore.current?.region || '',
    sensorId: '', deviceSn: '', deviceModel: '', firmware: ''
  }
  dialogVisible.value = true
}

function onEdit(row: Station) {
  isCreate.value = false
  editing.value = { ...row }
  dialogVisible.value = true
}

async function onSave() {
  if (!editing.value?.id || !editing.value?.stationName) {
    ElMessage.warning('站点编号和名称不能为空')
    return
  }
  saving.value = true
  try {
    const payload = { ...editing.value, projectId: projectStore.currentId }
    if (isCreate.value) {
      await stationApi.create(payload)
    } else {
      await stationApi.update(editing.value.id!, payload)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: Station) {
  try {
    await stationApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

function onDetail(row: Station) {
  current.value = row
  drawerVisible.value = true
}

function onExport() {
  ElMessage.success('导出任务已创建（demo）')
}

onMounted(load)
// 切换工程 -> 重新拉取
watch(() => projectStore.currentId, load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head-actions { display: flex; gap: 10px; }

.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 14px; }

.stat-card {
  background: #fafbfc; border: 1px solid #eceef2; border-radius: 10px;
  padding: 14px 16px; display: flex; align-items: center; gap: 12px;
}

.stat-icon {
  width: 40px; height: 40px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
}

.stat-label { font-size: 12px; color: #86909c; }
.stat-value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
</style>

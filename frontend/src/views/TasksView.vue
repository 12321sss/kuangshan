<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>解译任务 · {{ projectStore.current?.name || '全部项目' }}</span>
        <el-button v-if="auth.hasAction('action:task-manage')" type="primary" :icon="Plus" @click="onCreate">新建任务</el-button>
      </div>
    </template>
    <el-table :data="tasks" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="任务名称" min-width="220" show-overflow-tooltip />
      <el-table-column label="算法类型" width="120">
        <template #default="{ row }">
          <el-tag effect="plain" size="small">{{ algoLabel(row.algoType) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="190">
        <template #default="{ row }">
          <el-progress
            :percentage="row.progress"
            :status="row.status === 'FAILED' ? 'exception' : row.status === 'SUCCESS' ? 'success' : undefined"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" width="95">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="imageName" label="输入影像" min-width="200" show-overflow-tooltip />
      <el-table-column prop="createdAt" label="创建时间" width="160">
        <template #default="{ row }">{{ row.createdAt.replace('T', ' ').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column v-if="auth.hasAction('action:task-manage')" label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-popconfirm title="确定删除该任务？" @confirm="onDelete(row)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建任务对话框 -->
    <el-dialog v-model="dialogVisible" title="新建解译任务" width="460px">
      <el-form v-if="form" label-width="90px">
        <el-form-item label="任务名称" required>
          <el-input v-model="form.name" placeholder="如：宁都河源 2026-10 七类分割" />
        </el-form-item>
        <el-form-item label="算法类型" required>
          <el-select v-model="form.algoType" style="width: 100%">
            <el-option value="SEGMENTATION" label="语义分割（七类地物）" />
            <el-option value="CHANGE_DETECTION" label="变化检测（双时相）" />
            <el-option value="INDEX" label="指数计算（NDVI/NDWI）" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入影像">
          <el-input v-model="form.imageName" placeholder="如：S2A_20261016_NDHY.tif" />
        </el-form-item>
        <el-alert type="info" :closable="false"
                  title="demo：任务由内置模拟器推进（约 20 秒完成）；真实解译链路接入 inference 服务后由回调驱动" />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">提交任务</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { taskApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { InterpretTask } from '@/api/types'

const auth = useAuthStore()
const projectStore = useProjectStore()

const loading = ref(true)
const saving = ref(false)
const tasks = ref<InterpretTask[]>([])
const dialogVisible = ref(false)
const form = ref<{ name: string; algoType: string; imageName: string } | null>(null)

let pollTimer: ReturnType<typeof setInterval> | undefined

function algoLabel(t: InterpretTask['algoType']) {
  return { SEGMENTATION: '语义分割', CHANGE_DETECTION: '变化检测', INDEX: '指数计算' }[t]
}
function statusTag(s: InterpretTask['status']) {
  return { SUCCESS: 'success', RUNNING: 'primary', PENDING: 'info', FAILED: 'danger' }[s] as any
}
function statusLabel(s: InterpretTask['status']) {
  return { SUCCESS: '完成', RUNNING: '运行中', PENDING: '排队中', FAILED: '失败' }[s]
}

async function load(quiet = false) {
  if (!quiet) loading.value = true
  try {
    tasks.value = await taskApi.list(projectStore.currentId)
  } catch (e: any) {
    if (!quiet) ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

/** 有运行中的任务时轮询进度（5 秒一次）；没有就停 */
function syncPolling() {
  const hasRunning = tasks.value.some((t) => t.status === 'RUNNING')
  if (hasRunning && !pollTimer) {
    pollTimer = setInterval(() => load(true), 5000)
  } else if (!hasRunning && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function onCreate() {
  form.value = { name: '', algoType: 'SEGMENTATION', imageName: '' }
  dialogVisible.value = true
}

async function onSave() {
  if (!form.value?.name) {
    ElMessage.warning('任务名称不能为空')
    return
  }
  saving.value = true
  try {
    await taskApi.create({
      name: form.value.name,
      projectId: projectStore.currentId,
      algoType: form.value.algoType,
      imageName: form.value.imageName || undefined
    })
    ElMessage.success('任务已提交')
    dialogVisible.value = false
    await load()
    syncPolling()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: InterpretTask) {
  try {
    await taskApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  await load()
  syncPolling()
})

watch(() => projectStore.currentId, async () => {
  await load()
  syncPolling()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
</style>

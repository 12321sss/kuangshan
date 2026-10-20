<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>操作日志</span>
        <div class="head-right">
          <el-select v-model="actionFilter" size="small" style="width: 130px" clearable placeholder="全部操作">
            <el-option v-for="a in ACTION_OPTIONS" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
          <el-input v-model="keyword" size="small" placeholder="搜索用户/对象" clearable style="width: 180px" />
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <el-alert type="info" :closable="false" class="tip">
      审计日志只追加不修改，管理员可查看全量操作，普通用户仅看自己的记录。
    </el-alert>

    <el-empty v-if="!loading && filtered.length === 0" description="暂无操作日志">
      <el-button type="primary" size="small" @click="load">刷新</el-button>
    </el-empty>

    <el-table v-else :data="filtered" stripe size="small">
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 19) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作人" width="110" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="actionTagType(row.action)" effect="plain">{{ actionLabel(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="对象" width="180">
        <template #default="{ row }">
          <span class="ref">{{ entityLabel(row.entityType) }}<template v-if="row.entityRef"> · {{ row.entityRef }}</template></span>
        </template>
      </el-table-column>
      <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
      <el-table-column prop="ip" label="IP" width="120" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { auditApi } from '@/api'

interface LogRow {
  id: number
  username: string
  action: string
  entityType: string
  entityRef: string
  detail: string
  ip: string
  createdAt: string
}

const loading = ref(false)
const logs = ref<LogRow[]>([])
const actionFilter = ref('')
const keyword = ref('')

const ACTION_OPTIONS = [
  { value: 'LOGIN', label: '登录' },
  { value: 'LOGOUT', label: '登出' },
  { value: 'EXTRACT_SAVE', label: '保存解译' },
  { value: 'EXTRACT_SUBMIT', label: '提交解译' },
  { value: 'IMAGERY_UPLOAD', label: '上传影像' },
  { value: 'DELETE', label: '删除' },
  { value: 'UPDATE', label: '修改' }
]

const ACTION_LABEL: Record<string, string> = {
  LOGIN: '登录', LOGOUT: '登出',
  EXTRACT_SAVE: '保存解译', EXTRACT_SUBMIT: '提交解译',
  IMAGERY_UPLOAD: '上传影像', DELETE: '删除', UPDATE: '修改',
  REPORT_GENERATE: '生成报告', SHARE_CREATE: '创建分享'
}

const ENTITY_LABEL: Record<string, string> = {
  AUTH: '认证', EXTRACTION: '解译记录', IMAGERY: '影像',
  PROJECT: '工程', ROLE: '角色', ALARM: '告警', REPORT: '报告', SHARE: '分享'
}

function actionLabel(a: string) {
  return ACTION_LABEL[a] || a
}
function actionTagType(a: string): 'success' | 'warning' | 'danger' | 'info' {
  if (a === 'DELETE') return 'danger'
  if (a === 'LOGIN' || a === 'LOGOUT') return 'info'
  if (a.startsWith('EXTRACT') || a === 'IMAGERY_UPLOAD') return 'success'
  return 'warning'
}
function entityLabel(t: string) {
  return ENTITY_LABEL[t] || t || '-'
}

const filtered = computed(() =>
  logs.value.filter((l) => {
    if (actionFilter.value && l.action !== actionFilter.value) return false
    if (keyword.value) {
      const k = keyword.value.toLowerCase()
      return (l.username || '').toLowerCase().includes(k)
        || (l.detail || '').toLowerCase().includes(k)
        || (l.entityRef || '').toLowerCase().includes(k)
    }
    return true
  })
)

async function load() {
  loading.value = true
  try {
    logs.value = await auditApi.list(300)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head-right { display: flex; align-items: center; gap: 8px; }
.tip { margin-bottom: 12px; }
.ref { font-size: 12px; color: #4e5969; }
</style>

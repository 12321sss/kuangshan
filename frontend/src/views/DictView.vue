<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>数据字典</span>
        <div class="head-right">
          <el-radio-group v-model="category" size="small" @change="load">
            <el-radio-button value="CLASS_TYPE">地物类型</el-radio-button>
            <el-radio-button value="ALARM_LEVEL">告警级别</el-radio-button>
            <el-radio-button value="UNIT">单位</el-radio-button>
          </el-radio-group>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <el-alert type="info" :closable="false" class="tip">
      地物类型的中文名与颜色在这里统一维护，图层渲染与报告口径都读这里；改完立即对新渲染生效。
    </el-alert>

    <el-empty v-if="!loading && items.length === 0" description="暂无字典项" />

    <el-table v-else :data="items" stripe size="small">
      <el-table-column prop="code" label="编码" width="150" />
      <el-table-column label="中文名" min-width="180">
        <template #default="{ row }">
          <el-input v-if="row.editing" v-model="row.editLabel" size="small" />
          <span v-else>{{ row.label }}</span>
        </template>
      </el-table-column>
      <el-table-column label="颜色" width="130">
        <template #default="{ row }">
          <span v-if="row.color" class="color-cell">
            <span class="swatch" :style="{ background: row.color }"></span>
            <span class="code-text">{{ row.color }}</span>
          </span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="sortOrder" label="排序" width="80" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <template v-if="row.editing">
            <el-button size="small" type="primary" text @click="save(row)">保存</el-button>
            <el-button size="small" text @click="row.editing = false">取消</el-button>
          </template>
          <el-button v-else-if="canEdit" size="small" text type="primary" @click="startEdit(row)">编辑</el-button>
          <span v-else class="muted">只读</span>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { dictApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => ['ADMIN', 'MANAGER'].includes(auth.user?.role || ''))

interface DictRow {
  id: number
  category: string
  code: string
  label: string
  color?: string
  sortOrder: number
  editing?: boolean
  editLabel?: string
}

const loading = ref(false)
const category = ref('CLASS_TYPE')
const items = ref<DictRow[]>([])

async function load() {
  loading.value = true
  try {
    items.value = (await dictApi.list(category.value)).map((d) => ({ ...d, editing: false }))
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function startEdit(row: DictRow) {
  row.editLabel = row.label
  row.editing = true
}

async function save(row: DictRow) {
  try {
    await dictApi.update(row.id, { label: row.editLabel })
    row.label = row.editLabel || row.label
    row.editing = false
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head-right { display: flex; align-items: center; gap: 8px; }
.tip { margin-bottom: 12px; }
.color-cell { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.code-text { font-size: 12px; color: #86909c; }
.muted { color: #a9aeb8; font-size: 12px; }
</style>

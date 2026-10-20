<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>回收站</span>
        <div class="head-right">
          <span class="hint">已删除的解译记录会保留在这里，可随时还原</span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <el-empty v-if="!loading && rows.length === 0" description="回收站是空的（删除解译记录后会出现在这里）">
      <el-button type="primary" size="small" @click="$router.push('/remote-extract')">去遥感提取</el-button>
    </el-empty>

    <el-table v-else :data="rows" stripe size="small">
      <el-table-column prop="name" label="记录名称" min-width="200" show-overflow-tooltip />
      <el-table-column label="地物类型" width="110">
        <template #default="{ row }">{{ classLabel(row.classType) }}</template>
      </el-table-column>
      <el-table-column label="影像日期" width="110">
        <template #default="{ row }">{{ row.acquisitionDate || '-' }}</template>
      </el-table-column>
      <el-table-column label="面积(km²)" width="110">
        <template #default="{ row }">{{ ((row.extractAreaHa || 0) / 100).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column label="删除时间" width="160">
        <template #default="{ row }">{{ fmt(row.deletedAt) }}</template>
      </el-table-column>
      <el-table-column prop="deletedBy" label="删除人" width="110" />
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="onRestore(row)">还原</el-button>
          <el-popconfirm title="彻底删除后不可恢复，确认？" @confirm="onPurge(row)">
            <template #reference>
              <el-button size="small" text type="danger">彻底删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { extractionApi } from '@/api'
import { useProjectStore } from '@/stores/project'
import type { Extraction } from '@/api/types'

const projectStore = useProjectStore()
const loading = ref(false)
const rows = ref<Extraction[]>([])

const CLASS_LABEL: Record<string, string> = {
  PIT: '采坑', DUMP: '排土场', TAILINGS: '尾矿库', BARE: '裸地扰动',
  VEGETATION: '植被', WATER: '水体', ROAD: '道路设施', BUILDING: '建筑', MOUNTAIN: '山体'
}
function classLabel(c: string) { return CLASS_LABEL[c] || c }
function fmt(t?: string) { return t ? t.replace('T', ' ').slice(0, 16) : '-' }

async function load() {
  loading.value = true
  try {
    rows.value = await extractionApi.trash(projectStore.currentId ?? undefined)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function onRestore(row: Extraction) {
  try {
    await extractionApi.restore(row.id)
    ElMessage.success('已还原')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function onPurge(row: Extraction) {
  try {
    await extractionApi.purge(row.id)
    ElMessage.success('已彻底删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
watch(() => projectStore.currentId, load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.head-right { display: flex; align-items: center; gap: 10px; }
.hint { font-size: 12px; color: #a9aeb8; }
</style>

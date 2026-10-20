<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>预警阈值设置</span>
        <span class="hint">按传感器类型配置三级告警阈值；规则命中后自动生成告警记录并推送大屏</span>
      </div>
    </template>
    <el-table :data="rules" stripe>
      <el-table-column prop="sensorTypeName" label="传感器类型" width="140" />
      <el-table-column prop="indicator" label="监测指标" width="140" />
      <el-table-column prop="unit" label="单位" width="80" />
      <el-table-column label="黄色预警" width="120">
        <template #default="{ row }">
          <el-tag color="#fef9c3" style="color:#a16207;border:none">≥ {{ row.yellowThreshold }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="橙色预警" width="120">
        <template #default="{ row }">
          <el-tag color="#ffedd5" style="color:#c2410c;border:none">≥ {{ row.orangeThreshold }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="红色预警" width="120">
        <template #default="{ row }">
          <el-tag color="#fee2e2" style="color:#b91c1c;border:none">≥ {{ row.redThreshold }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" :disabled="!canEdit" @change="(v: boolean) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button v-if="canEdit" size="small" text type="primary" @click="onEdit(row)">编辑</el-button>
          <span v-else class="no-perm">只读</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="`编辑规则 · ${editing?.sensorTypeName || ''}`" width="440px">
      <el-form v-if="editing" label-width="110px">
        <el-form-item label="监测指标">
          <el-input v-model="editing.indicator" />
        </el-form-item>
        <el-form-item label="黄色阈值">
          <el-input-number v-model="editing.yellowThreshold" :precision="1" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="橙色阈值">
          <el-input-number v-model="editing.orangeThreshold" :precision="1" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="红色阈值">
          <el-input-number v-model="editing.redThreshold" :precision="1" :step="1" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { warningApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { WarningRule } from '@/api/types'

const auth = useAuthStore()
// 规则编辑仅 管理员/项目管理员（后端同样拦截，前端只是不亮按钮）
const canEdit = computed(() => ['ADMIN', 'MANAGER'].includes(auth.user?.role || ''))

const loading = ref(true)
const saving = ref(false)
const rules = ref<WarningRule[]>([])
const dialogVisible = ref(false)
const editing = ref<WarningRule | null>(null)

async function load() {
  loading.value = true
  try {
    rules.value = await warningApi.list()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onEdit(row: WarningRule) {
  editing.value = { ...row }
  dialogVisible.value = true
}

async function onSave() {
  if (!editing.value) return
  saving.value = true
  try {
    await warningApi.update(editing.value)
    ElMessage.success('规则已保存')
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function onToggle(row: WarningRule, enabled: boolean) {
  try {
    await warningApi.update({ ...row, enabled })
    ElMessage.success(enabled ? '规则已启用' : '规则已停用')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: baseline; gap: 12px; }
.hint { font-size: 12px; color: #a9aeb8; font-weight: 400; }
.no-perm { font-size: 12px; color: #c9cdd4; }
</style>

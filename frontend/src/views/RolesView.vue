<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>角色管理</span>
        <el-button v-if="auth.hasAction('action:role-manage')" type="primary" :icon="Plus" @click="onCreate">新增角色</el-button>
      </div>
    </template>
    <el-table :data="roles" stripe>
      <el-table-column prop="code" label="编码" width="120" />
      <el-table-column prop="name" label="角色名" width="140" />
      <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
      <el-table-column label="页面权限" width="120">
        <template #default="{ row }">{{ row.pagePerms.length }} 项</template>
      </el-table-column>
      <el-table-column label="操作权限" width="120">
        <template #default="{ row }">{{ row.actionPerms.length }} 项</template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="row.builtin ? 'info' : 'success'" size="small" effect="plain">{{ row.builtin ? '内置' : '自定义' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.hasAction('action:role-manage')" label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" :disabled="row.code === 'ADMIN'" @click="onEdit(row)">编辑权限</el-button>
          <el-popconfirm v-if="!row.builtin" title="确定删除该角色？" @confirm="onDelete(row)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 角色编辑对话框：权限勾选矩阵 -->
    <el-dialog v-model="dialogVisible" :title="isCreate ? '新增角色' : `编辑角色 · ${editing?.name}`" width="620px">
      <el-form v-if="editing" label-width="90px">
        <el-form-item label="角色编码" required>
          <el-input v-model="editing.code" :disabled="!isCreate" placeholder="大写字母/下划线，如 SAFETY_OFFICER" />
        </el-form-item>
        <el-form-item label="角色名" required>
          <el-input v-model="editing.name" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editing.description" />
        </el-form-item>
        <el-form-item label="页面权限">
          <div class="perm-box">
            <div class="perm-head">
              <el-checkbox :model-value="allPagesChecked" @change="toggleAllPages">全选</el-checkbox>
            </div>
            <el-checkbox-group v-model="editing.pagePerms">
              <el-checkbox v-for="p in catalog?.pages || []" :key="p.code" :value="p.code" class="perm-item">
                {{ p.name }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </el-form-item>
        <el-form-item label="操作权限">
          <div class="perm-box">
            <div class="perm-head">
              <el-checkbox :model-value="allActionsChecked" @change="toggleAllActions">全选</el-checkbox>
            </div>
            <el-checkbox-group v-model="editing.actionPerms">
              <el-checkbox v-for="a in catalog?.actions || []" :key="a.code" :value="a.code" class="perm-item">
                {{ a.name }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
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
import { Plus } from '@element-plus/icons-vue'
import { roleApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { PermCatalog, Role } from '@/api/types'

const auth = useAuthStore()

const loading = ref(true)
const saving = ref(false)
const roles = ref<Role[]>([])
const catalog = ref<PermCatalog | null>(null)
const dialogVisible = ref(false)
const isCreate = ref(false)
const editing = ref<{
  code: string; name: string; description: string; pagePerms: string[]; actionPerms: string[]
} | null>(null)

const allPagesChecked = computed(() =>
  !!catalog.value && editing.value?.pagePerms.length === catalog.value.pages.length
)
const allActionsChecked = computed(() =>
  !!catalog.value && editing.value?.actionPerms.length === catalog.value.actions.length
)

function toggleAllPages(v: boolean) {
  if (editing.value && catalog.value) {
    editing.value.pagePerms = v ? catalog.value.pages.map((p) => p.code) : []
  }
}
function toggleAllActions(v: boolean) {
  if (editing.value && catalog.value) {
    editing.value.actionPerms = v ? catalog.value.actions.map((a) => a.code) : []
  }
}

async function load() {
  loading.value = true
  try {
    ;[roles.value, catalog.value] = await Promise.all([roleApi.list(), roleApi.catalog()])
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onCreate() {
  isCreate.value = true
  editing.value = { code: '', name: '', description: '', pagePerms: ['page:dashboard'], actionPerms: [] }
  dialogVisible.value = true
}

function onEdit(row: Role) {
  isCreate.value = false
  editing.value = {
    code: row.code, name: row.name, description: row.description,
    pagePerms: [...row.pagePerms], actionPerms: [...row.actionPerms]
  }
  dialogVisible.value = true
}

async function onSave() {
  const e = editing.value
  if (!e?.code || !e.name) {
    ElMessage.warning('角色编码和名称不能为空')
    return
  }
  saving.value = true
  try {
    if (isCreate.value) {
      await roleApi.create(e)
    } else {
      await roleApi.update(e.code, e)
    }
    ElMessage.success('已保存（绑定该角色的用户下次操作即生效）')
    dialogVisible.value = false
    await load()
  } catch (err: any) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: Role) {
  try {
    await roleApi.remove(row.code)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }

.perm-box {
  width: 100%;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  padding: 4px 12px 10px;
  max-height: 180px;
  overflow-y: auto;
}

.perm-head { border-bottom: 1px dashed #eceef2; margin-bottom: 4px; }
.perm-item { width: 46%; margin-right: 0; }
</style>

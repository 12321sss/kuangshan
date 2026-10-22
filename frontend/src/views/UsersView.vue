<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>用户中心</span>
        <el-button v-if="auth.hasAction('action:user-manage')" type="primary" :icon="Plus" @click="onCreate">新增用户</el-button>
      </div>
    </template>
    <el-table :data="users" stripe>
      <el-table-column prop="username" label="用户名" width="130" />
      <el-table-column prop="displayName" label="姓名" width="130" />
      <el-table-column label="角色" width="150">
        <template #default="{ row }">
          <el-tag :type="roleTag(row.role)" size="small">{{ roleName(row.role) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机号" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ENABLED' ? 'success' : 'danger'" size="small" effect="plain">
            {{ row.status === 'ENABLED' ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.hasAction('action:user-manage')" label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="onEdit(row)">编辑</el-button>
          <el-popconfirm v-if="row.username !== 'admin'" title="确定删除该用户？" @confirm="onDelete(row)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑用户对话框 -->
    <el-dialog v-model="dialogVisible" :title="isCreate ? '新增用户' : `编辑用户 · ${editing?.username}`" width="460px">
      <el-form v-if="editing" label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="editing.username" :disabled="!isCreate"
                    placeholder="登录账号，建议英文/数字，如 yanshi" />
          <div class="field-hint">登录时输入的就是这个；创建后不可修改</div>
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="editing.displayName" placeholder="界面上显示的名字，可用中文，如 演示账号" />
          <div class="field-hint">只用于界面显示，不参与登录</div>
        </el-form-item>
        <el-form-item :label="isCreate ? '初始密码' : '重置密码'" :required="isCreate">
          <el-input v-model="editing.password" type="password" show-password
                    :placeholder="isCreate ? '必填' : '留空表示不修改'" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="editing.phone" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="editing.role" style="width: 100%">
            <el-option v-for="r in roles" :key="r.code" :value="r.code" :label="`${r.name}（${r.code}）`" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!isCreate" label="状态">
          <el-radio-group v-model="editing.status">
            <el-radio-button value="ENABLED">启用</el-radio-button>
            <el-radio-button value="DISABLED">禁用</el-radio-button>
          </el-radio-group>
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
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { roleApi, userApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { AdminUser, Role } from '@/api/types'

const auth = useAuthStore()

const loading = ref(true)
const saving = ref(false)
const users = ref<AdminUser[]>([])
const roles = ref<Role[]>([])
const dialogVisible = ref(false)
const isCreate = ref(true)
const editing = ref<{
  username: string; displayName: string; password: string; phone: string; role: string; status: string
} | null>(null)

function roleTag(role: string) {
  return { ADMIN: 'danger', MANAGER: 'warning', ANALYST: 'primary', VIEWER: 'info' }[role] as any || 'info'
}
function roleName(code: string) {
  return roles.value.find((r) => r.code === code)?.name || code
}

async function load() {
  loading.value = true
  try {
    ;[users.value, roles.value] = await Promise.all([userApi.list(), roleApi.list()])
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onCreate() {
  isCreate.value = true
  editing.value = { username: '', displayName: '', password: '', phone: '', role: 'VIEWER', status: 'ENABLED' }
  dialogVisible.value = true
}

function onEdit(row: AdminUser) {
  isCreate.value = false
  editing.value = { username: row.username, displayName: row.displayName, password: '', phone: row.phone, role: row.role, status: row.status }
  dialogVisible.value = true
}

async function onSave() {
  const e = editing.value
  if (!e?.username || !e.displayName || !e.role) {
    ElMessage.warning('用户名、姓名、角色不能为空')
    return
  }
  if (isCreate.value && !e.password) {
    ElMessage.warning('初始密码不能为空')
    return
  }
  // 用户名是登录凭据，限制为英文/数字/下划线/点/中划线。
  // 之前允许中文，出现过把「用户名」和「姓名」填反、结果登录不上（用户名成了中文、登录输英文）的情况。
  if (isCreate.value && !/^[A-Za-z0-9_.-]{2,32}$/.test(e.username)) {
    ElMessage.warning('用户名只能用英文、数字、下划线、点或中划线，2~32 位（如 yanshi）')
    return
  }
  // 用户名是登录凭据，限制为英文/数字/下划线/点/中划线。
  // 之前允许中文，出现过把「用户名」和「姓名」填反、结果登录不上（用户名成了中文、登录输英文）的情况。
  if (isCreate.value && !/^[A-Za-z0-9_.-]{2,32}$/.test(e.username)) {
    ElMessage.warning('用户名只能用英文、数字、下划线、点或中划线，2~32 位（如 yanshi）')
    return
  }
  saving.value = true
  try {
    if (isCreate.value) {
      await userApi.create({ username: e.username, displayName: e.displayName, password: e.password, phone: e.phone, role: e.role })
    } else {
      await userApi.update(e.username, { displayName: e.displayName, phone: e.phone, role: e.role, status: e.status, newPassword: e.password || undefined })
    }
    if (isCreate.value) {
      ElMessage.success(`用户已创建，登录账号是「${e.username}」（不是姓名「${e.displayName}」）`)
    } else {
      if (isCreate.value) {
      ElMessage.success(`用户已创建，登录账号是「${e.username}」（不是姓名「${e.displayName}」）`)
    } else {
      ElMessage.success('已保存（角色/状态变更对方下次操作即生效）')
    }
    }
    dialogVisible.value = false
    await load()
  } catch (err: any) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: AdminUser) {
  try {
    await userApi.remove(row.username)
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
.field-hint { font-size: 11px; color: #a9aeb8; line-height: 1.5; margin-top: 2px; }
</style>

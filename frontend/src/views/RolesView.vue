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
      <!-- 可见项目：让管理员一眼看清该角色能看哪些矿区，不用点进编辑才发现没配 -->
      <el-table-column label="可见项目" width="140">
        <template #default="{ row }">
          <el-tag v-if="row.projectScope === 'ALL'" type="success" size="small" effect="plain">全部</el-tag>
          <el-tag v-else-if="row.projectScope === 'SPECIFIC'" type="primary" size="small" effect="plain">
            {{ (row.projectIds || []).length }} 个
          </el-tag>
          <el-tag v-else type="danger" size="small" effect="plain">未配置</el-tag>
        </template>
      </el-table-column>
      <!-- 可见项目：让管理员一眼看清该角色能看哪些矿区，不用点进编辑才发现没配 -->
      <el-table-column label="可见项目" width="140">
        <template #default="{ row }">
          <el-tag v-if="row.projectScope === 'ALL'" type="success" size="small" effect="plain">全部</el-tag>
          <el-tag v-else-if="row.projectScope === 'SPECIFIC'" type="primary" size="small" effect="plain">
            {{ (row.projectIds || []).length }} 个
          </el-tag>
          <el-tag v-else type="danger" size="small" effect="plain">未配置</el-tag>
        </template>
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
        <!-- 页面权限：按业务分组展示，组级可一键全选，避免长列表看不清有哪些 -->
        <el-form-item label="页面权限">
          <div class="perm-box">
            <div class="perm-head">
              <el-checkbox :model-value="allPagesChecked" @change="toggleAllPages">全选</el-checkbox>
              <span class="perm-count">已选 {{ editing.pagePerms.length }} / {{ catalog?.pages.length || 0 }}</span>
            </div>
            <el-checkbox-group v-model="editing.pagePerms">
              <div v-for="g in pageGroups" :key="g.name" class="perm-group">
                <div class="perm-group-head">
                  <el-checkbox
                    :model-value="isGroupAll('page', g)"
                    :indeterminate="isGroupSome('page', g)"
                    @change="(v: any) => toggleGroup('page', g, v)"
                  >{{ g.name }}</el-checkbox>
                </div>
                <div class="perm-group-items">
                  <el-checkbox v-for="p in g.items" :key="p.code" :value="p.code" class="perm-item">
                    {{ p.name }}
                  </el-checkbox>
                </div>
              </div>
            </el-checkbox-group>
          </div>
        </el-form-item>

        <!-- 操作权限：同样分组 -->
        <el-form-item label="操作权限">
          <div class="perm-box">
            <div class="perm-head">
              <el-checkbox :model-value="allActionsChecked" @change="toggleAllActions">全选</el-checkbox>
              <span class="perm-count">已选 {{ editing.actionPerms.length }} / {{ catalog?.actions.length || 0 }}</span>
            </div>
            <el-checkbox-group v-model="editing.actionPerms">
              <div v-for="g in actionGroups" :key="g.name" class="perm-group">
                <div class="perm-group-head">
                  <el-checkbox
                    :model-value="isGroupAll('action', g)"
                    :indeterminate="isGroupSome('action', g)"
                    @change="(v: any) => toggleGroup('action', g, v)"
                  >{{ g.name }}</el-checkbox>
                </div>
                <div class="perm-group-items">
                  <el-checkbox v-for="a in g.items" :key="a.code" :value="a.code" class="perm-item">
                    {{ a.name }}
                  </el-checkbox>
                </div>
              </div>
            </el-checkbox-group>
          </div>
        </el-form-item>

        <!-- 项目可见范围：解决「新建角色的用户登录后一个项目都看不到」的问题 -->
        <el-form-item label="可见项目">
          <div class="perm-box scope-box">
            <el-radio-group v-model="scopeMode">
              <el-radio value="ALL">全部项目</el-radio>
              <el-radio value="SPECIFIC">指定项目</el-radio>
              <el-radio value="NONE">仅按个人成员</el-radio>
            </el-radio-group>
            <div v-if="scopeMode === 'SPECIFIC'" class="scope-project-list">
              <el-checkbox-group v-model="editing.projectIds">
                <el-checkbox v-for="p in projects" :key="p.id" :value="String(p.id)" class="perm-item">
                  {{ p.name }}
                </el-checkbox>
              </el-checkbox-group>
              <div v-if="!projects.length" class="scope-empty">还没有项目，请先到「项目管理」新建</div>
            </div>
            <div class="scope-tip">
              {{ scopeTip }}
            </div>
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
import { roleApi, projectApi } from '@/api'
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
  projectScope: 'ALL' | 'SPECIFIC' | 'NONE'; projectIds: string[]
} | null>(null)

/** 项目清单：供「可见项目」勾选 */
const projects = ref<{ id: number; name: string }[]>([])
const scopeMode = computed({
  // radio-group 要 v-model 绑定，必须是可写 computed
  get: () => editing.value?.projectScope || 'NONE',
  set: (v: 'ALL' | 'SPECIFIC' | 'NONE') => {
    if (!editing.value) return
    editing.value.projectScope = v
    if (v !== 'SPECIFIC') editing.value.projectIds = []
  }
})
const scopeTip = computed(() => {
  if (scopeMode.value === 'ALL') return '该角色下所有用户都能看到全部项目（相当于管理员级数据权限）'
  if (scopeMode.value === 'SPECIFIC') {
    const n = editing.value?.projectIds?.length || 0
    return n ? `该角色下所有用户可看到勾选的 ${n} 个项目；个人成员关系仍可额外补充` : '请至少勾选一个项目，否则该角色看不到任何项目'
  }
  return '不预设项目，用户必须被加入「项目管理 → 成员」才能看到对应项目'
})



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
/** 把权限点按 group 字段折叠成分组列表，保持后端给的顺序 */
interface PermGroup { name: string; items: { code: string; name: string; group?: string }[] }
function groupPerms(list: { code: string; name: string; group?: string }[] | undefined): PermGroup[] {
  const map = new Map<string, { code: string; name: string; group?: string }[]>()
  for (const it of list || []) {
    const g = it.group || '其他'
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push(it)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
}
const pageGroups = computed(() => groupPerms(catalog.value?.pages))
const actionGroups = computed(() => groupPerms(catalog.value?.actions))

function currentList(kind: 'page' | 'action'): string[] {
  if (!editing.value) return []
  return kind === 'page' ? editing.value.pagePerms : editing.value.actionPerms
}
function setCurrentList(kind: 'page' | 'action', v: string[]) {
  if (!editing.value) return
  if (kind === 'page') editing.value.pagePerms = v
  else editing.value.actionPerms = v
}
function isGroupAll(kind: 'page' | 'action', g: PermGroup): boolean {
  const cur = currentList(kind)
  return g.items.length > 0 && g.items.every((i) => cur.includes(i.code))
}
function isGroupSome(kind: 'page' | 'action', g: PermGroup): boolean {
  const cur = currentList(kind)
  const hit = g.items.filter((i) => cur.includes(i.code)).length
  return hit > 0 && hit < g.items.length
}
/** 组级勾选：全选本组 / 清空本组，不影响其它组 */
function toggleGroup(kind: 'page' | 'action', g: PermGroup, checked: boolean) {
  const cur = new Set(currentList(kind))
  for (const i of g.items) {
    if (checked) cur.add(i.code)
    else cur.delete(i.code)
  }
  setCurrentList(kind, [...cur])
}

function toggleAllActions(v: boolean) {
  if (editing.value && catalog.value) {
    editing.value.actionPerms = v ? catalog.value.actions.map((a) => a.code) : []
  }
}

async function load() {
  loading.value = true
  try {
    const [r, c, ps] = await Promise.all([
      roleApi.list(),
      roleApi.catalog(),
      projectApi.list().catch(() => [])
    ])
    roles.value = r
    catalog.value = c
    projects.value = (ps || []).map((p: any) => ({ id: p.id, name: p.name }))
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onCreate() {
  isCreate.value = true
  editing.value = {
    code: '', name: '', description: '',
    pagePerms: ['page:dashboard'], actionPerms: [],
    projectScope: 'SPECIFIC', projectIds: []
  }
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
  // 指定项目但一个都没勾，等于该角色看不到任何项目——提前拦下，避免保存后才发现
  if (e.projectScope === 'SPECIFIC' && !(e.projectIds || []).length) {
    ElMessage.warning('「可见项目」选了「指定项目」但一个都没勾，请至少选一个')
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
.perm-count { margin-left: auto; font-size: 12px; color: #86909c; }
.perm-group { margin-bottom: 10px; }
.perm-group-head {
  font-size: 12px; font-weight: 600; color: #4e5969;
  padding: 4px 0 2px; border-bottom: 1px dashed #eceef2; margin-bottom: 4px;
}
.perm-group-items { display: flex; flex-wrap: wrap; gap: 2px 12px; padding-left: 6px; }
.scope-box { display: flex; flex-direction: column; gap: 8px; }
.scope-project-list {
  padding: 6px 8px; border: 1px dashed #d9e0ea; border-radius: 6px;
  display: flex; flex-wrap: wrap; gap: 2px 12px;
}
.scope-empty { font-size: 12px; color: #a9aeb8; }
.scope-tip { font-size: 11px; color: #86909c; line-height: 1.5; }
</style>

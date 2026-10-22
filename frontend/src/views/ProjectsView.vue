<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>矿区项目</span>
        <div class="head-actions">
          <el-input v-model="keyword" placeholder="搜索项目名称" size="small" clearable style="width: 200px" :prefix-icon="Search" />
          <el-button v-if="auth.hasAction('action:project-manage')" type="primary" :icon="Plus" @click="onCreate">新增项目</el-button>
        </div>
      </div>
    </template>
    <el-table :data="filtered" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="项目名称" min-width="200" />
      <el-table-column prop="region" label="区域" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="成员" width="150">
        <template #default="{ row }">
          <el-tag v-for="m in row.members.slice(0, 3)" :key="m" size="small" effect="plain" style="margin-right:4px">{{ m }}</el-tag>
          <span v-if="row.members.length > 3" class="more">+{{ row.members.length - 3 }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="manager" label="负责人" width="100" />
      <el-table-column prop="description" label="说明" min-width="200" show-overflow-tooltip />
      <el-table-column v-if="auth.hasAction('action:project-manage')" label="操作" width="270" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="onEdit(row)">编辑</el-button>
          <el-button size="small" text type="primary" @click="onMembers(row)">成员</el-button>
          <el-button size="small" text type="warning" @click="onShare(row)">分享</el-button>
          <el-popconfirm title="确定删除该项目？" @confirm="onDelete(row)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分享链接弹窗 -->
    <el-dialog v-model="shareVisible" title="生成访客分享链接" width="520px">
      <div class="share-tip">
        生成一个只读链接，可发给未登录的领导或合作方查看本项目数据。
        链接默认 7 天有效，可在下方撤销。
      </div>
      <div v-if="shareResult" class="share-box">
        <el-input :model-value="shareUrl" readonly>
          <template #append>
            <el-button @click="copyShareUrl">复制</el-button>
          </template>
        </el-input>
        <div class="share-meta">有效期至 {{ (shareResult.expiresAt || '').replace('T', ' ').slice(0, 16) }}</div>
        <div class="share-actions">
          <el-button size="small" type="primary" @click="openSharePage">预览只读页</el-button>
        </div>
      </div>
      <div v-else class="share-empty">
        <el-button type="primary" :loading="shareLoading" @click="createShare">生成链接</el-button>
      </div>
      <el-divider v-if="shareList.length > 0" />
      <div v-if="shareList.length > 0">
        <div class="share-list-title">已有链接</div>
        <div v-for="s in shareList" :key="s.id" class="share-row">
          <span class="sr-token">{{ s.token.slice(0, 10) }}…</span>
          <span class="sr-time">{{ (s.createdAt || '').replace('T', ' ').slice(0, 16) }}</span>
          <el-tag size="small" :type="s.revoked ? 'info' : 'success'">{{ s.revoked ? '已撤销' : '有效' }}</el-tag>
          <el-button v-if="!s.revoked" size="small" text type="danger" @click="revokeShare(s)">撤销</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 新增/编辑对话框：按「基本信息 / 矿权与开采 / 对接与坐标」分组 -->
    <el-dialog v-model="dialogVisible" :title="editing?.id ? '编辑项目' : '新建矿区项目'"
               width="620px" top="6vh">
      <div v-if="!editing?.id" class="proj-tip">
        项目是所有数据的归属单元：影像、边界、解译结果、安全评估都挂在项目下，
        只有项目成员可见。新建后会自动切换到该项目。
      </div>
      <el-form v-if="editing" label-width="96px" size="default">
        <!-- ---------- 基本信息 ---------- -->
        <div class="form-block-title">基本信息</div>
        <el-form-item label="项目名称" required>
          <el-input v-model="editing.name" placeholder="如：宁都河源锂矿遥感监测" />
        </el-form-item>
        <el-form-item label="所在区域">
          <el-input v-model="editing.region" placeholder="如：江西省赣州市宁都县" />
        </el-form-item>
        <el-form-item label="项目状态">
          <el-select v-model="editing.status" style="width: 100%">
            <el-option value="RUNNING" label="进行中" />
            <el-option value="PLANNING" label="规划中" />
            <el-option value="ARCHIVED" label="已归档" />
          </el-select>
        </el-form-item>

        <!-- ---------- 矿权与开采 ---------- -->
        <div class="form-block-title">矿权与开采</div>
        <el-form-item label="矿种">
          <el-select v-model="editing.mineralType" style="width: 100%" filterable allow-create
                     placeholder="选择或输入矿种">
            <el-option value="锂矿" label="锂矿" />
            <el-option value="铁矿" label="铁矿" />
            <el-option value="铜矿" label="铜矿" />
            <el-option value="石灰岩" label="石灰岩" />
            <el-option value="煤矿" label="煤矿" />
          </el-select>
        </el-form-item>
        <el-form-item label="采矿许可证">
          <el-input v-model="editing.licenseNo" placeholder="许可证号，报告合规章节会引用" />
        </el-form-item>
        <el-form-item label="矿权面积">
          <el-input-number v-model="editing.licenseAreaKm2" :min="0" :precision="2" :step="0.1"
                           style="width: 180px" />
          <span class="unit">km²（越界分析的对比基准）</span>
        </el-form-item>
        <el-form-item label="开采方式">
          <el-radio-group v-model="editing.miningMethod">
            <el-radio-button value="露天">露天</el-radio-button>
            <el-radio-button value="井下">井下</el-radio-button>
            <el-radio-button value="联合">联合</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- ---------- 对接与坐标 ---------- -->
        <div class="form-block-title">对接与坐标</div>
        <el-form-item label="内部负责人">
          <el-input v-model="editing.manager" placeholder="我方项目经理" />
        </el-form-item>
        <el-form-item label="客户对接人">
          <el-input v-model="editing.contactPerson" placeholder="客户方联系人" />
        </el-form-item>
        <el-form-item label="联系方式">
          <el-input v-model="editing.contactPhone" placeholder="电话 / 邮箱" />
        </el-form-item>
        <el-form-item label="矿区中心点">
          <div class="coord-row">
            <el-input-number v-model="editing.centerLng" :precision="6" :controls="false"
                             placeholder="经度" style="width: 140px" />
            <el-input-number v-model="editing.centerLat" :precision="6" :controls="false"
                             placeholder="纬度" style="width: 140px" />
            <el-button size="small" text type="primary" @click="fillCenterFromBoundary">
              从边界取中心
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="坐标系">
          <el-select v-model="editing.crs" style="width: 100%" filterable allow-create
                     placeholder="成果与影像采用的坐标系">
            <el-option value="EPSG:4326" label="EPSG:4326（WGS84 经纬度）" />
            <el-option value="EPSG:4490" label="EPSG:4490（CGCS2000）" />
            <el-option value="EPSG:4547" label="EPSG:4547（CGCS2000 3度带 114E）" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目说明">
          <el-input v-model="editing.description" type="textarea" :rows="2"
                    placeholder="监测目标、交付范围等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成员分配对话框 -->
    <el-dialog v-model="memberVisible" :title="`成员分配 · ${memberProject?.name || ''}`" width="420px">
      <el-checkbox-group v-model="memberSelection">
        <div v-for="u in userOptions" :key="u.username" class="member-row">
          <el-checkbox :value="u.username">{{ u.displayName }}（{{ u.username }}）</el-checkbox>
        </div>
      </el-checkbox-group>
      <div class="member-hint">管理员可见全部项目，无需分配</div>
      <template #footer>
        <el-button @click="memberVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSaveMembers">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { projectApi, shareApi, userApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/api/types'

const auth = useAuthStore()
const projectStore = useProjectStore()

const loading = ref(true)
const saving = ref(false)

// ---- 访客分享链接 ----
const shareVisible = ref(false)
const shareLoading = ref(false)
const shareProject = ref<Project | null>(null)
const shareResult = ref<Awaited<ReturnType<typeof shareApi.create>> | null>(null)
const shareList = ref<Awaited<ReturnType<typeof shareApi.list>>>([])
const shareUrl = computed(() =>
  shareResult.value ? `${window.location.origin}${shareResult.value.path}` : ''
)

function onShare(row: Project) {
  shareProject.value = row
  shareResult.value = null
  shareList.value = []
  shareVisible.value = true
  loadShareList()
}

async function loadShareList() {
  if (!shareProject.value) return
  try {
    shareList.value = await shareApi.list(shareProject.value.id)
  } catch {
    shareList.value = []
  }
}

async function createShare() {
  if (!shareProject.value) return
  shareLoading.value = true
  try {
    shareResult.value = await shareApi.create(shareProject.value.id, 7)
    ElMessage.success('分享链接已生成')
    await loadShareList()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    shareLoading.value = false
  }
}

async function copyShareUrl() {
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    ElMessage.success('链接已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

function openSharePage() {
  if (!shareResult.value) return
  window.open(shareResult.value.path, '_blank')
}

async function revokeShare(s: { id: number }) {
  try {
    await shareApi.revoke(s.id)
    ElMessage.success('已撤销该链接')
    await loadShareList()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
const keyword = ref('')
const dialogVisible = ref(false)
const memberVisible = ref(false)
const editing = ref<Partial<Project> | null>(null)
const memberProject = ref<Project | null>(null)
const memberSelection = ref<string[]>([])
const userOptions = ref<{ username: string; displayName: string }[]>([])

const filtered = computed(() =>
  keyword.value
    ? projectStore.projects.filter((p) => p.name.includes(keyword.value))
    : projectStore.projects
)

function statusTag(s: Project['status']) {
  return { RUNNING: 'success', PLANNING: 'warning', ARCHIVED: 'info' }[s] as any
}
function statusLabel(s: Project['status']) {
  return { RUNNING: '进行中', PLANNING: '规划中', ARCHIVED: '已归档' }[s]
}

async function load() {
  loading.value = true
  try {
    await projectStore.load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onCreate() {
  editing.value = {
    name: '',
    region: '',
    status: 'PLANNING',
    manager: auth.user?.displayName || '',
    description: '',
    // 矿山业务档案初始值：留空由用户填，不预填假数据
    mineralType: '锂矿',
    licenseNo: '',
    licenseAreaKm2: undefined,
    miningMethod: '露天',
    centerLng: undefined,
    centerLat: undefined,
    contactPerson: '',
    contactPhone: '',
    crs: 'EPSG:4326'
  }
  dialogVisible.value = true
}

/** 从项目边界（GeoJSON）取几何中心，省得手填经纬度 */
async function fillCenterFromBoundary() {
  const id = editing.value?.id
  if (!id) {
    ElMessage.info('新项目还没有边界，请保存后到「边界管理」导入，再回来取中心')
    return
  }
  try {
    const raw = await projectApi.boundary(id)
    const j = typeof raw === 'string' ? JSON.parse(raw) : raw
    const ring = j?.mining || j?.disturbance || j?.ecological
    if (!Array.isArray(ring) || ring.length < 3) {
      ElMessage.warning('该项目还没有可用的边界，请先到「边界管理」导入')
      return
    }
    let sx = 0, sy = 0
    for (const p of ring) { sx += p[0]; sy += p[1] }
    editing.value!.centerLng = Number((sx / ring.length).toFixed(6))
    editing.value!.centerLat = Number((sy / ring.length).toFixed(6))
    ElMessage.success('已按边界中心填入坐标')
  } catch (e: any) {
    ElMessage.error('读取边界失败：' + (e?.message || e))
  }
}

function onEdit(row: Project) {
  editing.value = { ...row }
  dialogVisible.value = true
}

async function onSave() {
  if (!editing.value?.name) {
    ElMessage.warning('项目名称不能为空')
    return
  }
  saving.value = true
  try {
    if (editing.value.id) {
      await projectApi.update(editing.value.id, editing.value)
      ElMessage.success('已保存')
    } else {
      const created: any = await projectApi.create(editing.value)
      ElMessage.success('项目已创建，已切换为当前项目')
      // 新建后立刻切到该项目：避免用户建完还在旧项目里操作，导致数据挂错项目
      if (created?.id) {
        projectStore.set(created.id)
      }
    }
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function onDelete(row: Project) {
  try {
    await projectApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function onMembers(row: Project) {
  memberProject.value = row
  memberSelection.value = [...row.members]
  if (userOptions.value.length === 0) {
    userOptions.value = await userApi.options()
  }
  memberVisible.value = true
}

async function onSaveMembers() {
  if (!memberProject.value) return
  saving.value = true
  try {
    await projectApi.setMembers(memberProject.value.id, memberSelection.value)
    ElMessage.success('成员已更新')
    memberVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head-actions { display: flex; gap: 10px; align-items: center; }
.more { font-size: 12px; color: #a9aeb8; }
.member-row { padding: 4px 0; }
.member-hint { margin-top: 12px; font-size: 12px; color: #a9aeb8; }

/* ---- 分享链接弹窗 ---- */
.share-tip { font-size: 12px; color: #86909c; line-height: 1.6; margin-bottom: 12px; }
.share-box { margin-bottom: 8px; }
.share-meta { font-size: 12px; color: #a9aeb8; margin-top: 6px; }
.share-actions { margin-top: 10px; }
.share-empty { text-align: center; padding: 12px 0; }
.share-list-title { font-size: 12px; font-weight: 600; color: #4e5969; margin-bottom: 8px; }
.share-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 12px; }
.sr-token { font-family: monospace; color: #1f2329; width: 100px; }
.sr-time { color: #86909c; flex: 1; }
.proj-tip {
  background: #f0f7ff; border-left: 3px solid #1677ff;
  padding: 8px 12px; border-radius: 4px; font-size: 12px;
  color: #4e5969; line-height: 1.6; margin-bottom: 14px;
}
.form-block-title {
  font-size: 13px; font-weight: 600; color: #1f2329;
  margin: 14px 0 10px; padding-left: 8px;
  border-left: 3px solid #1677ff;
}
.form-block-title:first-of-type { margin-top: 0; }
.unit { font-size: 12px; color: #86909c; margin-left: 8px; }
.coord-row { display: flex; align-items: center; gap: 8px; }
</style>

<template>
  <div class="boundary-page">
    <!-- 顶部：边界用途说明 + 越界检测基准状态 -->
    <el-alert
      v-if="summary"
      :type="summary.encroachReady ? 'success' : 'warning'"
      :closable="false"
      show-icon
      class="top-alert"
    >
      <template #title>
        {{ summary.hint }}
      </template>
      <div class="alert-sub">
        矿权范围 {{ summary.permit }} 条（合计 {{ summary.permitAreaHa }} ha）·
        扰动边界 {{ summary.disturbance }} 条 · 生态缓冲区 {{ summary.eco }} 条
      </div>
    </el-alert>

    <div class="grid">
      <!-- 左：导入 -->
      <el-card shadow="never" class="import-card">
        <template #header>
          <div class="card-head">
            <span>导入边界</span>
            <span class="card-hint">支持 .zip（含 shp 四件套）/ .shp / .geojson / .kml</span>
          </div>
        </template>

        <el-form label-position="top" size="small">
          <el-form-item label="边界用途（决定能被哪些功能使用）">
            <el-radio-group v-model="boundaryType" class="type-group">
              <el-radio-button value="PERMIT">矿权范围</el-radio-button>
              <el-radio-button value="DISTURBANCE">实际扰动边界</el-radio-button>
              <el-radio-button value="ECO">生态缓冲区</el-radio-button>
            </el-radio-group>
            <div class="type-hint">{{ typeHint }}</div>
          </el-form-item>

          <el-form-item label="名称（可选，留空则取文件内要素名称）">
            <el-input v-model="customName" placeholder="如：宁都河源采矿权" maxlength="60" show-word-limit />
          </el-form-item>

          <el-form-item v-if="featureCount > 1">
            <el-checkbox v-model="mergeFeatures">
              合并为一个范围（文件含 {{ featureCount }} 个要素）
            </el-checkbox>
          </el-form-item>
        </el-form>

        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".zip,.shp,.geojson,.json,.kml,.kmz"
          :on-change="onFileChange"
        >
          <el-icon class="up-icon"><UploadFilled /></el-icon>
          <div class="up-text">把边界文件拖到这里，或<em>点击选择</em></div>
          <div class="up-tip">.shp 必须与 .shx/.dbf/.prj 一起打包成 zip，否则坐标系无法判定</div>
        </el-upload>

        <div v-if="pickedFile" class="picked">
          <el-icon><Document /></el-icon>
          <span class="picked-name">{{ pickedFile.name }}</span>
          <span class="picked-size">{{ (pickedFile.size / 1024).toFixed(1) }} KB</span>
        </div>

        <el-button
          type="primary"
          class="import-btn"
          :loading="importing"
          :disabled="!pickedFile"
          @click="doImport"
        >
          解析并导入
        </el-button>

        <div v-if="parsed" class="parse-result">
          <div class="pr-head">解析结果</div>
          <div class="pr-row"><span>格式</span><b>{{ parsed.sourceFormat }}</b></div>
          <div class="pr-row"><span>源坐标系</span><b>{{ parsed.sourceCrs }}</b></div>
          <div class="pr-row"><span>要素数</span><b>{{ parsed.count }} 个</b></div>
          <div class="pr-row"><span>总面积</span><b>{{ totalAreaHa }} ha</b></div>
          <div v-if="parsed.warnings" class="pr-warn">
            <el-icon><WarningFilled /></el-icon>
            <span>{{ parsed.warnings }}</span>
          </div>
        </div>
      </el-card>

      <!-- 右：已导入边界 -->
      <el-card shadow="never" class="list-card">
        <template #header>
          <div class="card-head">
            <span>已导入边界（{{ filtered.length }}）</span>
            <el-radio-group v-model="filterType" size="small">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="PERMIT">矿权</el-radio-button>
              <el-radio-button value="DISTURBANCE">扰动</el-radio-button>
              <el-radio-button value="ECO">缓冲区</el-radio-button>
            </el-radio-group>
          </div>
        </template>

        <el-table :data="filtered" size="small" height="calc(100vh - 330px)" empty-text="还没有导入边界">
          <el-table-column label="名称" min-width="170">
            <template #default="{ row }">
              <div class="name-cell">
                <span>{{ row.name }}</span>
                <el-tooltip v-if="row.warnings" :content="row.warnings" placement="top">
                  <el-icon class="warn-icon"><WarningFilled /></el-icon>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="用途" width="92">
            <template #default="{ row }">
              <el-tag size="small" :type="typeTagOf(row.boundaryType)" effect="plain">
                {{ typeLabelOf(row.boundaryType) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="面积" width="100" align="right">
            <template #default="{ row }">{{ row.areaHa }} ha</template>
          </el-table-column>
          <el-table-column prop="vertexCount" label="顶点" width="64" align="right" />
          <el-table-column label="来源" width="130">
            <template #default="{ row }">
              <div class="src-cell">
                <span>{{ row.sourceFormat }}</span>
                <span class="src-crs">{{ row.sourceCrs }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="preview(row)">预览</el-button>
              <el-button link type="primary" size="small" @click="useAsAoi(row)">用于提取</el-button>
              <el-popconfirm title="删除后不可恢复，确定？" @confirm="remove(row)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- 预览：把外环画成 SVG，够看清形状与范围，不为此再起一个 Cesium -->
    <el-dialog v-model="previewVisible" :title="previewItem?.name" width="640px">
      <div v-if="previewSvg" class="preview-box">
        <svg :viewBox="previewSvg.viewBox" preserveAspectRatio="xMidYMid meet">
          <polygon
            v-for="(ring, i) in previewSvg.rings"
            :key="i"
            :points="ring.points"
            :fill="i === 0 ? 'rgba(20,184,166,0.22)' : '#ffffff'"
            stroke="#0d9488"
            stroke-width="1.2"
          />
        </svg>
      </div>
      <div v-else class="preview-empty">几何数据为空</div>
      <el-descriptions :column="2" size="small" border class="preview-meta">
        <el-descriptions-item label="用途">{{ typeLabelOf(previewItem?.boundaryType || '') }}</el-descriptions-item>
        <el-descriptions-item label="面积">{{ previewItem?.areaHa }} ha</el-descriptions-item>
        <el-descriptions-item label="顶点数">{{ previewItem?.vertexCount }}</el-descriptions-item>
        <el-descriptions-item label="源坐标系">{{ previewItem?.sourceCrs || '-' }}</el-descriptions-item>
        <el-descriptions-item label="来源文件" :span="2">{{ previewItem?.sourceFile || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document, WarningFilled } from '@element-plus/icons-vue'
import { boundaryApi } from '@/api'
import type { AoiBoundaryItem } from '@/api'
import { useProjectStore } from '@/stores/project'

const router = useRouter()
const projectStore = useProjectStore()

const rows = ref<AoiBoundaryItem[]>([])
const summary = ref<Awaited<ReturnType<typeof boundaryApi.summary>> | null>(null)
const loading = ref(false)

const boundaryType = ref<'PERMIT' | 'DISTURBANCE' | 'ECO'>('PERMIT')
const customName = ref('')
const mergeFeatures = ref(false)
const pickedFile = ref<File | null>(null)
const importing = ref(false)
const parsed = ref<Awaited<ReturnType<typeof boundaryApi.importFile>> | null>(null)
const featureCount = ref(0)

const filterType = ref('')
const filtered = computed(() =>
  filterType.value ? rows.value.filter((r) => r.boundaryType === filterType.value) : rows.value
)
const totalAreaHa = computed(() =>
  parsed.value ? Math.round(parsed.value.saved.reduce((s, r) => s + r.areaHa, 0) * 100) / 100 : 0
)

const TYPE_LABEL: Record<string, string> = {
  PERMIT: '矿权范围',
  DISTURBANCE: '扰动边界',
  ECO: '生态缓冲区'
}
const TYPE_TAG: Record<string, 'primary' | 'warning' | 'success'> = {
  PERMIT: 'primary',
  DISTURBANCE: 'warning',
  ECO: 'success'
}
function typeLabelOf(t: string) {
  return TYPE_LABEL[t] || t
}
function typeTagOf(t: string) {
  return TYPE_TAG[t] || 'primary'
}

const typeHint = computed(() => {
  if (boundaryType.value === 'PERMIT') {
    return '登记数据。会作为越界开采检测的基准，也作为安全评估的分析区'
  }
  if (boundaryType.value === 'DISTURBANCE') {
    return '影像解译得到的地表扰动范围，不能当矿权用（否则越界检测失去意义）'
  }
  return '用于区分「矿区内部 / 缓冲区 / 对照区」分别统计植被变化'
})

async function load() {
  const pid = projectStore.currentId
  if (!pid) return
  loading.value = true
  try {
    rows.value = await boundaryApi.list(pid)
    summary.value = await boundaryApi.summary(pid)
  } catch {
    ElMessage.error('边界列表加载失败')
  } finally {
    loading.value = false
  }
}

function onFileChange(file: any) {
  pickedFile.value = file.raw as File
  parsed.value = null
  featureCount.value = 0
}

async function doImport() {
  const pid = projectStore.currentId
  if (!pid || !pickedFile.value) return
  const f = pickedFile.value
  if (f.size > 40 * 1024 * 1024) {
    ElMessage.warning('文件超过 40MB，请先裁剪或简化边界')
    return
  }
  importing.value = true
  try {
    const b64 = await toBase64(f)
    const res = await boundaryApi.importFile({
      projectId: pid,
      boundaryType: boundaryType.value,
      filename: f.name,
      contentBase64: b64,
      name: customName.value.trim() || undefined,
      merge: mergeFeatures.value
    })
    parsed.value = res
    featureCount.value = res.count
    ElMessage.success(`导入成功，共 ${res.count} 条边界`)
    pickedFile.value = null
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '导入失败')
  } finally {
    importing.value = false
  }
}

/** 读成 base64（去掉 dataURL 前缀），避免 multipart 在前后端之间的多层转发 */
function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const s = String(reader.result || '')
      resolve(s.includes(',') ? s.slice(s.indexOf(',') + 1) : s)
    }
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

async function remove(row: AoiBoundaryItem) {
  try {
    await boundaryApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    ElMessage.error('删除失败')
  }
}

// ---- 预览 ----
const previewVisible = ref(false)
const previewItem = ref<AoiBoundaryItem | null>(null)
const previewSvg = ref<{ viewBox: string; rings: Array<{ points: string }> } | null>(null)

async function preview(row: AoiBoundaryItem) {
  try {
    const detail = await boundaryApi.get(row.id)
    previewItem.value = detail
    previewSvg.value = buildSvg(detail)
    previewVisible.value = true
  } catch {
    ElMessage.error('边界详情加载失败')
  }
}

/** 经纬度 → SVG 坐标（经度按纬度余弦压缩，避免高纬度被拉宽） */
function buildSvg(item: AoiBoundaryItem) {
  const outer = item.geometry?.outer
  if (!outer || outer.length < 3) return null
  const lat0 = outer.reduce((s, p) => s + p[1], 0) / outer.length
  const kx = Math.cos((lat0 * Math.PI) / 180)
  const xs = outer.map((p) => p[0] * kx)
  const ys = outer.map((p) => p[1])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const w = maxX - minX || 1
  const h = maxY - minY || 1
  const pad = 0.06
  const toPt = (p: number[]) => {
    const x = (p[0] * kx - minX) / w
    const y = 1 - (p[1] - minY) / h
    return `${(x * 100).toFixed(3)},${(y * 100).toFixed(3)}`
  }
  const rings = [{ points: outer.map(toPt).join(' ') }]
  for (const hole of item.geometry?.holes || []) rings.push({ points: hole.map(toPt).join(' ') })
  const vbW = 100 / (1 - pad * 2)
  const vbH = 100 / (1 - pad * 2)
  return { viewBox: `${-pad * 100} ${-pad * 100} ${vbW} ${vbH}`, rings }
}

/** 把导入的边界交给在线解译页当 AOI（手圈边界容易点位不一致，指纹对不上） */
async function useAsAoi(row: AoiBoundaryItem) {
  try {
    const detail = await boundaryApi.get(row.id)
    const outer = detail.geometry?.outer
    if (!outer || outer.length < 3) {
      ElMessage.warning('该边界没有有效外环，无法作为 AOI')
      return
    }
    localStorage.setItem('pending_aoi', JSON.stringify(outer))
    router.push('/remote-extract')
  } catch {
    ElMessage.error('边界详情加载失败')
  }
}

onMounted(load)
watch(() => projectStore.currentId, load)
</script>

<style scoped>
.boundary-page { display: flex; flex-direction: column; gap: 12px; }
.top-alert { border-radius: 8px; }
.alert-sub { font-size: 12px; color: #6b7280; margin-top: 2px; }

.grid { display: grid; grid-template-columns: 340px 1fr; gap: 12px; }
@media (max-width: 1200px) { .grid { grid-template-columns: 1fr; } }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.card-hint { font-size: 11px; color: #a9aeb8; }

.type-group { width: 100%; display: flex; }
.type-group :deep(.el-radio-button) { flex: 1; }
.type-group :deep(.el-radio-button__inner) { width: 100%; padding: 7px 6px; font-size: 12px; }
.type-hint { font-size: 11px; color: #909399; line-height: 1.5; margin-top: 6px; }

.up-icon { font-size: 34px; color: #b0b6be; }
.up-text { font-size: 13px; color: #4e5969; }
.up-text em { color: #0d9488; font-style: normal; }
.up-tip { font-size: 11px; color: #a9aeb8; margin-top: 2px; }

.picked {
  display: flex; align-items: center; gap: 6px;
  margin-top: 8px; padding: 6px 8px;
  background: #f0fdfa; border: 1px solid #ccfbf1; border-radius: 6px;
  font-size: 12px; color: #0f766e;
}
.picked-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.picked-size { color: #6b7280; }

.import-btn { width: 100%; margin-top: 10px; }

.parse-result {
  margin-top: 12px; padding: 10px;
  background: #fafafa; border: 1px solid #eef0f3; border-radius: 6px;
}
.pr-head { font-size: 12px; font-weight: 600; color: #4e5969; margin-bottom: 6px; }
.pr-row { display: flex; justify-content: space-between; font-size: 12px; color: #6b7280; padding: 2px 0; }
.pr-row b { color: #303133; font-weight: 500; }
.pr-warn {
  display: flex; gap: 5px; align-items: flex-start;
  margin-top: 6px; padding-top: 6px; border-top: 1px dashed #e5e7eb;
  font-size: 11px; color: #b45309; line-height: 1.5;
}

.name-cell { display: flex; align-items: center; gap: 4px; }
.warn-icon { color: #f59e0b; font-size: 13px; }
.src-cell { display: flex; flex-direction: column; font-size: 12px; }
.src-crs { font-size: 10px; color: #a9aeb8; }

.preview-box {
  border: 1px solid #eef0f3; border-radius: 8px;
  background: #fafafa; padding: 8px;
}
.preview-box svg { width: 100%; height: 300px; display: block; }
.preview-empty { color: #a9aeb8; font-size: 12px; text-align: center; padding: 30px 0; }
.preview-meta { margin-top: 12px; }
</style>

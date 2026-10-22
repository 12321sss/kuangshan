<template>
  <div class="extract-page">
    <!-- 左侧地图 -->
    <div class="map-wrap">
      <div ref="cesiumRef" class="cesium-container"></div>
      <div class="map-toolbar">
        <el-button size="small" :type="drawing ? 'primary' : 'default'" @click="toggleDraw">
          {{ drawing ? '圈选中（左键加点·右键结束）' : '圈选 AOI' }}
        </el-button>
        <el-button size="small" :disabled="aoi.length === 0" @click="clearAoi">清除圈选</el-button>
        <!-- 客户给的边界直接当 AOI：上传影像 + 矿权边界是最常见的组合 -->
        <el-select
          v-model="boundaryPick"
          size="small"
          clearable
          placeholder="从边界加载"
          style="width: 160px"
          :loading="boundaryLoading"
          @change="applyBoundaryPick"
        >
          <el-option
            v-for="b in boundaryOptions"
            :key="b.id"
            :label="`${b.name}（${b.areaHa} ha）`"
            :value="b.id"
          />
        </el-select>
        <el-button size="small" :disabled="aoi.length < 3" @click="openSaveBoundary">存为边界</el-button>
        <span v-if="aoiAreaText" class="aoi-info">AOI 面积：{{ aoiAreaText }}</span>
      </div>
      <div v-if="!hasToken" class="token-notice">未配置天地图密钥，底图未加载</div>
    </div>

    <!-- 右侧面板 -->
    <div class="side">
      <el-card shadow="never" class="side-card">
        <template #header><span class="side-title">提取参数</span></template>
        <el-form label-width="80px" size="default">
          <el-form-item label="提取类型">
            <el-select v-model="form.classType" style="width: 100%">
              <el-option
                v-for="c in classChoices"
                :key="c.value"
                :value="c.value"
                :label="c.label"
              />
            </el-select>
            <div class="form-note">{{ classHint }}</div>
          </el-form-item>
          <el-form-item label="选择影像" required>
            <el-select v-model="selectedImageryId" placeholder="从影像库选择" style="width: 100%">
              <el-option
                v-for="img in imageryList"
                :key="img.id"
                :value="img.id"
                :label="`${img.name}（${img.acquisitionDate} · ${sourceLabel(img.source)}）`"
              />
            </el-select>
            <div v-if="!imageryList.length" class="form-note">
              影像库为空，请先到「影像库」页上传高分影像或登记 Sentinel-2 场景
            </div>
          </el-form-item>
          <el-form-item label="提取范围">
            <el-switch v-model="fullImage" active-text="整幅影像" inactive-text="手绘 AOI" />
            <div class="form-note">
              整幅影像：直接用影像覆盖范围提取，不用画 AOI；手绘则按圈选范围提取
            </div>
          </el-form-item>
          <el-form-item v-if="selectedImagery?.source === 'UPLOAD'" label="影像数据源">
            <el-select v-model="form.satellite" style="width: 100%">
              <el-option value="GF2" label="高分二号（GF-2，四波段）" />
              <el-option value="GF7" label="高分七号（GF-7，四波段）" />
            </el-select>
          </el-form-item>
          <el-form-item label="记录名称">
            <el-input v-model="form.name" placeholder="留空自动生成" />
          </el-form-item>
          <el-button
            type="primary"
            style="width: 100%"
            :loading="extracting"
            :disabled="aoi.length < 3 || !selectedImageryId || !auth.hasAction('action:extract-manage')"
            @click="runExtract"
          >
            {{ auth.hasAction('action:extract-manage') ? '开始真实解译' : '当前角色无提取权限' }}
          </el-button>
          <!-- 解译进行中的动态提示：让用户看到已等待多久，而不是以为卡死 -->
          <div v-if="extracting && extractHint" class="extract-hint">
            {{ extractHint }}
          </div>
          <!-- 解译进行中的动态提示：让用户看到已等待多久，而不是以为卡死 -->
          <div v-if="extracting && extractHint" class="extract-hint">
            {{ extractHint }}
          </div>
          <div class="form-note">
            真实解译：解译服务读取影像波段，NDVI/NDWI/NDBI 阈值分割后矢量化，
            属「潜在水土流失风险筛查」，非实测侵蚀量。
          </div>
        </el-form>
      </el-card>

      <el-card shadow="never" class="side-card records-card">
        <template #header>
          <div class="records-head">
            <span class="side-title">提取记录</span>
            <el-checkbox v-model="compareMode">对比模式</el-checkbox>
          </div>
        </template>
        <div v-if="compareMode" class="compare-tip">勾选两条同类型记录进行跨年对比</div>
        <div v-if="records.length === 0" class="empty">暂无记录，圈选 AOI 后开始提取</div>
        <div
          v-for="r in records"
          :key="r.id"
          class="record-item"
          :class="{ picked: comparePicks.includes(r.id) }"
          @click="onRecordClick(r)"
        >
          <div class="record-top">
            <span class="record-name">{{ r.name }}</span>
            <el-tag size="small" :color="classColor(r.classType)" style="color:#fff;border:none">
              {{ classLabel(r.classType) }}
            </el-tag>
          </div>
          <div class="record-meta">
            {{ satelliteLabel(r.satellite) }} · {{ r.year }} 年 · {{ haToKm2(r.extractAreaHa) }} km²（{{ r.coveragePct }}%）
          </div>
          <div class="record-foot">
            <span>{{ r.createdBy }} · {{ r.createdAt.replace('T', ' ').slice(0, 16) }}</span>
            <el-button
              v-if="auth.hasAction('action:extract-manage')"
              size="small" text type="danger"
              @click.stop="onDeleteRecord(r)"
            >删除</el-button>
          </div>
        </div>
      </el-card>

      <!-- 对比结果 -->
      <el-card v-if="compareMode && compareA && compareB" shadow="never" class="side-card">
        <template #header><span class="side-title">变化对比</span></template>
        <el-table :data="compareRows" size="small">
          <el-table-column prop="label" label="指标" width="110" />
          <el-table-column :label="`${compareA.year} 年`" width="90" />
          <el-table-column :label="`${compareB.year} 年`" width="90" />
          <el-table-column label="变化" />
        </el-table>
        <div class="compare-note">地图上红色 = {{ compareA.year }} 年，蓝色 = {{ compareB.year }} 年</div>
      </el-card>

      <!-- 时序播放：同一 AOI 多期结果按时间切换 -->
      <TimeSeriesPanel
        :project-id="projectStore.currentId ?? undefined"
        @frame="onTimeFrame"
      />
    </div>
  </div>
    <!-- 存为边界 -->
    <el-dialog v-model="saveBoundaryVisible" title="保存为边界" width="440px">
      <el-form label-width="88px" size="small">
        <el-form-item label="边界名称">
          <el-input v-model="saveBoundaryName" placeholder="留空自动按日期命名" maxlength="60" show-word-limit />
        </el-form-item>
        <el-form-item label="用途">
          <el-radio-group v-model="saveBoundaryType">
            <el-radio-button value="PERMIT">矿权范围</el-radio-button>
            <el-radio-button value="DISTURBANCE">实际扰动</el-radio-button>
            <el-radio-button value="ECO">生态缓冲区</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="当前 AOI">
          <span class="save-area">{{ aoi.length }} 个顶点 · {{ aoiAreaText || '—' }}</span>
        </el-form-item>
      </el-form>
      <div class="save-tip">
        用途决定后续能被哪些功能使用：矿权范围会成为越界检测基准；实际扰动边界不能当矿权用。
      </div>
      <template #footer>
        <el-button size="small" @click="saveBoundaryVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="savingBoundary" @click="doSaveBoundary">保存</el-button>
      </template>
    </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Viewer, Cartesian3, Color, ImageryLayer, Entity,
  ScreenSpaceEventHandler, ScreenSpaceEventType, Cartographic,
  CallbackProperty, PolygonHierarchy, Rectangle
} from 'cesium'
import { extractionApi, imageryApi, boundaryApi } from '@/api'
import { inferenceApi } from '@/api/sentinel'
import { haToKm2 } from '@/utils/format'
import TimeSeriesPanel from '@/components/TimeSeriesPanel.vue'
import { tiandituBaseLayers } from '@/map/basemap'
import { TIANDITU_TOKEN, MINE_CENTER } from '@/config'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import type { Extraction, Imagery } from '@/api/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const projectStore = useProjectStore()

const cesiumRef = ref<HTMLDivElement>()
const hasToken = !!TIANDITU_TOKEN
const years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

/** 七类地物：与在线解译、监督分类、方案表 6 保持同一套编码 */
const classChoices = [
  { value: 'PIT', label: '露天采坑', hint: '偏暗、台阶阴影多。注意：本地影像无 DEM 时与排土场/尾矿光谱重叠，统一按人工扰动裸地提取' },
  { value: 'DUMP', label: '排土场/废石堆', hint: '松散堆积、中高亮。本地影像同样并入扰动裸地，细分请用「监督分类」' },
  { value: 'TAILINGS', label: '尾矿设施', hint: '细粒高反射接近白色。本地影像同样并入扰动裸地，细分请用「监督分类」' },
  { value: 'BARE', label: '裸地/施工扰动', hint: '泛裸土，判据：低植被 + 非水体 + 短波红外信号' },
  { value: 'ROAD', label: '道路/工业设施', hint: '狭长形状，判据：亮度偏高 + 长宽比/紧凑度形态过滤' },
  { value: 'VEGETATION', label: '植被', hint: '判据：NDVI > 0.25；复绿趋势看这一类' },
  { value: 'WATER', label: '水体', hint: '判据：MNDWI > 0；坑内积水、尾矿库水面都靠它' }
]

const form = reactive({ classType: 'VEGETATION', satellite: 'SENTINEL2', year: 2025, name: '' })
const extracting = ref(false)
/** 解译过程中的动态提示（已等待时长 / 进度） */
const extractHint = ref('')
const drawing = ref(false)
const records = ref<Extraction[]>([])
const compareMode = ref(false)
const comparePicks = ref<number[]>([])

/** 影像库列表 + 当前选中影像（真实解译必选） */
const imageryList = ref<Imagery[]>([])
const selectedImageryId = ref<number | null>(null)
const selectedImagery = computed(() =>
  imageryList.value.find((i) => i.id === selectedImageryId.value) || null)

function sourceLabel(s: string) {
  return { UPLOAD: '上传影像', SENTINEL2: 'Sentinel-2', LANDSAT9: 'Landsat-9', GF2: 'GF-2' }[s] || s
}

let viewer: Viewer | null = null
let drawHandler: ScreenSpaceEventHandler | null = null
const aoi = ref<number[][]>([])
let aoiFloat: number[] | null = null
let aoiEntity: Entity | null = null
let aoiPoints: Entity[] = []
let resultEntities: Entity[] = []

// ---- 标注 ----

/** 当前类型的判别依据，避免用户面对 7 个选项不知道选哪个 */
const classHint = computed(() => {
  const c = classChoices.find((x) => x.value === form.classType)
  return c ? c.hint : ''
})

const aoiAreaText = computed(() => {
  if (aoi.value.length < 3) return ''
  return haToKm2(ringAreaHa(aoi.value)) + ' km²'
})

const compareA = computed(() => records.value.find((r) => r.id === comparePicks.value[0]) || null)
const compareB = computed(() => records.value.find((r) => r.id === comparePicks.value[1]) || null)

const compareRows = computed(() => {
  if (!compareA.value || !compareB.value) return []
  const a = compareA.value
  const b = compareB.value
  const dArea = b.extractAreaHa - a.extractAreaHa
  const dCov = b.coveragePct - a.coveragePct
  return [
    { label: '提取面积(km²)', a: haToKm2(a.extractAreaHa), b: haToKm2(b.extractAreaHa), d: fmtDelta(dArea, 'ha') },
    { label: '覆盖率(%)', a: a.coveragePct, b: b.coveragePct, d: fmtDelta(dCov, 'pct') },
    { label: 'AOI 面积(km²)', a: haToKm2(a.aoiAreaHa), b: haToKm2(b.aoiAreaHa), d: '-' }
  ].map((r) => ({ label: r.label, [String(a.year)]: r.a, [String(b.year)]: r.b, 变化: r.d }))
})

function fmtDelta(v: number, unit: string) {
  const text = unit === 'ha' ? `${(Math.abs(v) / 100).toFixed(2)} km²` : `${Math.abs(v).toFixed(2)} pct`
  return (v >= 0 ? '+' : '-') + text.replace('-', '')
}

function classLabel(t: Extraction['classType']) {
  // 覆盖全部九类：缺映射时退回编码本身，避免界面出现空白标签
  return ({
    VEGETATION: '植被', WATER: '水体', PIT: '采坑', DUMP: '排土场', BARE: '裸地扰动',
    TAILINGS: '尾矿库', ROAD: '道路设施', BUILDING: '建筑', MOUNTAIN: '山体'
  } as Record<string, string>)[t] || t
}
function classColor(t: Extraction['classType']) {
  return ({
    VEGETATION: '#22c55e', WATER: '#3b82f6', PIT: '#ef4444', DUMP: '#f59e0b', BARE: '#a8a29e',
    TAILINGS: '#8b5cf6', ROAD: '#64748b', BUILDING: '#f97316', MOUNTAIN: '#6b7280'
  } as Record<string, string>)[t] || '#888'
}
function satelliteLabel(s: Extraction['satellite']) {
  return { SENTINEL2: 'Sentinel-2', LANDSAT9: 'Landsat-9', GF2: '高分二号' }[s]
}

// ---- AOI 圈选（沿用测量页的 CallbackProperty 动态几何模式） ----

function toggleDraw() {
  if (drawing.value) {
    finishDraw()
    return
  }
  if (!viewer) return
  drawing.value = true
  clearResult()
  drawHandler = new ScreenSpaceEventHandler(viewer.scene.canvas)
  drawHandler.setInputAction((e: ScreenSpaceEventHandler.PositionedEvent) => {
    const pos = viewer?.camera.pickEllipsoid(e.position, viewer.scene.globe.ellipsoid)
    if (!pos) return
    const c = Cartographic.fromCartesian(pos)
    const lng = Cesium_toDeg(c.longitude)
    const lat = Cesium_toDeg(c.latitude)
    const last = aoi.value[aoi.value.length - 1]
    if (last && Math.abs(last[0] - lng) < 1e-9 && Math.abs(last[1] - lat) < 1e-9) return
    aoi.value.push([lng, lat])
    aoiPoints.push(viewer!.entities.add({
      position: pos,
      point: { pixelSize: 7, color: Color.fromCssColorString('#14b8a6'), outlineColor: Color.WHITE, outlineWidth: 2 }
    }))
    refreshAoiShape()
    viewer?.scene.requestRender()
  }, ScreenSpaceEventType.LEFT_CLICK)
  drawHandler.setInputAction((e: ScreenSpaceEventHandler.MotionEvent) => {
    if (aoi.value.length === 0) return
    const pos = viewer?.camera.pickEllipsoid(e.endPosition, viewer.scene.globe.ellipsoid)
    if (pos) {
      const c = Cartographic.fromCartesian(pos)
      aoiFloat = [Cesium_toDeg(c.longitude), Cesium_toDeg(c.latitude)]
      refreshAoiShape()
      viewer?.scene.requestRender()
    }
  }, ScreenSpaceEventType.MOUSE_MOVE)
  drawHandler.setInputAction(() => finishDraw(), ScreenSpaceEventType.RIGHT_CLICK)
}

function Cesium_toDeg(rad: number) {
  return (rad * 180) / Math.PI
}

function activeAoi(): number[][] {
  return aoiFloat ? [...aoi.value, aoiFloat] : aoi.value
}

/** 整幅影像模式：AOI 直接取影像覆盖范围，省掉手画 */
const fullImage = ref(false)

function imageRing(): number[][] {
  const img = selectedImagery.value
  if (!img) return []
  return [
    [img.west, img.south],
    [img.east, img.south],
    [img.east, img.north],
    [img.west, img.north]
  ]
}

/** 打开整幅模式或切换影像时，把 AOI 同步成影像范围并画到地图上 */
watch([fullImage, selectedImagery], () => {
  const img = selectedImagery.value
  // 选了影像就先把视角飞过去，用户才看得到影像在哪
  if (img && viewer) {
    const span = Math.max(img.east - img.west, img.north - img.south)
    viewer.camera.flyTo({
      destination: Cartesian3.fromDegrees(
        (img.west + img.east) / 2, (img.south + img.north) / 2,
        Math.max(1200, span * 111000 * 1.8)
      ),
      orientation: { heading: 0, pitch: -Math.PI / 3 },
      duration: 1.0
    })
  }
  if (!fullImage.value) return
  const ring = imageRing()
  if (ring.length < 3) return
  aoi.value = ring
  refreshAoiShape()
})

// ---- 从边界加载 AOI ----
const boundaryOptions = ref<Array<{ id: number; name: string; areaHa: number }>>([])
const boundaryPick = ref<number | null>(null)
const boundaryLoading = ref(false)

async function loadBoundaryOptions() {
  const pid = projectStore.currentId
  if (!pid) return
  boundaryLoading.value = true
  try {
    const rows = await boundaryApi.list(pid)
    boundaryOptions.value = rows.map((r) => ({ id: r.id, name: r.name, areaHa: r.areaHa }))
  } catch {
    boundaryOptions.value = []
  } finally {
    boundaryLoading.value = false
  }
}

// ---- 存为边界 ----
const saveBoundaryVisible = ref(false)
const saveBoundaryName = ref('')
const saveBoundaryType = ref<'PERMIT' | 'DISTURBANCE' | 'ECO'>('PERMIT')
const savingBoundary = ref(false)

function openSaveBoundary() {
  if (aoi.value.length < 3 && !fullImage.value) {
    ElMessage.warning('请先圈选 AOI 或从边界加载一个范围')
    return
  }
  saveBoundaryName.value = ''
  saveBoundaryType.value = 'PERMIT'
  saveBoundaryVisible.value = true
}

async function doSaveBoundary() {
  const pid = projectStore.currentId
  if (!pid) return
  savingBoundary.value = true
  try {
    const res = await boundaryApi.saveDrawn({
      projectId: pid,
      name: saveBoundaryName.value.trim() || undefined,
      boundaryType: saveBoundaryType.value,
      ring: aoi.value
    })
    ElMessage.success(`已保存边界「${res.saved.name}」（${res.saved.areaHa} ha）`)
    saveBoundaryVisible.value = false
    // 刷新下拉，刚存的边界立刻可用
    await loadBoundaryOptions()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    savingBoundary.value = false
  }
}

async function applyBoundaryPick(id: number | null) {
  if (!id) return
  try {
    const detail = await boundaryApi.get(id)
    const outer = detail.geometry?.outer
    if (!outer || outer.length < 3) {
      ElMessage.warning('该边界没有有效外环，无法作为 AOI')
      return
    }
    // 去掉闭合环的重复末点
    aoi.value = outer.filter((p, i) => i === 0 || p[0] !== outer[0][0] || p[1] !== outer[0][1])
    refreshAoiShape()
    const lngs = aoi.value.map((p) => p[0])
    const lats = aoi.value.map((p) => p[1])
    const cx = (Math.min(...lngs) + Math.max(...lngs)) / 2
    const cy = (Math.min(...lats) + Math.max(...lats)) / 2
    const span = Math.max(Math.max(...lngs) - Math.min(...lngs), Math.max(...lats) - Math.min(...lats))
    viewer?.camera.flyTo({
      destination: Cartesian3.fromDegrees(cx, cy, Math.max(1200, span * 111000 * 1.6)),
      orientation: { heading: 0, pitch: -Math.PI / 3 },
      duration: 1.2
    })
    ElMessage.success(`已加载边界「${detail.name}」作为 AOI（${detail.areaHa} ha）`)
  } catch {
    ElMessage.error('边界加载失败')
  }
}

function refreshAoiShape() {
  if (!viewer) return
  if (aoiEntity) {
    viewer.entities.remove(aoiEntity)
    aoiEntity = null
  }
  const pts = activeAoi()
  if (pts.length < 2) return
  aoiEntity = viewer.entities.add({
    polygon: {
      hierarchy: new CallbackProperty(() => {
        const p = activeAoi()
        return new PolygonHierarchy(p.map(([lng, lat]) => Cartesian3.fromDegrees(lng, lat)))
      }, false) as any,
      material: Color.fromCssColorString('#14b8a6').withAlpha(0.2),
      height: 0,
      outline: true,
      outlineColor: Color.fromCssColorString('#14b8a6'),
      show: new CallbackProperty(() => activeAoi().length >= 3, false)
    }
  })
}

function finishDraw() {
  aoiFloat = null
  drawHandler?.destroy()
  drawHandler = null
  drawing.value = false
  refreshAoiShape()
  viewer?.scene.requestRender()
}

function clearAoi() {
  drawHandler?.destroy()
  drawHandler = null
  drawing.value = false
  aoi.value = []
  aoiFloat = null
  if (viewer && aoiEntity) {
    viewer.entities.remove(aoiEntity)
    aoiEntity = null
  }
  aoiPoints.forEach((e) => viewer?.entities.remove(e))
  aoiPoints = []
  viewer?.scene.requestRender()
}

// ---- 提取与结果上图 ----

async function runExtract() {
  if (!selectedImagery.value) {
    ElMessage.warning('请先选择影像（可在「影像库」页上传或检索后登记）')
    return
  }
  extracting.value = true
  extractHint.value = ''
  extractHint.value = ''
  try {
    const { taskId } = await extractionApi.submit({
      projectId: projectStore.currentId,
      imageryId: selectedImagery.value.id,
      name: form.name || undefined,
      classType: form.classType,
      aoi: aoi.value,
      // 上传影像需告知波段来源（GF2/GF7），公开数据源后端可自行判断
      satellite: selectedImagery.value.source === 'UPLOAD' ? form.satellite : undefined
    })
    ElMessage.info('已提交真实解译任务，正在计算…')
    await pollUntilDone(taskId)
    await loadRecords()
    const fresh = records.value.find((r) => r.taskId === taskId)
    if (fresh) {
      showRecords([fresh.id])
      ElMessage.success(
        `解译完成：${haToKm2(fresh.extractAreaHa)} km²（覆盖率 ${fresh.coveragePct}%）`)
    } else {
      ElMessage.warning('该 AOI 内未检出目标地物')
    }
    form.name = ''
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    extracting.value = false
  }
}

/**
 * 轮询等待解译完成。
 *
 * 修复要点（原实现只盲等 60 秒，高分影像必然误报超时）：
 *  1. 先查 inference 的 /status —— 能拿到真实状态（RUNNING/SUCCESS/EMPTY/FAILED）
 *     与进度，失败时还能拿到具体错误，不用再让用户去翻服务日志
 *  2. 任务 SUCCESS/EMPTY 后，再等 Java 回调落库（回调与计算之间有延迟）
 *  3. 超时上限放宽到 10 分钟（高分影像读全波段 + 矢量化确实慢）
 *  4. 每 5 秒更新一次「已等待 N 秒」，让用户知道在跑而不是卡死
 */
async function pollUntilDone(taskId: string, maxSeconds = 600) {
  const started = Date.now()
  let remoteStatus = 'PENDING'
  let remoteError: string | null = null

  for (let i = 0; i < maxSeconds; i++) {
    await new Promise((r) => setTimeout(r, 1000))
    const waited = Math.round((Date.now() - started) / 1000)

    // 每 5 秒刷新一次提示，避免用户以为卡死
    if (waited % 5 === 0) {
      extractHint.value = `正在解译…已等待 ${waited} 秒（进度 ${remoteStatus === 'RUNNING' ? '计算中' : remoteStatus}）`
    }

    // 1. 查 inference 真实状态
    try {
      const st = await inferenceApi.status(taskId)
      remoteStatus = st.status || 'RUNNING'
      remoteError = st.error || null
      if (remoteStatus === 'FAILED') {
        throw new Error(`解译失败：${remoteError || '未知原因（详见解译服务日志）'}`)
      }
    } catch (e: any) {
      // FAILED 的异常要抛出；状态查询本身失败则忽略继续等
      if (String(e?.message || '').startsWith('解译失败')) throw e
    }

    // 2. 算完了再查数据库（等回调落库，可能滞后几秒）
    if (remoteStatus === 'SUCCESS' || remoteStatus === 'EMPTY') {
      try {
        const list = await extractionApi.list(projectStore.currentId)
        const hit = list.find((r) => r.taskId === taskId)
        if (hit) return hit
      } catch {
        // 后端暂时不可达，继续等回调
      }
    }
  }

  throw new Error(
    `解译超时（已等待 ${maxSeconds} 秒，任务状态 ${remoteStatus}）。` +
    '高分影像首次解译较慢，可稍后到「解译记录」中查看结果；' +
    '若反复超时请查看解译服务日志'
  )
}

async function loadRecords() {
  try {
    records.value = await extractionApi.list(projectStore.currentId)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

/** 加载影像库供下拉选择；自动选中第一景 */
async function loadImagery() {
  try {
    imageryList.value = await imageryApi.list({ projectId: projectStore.currentId })
    // 从影像库跳转过来时按 query 指定影像，否则选第一景
    const qid = Number(route.query.imageryId)
    if (qid && imageryList.value.some((i) => i.id === qid)) {
      selectedImageryId.value = qid
      if (route.query.imageryId) {
        router.replace({ path: '/extract' })  // 用完即清，避免刷新又跳
      }
    } else if (!selectedImageryId.value && imageryList.value.length) {
      selectedImageryId.value = imageryList.value[0].id
      // 顺带把数据源同步到实际影像（后端按影像 source 判定算法）
      form.satellite = imageryList.value[0].source === 'UPLOAD'
        ? 'GF2' : imageryList.value[0].source
      form.year = Number(imageryList.value[0].acquisitionDate?.slice(0, 4)) || form.year
    }
  } catch {
    imageryList.value = []
  }
}

/**
 * 时序播放帧切换：把当期结果上图，并清除上一期。
 * 时序是「同一时刻只显示一期」，与 compare 模式（两期双色叠加）互斥。
 */
function onTimeFrame(frame: Record<string, unknown> | null) {
  clearResult()
  if (!frame) {
    // 停止播放时只保留 AOI，避免地图空白
    redrawAoi()
    return
  }
  const features = safeParsePolygons(frame.featuresJson as string)
  features.forEach((ring) => {
    resultEntities.push(viewer!.entities.add({
      polygon: {
        hierarchy: new PolygonHierarchy(
          ring.map((p) => Cartesian3.fromDegrees(p[0], p[1]))
        ),
        material: Color.fromCssColorString(classColor(frame.classType as string)).withAlpha(0.55),
        outline: true,
        outlineColor: Color.fromCssColorString(frame.classType === 'WATER' ? '#1d4ed8' : '#166534'),
        height: 0
      }
    }))
  })
  // 飞到当期范围，让用户看清这一期
  if (features.length) {
    const xs = features.flat().map((p) => p[0])
    const ys = features.flat().map((p) => p[1])
    viewer?.camera.flyTo({
      destination: Rectangle.fromDegrees(
        Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)),
      duration: 0.8
    })
  }
  viewer?.scene.requestRender()
}

/** AOI 重绘（时序切帧清掉结果后，需要把圈选框恢复回来） */
function redrawAoi() {
  refreshAoiShape()
  viewer?.scene.requestRender()
}

function safeParsePolygons(json: string): number[][][] {
  try {
    const parsed = JSON.parse(json)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/** 把指定记录的结果多边形上图；compare 模式下双色 */
function showRecords(ids: number[]) {
  clearResult()
  if (!viewer) return
  const palette = ids.length === 2 ? ['#ef4444', '#3b82f6'] : null
  ids.forEach((id, idx) => {
    const r = records.value.find((x) => x.id === id)
    if (!r) return
    const colorHex = palette ? palette[idx] : classColor(r.classType)
    const features: number[][][] = JSON.parse(r.featuresJson)
    for (const ring of features) {
      resultEntities.push(viewer!.entities.add({
        polygon: {
          hierarchy: new PolygonHierarchy(ring.map(([lng, lat]) => Cartesian3.fromDegrees(lng, lat))),
          material: Color.fromCssColorString(colorHex).withAlpha(0.5),
          height: 0,
          outline: true,
          outlineColor: Color.fromCssColorString(colorHex)
        }
      }))
    }
  })
  viewer?.scene.requestRender()
}

function clearResult() {
  resultEntities.forEach((e) => viewer?.entities.remove(e))
  resultEntities = []
}

function onRecordClick(r: Extraction) {
  if (compareMode.value) {
    // 对比模式：勾选两条（先旧后新更有序，勾选时保持点击顺序即可）
    const idx = comparePicks.value.indexOf(r.id)
    if (idx >= 0) {
      comparePicks.value.splice(idx, 1)
    } else {
      if (comparePicks.value.length >= 2) comparePicks.value.shift()
      comparePicks.value.push(r.id)
    }
    showRecords(comparePicks.value)
  } else {
    showRecords([r.id])
    // 飞到记录 AOI
    const aoiRing: number[][] = JSON.parse(r.aoiJson)
    const lngs = aoiRing.map((p) => p[0])
    const lats = aoiRing.map((p) => p[1])
    viewer?.camera.flyTo({
      destination: Cartesian3.fromDegrees(
        (Math.min(...lngs) + Math.max(...lngs)) / 2,
        (Math.min(...lats) + Math.max(...lats)) / 2 - 0.004,
        3200
      ),
      orientation: { pitch: -1.35 },
      duration: 1
    })
  }
}

async function onDeleteRecord(r: Extraction) {
  try {
    await extractionApi.remove(r.id)
    ElMessage.success('已删除')
    comparePicks.value = comparePicks.value.filter((id) => id !== r.id)
    await loadRecords()
    showRecords(comparePicks.value)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

// ---- 几何小工具 ----

function ringAreaHa(ring: number[][]): number {
  if (ring.length < 3) return 0
  const R = 6371000
  const lat0 = ring[0][1]
  const lng0 = ring[0][0]
  const cosLat = Math.cos((lat0 * Math.PI) / 180)
  let area = 0
  for (let i = 0; i < ring.length; i++) {
    const [x1d, y1d] = ring[i]
    const [x2d, y2d] = ring[(i + 1) % ring.length]
    const x1 = R * ((x1d - lng0) * Math.PI) / 180 * cosLat
    const y1 = R * ((y1d - lat0) * Math.PI) / 180
    const x2 = R * ((x2d - lng0) * Math.PI) / 180 * cosLat
    const y2 = R * ((y2d - lat0) * Math.PI) / 180
    area += x1 * y2 - x2 * y1
  }
  return Math.abs(area) / 2 / 10000
}

// ---- 生命周期 ----

onMounted(() => {
  // 先拉边界列表（即使三维底图不可用，边界下拉也要能用）
  loadBoundaryOptions()
  if (!cesiumRef.value) return
  const layers = hasToken ? (() => {
    const { base, label } = tiandituBaseLayers('img')
    return [new ImageryLayer(base), new ImageryLayer(label)]
  })() : []
  viewer = new Viewer(cesiumRef.value, {
    baseLayer: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    creditContainer: document.createElement('div')
  })
  layers.forEach((l) => viewer!.imageryLayers.add(l))
  viewer.scene.requestRenderMode = true
  viewer.scene.maximumRenderTimeChange = Infinity
  viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK)
  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(MINE_CENTER.lng, MINE_CENTER.lat - 0.012, 5200),
    orientation: { pitch: -0.72 }
  })
  loadRecords()
  loadImagery()
})

// 切换工程：清空圈选与结果，重拉记录
watch(() => projectStore.currentId, () => {
  clearAoi()
  clearResult()
  comparePicks.value = []
  loadRecords()
  loadImagery()
})

onBeforeUnmount(() => {
  drawHandler?.destroy()
  viewer?.destroy()
  viewer = null
})
</script>

<style scoped>
.save-area { font-size: 12px; color: #4b5563; }
.save-tip { font-size: 11px; color: #b45309; line-height: 1.6; }
.extract-page {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 14px;
  height: calc(100vh - 132px);
}

.map-wrap {
  position: relative;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #eceef2;
}

.cesium-container { width: 100%; height: 100%; }

.map-toolbar {
  position: absolute;
  top: 12px; left: 12px;
  display: flex; align-items: center; gap: 10px;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.aoi-info { font-size: 12px; color: #0d9488; font-weight: 600; }

.token-notice {
  position: absolute; top: 60px; left: 50%; transform: translateX(-50%);
  background: #fef3c7; color: #b45309; font-size: 12px;
  padding: 6px 12px; border-radius: 6px;
}

.side { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow-y: auto; }

.side-card { border: 1px solid #eceef2; border-radius: 10px; flex-shrink: 0; }
.records-card { flex: 1 1 280px; min-height: 240px; }
/* 记录卡给足高度并内部滚动：之前被上下两张卡挤成一条，字都看不清 */
.records-card :deep(.el-card__body) { max-height: 360px; overflow-y: auto; }
.record-item { padding: 8px 10px; border-radius: 8px; }

.side-title { font-size: 14px; font-weight: 600; }
.records-head { display: flex; align-items: center; justify-content: space-between; }

.form-note { margin-top: 10px; font-size: 12px; color: #a9aeb8; line-height: 1.6; }

.compare-tip { font-size: 12px; color: #0d9488; margin-bottom: 8px; }
.empty { color: #a9aeb8; font-size: 12px; padding: 8px 0; }

.record-item {
  border: 1px solid #eceef2;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.record-item:hover { border-color: #14b8a6; }
.record-item.picked { border-color: #0d9488; background: #f0fdfa; }

.record-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.record-name { font-size: 13px; font-weight: 600; }
.record-meta { font-size: 12px; color: #4e5969; }
.record-foot {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 4px; font-size: 11px; color: #a9aeb8;
}

.compare-note { margin-top: 8px; font-size: 12px; color: #64748b; }
.extract-hint {
  margin-top: 8px; padding: 6px 10px; border-radius: 6px;
  background: #f0fdfa; color: #0d9488; font-size: 12px;
  display: flex; align-items: center; gap: 6px;
}
</style>

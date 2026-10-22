<template>
  <div class="fusion-page">
    <!-- 步骤条 -->
    <el-card shadow="never" class="step-card">
      <el-steps :active="activeStep" align-center finish-status="success" :space="180">
        <el-step title="选两套结果" description="分类结果 + 指数结果" />
        <el-step title="看一致性" description="IoU / 差异 / 待核查点" />
        <el-step title="出产品" description="融合 / 专题图" />
      </el-steps>
    </el-card>

    <!-- 第 1 步：选数据 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>① 选择要比较的两套结果</span>
          <span class="card-hint">同一 AOI、同一期才能比；跨期会提示风险</span>
        </div>
      </template>
      <div class="pick-grid">
        <div class="pick-col">
          <div class="pick-title">
            <span class="dot-a"></span>分类结果（监督分类，{{ supervised.length }} 条）
          </div>
          <el-select
            v-model="classifiedIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选同一期同一 AOI 的分类记录"
            style="width: 100%"
          >
            <el-option
              v-for="r in supervised"
              :key="r.id"
              :value="r.id"
              :label="`${classLabel(r.classType)} · ${r.acquisitionDate} · ${r.extractAreaHa} ha`"
            />
          </el-select>
          <div class="pick-tip">建议把同一期所有类别都选上，未参与比较的类不会被改动</div>
        </div>

        <div class="pick-col">
          <div class="pick-title">
            <span class="dot-b"></span>指数结果（阈值提取，{{ indexed.length }} 条）
          </div>
          <el-select
            v-model="indexIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选同类同期别的指数记录"
            style="width: 100%"
          >
            <el-option
              v-for="r in indexed"
              :key="r.id"
              :value="r.id"
              :label="`${classLabel(r.classType)} · ${r.acquisitionDate} · ${r.extractAreaHa} ha`"
            />
          </el-select>
          <div class="pick-tip">例如只比水体：选一条指数水体记录即可</div>
        </div>
      </div>

      <div v-if="!supervised.length && !indexed.length" class="empty-tip">
        还没有可比较的结果。请先在「监督分类」保存一次结果（会自动标记为分类结果），
        再到「在线解译」用指数法提取同类地物。
      </div>

      <div class="row-actions">
        <el-checkbox v-model="withImage">生成差异图</el-checkbox>
        <span class="lbl">最小斑块</span>
        <el-input-number v-model="minPatchHa" :min="0.05" :max="10" :step="0.1" :precision="2" size="small" style="width: 96px" />
        <span class="unit">ha</span>
        <el-button type="primary" :loading="comparing" @click="runCompare">开始差异分析</el-button>
      </div>
    </el-card>

    <!-- 第 2 步：差异 -->
    <template v-if="cmp">
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <span>② 一致性结果</span>
            <span class="card-hint">
              分类 {{ cmp.classifiedDate }} · 指数 {{ cmp.indicesDate }}
            </span>
          </div>
        </template>

        <el-alert
          v-for="(w, i) in cmp.warnings || []"
          :key="i"
          type="warning"
          :closable="false"
          show-icon
          class="warn-item"
          :title="w"
        />

        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-num">{{ cmp.summary?.avgIou }}</div>
            <div class="kpi-lbl">平均 IoU（一致性）</div>
          </div>
          <div class="kpi">
            <div class="kpi-num">{{ cmp.summary?.bothHa }}<span>ha</span></div>
            <div class="kpi-lbl">两边一致</div>
          </div>
          <div class="kpi warn">
            <div class="kpi-num">{{ cmp.summary?.onlyClassifiedHa }}<span>ha</span></div>
            <div class="kpi-lbl">仅分类有</div>
          </div>
          <div class="kpi info">
            <div class="kpi-num">{{ cmp.summary?.onlyIndicesHa }}<span>ha</span></div>
            <div class="kpi-lbl">仅指数有</div>
          </div>
        </div>

        <div class="conclusion">{{ cmp.summary?.conclusion }}</div>

        <div class="diff-wrap">
          <div class="diff-left">
            <el-table :data="cmp.pairs" size="small">
              <el-table-column label="地物" width="100">
                <template #default="{ row }">{{ classLabel(row.classType) }}</template>
              </el-table-column>
              <el-table-column label="分类" width="80" align="right">
                <template #default="{ row }">{{ row.classifiedHa }} ha</template>
              </el-table-column>
              <el-table-column label="指数" width="80" align="right">
                <template #default="{ row }">{{ row.indicesHa }} ha</template>
              </el-table-column>
              <el-table-column label="一致" width="80" align="right">
                <template #default="{ row }">{{ row.bothHa }} ha</template>
              </el-table-column>
              <el-table-column label="IoU" width="70" align="right">
                <template #default="{ row }">
                  <span :class="iouClass(row.iou)">{{ row.iou }}</span>
                </template>
              </el-table-column>
              <el-table-column label="差异" min-width="200">
                <template #default="{ row }">
                  <div class="diff-cell">
                    <el-tooltip v-if="row.onlyClassifiedPatches?.length" placement="top" :width="320">
                      <template #reference>
                        <span class="patch-link">仅分类 {{ row.onlyClassifiedHa }} ha（{{ row.onlyClassifiedPatches.length }} 处）</span>
                      </template>
                      <div v-for="(p, i) in row.onlyClassifiedPatches" :key="i" class="patch-item">
                        <span class="mono">{{ p.lng }}, {{ p.lat }}</span>
                        <span>{{ p.areaHa }} ha</span>
                        <el-button link type="primary" size="small" @click="copyCoord(p)">复制</el-button>
                      </div>
                    </el-tooltip>
                    <el-tooltip v-if="row.onlyIndicesPatches?.length" placement="top" :width="320">
                      <template #reference>
                        <span class="patch-link blue">仅指数 {{ row.onlyIndicesHa }} ha（{{ row.onlyIndicesPatches.length }} 处）</span>
                      </template>
                      <div v-for="(p, i) in row.onlyIndicesPatches" :key="i" class="patch-item">
                        <span class="mono">{{ p.lng }}, {{ p.lat }}</span>
                        <span>{{ p.areaHa }} ha</span>
                        <el-button link type="primary" size="small" @click="copyCoord(p)">复制</el-button>
                      </div>
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <div v-for="p in cmp.pairs" :key="'f' + p.classType" class="finding">· {{ p.finding }}</div>
          </div>

          <div class="diff-right">
            <img v-if="cmp.imageBase64" :src="'data:image/png;base64,' + cmp.imageBase64" class="diff-img" />
            <div class="legend">
              <span v-for="l in cmp.legend" :key="l.label" class="lg">
                <i :style="{ background: l.color }"></i>{{ l.label }}
              </span>
            </div>
            <div class="scale-hint">图幅约 {{ fmtSpan() }}，像素 {{ cmp.imageMeta?.mPerPixel }} m</div>
          </div>
        </div>

        <div class="disclaimer">{{ cmp.disclaimer }}</div>
      </el-card>

      <!-- 第 3 步：融合 -->
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <span>③ 按类选择策略并生成融合结果</span>
            <span class="card-hint">只有设了策略的类会被替换，其余类原样保留</span>
          </div>
        </template>

        <el-table :data="strategyRows" size="small">
          <el-table-column label="地物" width="100">
            <template #default="{ row }">{{ classLabel(row.classType) }}</template>
          </el-table-column>
          <el-table-column label="分类" width="90" align="right" prop="classifiedHa" />
          <el-table-column label="指数" width="90" align="right" prop="indicesHa" />
          <el-table-column label="IoU" width="70" align="right" prop="iou" />
          <el-table-column label="采用" min-width="220">
            <template #default="{ row }">
              <el-select v-model="row.strategy" size="small" style="width: 180px">
                <el-option label="保留分类结果" value="KEEP" />
                <el-option label="指数优先（用指数替换）" value="INDICES_FIRST" />
                <el-option label="仅保留一致部分" value="INTERSECT_ONLY" />
                <el-option label="指数补充（取并集）" value="UNION_ADD" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>

        <div class="row-actions">
          <el-button type="primary" :loading="merging" @click="runMerge">生成融合结果</el-button>
          <span v-if="merged" class="ok-tip">已生成，共 {{ merged.summary?.classCount }} 类，合计 {{ merged.summary?.totalAreaHa }} ha</span>
        </div>

        <template v-if="merged">
          <el-table :data="merged.classes" size="small" class="mt8">
            <el-table-column label="地物" width="100">
              <template #default="{ row }">{{ classLabel(row.classType) }}</template>
            </el-table-column>
            <el-table-column label="策略" width="130" prop="strategyLabel" />
            <el-table-column label="来源" width="110" prop="source" />
            <el-table-column label="分类(ha)" width="90" align="right" prop="classifiedHa" />
            <el-table-column label="最终(ha)" width="90" align="right" prop="finalHa" />
            <el-table-column label="变化(ha)" width="90" align="right">
              <template #default="{ row }">
                <span :class="row.deltaHa >= 0 ? 'up' : 'down'">{{ row.deltaHa > 0 ? '+' : '' }}{{ row.deltaHa }}</span>
              </template>
            </el-table-column>
          </el-table>

          <div class="merge-wrap">
            <img v-if="merged.imageBase64" :src="'data:image/png;base64,' + merged.imageBase64" class="merge-img" />
            <div class="merge-actions">
              <el-button type="success" :loading="saving" @click="saveFusion">保存为解译记录</el-button>
              <el-button :loading="exporting" @click="exportThematic">导出专题图 PNG</el-button>
              <div class="merge-tip">
                保存后标记为「融合结果」，可参与时序、安全评估与报告；专题图带图例、比例尺与数据来源。
              </div>
            </div>
          </div>
        </template>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { extractionApi, fusionApi } from '@/api'
import type { Extraction } from '@/api'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const CLASS_LABEL: Record<string, string> = {
  PIT: '露天采坑', DUMP: '排土场', TAILINGS: '尾矿', BARE: '裸地扰动',
  ROAD: '道路', VEGETATION: '植被', WATER: '水体', BUILDING: '建筑', MOUNTAIN: '山体'
}
function classLabel(c: string) {
  return CLASS_LABEL[c] || c || ''
}

const supervised = ref<Extraction[]>([])
const indexed = ref<Extraction[]>([])
const classifiedIds = ref<number[]>([])
const indexIds = ref<number[]>([])
const withImage = ref(true)
const minPatchHa = ref(0.2)
const comparing = ref(false)
const merging = ref(false)
const saving = ref(false)
const exporting = ref(false)

const cmp = ref<any>(null)
const merged = ref<any>(null)
const strategyRows = ref<any[]>([])

const activeStep = computed(() => (merged.value ? 3 : cmp.value ? 2 : 1))

async function loadRecords() {
  const pid = projectStore.currentId
  if (!pid) return
  try {
    const [s, i] = await Promise.all([
      extractionApi.list(pid, 'SUPERVISED'),
      extractionApi.list(pid, 'INDEX')
    ])
    supervised.value = s
    indexed.value = i
    // 默认把最近的分类记录全选（同一期通常是同一天保存的一批）
    if (s.length) {
      const latest = s[0].acquisitionDate
      classifiedIds.value = s.filter((r) => r.acquisitionDate === latest).map((r) => r.id)
    }
    // 指数结果默认选同类同期别的第一条
    if (i.length && classifiedIds.value.length) {
      const cls = s.find((r) => r.id === classifiedIds.value[0])
      const match = i.find((r) => r.classType === cls?.classType)
      if (match) indexIds.value = [match.id]
    }
  } catch {
    supervised.value = []
    indexed.value = []
  }
}

async function runCompare() {
  const pid = projectStore.currentId
  if (!pid) return
  if (!classifiedIds.value.length || !indexIds.value.length) {
    ElMessage.warning('请同时选择分类结果与指数结果')
    return
  }
  comparing.value = true
  merged.value = null
  try {
    cmp.value = await fusionApi.compare({
      projectId: pid,
      classifiedIds: classifiedIds.value,
      indexIds: indexIds.value,
      options: { minPatchHa: minPatchHa.value, topPatches: 8, withImage: withImage.value },
      withImage: withImage.value
    })
    // 初始化策略表：一致性低的默认"保留分类"，其余类默认"指数优先"
    strategyRows.value = (cmp.value.pairs || []).filter((p: any) => p.available).map((p: any) => ({
      ...p,
      strategy: p.iou >= 0.5 ? 'INDICES_FIRST' : 'KEEP'
    }))
    ElMessage.success(`已完成：平均 IoU ${cmp.value.summary?.avgIou}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '差异分析失败')
    cmp.value = null
  } finally {
    comparing.value = false
  }
}

async function runMerge() {
  const pid = projectStore.currentId
  if (!pid || !cmp.value) return
  merging.value = true
  try {
    merged.value = await fusionApi.merge({
      projectId: pid,
      classifiedIds: classifiedIds.value,
      indexIds: indexIds.value,
      pairs: strategyRows.value
        .filter((r) => r.strategy !== 'KEEP')
        .map((r) => ({ classType: r.classType, strategy: r.strategy })),
      withImage: withImage.value
    })
    ElMessage.success('融合结果已生成')
  } catch (e: any) {
    ElMessage.error(e?.message || '融合失败')
  } finally {
    merging.value = false
  }
}

/** 保存为解译记录：每类一条，method=FUSION，便于后续时序/评估/报告沿用 */
async function saveFusion() {
  const pid = projectStore.currentId
  if (!pid || !merged.value) return
  saving.value = true
  let saved = 0
  try {
    const aoiJson = JSON.stringify(
      // 用分类记录里第一条的 AOI（融合没有新范围）
      JSON.parse(supervised.value.find((r) => classifiedIds.value.includes(r.id))?.aoiJson || '[]')
    )
    const aoiAreaHa = supervised.value.find((r) => classifiedIds.value.includes(r.id))?.aoiAreaHa || 0
    const acq = cmp.value?.classifiedDate || ''
    for (const c of merged.value.classes) {
      const feats = merged.value.features?.[c.classType] || []
      if (!feats.length || c.finalHa <= 0) continue
      const rings = feats.map((f: any) => f.geometry.coordinates[0] as number[][])
      await extractionApi.save({
        projectId: pid,
        name: `${classLabel(c.classType)}-融合`,
        classType: c.classType,
        features: rings,
        aoiJson,
        coveragePct: aoiAreaHa > 0 ? (c.finalHa / aoiAreaHa) * 100 : 0,
        aoiAreaHa,
        acquisitionDate: acq,
        satellite: 'SENTINEL2',
        method: 'FUSION',
        accuracyJson: JSON.stringify({
          strategy: c.strategy,
          source: c.source,
          classifiedHa: c.classifiedHa,
          indicesHa: c.indicesHa,
          finalHa: c.finalHa,
          inputs: { classified: classifiedIds.value, indices: indexIds.value }
        })
      })
      saved++
    }
    ElMessage.success(`已保存 ${saved} 条融合记录（method=FUSION）`)
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function copyCoord(p: { lng: number; lat: number }) {
  try {
    await navigator.clipboard.writeText(`${p.lng},${p.lat}`)
    ElMessage.success('坐标已复制')
  } catch {
    ElMessage.warning(`${p.lng}, ${p.lat}`)
  }
}

function iouClass(v: number) {
  if (v >= 0.75) return 'iou-good'
  if (v >= 0.5) return 'iou-mid'
  return 'iou-bad'
}

function fmtSpan() {
  const m = cmp.value?.imageMeta
  if (!m?.mPerPixel || !m?.width) return '—'
  const km = (m.mPerPixel * m.width) / 1000
  return `${km.toFixed(2)} km × ${((m.mPerPixel * m.height) / 1000).toFixed(2)} km`
}

/**
 * 导出专题图：后端只出底图，这里补标题/图例/比例尺/来源/时间
 * 为什么在前端画：后端（尤其 Linux 服务器）常缺中文字体，图上会变方块
 */
function exportThematic() {
  const m = merged.value
  if (!m?.imageBase64) return
  exporting.value = true
  const img = new Image()
  img.onload = () => {
    const pad = 24
    const headerH = 96
    const footerH = 78
    const legendH = 34 + Math.ceil((m.classes?.length || 0) / 4) * 24
    const w = img.width + pad * 2
    const h = img.height + headerH + legendH + footerH
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, w, h)
    ctx.fillStyle = '#111827'
    ctx.font = 'bold 20px "Microsoft YaHei", "PingFang SC", sans-serif'
    ctx.fillText(`${projectStore.current?.name || '矿区'} 地物分类-指数融合专题图`, pad, 40)
    ctx.font = '13px "Microsoft YaHei", sans-serif'
    ctx.fillStyle = '#6b7280'
    ctx.fillText(
      `影像：Sentinel-2 L2A（${cmp.value?.classifiedDate || '—'}） · 分辨率 10 m · 融合 ${m.summary?.classCount || 0} 类 · 生成 ${new Date().toLocaleString('zh-CN')}`,
      pad, 66
    )

    const top = headerH
    ctx.drawImage(img, pad, top)

    // 图例
    let ly = top + img.height + 20
    ctx.font = '13px "Microsoft YaHei", sans-serif'
    ctx.fillStyle = '#374151'
    ctx.fillText('图例：', pad, ly)
    let lx = pad + 46
    const colors: Record<string, string> = {
      PIT: '#787878', DUMP: '#b08960', TAILINGS: '#e2dac4', BARE: '#c4a882',
      ROAD: '#fad65a', VEGETATION: '#4caf50', WATER: '#2182d6'
    }
    for (const c of m.classes || []) {
      if (lx > w - 140) { lx = pad + 46; ly += 24 }
      ctx.fillStyle = colors[c.classType] || '#999'
      ctx.fillRect(lx, ly - 10, 14, 12)
      ctx.fillStyle = '#374151'
      ctx.fillText(`${classLabel(c.classType)}（${c.source}）`, lx + 20, ly)
      lx += ctx.measureText(`${classLabel(c.classType)}（${c.source}）`).width + 46
    }

    // 比例尺
    const mpp = m.imageMeta?.mPerPixel || 10
    const candidates = [50, 100, 200, 500, 1000, 2000, 5000]
    const target = candidates.find((v) => v / mpp <= 160 && v / mpp >= 40) || 200
    const barPx = target / mpp
    const by = top + img.height - 18
    ctx.strokeStyle = '#111827'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(pad + 10, by)
    ctx.lineTo(pad + 10 + barPx, by)
    ctx.stroke()
    ctx.fillStyle = '#111827'
    ctx.font = '12px "Microsoft YaHei", sans-serif'
    ctx.fillText(`${target >= 1000 ? target / 1000 + ' km' : target + ' m'}`, pad + 10, by - 6)

    // 页面声明（口径）
    ctx.fillStyle = '#9ca3af'
    ctx.font = '11px "Microsoft YaHei", sans-serif'
    const footY = h - 26
    ctx.fillText('口径：IoU/一致率为两种解译方法的一致性，非精度指标；不一致区域应现场核实。', pad, footY)
    ctx.fillText('本图为潜在风险筛查结果，不构成储量、品位或稳定性评价。', pad, footY + 14)

    const url = canvas.toDataURL('image/png')
    const a = document.createElement('a')
    a.href = url
    a.download = `${projectStore.current?.name || '矿区'}-融合专题图-${new Date().toISOString().slice(0, 10)}.png`
    a.click()
    exporting.value = false
  }
  img.onerror = () => {
    ElMessage.error('专题图合成失败')
    exporting.value = false
  }
  img.src = 'data:image/png;base64,' + m.imageBase64
}

onMounted(loadRecords)
watch(() => projectStore.currentId, () => {
  cmp.value = null
  merged.value = null
  classifiedIds.value = []
  indexIds.value = []
  loadRecords()
})
</script>

<style scoped>
.fusion-page { display: flex; flex-direction: column; gap: 12px; }
.step-card :deep(.el-card__body) { padding: 14px 10px; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-hint { font-size: 11px; color: #a9aeb8; }

.pick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1200px) { .pick-grid { grid-template-columns: 1fr; } }
.pick-col { display: flex; flex-direction: column; gap: 6px; }
.pick-title { font-size: 12px; color: #374151; display: flex; align-items: center; gap: 6px; }
.dot-a, .dot-b { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.dot-a { background: #6e6e6e; }
.dot-b { background: #1e88e5; }
.pick-tip { font-size: 11px; color: #a9aeb8; line-height: 1.5; }

.row-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.lbl { font-size: 12px; color: #6b7280; }
.unit { font-size: 12px; color: #a9aeb8; }
.empty-tip { margin-top: 10px; font-size: 12px; color: #b45309; line-height: 1.7; }

.warn-item { margin-bottom: 8px; border-radius: 6px; }
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 10px; }
.kpi { background: #f6f8fa; border-radius: 8px; padding: 10px; text-align: center; }
.kpi.warn { background: #fff7ed; }
.kpi.info { background: #eff6ff; }
.kpi-num { font-size: 20px; font-weight: 700; color: #0d9488; }
.kpi-num span { font-size: 11px; font-weight: 400; margin-left: 2px; }
.kpi-lbl { font-size: 11px; color: #6b7280; margin-top: 2px; }

.conclusion { font-size: 13px; color: #1f2937; line-height: 1.7; padding: 8px 10px; background: #f6f8fa; border-radius: 8px; }

.diff-wrap { display: grid; grid-template-columns: 1fr 320px; gap: 12px; margin-top: 12px; align-items: start; }
@media (max-width: 1300px) { .diff-wrap { grid-template-columns: 1fr; } }
.diff-cell { display: flex; flex-direction: column; gap: 2px; }
.patch-link { font-size: 11px; color: #ef6c00; cursor: pointer; }
.patch-link.blue { color: #1e88e5; }
.patch-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 11px; padding: 2px 0; }
.mono { font-family: ui-monospace, Consolas, monospace; }
.finding { font-size: 11px; color: #6b7280; line-height: 1.7; margin-top: 4px; }
.iou-good { color: #2e7d32; font-weight: 600; }
.iou-mid { color: #b45309; font-weight: 600; }
.iou-bad { color: #d32f2f; font-weight: 600; }

.diff-img { width: 100%; border: 1px solid #eef0f3; border-radius: 6px; image-rendering: pixelated; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 6px; }
.lg { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #6b7280; }
.lg i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.scale-hint { font-size: 10px; color: #a9aeb8; margin-top: 4px; }

.ok-tip { font-size: 12px; color: #2e7d32; }
.mt8 { margin-top: 8px; }
.merge-wrap { display: grid; grid-template-columns: 320px 1fr; gap: 12px; margin-top: 10px; align-items: start; }
@media (max-width: 1200px) { .merge-wrap { grid-template-columns: 1fr; } }
.merge-img { width: 100%; border: 1px solid #eef0f3; border-radius: 6px; image-rendering: pixelated; }
.merge-actions { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.merge-tip { font-size: 11px; color: #909399; line-height: 1.6; }
.up { color: #d32f2f; }
.down { color: #2e7d32; }
.disclaimer { font-size: 10px; color: #a9aeb8; line-height: 1.6; margin-top: 8px; }
</style>

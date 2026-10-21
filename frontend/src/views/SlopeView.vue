<template>
  <div class="slope-page">
    <!-- ============ 说明与操作 ============ -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="head">
          <div>
            <span class="head-title">边坡单元与失稳风险</span>
            <span class="head-sub">
              按坡面划分单元，识别切脚 / 削坡 / 堆载三类力学扰动
            </span>
          </div>
          <div class="head-right">
            <el-tooltip placement="bottom">
              <template #content>
                <div style="max-width: 300px; line-height: 1.7">
                  边坡失稳多由「坡脚被切」引起：采坑边界推进到坡脚，
                  边坡失去支撑，即使坡度不大也可能突然失稳。
                  本页把采坑边界与 DEM 坡脚位置结合，算出每个边坡单元的切脚距离。
                </div>
              </template>
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
            <el-button type="primary" :loading="loading" @click="runAnalyze">开始识别</el-button>
          </div>
        </div>
      </template>

      <div class="intro-row">
        <div class="intro-item">
          <span class="intro-num">①</span>
          <div>
            <div class="intro-title">只看三类设施</div>
            <div class="intro-desc">采坑 / 排土场 / 尾矿。植被、水体不构成工程边坡，不参与</div>
          </div>
        </div>
        <div class="intro-item">
          <span class="intro-num">②</span>
          <div>
            <div class="intro-title">坡度 ≥15° 才算边坡</div>
            <div class="intro-desc">低于此视为平台或缓坡，不纳入失稳评估</div>
          </div>
        </div>
        <div class="intro-item">
          <span class="intro-num">③</span>
          <div>
            <div class="intro-title">按坡向拆单元</div>
            <div class="intro-desc">同一采坑四周朝向不同，拆成 8 个方位分别评估</div>
          </div>
        </div>
      </div>

      <div v-if="loading" class="loading-hint">
        正在读取 DEM 并划分边坡单元，约 10–30 秒
      </div>
    </el-card>

    <!-- ============ 空状态 ============ -->
    <el-card v-if="!result && !loading" shadow="never" class="panel">
      <el-empty description="还没有识别结果" :image-size="100">
        <div class="empty-hint">
          识别需要项目里有「采坑 / 排土场 / 尾矿」的解译记录。<br />
          如果这三类都没有，先到「遥感提取」页对开采相关地物做一次提取。
        </div>
        <el-button type="primary" size="small" @click="$router.push('/remote-extract')">
          去遥感提取
        </el-button>
      </el-empty>
    </el-card>

    <!-- ============ 不可用 ============ -->
    <el-card v-else-if="!result.available" shadow="never" class="panel">
      <el-alert :title="result.message || '无法识别'" type="warning" :closable="false" show-icon />
    </el-card>

    <template v-else>
      <!-- 诊断提示：解释为什么单元少 / 为什么切脚算不出 -->
      <el-alert
        v-if="diagTip"
        :title="diagTip.title"
        :description="diagTip.desc"
        :type="diagTip.type"
        :closable="false"
        show-icon
      />

      <!-- 概览 -->
      <div class="overview">
        <el-card shadow="never" class="panel">
          <template #header><span class="head-title">风险分布</span></template>
          <div class="risk-grid">
            <div class="risk-cell high">
              <div class="rc-num">{{ result.summary?.high ?? 0 }}</div>
              <div class="rc-label">高风险单元</div>
            </div>
            <div class="risk-cell higher">
              <div class="rc-num">{{ result.summary?.higher ?? 0 }}</div>
              <div class="rc-label">较高风险</div>
            </div>
            <div class="risk-cell medium">
              <div class="rc-num">{{ result.summary?.medium ?? 0 }}</div>
              <div class="rc-label">中风险</div>
            </div>
            <div class="risk-cell low">
              <div class="rc-num">{{ result.summary?.low ?? 0 }}</div>
              <div class="rc-label">低风险</div>
            </div>
          </div>
          <div class="stat-row">
            <span>单元总数 <b>{{ result.summary?.unitCount ?? 0 }}</b></span>
            <span>边坡总面积 <b>{{ result.summary?.totalAreaHa ?? 0 }} ha</b></span>
            <span>最大坡高 <b>{{ result.summary?.maxSlopeHeightM ?? 0 }} m</b></span>
            <span :class="{ danger: (result.summary?.cutToeCount ?? 0) > 0 }">
              已切脚单元 <b>{{ result.summary?.cutToeCount ?? 0 }}</b>
            </span>
          </div>
        </el-card>

        <el-card shadow="never" class="panel">
          <template #header>
            <div class="head">
              <span class="head-title">单元专题图</span>
              <span class="head-sub">{{ result.precision?.groundResolutionM }}m/像元</span>
            </div>
          </template>
          <img
            v-if="result.imageBase64"
            :src="'data:image/png;base64,' + result.imageBase64"
            class="risk-img"
            alt="边坡单元风险图"
          />
          <div class="legend">
            <span v-for="l in result.legend" :key="l.label" class="lg-item">
              <i :style="{ background: l.color }"></i>{{ l.label }}
            </span>
            <span class="lg-item"><i style="background: #f0f2f5"></i>非边坡区</span>
          </div>
        </el-card>
      </div>

      <!-- 单元明细 -->
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="head">
            <span class="head-title">边坡单元明细</span>
            <span class="head-sub">按风险等级与坡高排序，前 60 个</span>
          </div>
        </template>
        <el-table :data="result.units" size="small" stripe :default-sort="{ prop: 'slopeHeightM', order: 'descending' }">
          <el-table-column label="#" width="50" type="index" />
          <el-table-column label="设施" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ facilityLabel(row.facility) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风险" width="80">
            <template #default="{ row }">
              <span class="risk-tag" :style="{ background: levelColor(row.riskLevel) }">
                {{ row.riskLevel }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="坡高(m)" width="90" prop="slopeHeightM" sortable />
          <el-table-column label="坡度(°)" width="90" prop="meanSlopeDeg" sortable />
          <el-table-column label="朝向(°)" width="90" prop="aspectDeg" sortable />
          <el-table-column label="面积(ha)" width="90" prop="areaHa" sortable />
          <el-table-column label="切脚距离(m)" width="110" prop="toeDistanceM" sortable>
            <template #default="{ row }">
              <span :class="{ danger: row.toeDistanceM != null && row.toeDistanceM <= 10 }">
                {{ row.toeDistanceM ?? '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="切脚比例" width="90">
            <template #default="{ row }">{{ row.toeCutRatio }}%</template>
          </el-table-column>
          <el-table-column label="坡顶堆载" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.topLoaded" size="small" type="warning">有</el-tag>
              <span v-else class="muted">无</span>
            </template>
          </el-table-column>
          <el-table-column label="判定依据" min-width="240">
            <template #default="{ row }">
              <div v-for="(r, i) in row.reasons" :key="i" class="reason-line">{{ r }}</div>
            </template>
          </el-table-column>
          <el-table-column label="位置" width="90">
            <template #default="{ row }">
              <el-button link size="small" @click="copyCoord(row.toeLng, row.toeLat)">坡脚坐标</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 口径 -->
      <el-card shadow="never" class="panel note-panel">
        <el-icon class="note-icon"><WarningFilled /></el-icon>
        <div>
          <div class="note-title">口径说明（对外提交必须保留）</div>
          <div class="note-text">{{ result.disclaimer }}</div>
          <div class="note-text warn">{{ result.precision?.limitation }}</div>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled, WarningFilled } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import type { SlopeUnitsResult } from '@/api/types'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()
const loading = ref(false)
const result = ref<SlopeUnitsResult | null>(null)

const FACILITY_LABEL: Record<string, string> = {
  PIT: '采坑', DUMP: '排土场', TAILINGS: '尾矿'
}
function facilityLabel(c: string) { return FACILITY_LABEL[c] || c }

function levelColor(l: string): string {
  return { 高: '#d32f2f', 较高: '#ff9800', 中: '#ffd54f', 低: '#8bc34a' }[l] || '#ccc'
}

/**
 * 诊断提示：把"为什么结果是这样"直接说清楚，避免用户以为是系统问题。
 * 两种典型情况：① 没有采坑记录 → 切脚算不出；② 地形平缓 → 单元少或全低风险。
 */
const diagTip = computed(() => {
  const r = result.value
  if (!r?.available || !r.units?.length) return null
  const d = r.diagnostics
  const hasPit = r.units.some((u) => u.facility === 'PIT')
  const noToeDist = r.units.every((u) => u.toeDistanceM == null)

  if (noToeDist) {
    return {
      type: 'warning' as const,
      title: '切脚判定不可用：库里没有「露天采坑」的解译记录',
      desc: '切脚距离需要拿坡脚位置与采坑边界比对。当前只找到排土场/尾矿的边界，'
        + '所以这一列显示「-」。要评估切脚风险，请先对采坑做一次提取。',
    }
  }
  if (d && d.steepPixelsInDisturbed < 200) {
    return {
      type: 'info' as const,
      title: '该区域地形较平缓，边坡规模有限',
      desc: `扰动区内坡度≥${d.minSlopeDeg}° 的像元仅 ${d.steepPixelsInDisturbed} 个`
        + `（全区平均坡度 ${d.slopeMeanDeg}°、P90 ${d.slopeP90Deg}°）。`
        + '所以单元数量少、风险等级偏低是符合实际的，不是识别失败。',
    }
  }
  if (!hasPit) {
    return {
      type: 'info' as const,
      title: '当前只有堆体边坡（排土场/尾矿）',
      desc: '堆体边坡的稳定性由自身堆高与坡角决定；若还关心采坑边坡，请补充采坑解译。',
    }
  }
  return null
})

async function runAnalyze() {
  loading.value = true
  try {
    const res = await analysisApi.slopeUnits(projectStore.currentId ?? undefined)
    result.value = res
    if (!res.available) {
      ElMessage.warning(res.message || '无法识别')
    } else {
      const s = res.summary
      ElMessage.success(
        `识别完成：${s?.unitCount ?? 0} 个边坡单元，` +
        `高风险 ${s?.high ?? 0} 个、已切脚 ${s?.cutToeCount ?? 0} 个`
      )
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '识别失败，请确认解译服务已启动')
  } finally {
    loading.value = false
  }
}

/** 复制坡脚坐标，方便拿到现场或用 GIS 打开 */
async function copyCoord(lng: number, lat: number) {
  try {
    await navigator.clipboard.writeText(`${lng}, ${lat}`)
    ElMessage.success('坡脚坐标已复制')
  } catch {
    ElMessage.warning(`坡脚坐标：${lng}, ${lat}`)
  }
}

watch(() => projectStore.currentId, () => {
  result.value = null
})
</script>

<style scoped>
.slope-page { display: flex; flex-direction: column; gap: 14px; }
.panel { border: 1px solid #eceef2; border-radius: 10px; }

.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.head-title { font-size: 14px; font-weight: 700; color: #1d2129; }
.head-sub { font-size: 12px; color: #86909c; margin-left: 8px; font-weight: 400; }
.head-right { display: flex; align-items: center; gap: 10px; }
.help-icon { color: #86909c; font-size: 16px; cursor: help; }

/* 三条说明：横向铺开，不挤 */
.intro-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.intro-item { display: flex; gap: 10px; align-items: flex-start; background: #f8fafc; border-radius: 8px; padding: 12px; }
.intro-num { color: #0d9488; font-weight: 700; font-size: 14px; flex-shrink: 0; }
.intro-title { font-size: 12px; font-weight: 600; color: #1d2129; margin-bottom: 3px; }
.intro-desc { font-size: 11px; color: #86909c; line-height: 1.6; }
.loading-hint { margin-top: 12px; font-size: 12px; color: #0d9488; }
.empty-hint { font-size: 12px; color: #86909c; line-height: 1.8; margin-bottom: 12px; }

.overview { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.risk-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.risk-cell { border-radius: 8px; padding: 12px 8px; text-align: center; }
.risk-cell.high { background: #fef2f2; }
.risk-cell.higher { background: #fff7ed; }
.risk-cell.medium { background: #fefce8; }
.risk-cell.low { background: #f0fdf4; }
.rc-num { font-size: 22px; font-weight: 800; }
.risk-cell.high .rc-num { color: #d32f2f; }
.risk-cell.higher .rc-num { color: #f97316; }
.risk-cell.medium .rc-num { color: #ca8a04; }
.risk-cell.low .rc-num { color: #16a34a; }
.rc-label { font-size: 11px; color: #86909c; margin-top: 2px; }

.stat-row { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; font-size: 12px; color: #4e5969; }
.stat-row b { color: #1d2129; }
.stat-row .danger b { color: #d32f2f; }

.risk-img { width: 100%; border-radius: 8px; border: 1px solid #eceef2; image-rendering: pixelated; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 12px; color: #4e5969; }
.lg-item { display: inline-flex; align-items: center; gap: 5px; }
.lg-item i { width: 10px; height: 10px; border-radius: 2px; }

.risk-tag { display: inline-block; padding: 1px 8px; border-radius: 9px; color: #fff; font-size: 11px; }
.danger { color: #d32f2f; font-weight: 600; }
.muted { color: #a9aeb8; }
.reason-line { font-size: 11px; color: #4e5969; line-height: 1.6; }

.note-panel :deep(.el-card__body) { display: flex; gap: 10px; align-items: flex-start; }
.note-icon { color: #f59e0b; font-size: 18px; margin-top: 2px; flex-shrink: 0; }
.note-title { font-size: 12px; font-weight: 700; color: #b45309; margin-bottom: 5px; }
.note-text { font-size: 12px; color: #4e5969; line-height: 1.8; }
.note-text.warn { color: #b45309; }

@media (max-width: 1280px) {
  .overview { grid-template-columns: 1fr; }
  .intro-row { grid-template-columns: 1fr; }
  .risk-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>

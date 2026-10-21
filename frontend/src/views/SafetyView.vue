<template>
  <div class="safety-page">
    <!-- 顶部操作条 -->
    <el-card shadow="never" class="op-card">
      <div class="op-row">
        <div class="op-left">
          <span class="op-title">开采安全风险评估</span>
          <span class="op-sub">
            基于七类地物解译 + DEM 地形 + 时序扩张，融合五维因子给出风险筛查结论
          </span>
        </div>
        <div class="op-right">
          <el-tooltip placement="bottom">
            <template #content>
              <div style="max-width: 280px; line-height: 1.7">
                勾选后先用 DEM 划分边坡单元，形态维度按「最差 3 个单元」聚合，
                比全区平均更能反映真实危险点。会多花 10–30 秒。
              </div>
            </template>
            <el-checkbox v-model="withSlope" size="small">用边坡单元细化形态评估</el-checkbox>
          </el-tooltip>
          <el-checkbox v-model="withGrid" size="small">生成风险专题图与热点</el-checkbox>
          <el-button type="primary" :loading="loading" @click="runEvaluate">开始评估</el-button>
        </div>
      </div>
    </el-card>

    <!-- 未评估：引导 -->
    <el-card v-if="!result" shadow="never" class="empty-card">
      <el-empty description="还没有评估结果" :image-size="110">
        <div class="empty-hint">
          评估需要项目里已有解译记录（尤其是采坑/排土场/尾矿/裸地这类扰动地物）。<br />
          如果库里只有植被或建筑，扩张与越界维度会算不出有效值。
        </div>
        <el-button type="primary" size="small" @click="$router.push('/remote-extract')">
          去遥感提取
        </el-button>
      </el-empty>
    </el-card>

    <!-- 数据不足 -->
    <el-card v-else-if="!result.available" shadow="never" class="empty-card">
      <el-alert :title="result.message || '无法评估'" type="warning" :closable="false" show-icon />
    </el-card>

    <template v-else>
      <!-- 总览：总分 + 雷达 -->
      <div class="overview">
        <el-card shadow="never" class="score-card">
          <div class="score-main">
            <div class="score-ring" :style="{ '--c': result.score!.color }">
              <div class="score-num">{{ result.score!.total }}</div>
              <div class="score-unit">/ 100</div>
            </div>
            <div class="score-meta">
              <div class="level-tag" :style="{ background: result.score!.color }">
                {{ result.score!.level }}风险
              </div>
              <!-- 安全指数视角：100 - 风险分，客户更直观理解「分越高越安全」 -->
              <div v-if="result.score!.safetyIndex != null" class="safety-index">
                矿山安全指数 <b>{{ result.score!.safetyIndex }}</b>
                <span class="si-level">（{{ result.score!.safetyLevel }}）</span>
              </div>
              <div v-if="result.score!.ahp" class="ahp-note">
                权重：{{ result.score!.weightMethod }}，一致性 CR={{ result.score!.ahp.CR }}
              </div>
              <div class="score-project">{{ result.projectName }}</div>
              <div class="score-time">
                {{ formatTime(result.generatedAt) }} · {{ result.recordCount }} 条解译记录
              </div>
            </div>
          </div>
          <!-- 加权构成条 -->
          <div class="weight-bar">
            <div
              v-for="d in result.score!.dimensions"
              :key="d.key"
              class="wb-seg"
              :style="{ width: d.weight * 100 + '%', background: dimColor(d.score) }"
              :title="`${d.label} 得分 ${d.score} · 权重 ${d.weight * 100}%`"
            ></div>
          </div>
          <div class="weight-legend">
            <span v-for="d in result.score!.dimensions" :key="d.key" class="wl-item">
              <i :style="{ background: dimColor(d.score) }"></i>{{ d.label }}
              {{ d.score }}<em>(×{{ Math.round(d.weight * 100) }}%)</em>
            </span>
          </div>
        </el-card>

        <el-card shadow="never" class="radar-card">
          <template #header><span>五维风险雷达</span></template>
          <div ref="radarRef" class="radar"></div>
        </el-card>
      </div>

      <!-- 维度明细 -->
      <el-card shadow="never" class="dim-card">
        <template #header>
          <div class="card-head">
            <span>分维度依据与建议</span>
            <span class="card-sub">每项都给具体数值，避免只给一个总分</span>
          </div>
        </template>
        <div v-for="d in result.score!.dimensions" :key="d.key" class="dim-item">
          <div class="dim-head">
            <span class="dim-label">{{ d.label }}</span>
            <el-tag size="small" :type="d.score >= 60 ? 'danger' : d.score >= 40 ? 'warning' : 'success'">
              {{ d.score }} 分
            </el-tag>
            <el-tag size="small" effect="plain" type="info">权重 {{ Math.round(d.weight * 100) }}%</el-tag>
            <el-tag size="small" effect="plain" :type="confType(d.confidence)">
              可信度 {{ confLabel(d.confidence) }}
            </el-tag>
            <el-tag
              v-if="d.basis === 'slope_units'"
              size="small" effect="plain" type="success"
            >基于边坡单元</el-tag>
            <el-tag
              v-else-if="d.basis === 'fallback' && d.key === 'terrain'"
              size="small" effect="plain" type="info"
            >全区统计</el-tag>
          </div>
          <ul class="dim-evidence">
            <li v-for="(e, i) in d.evidence" :key="i">{{ e }}</li>
          </ul>
          <div class="dim-advice">建议：{{ d.advice }}</div>
        </div>
      </el-card>

      <!-- 越界 + 面积 -->
      <div class="two-col">
        <el-card shadow="never" class="panel">
          <template #header><span>越界开采检测</span></template>
          <div v-if="result.encroachment?.available">
            <div class="kpi-row">
              <div class="kpi">
                <div class="kpi-num" :class="{ danger: (result.encroachment?.areaHa || 0) > 0 }">
                  {{ result.encroachment?.areaHa }}
                </div>
                <div class="kpi-label">越界面积(ha)</div>
              </div>
              <div class="kpi">
                <div class="kpi-num">{{ result.encroachment?.pctOfDisturbance }}%</div>
                <div class="kpi-label">占扰动总面积</div>
              </div>
              <div class="kpi">
                <div class="kpi-num">{{ result.encroachment?.permitAreaHa ?? '-' }}</div>
                <div class="kpi-label">矿权面积(ha)</div>
              </div>
            </div>
            <el-alert
              v-if="(result.encroachment?.areaHa || 0) > 0"
              type="warning"
              :closable="false"
              show-icon
              title="检测到扰动范围超出登记矿权边界"
              :description="result.encroachment?.note"
            />
            <div v-else class="ok-note">扰动范围未超出登记矿权边界。</div>
          </div>
          <el-alert
            v-else
            type="info"
            :closable="false"
            show-icon
            title="未提供矿权边界，无法做越界判定"
            description="在「项目管理」里登记矿权边界后可自动检测"
          />
        </el-card>

        <el-card shadow="never" class="panel">
          <template #header>
            <div class="card-head">
              <span>面积汇总（并集口径）</span>
              <span class="card-sub">{{ result.areaSummary?.note }}</span>
            </div>
          </template>
          <div class="kpi-row">
            <div class="kpi">
              <div class="kpi-num">{{ result.areaSummary?.aoiHa }}</div>
              <div class="kpi-label">分析区(ha)</div>
            </div>
            <div class="kpi">
              <div class="kpi-num">{{ result.areaSummary?.disturbanceHa }}</div>
              <div class="kpi-label">扰动并集(ha)</div>
            </div>
          </div>
          <div class="class-list">
            <div v-for="(ha, ct) in result.areaSummary?.byClass" :key="ct" class="class-item">
              <span class="cls-dot" :style="{ background: classColor(ct) }"></span>
              <span class="cls-name">{{ classLabel(ct) }}</span>
              <span class="cls-val">{{ ha }} ha</span>
            </div>
          </div>
          <!-- 面积自检：各类之和明显超过分析区时明确提示，不隐藏 -->
          <el-alert
            v-if="result.areaSummary?.check"
            type="warning"
            :closable="false"
            show-icon
            :title="result.areaSummary.check"
            style="margin-top: 8px"
          />
        </el-card>
      </div>

      <!-- 风险专题图 + 热点 -->
      <el-card v-if="result.riskImageBase64" shadow="never" class="panel">
        <template #header>
          <div class="card-head">
            <span>风险分级专题图</span>
            <span class="card-sub">
              栅格 {{ result.grid?.width }}×{{ result.grid?.height }} @ {{ result.grid?.mPerPixel }}m
            </span>
          </div>
        </template>
        <div class="risk-wrap">
          <img :src="'data:image/png;base64,' + result.riskImageBase64" class="risk-img" alt="风险专题图" />
          <div class="risk-side">
            <div class="level-list">
              <div v-for="l in result.levelStats" :key="l.label" class="level-item">
                <span class="lv-dot" :style="{ background: l.color }"></span>
                <span class="lv-name">{{ l.label }}风险</span>
                <span class="lv-pct">{{ l.pct }}%</span>
              </div>
            </div>
            <div class="hotspot-head">
              风险热点（阈值 {{ result.hotspotThreshold }} 分，按 分值×面积 排序）
            </div>
            <el-table :data="result.hotspots || []" size="small" empty-text="没有超过阈值的连片区域">
              <el-table-column label="位置" min-width="120">
                <template #default="{ row }">
                  {{ row.lng.toFixed(5) }}, {{ row.lat.toFixed(5) }}
                </template>
              </el-table-column>
              <el-table-column label="面积(ha)" width="90">
                <template #default="{ row }">{{ row.areaHa }}</template>
              </el-table-column>
              <el-table-column label="风险分" width="80">
                <template #default="{ row }">
                  <span :style="{ color: dimColor(row.score), fontWeight: 600 }">{{ row.score }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-card>

      <!-- 口径红线 -->
      <el-card shadow="never" class="disclaimer-card">
        <el-icon class="dc-icon"><WarningFilled /></el-icon>
        <div>
          <div class="dc-title">口径说明（对外提交时必须保留）</div>
          <div class="dc-text">{{ result.disclaimer }}</div>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import { useProjectStore } from '@/stores/project'
import type { SafetyEvaluation } from '@/api/types'

const projectStore = useProjectStore()

const loading = ref(false)
const withGrid = ref(true)
/** 是否用边坡单元细化形态维度（多花 10-30 秒，但结果更贴近实际） */
const withSlope = ref(false)
const result = ref<SafetyEvaluation | null>(null)
const radarRef = ref<HTMLDivElement>()
let radar: echarts.ECharts | undefined

const CLASS_LABEL: Record<string, string> = {
  PIT: '露天采坑', DUMP: '排土场', TAILINGS: '尾矿设施', BARE: '裸地扰动',
  VEGETATION: '植被', ROAD: '道路/设施', WATER: '水体', BUILDING: '建筑', MOUNTAIN: '山体'
}
const CLASS_COLOR: Record<string, string> = {
  PIT: '#ef4444', DUMP: '#f59e0b', TAILINGS: '#8b5cf6', BARE: '#a8a29e',
  VEGETATION: '#22c55e', ROAD: '#64748b', WATER: '#3b82f6', BUILDING: '#f97316', MOUNTAIN: '#6b7280'
}
function classLabel(c: string) { return CLASS_LABEL[c] || c }
function classColor(c: string) { return CLASS_COLOR[c] || '#888' }

/** 分项得分 → 颜色（始终用统一的 5 级色，便于跨维度比较） */
function dimColor(score: number): string {
  if (score < 20) return '#4caf50'
  if (score < 40) return '#aed581'
  if (score < 60) return '#ffd54f'
  if (score < 80) return '#ff9800'
  return '#d32f2f'
}
function confLabel(c: string) { return { low: '低', medium: '中', high: '高' }[c] || c }
function confType(c: string): 'success' | 'warning' | 'info' {
  return c === 'high' ? 'success' : c === 'medium' ? 'warning' : 'info'
}
function formatTime(t?: string) { return t ? t.replace('T', ' ').slice(0, 16) : '-' }

async function runEvaluate() {
  loading.value = true
  try {
    const res = await analysisApi.safetyEvaluate(projectStore.currentId ?? undefined, withGrid.value, withSlope.value)
    result.value = res
    if (res.available) {
      await nextTick()
      renderRadar()
      ElMessage.success(`评估完成：风险分 ${res.score?.total}（${res.score?.level}）`)
    } else {
      ElMessage.warning(res.message || '数据不足，无法评估')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '评估失败')
  } finally {
    loading.value = false
  }
}

function renderRadar() {
  const el = radarRef.value
  if (!el || !result.value?.score) return
  if (!radar || radar.getDom() !== el) {
    radar?.dispose()
    radar = echarts.init(el)
  }
  const dims = result.value.score.dimensions
  radar.setOption({
    tooltip: {},
    radar: {
      indicator: dims.map((d) => ({ name: `${d.label}\n${d.score}`, max: 100 })),
      radius: '66%',
      splitNumber: 4,
      axisName: { fontSize: 11, color: '#4e5969' },
      splitLine: { lineStyle: { color: '#e8eaef' } },
      splitArea: { areaStyle: { color: ['#fafbfc', '#f3f5f8'] } },
      axisLine: { lineStyle: { color: '#e8eaef' } }
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map((d) => d.score),
        name: '风险得分',
        areaStyle: { color: 'rgba(13, 148, 136, 0.18)' },
        lineStyle: { color: '#0d9488', width: 2 },
        itemStyle: { color: '#0d9488' }
      }]
    }]
  }, true)
}

function resize() { radar?.resize() }

onMounted(() => {
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  radar?.dispose()
})
watch(() => projectStore.currentId, () => {
  // 切项目后清空旧结果，避免误把上一个项目的结论当成本项目的
  result.value = null
})
</script>

<style scoped>
.safety-page { display: flex; flex-direction: column; gap: 12px; }

.op-card { border: 1px solid #eceef2; border-radius: 10px; }
.op-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.op-left { display: flex; flex-direction: column; gap: 3px; }
.op-title { font-size: 15px; font-weight: 700; color: #1d2129; }
.op-sub { font-size: 12px; color: #86909c; }
.op-right { display: flex; align-items: center; gap: 12px; }

.empty-card { border: 1px solid #eceef2; border-radius: 10px; }
.empty-hint { font-size: 12px; color: #86909c; line-height: 1.8; margin-bottom: 12px; }

.overview { display: grid; grid-template-columns: 1.35fr 1fr; gap: 12px; }
.score-card, .radar-card, .dim-card, .panel, .disclaimer-card {
  border: 1px solid #eceef2; border-radius: 10px;
}
.score-main { display: flex; align-items: center; gap: 18px; }
.score-ring {
  width: 104px; height: 104px; border-radius: 50%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border: 6px solid var(--c);
  background: #fafbfc;
  flex-shrink: 0;
}
.score-num { font-size: 30px; font-weight: 800; color: var(--c); line-height: 1; }
.score-unit { font-size: 11px; color: #a9aeb8; margin-top: 2px; }
.score-meta { display: flex; flex-direction: column; gap: 6px; }
.level-tag {
  align-self: flex-start; color: #fff; font-size: 12px; font-weight: 700;
  padding: 2px 10px; border-radius: 10px;
}
.score-project { font-size: 14px; font-weight: 600; color: #1d2129; }
.score-time { font-size: 11px; color: #a9aeb8; }
.weight-bar { display: flex; height: 9px; border-radius: 5px; overflow: hidden; margin-top: 14px; }
.wb-seg { height: 100%; }
.weight-legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; font-size: 11px; color: #4e5969; }
.wl-item { display: inline-flex; align-items: center; gap: 4px; }
.wl-item i { width: 8px; height: 8px; border-radius: 2px; }
.wl-item em { color: #a9aeb8; font-style: normal; margin-left: 2px; }
.radar { height: 230px; }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.card-sub { font-size: 11px; color: #a9aeb8; font-weight: 400; }

.dim-item { padding: 10px 0; border-bottom: 1px dashed #f0f2f5; }
.dim-item:last-child { border-bottom: none; }
.dim-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dim-label { font-size: 13px; font-weight: 600; color: #1d2129; min-width: 76px; }
.dim-evidence { margin: 6px 0 0 0; padding-left: 18px; font-size: 12px; color: #4e5969; line-height: 1.8; }
.dim-advice { margin-top: 4px; font-size: 12px; color: #0d9488; line-height: 1.7; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.kpi-row { display: flex; gap: 10px; margin-bottom: 10px; }
.kpi { flex: 1; background: #f6f8fa; border-radius: 8px; padding: 10px; text-align: center; }
.kpi-num { font-size: 18px; font-weight: 700; color: #0d9488; }
.kpi-num.danger { color: #ef4444; }
.kpi-label { font-size: 11px; color: #86909c; margin-top: 2px; }
.ok-note { font-size: 12px; color: #22c55e; }
.class-list { display: flex; flex-direction: column; gap: 5px; margin-top: 6px; }
.class-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #4e5969; }
.cls-dot { width: 8px; height: 8px; border-radius: 50%; }
.cls-name { flex: 1; }
.cls-val { color: #1d2129; font-weight: 600; }

.risk-wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.risk-img { width: 100%; border-radius: 8px; border: 1px solid #eceef2; image-rendering: pixelated; }
.risk-side { display: flex; flex-direction: column; gap: 8px; }
.level-list { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; }
.level-item { display: inline-flex; align-items: center; gap: 5px; }
.lv-dot { width: 9px; height: 9px; border-radius: 2px; }
.lv-name { color: #4e5969; }
.lv-pct { color: #1d2129; font-weight: 600; }
.hotspot-head { font-size: 12px; font-weight: 600; color: #1d2129; margin-top: 4px; }

.disclaimer-card :deep(.el-card__body) { display: flex; gap: 10px; align-items: flex-start; }
.dc-icon { color: #f59e0b; font-size: 18px; margin-top: 2px; flex-shrink: 0; }
.dc-title { font-size: 12px; font-weight: 700; color: #b45309; margin-bottom: 3px; }
.dc-text { font-size: 12px; color: #4e5969; line-height: 1.8; }

@media (max-width: 1280px) {
  .overview { grid-template-columns: 1fr; }
  .two-col, .risk-wrap { grid-template-columns: 1fr; }
}
.safety-index {
  font-size: 13px; color: #1f2329; margin-top: 4px;
}
.safety-index b { font-size: 18px; color: #0d9488; margin: 0 2px; }
.si-level { color: #4e5969; font-size: 12px; }
.ahp-note { font-size: 11px; color: #a9aeb8; margin-top: 2px; }
</style>

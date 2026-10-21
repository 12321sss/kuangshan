<template>
  <div class="spatial-page">
    <!-- 顶栏：参数 + 执行 -->
    <el-card shadow="never" class="op-card">
      <div class="op-bar">
        <div class="op-left">
          <span class="op-title">空间关系与专项风险</span>
          <span class="op-hint">用现有解译结果叠地形，回答「水有没有淹到坑里、路有没有切在陡坡上」</span>
        </div>
        <div class="op-right">
          <span class="param-label">缓冲区</span>
          <el-input-number v-model="bufferKm" :min="0.5" :max="10" :step="0.5" :precision="1" size="small" style="width: 96px" />
          <span class="param-unit">km</span>
          <span class="param-label">陡坡阈值</span>
          <el-input-number v-model="slopeCutDeg" :min="5" :max="45" :step="1" size="small" style="width: 84px" />
          <span class="param-unit">°</span>
          <el-button type="primary" size="small" :loading="loading" @click="run">开始分析</el-button>
        </div>
      </div>
    </el-card>

    <el-card v-if="!result" shadow="never" class="empty-card">
      <el-empty description="还没有分析结果" :image-size="80">
        <div class="empty-tip">
          分析前请确认：已在「在线解译」提取过采坑／排土场／尾矿／道路／水体／植被，
          并在「边界管理」导入矿权范围（没有矿权时按解译范围的外包框计算）
        </div>
      </el-empty>
    </el-card>

    <template v-else-if="result.available">
      <!-- 结论概览 -->
      <div class="headline" :class="'lv-' + levelClass(result.summary?.headline ? topLevel() : '低')">
        <el-icon><WarningFilled /></el-icon>
        <div class="hl-text">
          <div class="hl-main">{{ result.summary?.headline }}</div>
          <div class="hl-sub">
            共 {{ result.summary?.total }} 项，可评估 {{ result.summary?.available }} 项 ·
            高 {{ result.summary?.high }} / 较高 {{ result.summary?.higher }} /
            中 {{ result.summary?.medium }} / 低 {{ result.summary?.low }}
          </div>
        </div>
      </div>

      <div class="main-grid">
        <!-- 左：六项卡片 -->
        <div class="items">
          <el-card
            v-for="item in result.items"
            :key="item.key"
            shadow="never"
            class="item-card"
            :class="{ disabled: !item.available }"
          >
            <div class="ic-head">
              <span class="ic-dot" :style="{ background: item.color }"></span>
              <span class="ic-title">{{ item.label }}</span>
              <el-tag size="small" :color="item.color" effect="dark" class="ic-tag">
                {{ item.available ? item.level : '不可用' }}
              </el-tag>
            </div>
            <div class="ic-finding">{{ item.finding }}</div>
            <div v-if="item.metrics.length" class="ic-metrics">
              <div v-for="m in item.metrics" :key="m.label" class="metric">
                <span class="mt-label">{{ m.label }}</span>
                <span class="mt-value">{{ m.value }}<span class="mt-unit">{{ m.unit }}</span></span>
              </div>
            </div>
            <div v-if="item.available" class="ic-advice">
              <el-icon><Position /></el-icon><span>{{ item.advice }}</span>
            </div>
            <div v-if="item.note" class="ic-note">{{ item.note }}</div>
          </el-card>
        </div>

        <!-- 右：专题图 + 采坑形态 -->
        <div class="side">
          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>叠加关系专题图</span>
                <div class="head-right">
                  <span class="card-hint">
                    {{ result.grid?.width }}×{{ result.grid?.height }} @ {{ result.grid?.mPerPixel }}m
                  </span>
                  <el-button v-if="result.imageBase64" link type="primary" size="small" @click="downloadImage">
                    下载 PNG
                  </el-button>
                </div>
              </div>
            </template>
            <img v-if="result.imageBase64" :src="'data:image/png;base64,' + result.imageBase64" class="overlay" alt="叠加图" />
            <div v-else class="no-img">无专题图</div>
            <div class="legend">
              <span v-for="l in result.legend" :key="l.label" class="lg-item">
                <i :style="{ background: l.color }"></i>{{ l.label }}
              </span>
            </div>
          </el-card>

          <el-card v-if="result.pitShapes?.length" shadow="never">
            <template #header>
              <div class="card-head">
                <span>采坑形态指标</span>
                <span class="card-hint">形状指数 1=正圆，越低越曲折</span>
              </div>
            </template>
            <el-table :data="result.pitShapes" size="small">
              <el-table-column prop="id" label="#" width="44" />
              <el-table-column label="面积" width="86">
                <template #default="{ row }">{{ row.areaHa }} ha</template>
              </el-table-column>
              <el-table-column label="周长" width="86">
                <template #default="{ row }">{{ row.perimeterM }} m</template>
              </el-table-column>
              <el-table-column label="形状指数" width="88">
                <template #default="{ row }">
                  <span :class="{ warn: row.shapeIndex < 0.35 }">{{ row.shapeIndex }}</span>
                </template>
              </el-table-column>
              <el-table-column label="等效推进" width="90">
                <template #default="{ row }">
                  {{ row.advanceM == null ? '—' : row.advanceM + ' m' }}
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </div>

      <div class="disclaimer">{{ result.disclaimer }}</div>
    </template>

    <el-card v-else shadow="never" class="empty-card">
      <el-empty :description="result.message || '分析不可用'" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { WarningFilled, Position } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import type { SpatialRelationsResult } from '@/api'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()
const loading = ref(false)
const result = ref<SpatialRelationsResult | null>(null)
const bufferKm = ref(2)
const slopeCutDeg = ref(15)

function levelClass(level: string) {
  return { 高: 'high', 较高: 'higher', 中: 'medium', 低: 'low' }[level] || 'low'
}

/** 取最高等级，用于顶部结论条配色 */
function topLevel(): string {
  const items = result.value?.items?.filter((i) => i.available) || []
  const order = ['高', '较高', '中', '低']
  for (const lv of order) {
    if (items.some((i) => i.level === lv)) return lv
  }
  return '低'
}

async function run() {
  const pid = projectStore.currentId
  if (!pid) {
    ElMessage.warning('请先在右上角选择工程')
    return
  }
  loading.value = true
  try {
    result.value = await analysisApi.spatialRelations(pid, bufferKm.value, slopeCutDeg.value)
    if (result.value.available && result.value.summary) {
      ElMessage.success(`分析完成：${result.value.summary.available} 项可评估`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '分析失败')
    result.value = null
  } finally {
    loading.value = false
  }
}

/** 专题图存成 PNG：报告和汇报材料里要用，不能只有屏幕上的 base64 */
function downloadImage() {
  const b64 = result.value?.imageBase64
  if (!b64) return
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'image/png' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // 文件名带上项目与日期，避免下载一堆同名的专题图
  const name = (result.value?.projectName || '项目').replace(/[\/:*?"<>|]/g, '_')
  a.download = `${name}-空间关系专题图-${new Date().toISOString().slice(0, 10)}.png`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(run)
watch(() => projectStore.currentId, () => { result.value = null; run() })
</script>

<style scoped>
.spatial-page { display: flex; flex-direction: column; gap: 12px; }

.op-card :deep(.el-card__body) { padding: 12px 16px; }
.op-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.op-title { font-size: 14px; font-weight: 600; color: #1f2937; margin-right: 10px; }
.op-hint { font-size: 12px; color: #a9aeb8; }
.op-right { display: flex; align-items: center; gap: 6px; }
.param-label { font-size: 12px; color: #6b7280; margin-left: 6px; }
.param-unit { font-size: 12px; color: #a9aeb8; }

.empty-card :deep(.el-card__body) { padding: 30px 16px; }
.empty-tip { font-size: 12px; color: #909399; line-height: 1.7; max-width: 520px; }

.headline {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px; border-radius: 8px; border-left: 4px solid #8bc34a;
  background: #f7f9f8;
}
.headline.lv-high { border-left-color: #d32f2f; background: #fef2f2; }
.headline.lv-higher { border-left-color: #ff9800; background: #fff7ed; }
.headline.lv-medium { border-left-color: #fbc02d; background: #fffbea; }
.headline :deep(.el-icon) { font-size: 18px; color: #6b7280; margin-top: 2px; }
.hl-main { font-size: 13px; color: #1f2937; font-weight: 600; line-height: 1.5; }
.hl-sub { font-size: 12px; color: #6b7280; margin-top: 2px; }

.main-grid { display: grid; grid-template-columns: 1fr 380px; gap: 12px; align-items: start; }
@media (max-width: 1300px) { .main-grid { grid-template-columns: 1fr; } }

.items { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1100px) { .items { grid-template-columns: 1fr; } }

.item-card :deep(.el-card__body) { padding: 12px 14px; }
.item-card.disabled { background: #fafafa; }
.ic-head { display: flex; align-items: center; gap: 7px; }
.ic-dot { width: 9px; height: 9px; border-radius: 50%; }
.ic-title { font-size: 13px; font-weight: 600; color: #1f2937; flex: 1; }
.ic-tag { border: none; color: #fff; font-weight: 500; }
.ic-finding { font-size: 12px; color: #4b5563; line-height: 1.65; margin-top: 8px; }
.ic-metrics { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 8px; }
.metric { display: flex; flex-direction: column; }
.mt-label { font-size: 11px; color: #9ca3af; }
.mt-value { font-size: 14px; font-weight: 600; color: #111827; }
.mt-unit { font-size: 11px; font-weight: 400; color: #9ca3af; margin-left: 2px; }
.ic-advice {
  display: flex; gap: 5px; align-items: flex-start;
  margin-top: 9px; padding-top: 8px; border-top: 1px dashed #eef0f3;
  font-size: 11px; color: #0f766e; line-height: 1.6;
}
.ic-note { font-size: 11px; color: #b45309; margin-top: 6px; line-height: 1.5; }

.side { display: flex; flex-direction: column; gap: 12px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.head-right { display: flex; align-items: center; gap: 6px; }
.head-right { display: flex; align-items: center; gap: 6px; }
.card-hint { font-size: 11px; color: #a9aeb8; }
.overlay { width: 100%; border-radius: 6px; border: 1px solid #eef0f3; image-rendering: pixelated; }
.no-img { font-size: 12px; color: #a9aeb8; text-align: center; padding: 30px 0; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; }
.lg-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #6b7280; }
.lg-item i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.warn { color: #d32f2f; font-weight: 600; }

.disclaimer { font-size: 11px; color: #a9aeb8; line-height: 1.6; padding: 0 2px 4px; }
</style>

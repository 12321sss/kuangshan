<template>
  <div class="share-page" v-loading="loading">
    <div v-if="errorMsg" class="share-error">
      <el-icon :size="40"><WarningFilled /></el-icon>
      <div class="se-title">{{ errorMsg }}</div>
      <div class="se-hint">该分享链接可能已过期或被撤销，请联系分享人重新生成。</div>
    </div>

    <template v-else-if="data">
      <!-- 顶部品牌 + 项目信息 -->
      <header class="share-head">
        <div class="sh-left">
          <div class="sh-logo">
            <svg viewBox="0 0 32 32" width="18" height="18"><path d="M6 22 L13 11 L18 17 L21 12 L26 22 Z" fill="#fff" /></svg>
          </div>
          <div>
            <div class="sh-brand">智慧矿山 · 数据分享</div>
            <div class="sh-sub">只读视图 · 数据来自平台真实解译记录</div>
          </div>
        </div>
        <div class="sh-right">
          <div class="sh-expire">有效期至 {{ (data.expiresAt || '').replace('T', ' ').slice(0, 16) }}</div>
        </div>
      </header>

      <!-- 项目概况 -->
      <section class="share-card">
        <div class="sc-title">{{ data.projectName }}</div>
        <div class="sc-meta">{{ data.region || '—' }}</div>
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-num">{{ data.recordCount }}</div>
            <div class="kpi-label">解译记录</div>
          </div>
          <div class="kpi">
            <div class="kpi-num">{{ data.classes.length }}</div>
            <div class="kpi-label">地物类型</div>
          </div>
          <div class="kpi">
            <div class="kpi-num">{{ totalKm2 }}</div>
            <div class="kpi-label">当前地物面积(km²)</div>
          </div>
        </div>
      </section>

      <!-- 地物构成 -->
      <section class="share-card">
        <div class="sc-title-sm">地物构成</div>
        <el-empty v-if="data.classes.length === 0" description="暂无解译数据" :image-size="70" />
        <div v-else class="class-list">
          <div v-for="c in data.classes" :key="c.classType" class="class-row">
            <span class="cl-dot" :style="{ background: classColor(c.classType) }"></span>
            <span class="cl-name">{{ classLabel(c.classType) }}</span>
            <span class="cl-area">{{ (c.totalAreaHa / 100).toFixed(2) }} km²</span>
            <span class="cl-count">{{ c.recordCount }} 条</span>
          </div>
        </div>
      </section>

      <!-- 解译记录明细 -->
      <section class="share-card">
        <div class="sc-title-sm">解译记录（最多显示 100 条）</div>
        <el-table :data="data.records" size="small" stripe>
          <el-table-column prop="name" label="记录名称" min-width="180" />
          <el-table-column label="地物类型" width="110">
            <template #default="{ row }">{{ classLabel(row.classType) }}</template>
          </el-table-column>
          <el-table-column prop="date" label="影像日期" width="120" />
          <el-table-column label="面积(km²)" width="110">
            <template #default="{ row }">{{ (row.areaHa / 100).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="覆盖率(%)" width="110">
            <template #default="{ row }">{{ (row.coveragePct || 0).toFixed(2) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <footer class="share-foot">{{ data.note }}</footer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { WarningFilled } from '@element-plus/icons-vue'
import { shareApi } from '@/api'

const route = useRoute()
const loading = ref(true)
const errorMsg = ref('')
const data = ref<Awaited<ReturnType<typeof shareApi.view>> | null>(null)

const CLASS_LABEL: Record<string, string> = {
  PIT: '采坑', DUMP: '排土场', TAILINGS: '尾矿库', BARE: '裸地扰动',
  VEGETATION: '植被', WATER: '水体', ROAD: '道路设施', BUILDING: '建筑', MOUNTAIN: '山体'
}
const CLASS_COLOR: Record<string, string> = {
  PIT: '#ef4444', DUMP: '#f59e0b', TAILINGS: '#8b5cf6', BARE: '#a8a29e',
  VEGETATION: '#22c55e', WATER: '#3b82f6', ROAD: '#78716c', BUILDING: '#f97316', MOUNTAIN: '#6b7280'
}
function classLabel(c: string) { return CLASS_LABEL[c] || c }
function classColor(c: string) { return CLASS_COLOR[c] || '#94a3b8' }

const totalKm2 = computed(() => {
  if (!data.value) return '0.00'
  const ha = data.value.classes.reduce((s, c) => s + c.totalAreaHa, 0)
  return (ha / 100).toFixed(2)
})

onMounted(async () => {
  const token = String(route.params.token || '')
  try {
    data.value = await shareApi.view(token)
  } catch (e: any) {
    errorMsg.value = e.message || '分享链接无效'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.share-page {
  min-height: 100vh;
  background: #f6f8fa;
  padding: 20px;
  max-width: 1100px;
  margin: 0 auto;
}

.share-error {
  margin-top: 15vh; text-align: center; color: #86909c;
}
.se-title { font-size: 16px; font-weight: 600; color: #1f2329; margin: 12px 0 6px; }
.se-hint { font-size: 13px; color: #a9aeb8; }

.share-head {
  display: flex; align-items: center; justify-content: space-between;
  background: linear-gradient(90deg, #0b6b62 0%, #0d9488 60%, #14b8a6 100%);
  border-radius: 12px; padding: 14px 18px; color: #fff; margin-bottom: 14px;
}
.sh-left { display: flex; align-items: center; gap: 12px; }
.sh-logo {
  width: 32px; height: 32px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.2);
  display: flex; align-items: center; justify-content: center;
}
.sh-brand { font-size: 15px; font-weight: 700; letter-spacing: 2px; }
.sh-sub { font-size: 11px; color: rgba(255, 255, 255, 0.78); margin-top: 2px; }
.sh-expire { font-size: 12px; color: rgba(255, 255, 255, 0.85); }

.share-card {
  background: #fff; border: 1px solid #eceef2; border-radius: 12px;
  padding: 16px 18px; margin-bottom: 12px;
}
.sc-title { font-size: 18px; font-weight: 700; color: #1f2329; }
.sc-meta { font-size: 12px; color: #86909c; margin-top: 4px; }
.sc-title-sm { font-size: 14px; font-weight: 600; color: #1f2329; margin-bottom: 10px; }

.kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px; }
.kpi { background: #f6f8fa; border-radius: 10px; padding: 12px; text-align: center; }
.kpi-num { font-size: 24px; font-weight: 700; color: #0d9488; }
.kpi-label { font-size: 12px; color: #86909c; margin-top: 2px; }

.class-list { display: flex; flex-direction: column; gap: 8px; }
.class-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.cl-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.cl-name { flex: 1; color: #1f2329; }
.cl-area { color: #0d9488; font-weight: 600; width: 100px; text-align: right; }
.cl-count { color: #a9aeb8; font-size: 12px; width: 60px; text-align: right; }

.share-foot { font-size: 12px; color: #a9aeb8; line-height: 1.6; padding: 8px 4px 30px; }

@media (max-width: 700px) {
  .share-page { padding: 12px; }
  .kpi-row { grid-template-columns: 1fr; }
  .share-head { flex-direction: column; align-items: flex-start; gap: 8px; }
}
</style>

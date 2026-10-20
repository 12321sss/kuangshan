<template>
  <el-card shadow="never" class="page-card" v-loading="loading">
    <template #header>
      <div class="head">
        <span>系统健康</span>
        <div class="head-right">
          <span v-if="result" class="summary" :class="{ ok: result.allOk, bad: !result.allOk }">
            {{ result.okCount }} / {{ result.total }} 正常
          </span>
          <el-button size="small" @click="load">重新检测</el-button>
        </div>
      </div>
    </template>

    <el-alert :type="allOk ? 'success' : 'warning'" :closable="false" class="tip">
      <template #title>
        <template v-if="allOk">所有依赖正常，演示可以正常进行。</template>
        <template v-else>存在异常依赖，演示前请先排查（顶部橙色项）。</template>
      </template>
    </el-alert>

    <el-empty v-if="!loading && !result" description="暂无检测结果">
      <el-button type="primary" size="small" @click="load">开始检测</el-button>
    </el-empty>

    <div v-else class="check-grid">
      <div v-for="item in result?.items || []" :key="item.name" class="check-card" :class="{ bad: !item.ok }">
        <div class="cc-head">
          <span class="cc-dot" :class="{ on: item.ok }"></span>
          <span class="cc-name">{{ item.name }}</span>
          <span class="cc-status">{{ item.ok ? '正常' : '异常' }}</span>
        </div>
        <div class="cc-target">{{ item.target }}</div>
        <div class="cc-foot">
          <span>耗时 {{ item.latencyMs }} ms</span>
        </div>
        <div v-if="item.error" class="cc-error">{{ item.error }}</div>
      </div>
    </div>

    <div class="foot-note">
      检测项：数据库（MySQL）、解译服务（inference）、天地图底图、AWS STAC 影像源。
      每项独立 3 秒超时，互不影响。
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { healthApi } from '@/api'

interface CheckItem {
  name: string
  target: string
  ok: boolean
  error?: string
  latencyMs: number
}

const loading = ref(false)
const result = ref<{ items: CheckItem[]; okCount: number; total: number; allOk: boolean } | null>(null)

const allOk = computed(() => result.value?.allOk ?? false)

async function load() {
  loading.value = true
  try {
    result.value = await healthApi.checks()
  } catch (e: any) {
    // 健康检查自身失败：说明后端不可用
    ElMessage.error('健康检查失败：' + e.message)
    result.value = {
      items: [{ name: '业务后端', target: '/api/health/checks', ok: false, error: e.message, latencyMs: 0 }],
      okCount: 0, total: 1, allOk: false
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-card { border: 1px solid #eceef2; border-radius: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.head-right { display: flex; align-items: center; gap: 10px; }
.summary { font-size: 13px; font-weight: 600; }
.summary.ok { color: #16a34a; }
.summary.bad { color: #f59e0b; }
.tip { margin-bottom: 14px; }

.check-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.check-card {
  border: 1px solid #d6f5e3; background: #f6fef9;
  border-radius: 10px; padding: 12px 14px;
}
.check-card.bad { border-color: #fde2c8; background: #fffaf4; }
.cc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.cc-dot { width: 9px; height: 9px; border-radius: 50%; background: #f59e0b; }
.cc-dot.on { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16); }
.cc-name { font-size: 13px; font-weight: 600; color: #1f2329; flex: 1; }
.cc-status { font-size: 12px; color: #16a34a; }
.check-card.bad .cc-status { color: #f59e0b; }
.cc-target { font-size: 11px; color: #86909c; word-break: break-all; }
.cc-foot { font-size: 11px; color: #a9aeb8; margin-top: 6px; }
.cc-error { margin-top: 6px; font-size: 11px; color: #ef4444; word-break: break-all; }

.foot-note { margin-top: 14px; font-size: 12px; color: #a9aeb8; line-height: 1.6; }
</style>

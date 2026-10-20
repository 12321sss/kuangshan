<template>
  <div class="ts-panel">
    <div class="ts-header">
      <span class="ts-title">时序播放</span>
      <el-select
        v-model="currentSignature"
        size="small"
        placeholder="选择监测区域"
        style="width: 200px"
        :loading="loadingGroups"
        @change="loadSequence"
      >
        <el-option
          v-for="g in groups"
          :key="g.signature"
          :value="g.signature"
          :label="`${g.label} · ${g.periodCount}期`"
        />
      </el-select>
      <span v-if="currentGroup" class="ts-summary">
        {{ currentGroup.startDate }} → {{ currentGroup.endDate }}
        <b :class="currentGroup.areaChangeHa >= 0 ? 'up' : 'down'">
          {{ currentGroup.areaChangeHa >= 0 ? '+' : '' }}{{ haToKm2(currentGroup.areaChangeHa) }} km²
        </b>
      </span>
    </div>

    <div v-if="!groups.length" class="ts-empty">
      暂无时序数据。对<b>同一区域</b>用不同日期的影像各提取一次，这里就会按时间串起来。
    </div>

    <div v-else-if="!sequence.length" class="ts-empty">该区域暂无提取记录</div>

    <div v-else class="ts-play">
      <el-button-group size="small">
        <el-button :icon="CaretLeft" @click="step(-1)" :disabled="currentIndex <= 0" />
        <el-button :type="playing ? 'primary' : 'default'" :icon="playing ? VideoPause : VideoPlay"
                   @click="togglePlay" />
        <el-button :icon="CaretRight" @click="step(1)"
                   :disabled="currentIndex >= sequence.length - 1" />
      </el-button-group>

      <el-slider
        v-model="currentIndex"
        :min="0"
        :max="sequence.length - 1"
        :step="1"
        :format-tooltip="fmtTooltip"
        :disabled="sequence.length < 2"
        @input="onSlide"
      />

      <div class="ts-meta">
        <span class="ts-date">{{ currentItem?.date || '-' }}</span>
        <span class="ts-stat">提取面积 <b>{{ haToKm2(currentItem?.extractAreaHa) }}</b> km²</span>
        <span class="ts-stat">覆盖率 <b>{{ currentItem?.coveragePct ?? '-' }}</b> %</span>
        <span class="ts-stat">影像 {{ currentItem?.satellite || '-' }}</span>
      </div>

      <!-- 各期面积迷你趋势，一眼看出变化趋势 -->
      <div class="ts-trend">
        <div
          v-for="(s, i) in sequence"
          :key="s.id"
          class="ts-bar"
          :class="{ active: i === currentIndex }"
          :title="`${s.date} · ${haToKm2(s.extractAreaHa)} km²`"
          @click="currentIndex = i; onSlide()"
        >
          <div class="ts-bar-fill" :style="{ height: barHeight(s) }"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CaretLeft, CaretRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { timeSeriesApi } from '@/api'
import { haToKm2 } from '@/utils/format'

const props = defineProps<{
  projectId?: number
  /** 父组件（地图）接收当前期索引，据此切换显示的多边形 */
  onFrame?: (seqItem: Record<string, unknown> | null) => void
}>()

const emit = defineEmits<{ (e: 'frame', item: Record<string, unknown> | null): void }>()

const groups = ref<any[]>([])
const sequence = ref<any[]>([])
const currentSignature = ref<string>('')
const currentIndex = ref(0)
const loadingGroups = ref(false)
const playing = ref(false)
let timer: number | null = null

const currentGroup = computed(() => groups.value.find((g) => g.signature === currentSignature.value) || null)
const currentItem = computed(() => sequence.value[currentIndex.value] || null)

const maxArea = computed(() => Math.max(...sequence.value.map((s) => s.extractAreaHa || 0), 1))

function barHeight(s: any) {
  const h = ((s.extractAreaHa || 0) / maxArea.value) * 100
  return Math.max(h, 4) + '%'
}

function fmtTooltip(idx: number) {
  const s = sequence.value[idx]
  return s ? `${s.date}：${haToKm2(s.extractAreaHa)} km²` : ''
}

async function loadGroups() {
  loadingGroups.value = true
  try {
    groups.value = await timeSeriesApi.groups(props.projectId)
    // 默认选期数最多的一组
    if (groups.value.length && !currentSignature.value) {
      currentSignature.value = groups.value[0].signature
      await loadSequence()
    }
  } catch (e: any) {
    ElMessage.error('时序分组加载失败：' + (e.message || ''))
  } finally {
    loadingGroups.value = false
  }
}

async function loadSequence() {
  if (!currentSignature.value) {
    sequence.value = []
    return
  }
  try {
    sequence.value = await timeSeriesApi.sequence(currentSignature.value)
    currentIndex.value = 0
    onSlide()
  } catch (e: any) {
    ElMessage.error('时序序列加载失败：' + (e.message || ''))
  }
}

function onSlide() {
  const item = currentItem.value
  emit('frame', item || null)
  props.onFrame?.(item || null)
}

function step(delta: number) {
  const next = currentIndex.value + delta
  if (next < 0 || next >= sequence.value.length) return
  currentIndex.value = next
  onSlide()
}

function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    if (sequence.value.length < 2) {
      playing.value = false
      return
    }
    timer = window.setInterval(() => {
      if (currentIndex.value >= sequence.value.length - 1) {
        currentIndex.value = 0     // 循环播放
      } else {
        currentIndex.value++
      }
      onSlide()
    }, 1500)
  } else if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

watch(() => props.projectId, () => {
  currentSignature.value = ''
  sequence.value = []
  loadGroups()
})

watch(() => currentIndex.value, onSlide)

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  timer = null
})

// 初始加载
loadGroups()
</script>

<style scoped>
.ts-panel {
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color);
  padding: 8px 12px 10px;
}
.ts-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.ts-title {
  font-size: 13px;
  font-weight: 500;
}
.ts-summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ts-summary b.up {
  color: var(--el-color-danger);
}
.ts-summary b.down {
  color: var(--el-color-success);
}
.ts-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  padding: 4px 0;
}
.ts-play {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ts-meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  align-items: baseline;
}
.ts-date {
  font-size: 13px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}
.ts-stat b {
  color: var(--el-text-color-primary);
}
.ts-trend {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 34px;
  padding: 0 2px;
}
.ts-bar {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  cursor: pointer;
}
.ts-bar-fill {
  width: 100%;
  background: var(--el-color-primary-light-3);
  border-radius: 2px 2px 0 0;
  transition: background 0.2s;
}
.ts-bar.active .ts-bar-fill {
  background: var(--el-color-primary);
}
</style>
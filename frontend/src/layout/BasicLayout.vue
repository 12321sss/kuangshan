<template>
  <div class="layout">
    <!-- 顶部导航（青色顶栏 + 横向模块菜单 + 全局工程切换器） -->
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 32 32" width="18" height="18"><path d="M6 22 L13 11 L18 17 L21 12 L26 22 Z" fill="#fff" /></svg>
        </div>
        <span class="brand-name">智慧矿山</span>
      </div>
      <nav class="topnav">
        <div
          v-for="m in visibleModules"
          :key="m.key"
          class="topnav-item"
          :class="{ active: activeModule === m.key }"
          @click="goModule(m)"
        >
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </div>
        <!-- GIS 大屏：直接跳转，不要下拉 -->
        <div v-if="auth.hasPage('page:screen')" class="topnav-item" @click="goScreen">
          <el-icon><MapLocation /></el-icon>
          <span>GIS 大屏</span>
        </div>
      </nav>
      <div class="topbar-right">
        <!-- 全局搜索：聚合工程/影像/解译/告警 -->
        <div class="global-search">
          <el-icon class="gs-icon"><Search /></el-icon>
          <input
            v-model="searchKeyword"
            class="gs-input"
            placeholder="搜索工程 / 影像 / 记录 / 告警"
            @input="onSearchInput"
            @focus="searchOpen = searchKeyword.length > 0"
            @keydown.esc="searchOpen = false"
          />
          <!-- 搜索结果下拉 -->
          <div v-if="searchOpen && searchResults.length > 0" class="gs-panel">
            <div
              v-for="(r, i) in searchResults"
              :key="i"
              class="gs-item"
              @mousedown.prevent="gotoSearchResult(r)"
            >
              <el-tag size="small" type="info">{{ r.typeLabel }}</el-tag>
              <span class="gs-item-name">{{ r.name }}</span>
            </div>
          </div>
          <div v-else-if="searchOpen && searchKeyword && !searching" class="gs-panel">
            <div class="gs-empty">未找到匹配内容</div>
          </div>
        </div>

        <!-- 消息中心：未读告警通知 -->
        <el-badge :value="unreadCount" :hidden="unreadCount === 0" class="bell-badge">
          <div class="bell" title="消息中心" @click="openNotifications">
            <el-icon><Bell /></el-icon>
          </div>
        </el-badge>

        <!-- 全局工程切换器：所有页面数据以它为过滤条件 -->
        <el-select
          :model-value="projectStore.currentId"
          size="small"
          class="project-select"
          placeholder="请选择工程"
          @change="(v: number) => projectStore.set(v)"
        >
          <el-option v-for="p in projectStore.projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-dropdown @command="onCommand">
          <div class="user-chip">
            <el-icon><UserFilled /></el-icon>
            <span>{{ auth.user?.displayName || '未登录' }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ roleLabel }}</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 消息中心抽屉 -->
    <el-drawer v-model="notifyVisible" title="消息中心" size="380px">
      <div v-if="notifications.length === 0" class="notify-empty">暂无消息</div>
      <div v-for="n in notifications" :key="n.id" class="notify-item" :class="{ unread: !n.read }">
        <div class="ni-head">
          <el-tag size="small" :type="n.level === 'RED' ? 'danger' : 'warning'">{{ n.levelLabel }}</el-tag>
          <span class="ni-time">{{ n.time }}</span>
        </div>
        <div class="ni-title">{{ n.title }}</div>
        <div class="ni-body">{{ n.body }}</div>
      </div>
      <template #footer>
        <el-button size="small" @click="markAllRead" :disabled="unreadCount === 0">全部标为已读</el-button>
      </template>
    </el-drawer>

    <div class="body">
      <!-- 左侧菜单：随顶部模块切换，按页面权限过滤；可折叠 -->
      <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div v-for="group in currentGroups" :key="group.title" class="menu-group">
          <div class="group-title">{{ group.title }}</div>
          <div
            v-for="item in group.items"
            :key="item.path"
            class="menu-item"
            :class="{ active: route.path === item.path }"
            @click="goPage(item)"
          >
            {{ item.title }}
          </div>
        </div>
        <!-- 折叠按钮：收起侧边栏，给内容区腾空间 -->
        <div class="sidebar-collapse" @click="sidebarCollapsed = true">
          <el-icon><Fold /></el-icon>
          <span>收起菜单</span>
        </div>
      </aside>

      <!-- 内容区：页签栏 + 页面 -->
      <section class="content">
        <div class="tabs-bar">
          <!-- 展开按钮：侧边栏收起后从这里恢复 -->
          <div v-if="sidebarCollapsed" class="expand-btn" @click="sidebarCollapsed = false">
            <el-icon><Expand /></el-icon>
          </div>
          <!-- 页签横向滚动容器（隐藏滚动条，超宽时滚轮滚动） -->
          <div ref="tabsScrollRef" class="tabs-scroll" @wheel.prevent="onTabsWheel">
            <div
              v-for="tab in tabsStore.tabs"
              :key="tab.path"
              class="tab"
              :class="{ active: tabsStore.active === tab.path }"
              :title="tab.title"
              @click="goTab(tab.path)"
            >
              <span class="tab-dot"></span>
              <span class="tab-text">{{ tab.title }}</span>
              <el-icon v-if="tabsStore.tabs.length > 1" class="tab-close" @click.stop="closeTab(tab.path)">
                <Close />
              </el-icon>
            </div>
          </div>
          <!-- 溢出下拉：页签过多时从这里选择，避免挤压变形 -->
          <el-dropdown v-if="tabsStore.tabs.length > 4" trigger="click" @command="goTab">
            <div class="tabs-more" title="全部页签">
              <el-icon><MoreFilled /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="tab in tabsStore.tabs"
                  :key="tab.path"
                  :command="tab.path"
                  :class="{ 'is-active-tab': tabsStore.active === tab.path }"
                >
                  {{ tab.title }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <!-- 关闭全部 -->
          <div v-if="tabsStore.tabs.length > 1" class="tabs-clear" title="关闭其他页签" @click="closeOthers">
            <el-icon><CircleClose /></el-icon>
          </div>
        </div>
        <main class="page">
          <router-view />
        </main>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Odometer, Monitor, Bell, Tools, DataAnalysis, Cpu, Setting,
  UserFilled, MapLocation, Close, Fold, Expand, MoreFilled, CircleClose, Search
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useTabsStore } from '@/stores/tabs'
import { useProjectStore } from '@/stores/project'
import { alarmApi, searchApi } from '@/api'

const route = useRoute()
const router = useRouter()
/** 侧边栏折叠状态：收起后页签栏左侧出现展开按钮 */
const sidebarCollapsed = ref(false)
const auth = useAuthStore()
const tabsStore = useTabsStore()
const projectStore = useProjectStore()

interface MenuItem { path: string; title: string; perm: string }
interface MenuGroup { title: string; items: MenuItem[] }
interface Module { key: string; label: string; icon: any; firstPath: string; perm: string }

/** 顶部模块 -> 左侧菜单组（每项携带页面权限点，按当前用户过滤）
 *
 * 五大功能域（2026-10-19 重构）：
 *  ① 总览（首页）  ② 遥感解译（影像库+遥感提取+变化分析）
 *  ③ 监测告警（设备监测+预警告警）  ④ 报告中心（数据分析+报告生成）  ⑤ 平台管理
 */
const modules: Module[] = [
  { key: 'home', label: '总览', icon: Odometer, firstPath: '/', perm: 'page:dashboard' },
  { key: 'rs', label: '遥感解译', icon: Cpu, firstPath: '/imagery', perm: 'page:imagery' },
  { key: 'iot', label: '监测告警', icon: Monitor, firstPath: '/monitor/data', perm: 'page:monitor' },
  { key: 'report', label: '报告中心', icon: DataAnalysis, firstPath: '/analysis', perm: 'page:analysis' },
  { key: 'platform', label: '平台管理', icon: Setting, firstPath: '/platform/projects', perm: 'page:projects' }
]

const moduleMenus: Record<string, MenuGroup[]> = {
  home: [{ title: '总览', items: [{ path: '/', title: '总览', perm: 'page:dashboard' }] }],
  rs: [{
    title: '遥感解译',
    items: [
      { path: '/imagery', title: '影像库', perm: 'page:imagery' },
      { path: '/remote-extract', title: '遥感提取（在线）', perm: 'page:extract' },
      { path: '/extract', title: '影像解译（本地）', perm: 'page:extract' },
      { path: '/compare', title: '数据对比', perm: 'page:extract' }
    ]
  }],
  iot: [{
    title: '监测告警',
    items: [
      { path: '/monitor/data', title: '设备监测', perm: 'page:monitor' },
      { path: '/ops/stations', title: '站点监控', perm: 'page:ops-stations' },
      { path: '/warning/rules', title: '预警设置', perm: 'page:warning-rules' },
      { path: '/warning/alarms', title: '告警日志', perm: 'page:warning-alarms' }
    ]
  }],
  report: [{
    title: '报告中心',
    items: [
      { path: '/analysis', title: '数据分析', perm: 'page:analysis' },
      { path: '/analysis/safety', title: '安全评估', perm: 'page:analysis' },
      { path: '/report', title: '报告生成', perm: 'page:analysis' }
    ]
  }],
  platform: [{
    title: '平台管理',
    items: [
      { path: '/platform/projects', title: '项目管理', perm: 'page:projects' },
      { path: '/platform/users', title: '用户中心', perm: 'page:users' },
      { path: '/platform/roles', title: '角色管理', perm: 'page:roles' },
      { path: '/platform/audit-logs', title: '操作日志', perm: 'page:audit-logs' },
      { path: '/platform/dict', title: '数据字典', perm: 'page:dict' },
      { path: '/platform/health', title: '系统健康', perm: 'page:health' },
      { path: '/platform/trash', title: '回收站', perm: 'page:extract' }
    ]
  }]
}

// 模块可见性：多子项模块，只要有一个子页可见就显示
const MODULE_GROUP_PERMS: Record<string, string[]> = {
  rs: ['page:imagery', 'page:extract', 'page:analysis'],
  iot: ['page:monitor', 'page:ops-stations', 'page:warning-rules', 'page:warning-alarms'],
  report: ['page:analysis'],
  platform: ['page:projects', 'page:users', 'page:roles', 'page:audit-logs', 'page:dict', 'page:health']
}

const visibleModules = computed(() =>
  modules.filter((m) => {
    const groupPerms = MODULE_GROUP_PERMS[m.key]
    if (groupPerms) return groupPerms.some((p) => auth.hasPage(p))
    return auth.hasPage(m.perm)
  })
)

const activeModule = computed(() => (route.meta.module as string) || 'home')
const currentGroups = computed(() => {
  const groups = moduleMenus[activeModule.value] || moduleMenus.home
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => auth.hasPage(i.perm)) }))
    .filter((g) => g.items.length > 0)
})

const roleLabel = computed(() => {
  // 角色名改从角色表来会更准；这里先展示角色编码，角色管理页有中文名
  const map: Record<string, string> = {
    ADMIN: '系统管理员', MANAGER: '项目管理员', ANALYST: '解译分析师', VIEWER: '观察员'
  }
  return map[auth.user?.role || ''] || auth.user?.role || ''
})

// ---- 全局搜索 ----
interface SearchHit { type: string; typeLabel: string; name: string; path: string }
const searchKeyword = ref('')
const searchResults = ref<SearchHit[]>([])
const searchOpen = ref(false)
const searching = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | undefined

function onSearchInput() {
  searchOpen.value = searchKeyword.value.length > 0
  if (searchTimer) clearTimeout(searchTimer)
  const kw = searchKeyword.value.trim()
  if (!kw) { searchResults.value = []; return }
  // 300ms 防抖，避免每敲一个字就请求
  searchTimer = setTimeout(async () => {
    searching.value = true
    try {
      searchResults.value = await searchApi.global(kw)
      searchOpen.value = true
    } catch {
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }, 300)
}

function gotoSearchResult(r: SearchHit) {
  searchOpen.value = false
  searchKeyword.value = ''
  searchResults.value = []
  router.push(r.path)
}

// ---- 消息中心（未读告警） ----
interface Notification {
  id: number | string
  title: string
  body: string
  level: string
  levelLabel: string
  time: string
  read: boolean
}
const notifyVisible = ref(false)
const notifications = ref<Notification[]>([])
const unreadCount = computed(() => notifications.value.filter((n) => !n.read).length)

const LEVEL_LABEL: Record<string, string> = {
  RED: '红色', ORANGE: '橙色', YELLOW: '黄色', BLUE: '蓝色'
}

async function loadNotifications() {
  if (!auth.isLoggedIn) return
  try {
    const list = await alarmApi.list(projectStore.currentId ?? undefined)
    // 只把未关闭的告警作为消息；已读状态存 localStorage
    const readIds: number[] = JSON.parse(localStorage.getItem('rs_read_notifications') || '[]')
    notifications.value = list
      .filter((a) => a.status !== 'RESOLVED')
      .slice(0, 20)
      .map((a) => ({
        id: a.id,
        title: `${a.sensorName} · ${a.indicator}`,
        body: `当前值 ${a.value}${a.unit || ''}，阈值 ${a.threshold}${a.unit || ''}（${a.status === 'UNACK' ? '未确认' : '已确认'}）`,
        level: a.level,
        levelLabel: LEVEL_LABEL[a.level] || a.level,
        time: (a.createdAt || '').replace('T', ' ').slice(0, 16),
        read: readIds.includes(a.id)
      }))
  } catch {
    notifications.value = []
  }
}

function openNotifications() {
  notifyVisible.value = true
  loadNotifications()
}

function markAllRead() {
  const ids = notifications.value.map((n) => Number(n.id))
  const prev: number[] = JSON.parse(localStorage.getItem('rs_read_notifications') || '[]')
  localStorage.setItem('rs_read_notifications', JSON.stringify(Array.from(new Set([...prev, ...ids]))))
  notifications.value.forEach((n) => (n.read = true))
  ElMessage.success('已全部标为已读')
}

function goModule(m: Module) {
  // 模块首页可能被权限过滤，落到第一个可见子页
  const groups = (moduleMenus[m.key] || [])
    .map((g) => ({ ...g, items: g.items.filter((i) => auth.hasPage(i.perm)) }))
    .filter((g) => g.items.length > 0)
  const first = groups[0]?.items[0]
  router.push(first ? first.path : m.firstPath)
}

function goPage(item: MenuItem) {
  router.push(item.path)
}

function goTab(path: string) {
  tabsStore.active = path
  router.push(path)
}

/** 关闭其他页签，只保留当前 */
function closeOthers() {
  const cur = tabsStore.active
  const others = tabsStore.tabs.filter((t) => t.path !== cur).map((t) => t.path)
  others.forEach((p) => tabsStore.close(p))
  // close 会返回兜底路径，这里确保仍停在当前页
  if (tabsStore.active !== cur) tabsStore.active = cur
}

/** 页签过多：滚轮转横向滚动 */
const tabsScrollRef = ref<HTMLDivElement>()
function onTabsWheel(e: WheelEvent) {
  const el = tabsScrollRef.value
  if (!el) return
  if (el.scrollWidth <= el.clientWidth) return
  el.scrollLeft += e.deltaY || e.deltaX
  e.preventDefault()
}
/** 激活页签自动滚入可视区 */
function scrollActiveIntoView() {
  nextTick(() => {
    const el = tabsScrollRef.value
    if (!el) return
    const active = el.querySelector('.tab.active') as HTMLElement | null
    if (active) {
      const left = active.offsetLeft
      const right = left + active.offsetWidth
      if (left < el.scrollLeft) el.scrollLeft = left - 8
      else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth + 8
    }
  })
}

function closeTab(path: string) {
  const next = tabsStore.close(path)
  if (route.path === path) {
    router.push(next)
  }
}

function goScreen() {
  router.push('/screen')
}

async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    await auth.logout()
    projectStore.reset()
    router.push('/login')
  }
}

// 登录态就绪后加载项目清单（含静默刷新恢复的会话）
watch(
  () => auth.isLoggedIn,
  async (logged) => {
    if (logged && projectStore.projects.length === 0) {
      try {
        await projectStore.load()
      } catch {
        // 项目加载失败不阻塞页面，由各页面自行报错
      }
    }
    if (logged) loadNotifications()
  },
  { immediate: true }
)

// 切换项目 -> 重新拉取本项目未读消息
watch(() => projectStore.currentId, () => loadNotifications())

// 点击页面其他区域关闭搜索下拉
onMounted(() => {
  document.addEventListener('click', (e) => {
    const el = e.target as HTMLElement
    if (!el.closest('.global-search')) searchOpen.value = false
  })
})

// 路由变化 -> 页签登记
watch(
  () => route.path,
  () => {
    if (route.meta.title) {
      tabsStore.open(route.path, route.meta.title as string)
    }
    scrollActiveIntoView()
  },
  { immediate: true }
)
</script>

<style scoped>
.layout { height: 100%; display: flex; flex-direction: column; }

/* ---- 顶部导航 ---- */
.topbar {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  background: linear-gradient(90deg, #0b6b62 0%, #0d9488 60%, #14b8a6 100%);
  color: #fff;
  padding: 0 12px;
  gap: 10px;
}

.brand { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.brand-logo {
  width: 28px; height: 28px; border-radius: 6px;
  background: rgba(255, 255, 255, 0.2);
  display: flex; align-items: center; justify-content: center;
}

.brand-name { font-size: 16px; font-weight: 700; letter-spacing: 4px; white-space: nowrap; }

.topnav { display: flex; height: 100%; flex: 1; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.topnav::-webkit-scrollbar { display: none; }

.topnav-item {
  display: flex; align-items: center; gap: 5px;
  padding: 0 12px; font-size: 13px; cursor: pointer;
  color: rgba(255, 255, 255, 0.82);
  transition: background 0.15s;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;
}

.topnav-item:hover { background: rgba(255, 255, 255, 0.12); }
.topnav-item.active {
  background: rgba(255, 255, 255, 0.18);
  color: #fff; font-weight: 600;
  box-shadow: inset 0 -2px 0 #fff;
}

.topbar-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }

/* ---- 全局搜索 ---- */
.global-search {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  height: 30px; padding: 0 10px;
  width: 230px;
  background: rgba(255, 255, 255, 0.16);
  border-radius: 16px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.28) inset;
}
.gs-icon { color: rgba(255, 255, 255, 0.8); font-size: 14px; flex-shrink: 0; }
.gs-input {
  flex: 1; min-width: 0;
  border: none; outline: none; background: transparent;
  color: #fff; font-size: 12px;
}
.gs-input::placeholder { color: rgba(255, 255, 255, 0.65); }

.gs-panel {
  position: absolute; top: 36px; left: 0; right: 0;
  max-height: 320px; overflow-y: auto;
  background: #fff; border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
  padding: 6px; z-index: 3000;
}
.gs-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 8px; border-radius: 6px; cursor: pointer;
  font-size: 12px; color: #1f2329;
}
.gs-item:hover { background: #f2f7f6; }
.gs-item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gs-empty { padding: 10px 8px; font-size: 12px; color: #a9aeb8; }

/* ---- 消息铃铛 ---- */
.bell-badge { display: flex; align-items: center; }
.bell {
  width: 30px; height: 30px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff; cursor: pointer; font-size: 16px;
}
.bell:hover { background: rgba(255, 255, 255, 0.18); }

.notify-empty { color: #a9aeb8; font-size: 13px; text-align: center; padding: 30px 0; }
.notify-item { padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.notify-item.unread .ni-title { font-weight: 600; color: #1f2329; }
.ni-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.ni-time { font-size: 11px; color: #a9aeb8; }
.ni-title { font-size: 13px; color: #4e5969; margin-bottom: 2px; }
.ni-body { font-size: 12px; color: #86909c; line-height: 1.5; }

/* 工程切换器 */
.project-select { width: 200px; }
.project-select :deep(.el-select__wrapper) {
  background: rgba(255, 255, 255, 0.15);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.35) inset;
}
.project-select :deep(.el-select__selected-item) { color: #fff; }
.project-select :deep(.el-select__placeholder) { color: rgba(255, 255, 255, 0.7); }

.user-chip {
  display: flex; align-items: center; gap: 6px;
  color: #fff; font-size: 13px; cursor: pointer; outline: none;
}

/* ---- 主体 ---- */
.body { flex: 1; display: flex; min-height: 0; }

.sidebar {
  width: 176px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #e5e6eb;
  padding: 8px 0;
  overflow-y: auto;
  transition: width 0.2s ease;
  display: flex;
  flex-direction: column;
}
.sidebar.collapsed {
  width: 0;
  padding: 0;
  border-right: none;
  overflow: hidden;
}
.sidebar-collapse {
  margin-top: auto;
  padding: 10px 16px;
  font-size: 12px;
  color: #86909c;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  border-top: 1px solid #f0f2f5;
  user-select: none;
}
.sidebar-collapse:hover { color: #0d9488; background: #f2f7f6; }

.expand-btn {
  width: 28px; height: 28px;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #4e5969; cursor: pointer;
  border-radius: 6px;
  margin-right: 4px;
}
.expand-btn:hover { background: #e8eaee; color: #0d9488; }

.menu-group { margin-bottom: 4px; }

.group-title {
  padding: 10px 16px 6px;
  font-size: 12px;
  color: #a9aeb8;
}

.menu-item {
  padding: 9px 16px 9px 24px;
  font-size: 13px;
  color: #4e5969;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.12s;
}

.menu-item:hover { background: #f2f7f6; color: #0d9488; }
.menu-item.active {
  background: #e6f6f4;
  color: #0d9488;
  font-weight: 600;
  border-left-color: #0d9488;
}

.content { flex: 1; display: flex; flex-direction: column; min-width: 0; }

/* ---- 页签栏 ---- */
.tabs-bar {
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding: 0 8px 0 12px;
  background: #f0f2f5;
  border-bottom: 1px solid #e5e6eb;
  min-width: 0;
}

/* 横向滚动容器：隐藏原生滚动条，滚轮可横向滚 */
.tabs-scroll {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-end;
  gap: 4px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;      /* Firefox */
  -ms-overflow-style: none;   /* IE */
}
.tabs-scroll::-webkit-scrollbar { display: none; }

.tab {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 10px 6px 12px;
  font-size: 12px;
  color: #4e5969;
  background: #e8eaee;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;   /* 关键：禁止被压缩，超出时由容器横向滚动 */
  max-width: 150px;
}
.tab-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 96px;
}

.tab.active { background: #fff; color: #0d9488; font-weight: 600; }

.tab-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #c9cdd4;
  flex-shrink: 0;
}

.tab.active .tab-dot { background: #0d9488; }

.tab-close { font-size: 12px; border-radius: 50%; flex-shrink: 0; }
.tab-close:hover { background: #d4d7de; }

/* 溢出下拉 + 关闭其他 */
.tabs-more, .tabs-clear {
  width: 24px; height: 28px;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #86909c; cursor: pointer; border-radius: 6px; margin-bottom: 2px;
}
.tabs-more:hover, .tabs-clear:hover { background: #e2e5ea; color: #0d9488; }
.is-active-tab { color: #0d9488; font-weight: 600; }

.page { flex: 1; overflow: auto; padding: 16px; background: #f6f8fa; }

/* ---- 响应式：窄屏适配（笔记本 1366 / 平板 / 手机）---- */
@media (max-width: 1440px) {
  /* 中等屏收窄搜索框与工程切换器 */
  .global-search { width: 180px; }
  .project-select { width: 160px !important; }
}

@media (max-width: 1200px) {
  /* 小屏隐藏搜索框文字，只留图标入口 */
  .global-search { width: 34px; padding: 0 9px; }
  .gs-input { display: none; }
  .global-search:focus-within {
    position: absolute; right: 12px; width: 220px; z-index: 3000;
    background: #0d9488;
  }
  .global-search:focus-within .gs-input { display: block; }
  .brand-name { display: none; }
  .sidebar { width: 150px; }
  .page { padding: 12px; }
}

@media (max-width: 900px) {
  /* 手机：侧边栏默认收起、顶栏只留核心项 */
  .sidebar { position: absolute; left: 0; top: 48px; bottom: 0; z-index: 900;
    box-shadow: 4px 0 16px rgba(0,0,0,0.12); }
  .project-select { display: none; }
  .page { padding: 10px; }
  .tabs-bar { height: 32px; }
}
</style>

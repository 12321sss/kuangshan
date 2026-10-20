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

    <div class="body">
      <!-- 左侧菜单：随顶部模块切换，按页面权限过滤 -->
      <aside class="sidebar">
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
      </aside>

      <!-- 内容区：页签栏 + 页面 -->
      <section class="content">
        <div class="tabs-bar">
          <div
            v-for="tab in tabsStore.tabs"
            :key="tab.path"
            class="tab"
            :class="{ active: tabsStore.active === tab.path }"
            @click="goTab(tab.path)"
          >
            <span class="tab-dot"></span>
            {{ tab.title }}
            <el-icon v-if="tabsStore.tabs.length > 1" class="tab-close" @click.stop="closeTab(tab.path)">
              <Close />
            </el-icon>
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
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Odometer, Monitor, Bell, Tools, DataAnalysis, Cpu, Setting,
  UserFilled, MapLocation, Close
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useTabsStore } from '@/stores/tabs'
import { useProjectStore } from '@/stores/project'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const tabsStore = useTabsStore()
const projectStore = useProjectStore()

interface MenuItem { path: string; title: string; perm: string }
interface MenuGroup { title: string; items: MenuItem[] }
interface Module { key: string; label: string; icon: any; firstPath: string; perm: string }

/** 顶部模块 -> 左侧菜单组（每项携带页面权限点，按当前用户过滤） */
const modules: Module[] = [
  { key: 'home', label: '首页', icon: Odometer, firstPath: '/', perm: 'page:dashboard' },
  { key: 'monitor', label: '监测数据', icon: Monitor, firstPath: '/monitor/data', perm: 'page:monitor' },
  { key: 'warning', label: '预警管理', icon: Bell, firstPath: '/warning/rules', perm: 'page:warning-rules' },
  { key: 'ops', label: '运维管理', icon: Tools, firstPath: '/ops/stations', perm: 'page:ops-stations' },
  { key: 'analysis', label: '遥感分析', icon: DataAnalysis, firstPath: '/analysis', perm: 'page:analysis' },
  { key: 'interpret', label: '解译中心', icon: Cpu, firstPath: '/tasks', perm: 'page:tasks' },
  { key: 'platform', label: '平台管理', icon: Setting, firstPath: '/platform/projects', perm: 'page:projects' }
]

const moduleMenus: Record<string, MenuGroup[]> = {
  home: [{ title: '总览', items: [{ path: '/', title: '总览', perm: 'page:dashboard' }] }],
  monitor: [{ title: '监测数据', items: [{ path: '/monitor/data', title: '监测数据', perm: 'page:monitor' }] }],
  warning: [{
    title: '预警管理',
    items: [
      { path: '/warning/rules', title: '预警设置', perm: 'page:warning-rules' },
      { path: '/warning/alarms', title: '告警日志', perm: 'page:warning-alarms' }
    ]
  }],
  ops: [{ title: '运维管理', items: [{ path: '/ops/stations', title: '站点监控', perm: 'page:ops-stations' }] }],
  analysis: [{
    title: '遥感分析',
    items: [
      { path: '/analysis', title: '变化分析', perm: 'page:analysis' },
      { path: '/remote-extract', title: '遥感提取', perm: 'page:analysis' },
      { path: '/extract', title: '在线提取', perm: 'page:extract' }
    ]
  }],
  interpret: [{ title: '解译中心', items: [{ path: '/tasks', title: '解译任务', perm: 'page:tasks' }] }],
  platform: [{
    title: '平台管理',
    items: [
      { path: '/platform/projects', title: '项目管理', perm: 'page:projects' },
      { path: '/platform/users', title: '用户中心', perm: 'page:users' },
      { path: '/platform/roles', title: '角色管理', perm: 'page:roles' }
    ]
  }]
}

// 模块可见性：预警管理这种多子项模块，只要有一个子页可见就显示
const MODULE_GROUP_PERMS: Record<string, string[]> = {
  warning: ['page:warning-rules', 'page:warning-alarms'],
  analysis: ['page:analysis', 'page:extract'],
  platform: ['page:projects', 'page:users', 'page:roles']
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
  },
  { immediate: true }
)

// 路由变化 -> 页签登记
watch(
  () => route.path,
  () => {
    if (route.meta.title) {
      tabsStore.open(route.path, route.meta.title as string)
    }
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
  padding: 0 16px;
}

.brand { display: flex; align-items: center; gap: 8px; margin-right: 28px; }

.brand-logo {
  width: 28px; height: 28px; border-radius: 6px;
  background: rgba(255, 255, 255, 0.2);
  display: flex; align-items: center; justify-content: center;
}

.brand-name { font-size: 16px; font-weight: 700; letter-spacing: 4px; }

.topnav { display: flex; height: 100%; flex: 1; }

.topnav-item {
  display: flex; align-items: center; gap: 5px;
  padding: 0 15px; font-size: 13px; cursor: pointer;
  color: rgba(255, 255, 255, 0.82);
  transition: background 0.15s;
  user-select: none;
}

.topnav-item:hover { background: rgba(255, 255, 255, 0.12); }
.topnav-item.active {
  background: rgba(255, 255, 255, 0.18);
  color: #fff; font-weight: 600;
  box-shadow: inset 0 -2px 0 #fff;
}

.topbar-right { display: flex; align-items: center; gap: 14px; }

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
}

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
  padding: 0 12px;
  background: #f0f2f5;
  border-bottom: 1px solid #e5e6eb;
  overflow-x: auto;
}

.tab {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 14px;
  font-size: 12px;
  color: #4e5969;
  background: #e8eaee;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.tab.active { background: #fff; color: #0d9488; font-weight: 600; }

.tab-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #c9cdd4;
}

.tab.active .tab-dot { background: #0d9488; }

.tab-close { font-size: 12px; border-radius: 50%; }
.tab-close:hover { background: #d4d7de; }

.page { flex: 1; overflow: auto; padding: 16px; background: #f6f8fa; }
</style>

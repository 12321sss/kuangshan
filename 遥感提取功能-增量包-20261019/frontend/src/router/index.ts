import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true }
    },
    {
      // GIS 大屏：独立整页，不套管理平台布局
      path: '/screen',
      name: 'screen',
      component: () => import('@/views/ScreenView.vue'),
      meta: { title: 'GIS 大屏', perm: 'page:screen' }
    },
    {
      path: '/',
      component: () => import('@/layout/BasicLayout.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览', module: 'home', perm: 'page:dashboard' } },
        { path: 'monitor/data', name: 'monitor-data', component: () => import('@/views/MonitorDataView.vue'), meta: { title: '监测数据', module: 'monitor', perm: 'page:monitor' } },
        { path: 'warning/rules', name: 'warning-rules', component: () => import('@/views/WarningRulesView.vue'), meta: { title: '预警设置', module: 'warning', perm: 'page:warning-rules' } },
        { path: 'warning/alarms', name: 'warning-alarms', component: () => import('@/views/AlarmLogView.vue'), meta: { title: '告警日志', module: 'warning', perm: 'page:warning-alarms' } },
        { path: 'ops/stations', name: 'ops-stations', component: () => import('@/views/StationsView.vue'), meta: { title: '站点监控', module: 'ops', perm: 'page:ops-stations' } },
        { path: 'analysis', name: 'analysis', component: () => import('@/views/AnalysisView.vue'), meta: { title: '变化分析', module: 'analysis', perm: 'page:analysis' } },
        { path: 'remote-extract', name: 'remote-extract', component: () => import('@/views/RemoteExtractView.vue'), meta: { title: '遥感提取', module: 'analysis', perm: 'page:analysis' } },
        { path: 'extract', name: 'extract', component: () => import('@/views/ExtractView.vue'), meta: { title: '在线提取', module: 'analysis', perm: 'page:extract' } },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { title: '解译任务', module: 'interpret', perm: 'page:tasks' } },
        { path: 'platform/projects', name: 'platform-projects', component: () => import('@/views/ProjectsView.vue'), meta: { title: '项目管理', module: 'platform', perm: 'page:projects' } },
        { path: 'platform/users', name: 'platform-users', component: () => import('@/views/UsersView.vue'), meta: { title: '用户中心', module: 'platform', perm: 'page:users' } },
        { path: 'platform/roles', name: 'platform-roles', component: () => import('@/views/RolesView.vue'), meta: { title: '角色管理', module: 'platform', perm: 'page:roles' } }
      ]
    }
  ]
})

// 路由守卫：未登录先静默刷新恢复会话；再按页面权限点拦截
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    return true
  }
  if (!auth.isLoggedIn) {
    if (!auth.sessionChecked) {
      try {
        await auth.refresh()
      } catch {
        // 无会话或刷新失败 = 未登录，下面统一跳转
      }
      auth.sessionChecked = true
    }
    if (!auth.isLoggedIn) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  // 页面权限：路由声明了 perm 时，用户必须持有该页面权限点
  const perm = to.meta.perm as string | undefined
  if (perm && !auth.hasPage(perm)) {
    return { path: '/', query: { denied: to.fullPath } }
  }
  return true
})

export default router

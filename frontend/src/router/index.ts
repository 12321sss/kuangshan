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
        { path: 'monitor/data', name: 'monitor-data', component: () => import('@/views/MonitorDataView.vue'), meta: { title: '设备监测', module: 'iot', perm: 'page:monitor' } },
        { path: 'warning/rules', name: 'warning-rules', component: () => import('@/views/WarningRulesView.vue'), meta: { title: '预警设置', module: 'iot', perm: 'page:warning-rules' } },
        { path: 'warning/alarms', name: 'warning-alarms', component: () => import('@/views/AlarmLogView.vue'), meta: { title: '告警日志', module: 'iot', perm: 'page:warning-alarms' } },
        { path: 'ops/stations', name: 'ops-stations', component: () => import('@/views/StationsView.vue'), meta: { title: '站点监控', module: 'iot', perm: 'page:ops-stations' } },
        { path: 'imagery', name: 'imagery', component: () => import('@/views/ImageryView.vue'), meta: { title: '影像库', module: 'rs', perm: 'page:imagery' } },
        { path: 'remote-extract', name: 'remote-extract', component: () => import('@/views/RemoteExtractView.vue'), meta: { title: '遥感提取', module: 'rs', perm: 'page:extract' } },
        { path: 'extract', name: 'extract', component: () => import('@/views/ExtractView.vue'), meta: { title: '影像解译', module: 'rs', perm: 'page:extract' } },
        { path: 'analysis', name: 'analysis', component: () => import('@/views/AnalysisView.vue'), meta: { title: '变化分析', module: 'report', perm: 'page:analysis' } },
        { path: 'analysis/safety', name: 'analysis-safety', component: () => import('@/views/SafetyView.vue'), meta: { title: '安全评估', module: 'report', perm: 'page:analysis' } },
        { path: 'analysis/terrain', name: 'analysis-terrain', component: () => import('@/views/TerrainView.vue'), meta: { title: '地形分析', module: 'report', perm: 'page:analysis' } },
        { path: 'analysis/ecology', name: 'analysis-ecology', component: () => import('@/views/EcologyView.vue'), meta: { title: '生态指数', module: 'report', perm: 'page:analysis' } },
        { path: 'report', name: 'report', component: () => import('@/views/ReportView.vue'), meta: { title: '报告生成', module: 'report', perm: 'page:analysis' } },
        { path: 'platform/projects', name: 'platform-projects', component: () => import('@/views/ProjectsView.vue'), meta: { title: '项目管理', module: 'platform', perm: 'page:projects' } },
        { path: 'platform/users', name: 'platform-users', component: () => import('@/views/UsersView.vue'), meta: { title: '用户中心', module: 'platform', perm: 'page:users' } },
        { path: 'platform/roles', name: 'platform-roles', component: () => import('@/views/RolesView.vue'), meta: { title: '角色管理', module: 'platform', perm: 'page:roles' } },
        { path: 'platform/audit-logs', name: 'platform-audit', component: () => import('@/views/AuditLogView.vue'), meta: { title: '操作日志', module: 'platform', perm: 'page:audit-logs' } },
        { path: 'platform/dict', name: 'platform-dict', component: () => import('@/views/DictView.vue'), meta: { title: '数据字典', module: 'platform', perm: 'page:dict' } },
        { path: 'platform/health', name: 'platform-health', component: () => import('@/views/HealthView.vue'), meta: { title: '系统健康', module: 'platform', perm: 'page:health' } },
        { path: 'platform/trash', name: 'platform-trash', component: () => import('@/views/TrashView.vue'), meta: { title: '回收站', module: 'platform', perm: 'page:extract' } },
        { path: 'compare', name: 'compare', component: () => import('@/views/CompareView.vue'), meta: { title: '数据对比', module: 'rs', perm: 'page:extract' } }
      ]
    },
    {
      // 访客分享只读页：无需登录，凭 token 访问
      path: '/share/:token',
      name: 'share',
      component: () => import('@/views/ShareView.vue'),
      meta: { public: true, title: '分享视图' }
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

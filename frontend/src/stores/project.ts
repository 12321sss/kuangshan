import { defineStore } from 'pinia'
import { projectApi } from '@/api'
import type { Project } from '@/api/types'

/**
 * 当前选中项目（数据中台的全局上下文）：
 * 顶栏工程切换器写它，所有页面的数据查询都以它为过滤条件
 * 选择持久化到 localStorage（非敏感数据），刷新后保持
 */
export const useProjectStore = defineStore('project', {
  state: () => ({
    currentId: Number(localStorage.getItem('rs_project')) || 0,
    projects: [] as Project[]
  }),
  getters: {
    current: (s) => s.projects.find((p) => p.id === s.currentId) || null
  },
  actions: {
    set(id: number) {
      this.currentId = id
      localStorage.setItem('rs_project', String(id))
    },
    /** 登录后加载当前用户可见的项目清单，并校正选中项 */
    async load() {
      this.projects = await projectApi.list()
      if (!this.projects.some((p) => p.id === this.currentId)) {
        this.set(this.projects[0]?.id ?? 0)
      }
    },
    reset() {
      this.projects = []
      this.currentId = 0
      localStorage.removeItem('rs_project')
    }
  }
})

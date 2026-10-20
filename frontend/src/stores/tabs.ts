import { defineStore } from 'pinia'

export interface PageTab {
  path: string
  title: string
}

/**
 * 多页签状态：参考监测云平台，打开的页面以页签形式驻留顶部
 */
export const useTabsStore = defineStore('tabs', {
  state: () => ({
    tabs: [{ path: '/', title: '总览' }] as PageTab[],
    active: '/'
  }),
  actions: {
    open(path: string, title: string) {
      if (!this.tabs.some((t) => t.path === path)) {
        this.tabs.push({ path, title })
      }
      this.active = path
    },
    close(path: string): string {
      const idx = this.tabs.findIndex((t) => t.path === path)
      if (idx >= 0 && this.tabs.length > 1) {
        this.tabs.splice(idx, 1)
        if (this.active === path) {
          this.active = this.tabs[Math.min(idx, this.tabs.length - 1)].path
        }
      }
      return this.active
    }
  }
})

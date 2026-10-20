import { defineStore } from 'pinia'
import axios from 'axios'

export interface UserInfo {
  username: string
  displayName: string
  role: string
  phone: string
  pagePerms: string[]
  actionPerms: string[]
}

interface LoginResponse {
  accessToken: string
  expiresInMinutes: number
  user: UserInfo
}

/** 会话标记 Cookie（后端登录时写入的非敏感标记）：没有它就不做静默刷新探测，避免控制台刷 401 */
function hasSessionMarker(): boolean {
  return document.cookie.split(';').some((c) => c.trim().startsWith('rs_session=1'))
}

/**
 * 认证状态：
 * - 访问令牌只存内存（不落 localStorage），刷新页面时通过刷新令牌 Cookie 静默恢复
 * - 刷新令牌由后端写入 HttpOnly Cookie（path=/api/auth），JS 不可读
 * - 权限清单随登录/刷新下发，菜单和按钮据此渲染
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: '',
    user: null as UserInfo | null,
    /** 本次会话是否已尝试过静默刷新（避免路由守卫重复调用） */
    sessionChecked: false
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken,
    hasPage: (s) => (perm: string) => !!s.user?.pagePerms?.includes(perm),
    hasAction: (s) => (perm: string) => !!s.user?.actionPerms?.includes(perm)
  },
  actions: {
    async login(username: string, password: string) {
      const res = await axios.post('/api/auth/login', { username, password }, { withCredentials: true })
      if (res.data.code !== 0) throw new Error(res.data.message || '登录失败')
      const data = res.data.data as LoginResponse
      this.accessToken = data.accessToken
      this.user = data.user
      this.sessionChecked = true
    },
    async refresh() {
      if (!hasSessionMarker()) {
        throw new Error('无会话标记')
      }
      const res = await axios.post('/api/auth/refresh', null, { withCredentials: true })
      if (res.data.code !== 0) throw new Error(res.data.message)
      const data = res.data.data as LoginResponse
      this.accessToken = data.accessToken
      this.user = data.user
    },
    async logout() {
      try {
        await axios.post('/api/auth/logout', null, { withCredentials: true })
      } catch {
        // 注销失败也清空本地状态
      }
      this.accessToken = ''
      this.user = null
    }
  }
})

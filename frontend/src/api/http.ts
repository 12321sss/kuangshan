import axios from 'axios'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

/**
 * 业务 API 客户端（axios 封装）
 * - baseURL 走相对路径 /api，由 vite proxy 转发到 Java 服务（Cookie 同源）
 * - 请求自动附加访问令牌
 * - 401 时自动用刷新令牌重试一次（4xx 其他状态不重试）
 * - 统一错误：后端 {code,message,data} 结构映射为 Error(message)
 */
const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
  withCredentials: true
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// 并发请求同时遇到 401 时只刷新一次
let refreshing: Promise<void> | null = null

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body.code === 'number') {
      if (body.code !== 0) return Promise.reject(new Error(body.message || '请求失败'))
      return body.data
    }
    return body
  },
  async (err) => {
    const { response, config } = err
    if (!response) {
      return Promise.reject(new Error('网络异常，请检查后端服务是否启动'))
    }
    // 401 且非认证接口自身：静默刷新后重放原请求
    if (response.status === 401 && !config._retry && !String(config.url).startsWith('/auth/')) {
      config._retry = true
      refreshing ??= useAuthStore().refresh().finally(() => { refreshing = null })
      try {
        await refreshing
        return http(config)
      } catch {
        await router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
        return Promise.reject(new Error('登录已过期，请重新登录'))
      }
    }
    return Promise.reject(new Error(response.data?.message || `请求失败 (${response.status})`))
  }
)

export default http

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import cesium from 'vite-plugin-cesium'
import { fileURLToPath, URL } from 'node:url'

// 开发服务器：/api 代理到 Java 业务服务，避免跨域，Cookie 同源可用
export default defineConfig({
  plugins: [vue(), cesium()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    // 为什么必须显式指定 host：
    // 不配 host 时 Vite 默认只听 localhost，而 Windows 上 localhost 优先解析到 IPv6 ::1，
    // 结果就是 http://localhost:5173 能开、http://127.0.0.1:5173 打不开（netstat 里只有 [::1]）。
    // 绑 0.0.0.0 后 IPv4 的 127.0.0.1 与局域网 IP 都可访问，方便手机/另一台电脑调试。
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 用 127.0.0.1 而不是 localhost：避免代理层再做一次 DNS 解析，
        // 若后端只监听 IPv4，写 localhost 可能解析到 ::1 导致 ECONNREFUSED
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        // 高分影像可达数百 MB：默认 http-proxy 缓冲与超时限制会截断上传
        timeout: 30 * 60 * 1000,
        proxyTimeout: 30 * 60 * 1000
      },
      // Sentinel-2 遥感提取服务（inference，8010 端口；8000 被 IncrediBuild 占用）
      '/sentinel': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sentinel/, ''),
        // AWS STAC 首次拉景较慢（COG Range 下载），给足超时
        timeout: 10 * 60 * 1000,
        proxyTimeout: 10 * 60 * 1000
      }
    }
  }
})

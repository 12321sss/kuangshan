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
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        // 高分影像可达数百 MB：默认 http-proxy 缓冲与超时限制会截断上传
        timeout: 30 * 60 * 1000,
        proxyTimeout: 30 * 60 * 1000
      },
      // Sentinel-2 遥感提取服务（inference，8000 端口）
      '/sentinel': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sentinel/, ''),
        // AWS STAC 首次拉景较慢（COG Range 下载），给足超时
        timeout: 10 * 60 * 1000,
        proxyTimeout: 10 * 60 * 1000
      }
    }
  }
})

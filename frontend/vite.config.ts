import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import cesium from 'vite-plugin-cesium'
import { fileURLToPath, URL } from 'node:url'

/**
 * 演示模式（内网穿透给外部试用）
 *
 * 用法：命令行设置 TUNNEL=1 后启动
 *   PowerShell:  $env:TUNNEL=1; npm run dev
 *   Git Bash  :  TUNNEL=1 npm run dev
 *
 * 开启后会做两件事：
 *  1. allowedHosts 全放开 —— 穿透服务给的域名随机，省得每次改白名单
 *  2. HMR 改走 wss:443 —— https 穿透域名下前端页面的 ws 才能连上（否则只是没热更新）
 *
 * 不开这个开关时，本地开发保持默认行为（只听 localhost + IP、HMR 用 5173）。
 */
const TUNNEL = process.env.TUNNEL === '1'

// 本地开发白名单：列出常见穿透服务的域名后缀（前导点匹配所有子域）
const LOCAL_ALLOWED_HOSTS = [
  '.ofalias.net',
  '.ngrok.io',
  '.ngrok-free.app',
  '.ngrok-free.dev',
  '.cpolar.top',
  '.cpolar.cn',
  '.natappfree.cc',
  '.trycloudflare.com',
  '.loca.lt',
  '.serveo.net'
]

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

    // Vite 5+ 的 DNS rebinding 防护：默认只允许 localhost / IP 直连。
    // 用域名访问（穿透服务）会被拦下并报 Blocked request。
    allowedHosts: TUNNEL ? true : LOCAL_ALLOWED_HOSTS,

    // HMR 不写死 protocol/clientPort：
    // 之前配成 wss:443 是为了适配 https 穿透，但副作用是本地用 localhost:5173 打开时，
    // 浏览器也会去连 wss://localhost:443，控制台持续报错「WebSocket connection failed」。
    // Vite 默认会按当前页面协议+端口自动推断 ws 地址，穿透场景下同样能正确工作。

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

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import { Ion } from 'cesium'
import App from './App.vue'
import router from './router'
import { CESIUM_TOKEN } from './config'
import './style.css'

// Cesium ion 令牌（本地 .env.local 注入；天地图底图不依赖 ion，这里只是备用资产通道）
if (CESIUM_TOKEN) {
  Ion.defaultAccessToken = CESIUM_TOKEN
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')

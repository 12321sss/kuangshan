/**
 * 全局配置
 *
 * 天地图密钥（合规要求：前端不内置任何可用 key）：
 * 1. 到天地图开放平台 https://console.tianditu.gov.cn/ 注册并创建"浏览器端"应用，免费获取 tk
 * 2. 在项目根目录 frontend/ 下新建 .env.local，写入：
 *    VITE_TIANDITU_TOKEN=你的密钥
 * 3. 重启 vite 开发服务器生效
 * （个人使用建议同时配置 Referer 域名白名单；商用应走后端代理鉴权）
 */
export const TIANDITU_TOKEN: string = import.meta.env.VITE_TIANDITU_TOKEN || ''

/** Cesium ion 访问令牌（本地 .env.local 注入） */
export const CESIUM_TOKEN: string = import.meta.env.VITE_CESIUM_TOKEN || ''

/** 大屏矿山中心点（宁都河源，模拟坐标，以矿界核验为准） */
export const MINE_CENTER = { lng: 116.021, lat: 26.4725 }

// 让 TS 识别 .vue 单文件组件（编辑器用；构建走 vite 不做 vue-tsc 严格检查）
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

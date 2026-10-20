import type { Viewer } from 'cesium'
import { ElMessage } from 'element-plus'

/**
 * 自适应性能调节：低配显卡（如 Quadro K2200 4GB）跑 Cesium 容易掉帧。
 *
 * 做法：启动后采样 2 秒帧率，若平均 FPS 低于阈值，则降低 scene.resolutionScale
 * （减少渲染像素数，画面略糊但交互流畅），并对用户做一次性提示。
 *
 * 只在页面首次加载时判定，不做动态反复调整，避免画面忽清忽糊。
 */
export function autoAdjustPerformance(viewer: Viewer, opts?: { minFps?: number; targetScale?: number }) {
  const minFps = opts?.minFps ?? 30
  const targetScale = opts?.targetScale ?? 0.8

  let frames = 0
  let start = performance.now()
  let done = false

  const tick = () => {
    if (done) return
    frames++
    const elapsed = performance.now() - start
    if (elapsed < 2000) {
      requestAnimationFrame(tick)
      return
    }
    done = true
    const fps = (frames / elapsed) * 1000
    if (fps < minFps) {
      try {
        viewer.scene.resolutionScale = targetScale
      } catch {
        /* 忽略：个别版本只读 */
      }
      ElMessage.warning(
        `检测到当前帧率约 ${Math.round(fps)} FPS，已自动降低渲染精度以保证操作流畅（可在系统健康页查看设备情况）`
      )
    }
  }
  requestAnimationFrame(tick)
}

/** 手动切换渲染精度：1 = 原生，0.8 = 流畅优先 */
export function setRenderScale(viewer: Viewer, scale: number) {
  try {
    viewer.scene.resolutionScale = scale
  } catch {
    /* ignore */
  }
}

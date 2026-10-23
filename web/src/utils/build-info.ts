/** U5：构建版本与“旧 chunk 自愈”。
 *
 * 背景：移动端浏览器常从 bfcache/缓存恢复整页，拿到的还是旧 bundle，
 * 导致「明明修好了却还是老样子」。这里做两件事：
 *  1) 暴露构建版本，便于一眼确认页面新旧；
 *  2) 动态 chunk 加载失败（发布后旧文件名 404）时自动硬刷新一次。
 */
export const BUILD_SHA = typeof __BUILD_SHA__ === 'string' ? __BUILD_SHA__ : 'dev'
export const BUILD_TIME = typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__ : '—'

const GUARD_KEY = 'ms.staleBundleReloaded'

/** 带缓存破坏参数的整页刷新（SPA 路由也能落到同一地址）。 */
export function hardReload(): void {
  try {
    const u = new URL(location.href)
    u.searchParams.set('_v', Date.now().toString(36))
    location.replace(u.toString())
  } catch {
    location.reload()
  }
}

export function installStaleBundleGuard(): void {
  const reloadOnce = () => {
    try {
      if (sessionStorage.getItem(GUARD_KEY)) return
      sessionStorage.setItem(GUARD_KEY, '1')
    } catch { /* 隐私模式禁用 storage：直接刷新 */ }
    hardReload()
  }

  // Vite 在动态 import 失败时派发该事件（构建产物 / 模块预加载）
  window.addEventListener('vite:preloadError', (e) => {
    e.preventDefault()
    reloadOnce()
  })

  window.addEventListener('unhandledrejection', (e) => {
    const msg = String((e as PromiseRejectionEvent).reason?.message ?? e.reason ?? '')
    if (/Loading chunk|dynamically imported module|Importing a module script failed/i.test(msg)) {
      reloadOnce()
    }
  })
}

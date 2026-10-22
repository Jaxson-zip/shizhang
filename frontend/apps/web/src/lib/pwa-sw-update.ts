/**
 * PWA service worker 升级通知 lifecycle —— 桥接 SW 的「检测到 waiting 版本」
 * 信号到 React 层。
 *
 * 之前 sw.js 在 install 阶段 self.skipWaiting() 直接抢占,用户哪怕在填表单
 * 都会被无声 reload。现在 SW 改为不主动 skipWaiting,这里检测到 waiting 后:
 *   1. 派发 CustomEvent 'pwa:sw-update-available'
 *   2. App 顶部的 SwUpdateBanner 监听,弹「检测到新版本」+「立即更新」按钮
 *   3. 用户点击后这里再通过 postMessage 向 waiting SW 发 SKIP_WAITING
 *   4. SW skipWaiting + 自动 controllerchange,刷新页面拿新版
 *
 * 发出状态变更信号，UI 每次读取当前 waiting 状态，也能清除过期提示:
 *   A. register 时已经有 waiting:页面进来时 SW 早就升级好了,只是没激活
 *   B. updatefound + installed + 有 controller:运行中检测到新版本下载完
 *   C. controllerchange:仅在本页明确接受更新后刷新；首次安装或其他窗口
 *      接受更新不应丢弃本页的编辑内容。
 */

export const SW_UPDATE_EVENT = 'pwa:sw-update-available'
export const SW_UPDATE_ACCEPT_EVENT = 'pwa:sw-update-accept'

let activeRegistration: ServiceWorkerRegistration | null = null

/** Read the current state as well as listening for events: login may mount late. */
export function hasServiceWorkerUpdate(): boolean {
  return activeRegistration?.waiting?.state === 'installed'
    && typeof navigator !== 'undefined' && !!navigator.serviceWorker?.controller
}

export function setupServiceWorkerUpdates(registration: ServiceWorkerRegistration): () => void {
  activeRegistration = registration
  let stopped = false
  const observed = new Map<ServiceWorker, () => void>()
  const notify = () => { if (!stopped) dispatchUpdateAvailable() }
  const observeWorker = (worker: ServiceWorker | null) => {
    if (!worker || observed.has(worker)) return
    // installed can fire just before registration.waiting is updated.
    const onState = () => queueMicrotask(notify)
    observed.set(worker, onState)
    worker.addEventListener('statechange', onState)
  }
  observeWorker(registration.waiting)
  observeWorker(registration.installing)
  notify()

  // B) 运行中 update found
  const onUpdateFound = () => { observeWorker(registration.installing); notify() }
  registration.addEventListener('updatefound', onUpdateFound)

  // First installation and another tab accepting an update also cause this
  // event. Only this page's explicit acceptance may discard its open form.
  let updateAccepted = false
  let refreshing = false
  const onControllerChange = () => {
    notify()
    if (!updateAccepted || refreshing) return
    refreshing = true
    window.location.reload()
  }
  navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)

  // UI 侧确认「立即更新」后回调进来:posetMessage 给 waiting SW
  const onAccept = () => {
    const waiting = activeRegistration?.waiting
    if (!waiting || !hasServiceWorkerUpdate()) { notify(); return }
    updateAccepted = true
    waiting.postMessage({ type: 'SKIP_WAITING' })
  }
  window.addEventListener(SW_UPDATE_ACCEPT_EVENT, onAccept)

  // 后台周期性检查更新 —— 标签页存活时每 30 分钟跑一次 registration.update(),
  // 这样长期挂着的标签页也能及时看到新版本(浏览器默认只在导航时检查)。
  // 不在乎失败,静默吞掉。
  const POLL_MS = 30 * 60 * 1000
  const poll = setInterval(() => {
    registration.update().then(notify, notify)
  }, POLL_MS)
  return () => {
    stopped = true
    clearInterval(poll)
    registration.removeEventListener('updatefound', onUpdateFound)
    navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange)
    window.removeEventListener(SW_UPDATE_ACCEPT_EVENT, onAccept)
    for (const [worker, listener] of observed) worker.removeEventListener('statechange', listener)
    if (activeRegistration === registration) activeRegistration = null
  }
}

function dispatchUpdateAvailable(): void {
  window.dispatchEvent(new CustomEvent(SW_UPDATE_EVENT))
}

/** 给 UI 用 —— 用户点「立即更新」时调,会触发 SW 替换 + 页面 reload */
export function acceptServiceWorkerUpdate(): void {
  window.dispatchEvent(new CustomEvent(SW_UPDATE_ACCEPT_EVENT))
}

import { useEffect, useState } from 'react'
import { RefreshCw, X } from 'lucide-react'

import { Button, useT } from '@beecount/ui'

import { acceptServiceWorkerUpdate, hasServiceWorkerUpdate, SW_UPDATE_EVENT } from '../lib/pwa-sw-update'

/**
 * 检测到 SW 新版本可用时的顶部 banner —— 替代以前 SW skipWaiting 直接静默
 * reload 的体验。
 *
 * 显示规则:
 *   - 监听 SW_UPDATE_EVENT，每次读取真实 waiting 状态；其他窗口更新后清除残留
 *   - 用户点「立即更新」→ acceptServiceWorkerUpdate → SW skipWaiting + reload
 *   - 用户点 X → 本次会话内不再显示(sessionStorage 标记),下次进来若仍有
 *     waiting 还会再弹,直到用户接受
 *
 * 位置:AppShell 内容流中、outlet 上方，不覆盖导航/账本选择器；Login 页面不显示
 * (login 没有 token,SW 升级跟登录无关,先让用户看到表单)。
 */

const DISMISS_KEY = 'beecount.pwa.update-dismissed'

export function PwaUpdateBanner() {
  const t = useT()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const sessionDismissed = sessionStorage.getItem(DISMISS_KEY) === '1'
    if (sessionDismissed) return

    const onUpdate = () => setVisible(hasServiceWorkerUpdate())
    window.addEventListener(SW_UPDATE_EVENT, onUpdate)
    onUpdate()
    return () => window.removeEventListener(SW_UPDATE_EVENT, onUpdate)
  }, [])

  if (!visible) return null

  return (
    <div className="w-full">
      <div className="flex items-center gap-3 rounded-lg border border-primary/40 bg-background/95 p-3 shadow-lg backdrop-blur">
        <RefreshCw className="h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1 text-sm" role="status">
          <p>{t('pwa.update.available')}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t('pwa.update.saveFirst')}</p>
        </div>
        <Button
          size="sm"
          className="min-h-11 shrink-0 px-3"
          onClick={() => {
            acceptServiceWorkerUpdate()
            // 这里不直接 setVisible(false) —— SW 会触发 controllerchange,
            // pwa-sw-update.ts 自动 location.reload(),整个页面会换新版
          }}
        >
          {t('pwa.update.apply')}
        </Button>
        <button
          type="button"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted"
          aria-label={t('common.close') as string}
          onClick={() => {
            sessionStorage.setItem(DISMISS_KEY, '1')
            setVisible(false)
          }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

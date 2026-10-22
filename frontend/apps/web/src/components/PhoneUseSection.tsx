import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'

import { isStandalonePwa } from '../lib/pwa-runtime'

/** Safari has no install-prompt event; keep these instructions accessible. */
export function PhoneUseSection() {
  const t = useT()
  const [online, setOnline] = useState(() => navigator.onLine)
  const standalone = isStandalonePwa()
  const secure = window.isSecureContext

  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('phone.title')}</CardTitle>
        <p className="text-sm leading-relaxed text-muted-foreground">{t('phone.intro')}</p>
      </CardHeader>
      <CardContent className="space-y-5 text-sm leading-relaxed">
        <p className="rounded-lg bg-muted/40 px-4 py-3" role="status">
          {t(standalone ? 'phone.standalone' : 'phone.browser')}
        </p>
        {!secure ? <p className="rounded-lg border border-border p-4">{t('phone.insecure')}</p> : null}
        {!standalone ? (
          <div>
            <h3 className="font-medium">{t('phone.installTitle')}</h3>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-muted-foreground">
              <li>{t('phone.install1')}</li>
              <li>{t('phone.install2')}</li>
              <li>{t('phone.install3')}</li>
            </ol>
          </div>
        ) : null}
        <div className="border-t border-border pt-4">
          <h3 className="font-medium">{t('phone.captureTitle')}</h3>
          <p className="mt-2">{t('phone.captureFlow')}</p>
          <p className="mt-2 text-muted-foreground">{t('phone.captureSetup')}</p>
          <a className="mt-2 inline-flex min-h-11 items-center font-medium text-primary underline underline-offset-4" href="/validation/shortcut-import.html?v=9">{t('phone.captureDownload')}</a>
          <p className="mt-2 text-muted-foreground">{t('phone.captureLimit')}</p>
        </div>
        <p className="border-t border-border pt-4 text-muted-foreground" role="status">
          {t(online ? 'phone.networkNote' : 'phone.offline')}
        </p>
      </CardContent>
    </Card>
  )
}

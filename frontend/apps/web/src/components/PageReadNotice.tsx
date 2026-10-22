import { Button, useT } from '@beecount/ui'

export function PageReadNotice({ ready, pending, failed, retry }: {
  ready: boolean; pending: boolean; failed: boolean; retry: () => void
}) {
  const t = useT()
  if (ready && !failed) return null
  return <div role={failed ? 'alert' : 'status'} className="mb-4 flex flex-col gap-3 rounded-xl border border-border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
    <div className="space-y-1">
      <p className="text-sm font-medium">{t(failed ? 'data.readFailed' : 'data.loading')}</p>
      <p className="text-sm leading-relaxed text-muted-foreground">{t(ready ? 'data.stale' : 'data.unconfirmed')}</p>
    </div>
    {failed && <Button type="button" variant="outline" className="self-start" disabled={pending} onClick={retry}>
      {t(pending ? 'data.loading' : 'data.retry')}
    </Button>}
  </div>
}

import type { WorkspaceAccount } from '@beecount/api-client'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'

/** Native income/expense aggregates include booked pending entries; balances are not used. */
export function ChannelAccountsSummary({ accounts, primaryIds, onSelectAccount }: {
  accounts: WorkspaceAccount[]; primaryIds?: string[]; onSelectAccount?: (account: WorkspaceAccount) => void
}) {
  const t = useT()
  const rows = [...new Map(accounts.filter(a => !a.hidden && (a.currency || 'CNY') === 'CNY').map(a => [a.id, a])).values()]
  const cents = (value: number | null | undefined) => Math.round((value || 0) * 100)
  const income = rows.reduce((sum, a) => sum + cents(a.income_total), 0)
  const expense = rows.reduce((sum, a) => sum + cents(a.expense_total), 0)
  const primary = primaryIds ? rows.filter(a => primaryIds.includes(a.id)) : rows
  const others = primaryIds ? rows.filter(a => !primaryIds.includes(a.id)) : []
  const fmt = (value: number) => (value / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const metrics = (inc: number, exp: number) => <dl className="grid min-w-0 grid-cols-3 gap-2">
    {[[t('channelAccounts.income'), inc], [t('channelAccounts.expense'), exp], [t('channelAccounts.net'), inc - exp]].map(([label, value]) =>
      <div className="min-w-0" key={label}><dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="mt-1 break-all font-mono text-base font-semibold tabular-nums">{fmt(Number(value))}</dd></div>)}
  </dl>
  const accountRow = (account: WorkspaceAccount) => <section key={account.id} className="rounded-xl border border-border p-4">
    {onSelectAccount ? <button type="button" className="mb-2 flex min-h-11 w-full items-center justify-between gap-3 text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={() => onSelectAccount(account)}><span>{account.name}</span><span className="text-sm text-muted-foreground">{t('channelAccounts.details')} ›</span></button>
      : <h3 className="mb-3 font-medium">{account.name}</h3>}
    {metrics(cents(account.income_total), cents(account.expense_total))}
  </section>
  return <Card className="bc-panel overflow-hidden">
    <CardHeader><CardTitle>{t('channelAccounts.title')}</CardTitle>
      <p className="text-sm leading-relaxed text-muted-foreground">{t('channelAccounts.hint')}</p></CardHeader>
    <CardContent className="space-y-3">
      <section className="rounded-xl border border-primary/20 bg-primary/5 p-4">
        <h3 className="mb-3 font-medium">{t('channelAccounts.all')}</h3>{metrics(income, expense)}
      </section>
      {primary.map(accountRow)}
      {others.length ? <details className="rounded-xl border border-border p-3"><summary className="cursor-pointer text-sm text-muted-foreground">{t('channelAccounts.other')} ({others.length})</summary>
        <div className="mt-3 space-y-3">{others.map(accountRow)}</div></details> : null}
      <p className="text-xs leading-relaxed text-muted-foreground">{t('channelAccounts.pendingHint')}</p>
    </CardContent>
  </Card>
}

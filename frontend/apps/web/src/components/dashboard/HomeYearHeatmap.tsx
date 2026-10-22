import { useId, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'

import type { WorkspaceAnalyticsSeriesItem } from '@beecount/api-client'
import { Amount } from '@beecount/web-features'

interface Props {
  /** year scope 的 series，bucket 是 YYYY-MM。 */
  yearSeries?: WorkspaceAnalyticsSeriesItem[]
  currency?: string
}

/**
 * 12 个月支出热力条：用当月支出的相对大小染色，把"今年哪几个月花得最多"
 * 一眼能看出。对比之下 MonthlyTrendBars 只展示最近 6 期，这里补齐整年。
 */
export function HomeYearHeatmap({ yearSeries, currency = 'CNY' }: Props) {
  const t = useT()
  const [selectedMonth, setSelectedMonth] = useState(() => new Date().getMonth())
  const detailsId = useId()
  const data = useMemo(() => {
    const year = new Date().getFullYear()
    const byBucket = new Map<string, { income: number; expense: number }>()
    for (const it of yearSeries || []) {
      byBucket.set(it.bucket, { income: it.income || 0, expense: it.expense || 0 })
    }
    const rows = []
    let maxExpense = 0
    for (let m = 0; m < 12; m += 1) {
      const key = `${year}-${String(m + 1).padStart(2, '0')}`
      const rec = byBucket.get(key) || { income: 0, expense: 0 }
      if (rec.expense > maxExpense) maxExpense = rec.expense
      rows.push({
        monthIndex: m,
        monthLabel: t('home.heatmap.monthLabel').replace('{month}', String(m + 1)),
        income: rec.income,
        expense: rec.expense,
        balance: rec.income - rec.expense
      })
    }
    return { rows, maxExpense, year }
  }, [yearSeries, t])

  const selected = data.rows[selectedMonth]

  return (
    <Card className="bc-panel">
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="text-base">
          {t('home.heatmap.title').replace('{year}', String(data.year))}
        </CardTitle>
        <span className="text-xs leading-relaxed text-muted-foreground">{t('home.heatmap.hint')}</span>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {data.rows.map((row) => {
            const pct = data.maxExpense > 0 ? row.expense / data.maxExpense : 0
            const bg =
              pct === 0
                ? 'hsl(var(--muted) / 0.5)'
                : `rgb(var(--expense-rgb) / ${(0.04 + pct * 0.14).toFixed(2)})`
            const isSelected = row.monthIndex === selectedMonth
            return (
              <button
                key={row.monthIndex}
                type="button"
                aria-pressed={isSelected}
                aria-controls={detailsId}
                aria-label={t('home.heatmap.monthAction').replace('{month}', row.monthLabel)
                  .replace('{value}', row.expense.toFixed(2)).replace('{currency}', currency)}
                onClick={() => setSelectedMonth(row.monthIndex)}
                className={`flex min-h-16 min-w-0 flex-col gap-1 rounded-xl border px-2 py-2.5 text-left transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                  isSelected ? 'border-primary ring-1 ring-primary/30' : 'border-border/50'
                }`}
                style={{ background: bg }}
              >
                <span className="text-xs font-medium text-foreground">
                  {row.monthLabel}
                </span>
                {row.expense > 0 ? (
                  <Amount value={row.expense} currency={currency} size="sm" tone="default" className="break-all leading-tight" />
                ) : (
                  <span className="text-xs leading-tight text-muted-foreground">—</span>
                )}
              </button>
            )
          })}
        </div>
        <div id={detailsId} role="region" aria-label={t('home.heatmap.details').replace('{month}', selected.monthLabel)}
          aria-live="polite" className="mt-4 rounded-xl border border-border/60 bg-muted/25 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium">
            {t('home.heatmap.details').replace('{month}', selected.monthLabel)}
            <span className="text-xs font-normal text-muted-foreground">{currency}</span>
          </div>
          <dl className="grid gap-3 sm:grid-cols-3">
            {([
              ['tooltipIncome', selected.income, 'positive'],
              ['tooltipExpense', selected.expense, 'negative'],
              ['tooltipBalance', selected.balance, 'default'],
            ] as const).map(([key, value, tone]) => (
              <div key={key} className="flex min-w-0 items-baseline justify-between gap-3 sm:block">
                <dt className="shrink-0 text-xs text-muted-foreground">{t(`home.heatmap.${key}`).replace('{value}', '').trim()}</dt>
                <dd className="mt-1 min-w-0 text-right sm:text-left"><Amount value={value} currency={currency} showCurrency compact={false} tone={tone}
                  size="lg" bold className="break-all" /></dd>
              </div>
            ))}
          </dl>
        </div>
      </CardContent>
    </Card>
  )
}

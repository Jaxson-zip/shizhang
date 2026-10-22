import { useMemo, useState } from 'react'
import { Area, AreaChart, ResponsiveContainer, Tooltip } from 'recharts'
import {
  ArrowDownLeft,
  ArrowUpRight,
  CalendarDays,
  Receipt,
  Plus
} from 'lucide-react'

import type {
  ReadBudget,
  ReadLedger,
  WorkspaceAnalyticsAnomalyMonth,
  WorkspaceAnalyticsSeriesItem,
  WorkspaceAnalyticsSummary,
  WorkspaceLedgerCounts
} from '@beecount/api-client'
import { Amount, periodRangeText, type BudgetUsage } from '@beecount/web-features'
import { Button, useT } from '@beecount/ui'

import { HeroInsightsRow } from './HeroInsightsRow'
import { dispatchOpenNewTx } from '../../lib/txDialogEvents'

type HeroScope = 'month' | 'year' | 'all'

interface Props {
  ledgers: ReadLedger[]
  currentLedgerId?: string
  monthSummary?: WorkspaceAnalyticsSummary
  monthSeries?: WorkspaceAnalyticsSeriesItem[]
  yearSummary?: WorkspaceAnalyticsSummary
  yearSeries?: WorkspaceAnalyticsSeriesItem[]
  allSummary?: WorkspaceAnalyticsSummary
  allSeries?: WorkspaceAnalyticsSeriesItem[]
  ledgerCounts?: WorkspaceLedgerCounts
  /** 当前账本预算配置 + 当周期 used,空数组 → chip 不显示。 */
  budgets?: ReadBudget[]
  budgetUsageById?: Record<string, BudgetUsage>
  /** 异常月份(scope=year analytics 返回),空数组 + hasEnoughMonths=true 显示 ✓ */
  anomalyMonths?: WorkspaceAnalyticsAnomalyMonth[]
  hasEnoughMonthsForAnomaly?: boolean
}

// 三个 scope 的 label/hint 在组件里 t() 时动态查,这里只留 value 列表
const SCOPE_VALUES: HeroScope[] = ['month', 'year', 'all']

/**
 * 首页 hero 卡。三视角切换（本月 / 今年 / 汇总）：
 * - 大号结余 = 对应 scope 的 income - expense（对齐 mobile `monthlyTotals` /
 *   `yearlyTotals` / 全量聚合）
 * - 本月/今年/全部 收入 + 支出 两个 HeroStat 跟随 scope 变
 * - 记账笔数 / 记账天数 从 ledgerCounts 来（账本全量，不随 scope 变）
 * - 右侧 sparkline: month 按日累计；year / all 按月累计
 */
export function HomeHero({
  ledgers,
  currentLedgerId,
  monthSummary,
  monthSeries,
  yearSummary,
  yearSeries,
  allSummary,
  allSeries,
  ledgerCounts,
  budgets,
  budgetUsageById,
  anomalyMonths,
  hasEnoughMonthsForAnomaly
}: Props) {
  const t = useT()
  const [scope, setScope] = useState<HeroScope>('month')

  const activeLedger =
    ledgers.find((l) => l.ledger_id === currentLedgerId) || ledgers[0]
  const currency = activeLedger?.currency || 'CNY'
  const ledgerMonthStartDay = Math.max(1, Math.min(28, activeLedger?.month_start_day ?? 1))

  const summaryByScope: Record<HeroScope, WorkspaceAnalyticsSummary | undefined> = {
    month: monthSummary,
    year: yearSummary,
    all: allSummary
  }
  const seriesByScope: Record<HeroScope, WorkspaceAnalyticsSeriesItem[]> = {
    month: monthSeries || [],
    year: yearSeries || [],
    all: allSeries || []
  }

  const activeSummary = summaryByScope[scope]
  const activeSeries = seriesByScope[scope]
  const scopeLabel = t(`home.scope.${scope}`)
  const scopeBalanceHint = t(`home.scope.${scope}.hint`)
  const monthRangeLabel = scope === 'month' ? periodRangeText(ledgerMonthStartDay) : null

  const income = activeSummary?.income_total ?? 0
  const expense = activeSummary?.expense_total ?? 0
  const balance = activeSummary?.balance ?? income - expense

  const txCount = ledgerCounts?.tx_count ?? 0
  const days = ledgerCounts?.distinct_days ?? 0

  // sparkline: 本月按日累计；年/全部按月累计。series 已按 bucket 分桶。
  const trendData = useMemo(() => {
    const sorted = activeSeries.slice().sort((a, b) => a.bucket.localeCompare(b.bucket))
    let running = 0
    return sorted.map((it) => {
      running += (it.income || 0) - (it.expense || 0)
      return { bucket: it.bucket, v: running }
    })
  }, [activeSeries])

  return (
    <div className="sz-home-hero relative rounded-2xl border border-border/70 bg-card">

      {/* 窄屏 p-4 / 桌面 p-6:mobile 视口下 hero 体积大,内容只占一列时
           24px padding 显得很空,16px 紧凑但不挤。grid gap 同步收一点。 */}
      <div className="relative grid gap-6 p-5 sm:p-7 lg:grid-cols-[1.3fr_1fr]">
        <div className="min-w-0">
          {/* 顶部：账本名 + 三视角切换 */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              {/* flex-wrap + 分段 nowrap:窄屏被右侧切换器挤压时整段换行,
                  而不是 CJK 逐字断行(范围括号最多整体掉到第二行) */}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <CalendarDays className="h-3 w-3 shrink-0" />
                <span className="whitespace-nowrap">
                  {t('home.scope.current')} · {scopeLabel}
                </span>
                {monthRangeLabel && (
                  <span className="whitespace-nowrap font-normal normal-case tracking-normal text-muted-foreground/70">
                    ({monthRangeLabel})
                  </span>
                )}
              </div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="min-w-0 break-words text-base font-medium leading-relaxed">
                  {activeLedger?.ledger_name || '—'}
                </span>
                <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                  {currency}
                </span>
              </div>
            </div>
            <div className="shrink-0">
              <ScopeSwitcher value={scope} onChange={setScope} />
            </div>
          </div>

          <div className="mt-6 text-sm text-muted-foreground">
            {scopeBalanceHint}
          </div>
          <Amount
            value={balance}
            showCurrency
            currency={currency}
            size="4xl"
            bold
            animate
            tone="default"
            className="mt-1 block font-semibold tracking-tight"
          />
          <Button type="button" className="mt-5 h-11 gap-2 rounded-xl px-5" disabled={!activeLedger} onClick={() => dispatchOpenNewTx()}>
            <Plus className="h-4 w-4" />{t('home.quickEntry')}
          </Button>

          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <HeroStat
              icon={<ArrowDownLeft className="h-3.5 w-3.5 text-income" />}
              label={t('home.hero.income').replace('{scope}', scopeLabel)}
              className="bee-rise-in"
              style={{ animationDelay: '0ms' }}
            >
              <Amount
                value={income}
                currency={currency}
                showCurrency
                bold
                animate
                animateDelay={0.45}
                size="xl"
                tone="positive"
                className="mt-0.5 block leading-tight"
              />
            </HeroStat>
            <HeroStat
              icon={<ArrowUpRight className="h-3.5 w-3.5 text-expense" />}
              label={t('home.hero.expense').replace('{scope}', scopeLabel)}
              className="bee-rise-in"
              style={{ animationDelay: '110ms' }}
            >
              <Amount
                value={expense}
                currency={currency}
                showCurrency
                bold
                animate
                animateDelay={0.55}
                size="xl"
                tone="negative"
                className="mt-0.5 block leading-tight"
              />
            </HeroStat>
            <HeroStat
              icon={<Receipt className="h-3.5 w-3.5 text-amber-500" />}
              label={t('home.hero.count')}
              className="bee-rise-in"
              style={{ animationDelay: '220ms' }}
            >
              <div className="mt-0.5 font-mono text-xl font-bold tabular-nums leading-tight">
                {txCount.toLocaleString()}
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">
                  {t('home.hero.countUnit')}
                </span>
              </div>
            </HeroStat>
            <HeroStat
              icon={<CalendarDays className="h-3.5 w-3.5 text-sky-500" />}
              label={t('home.hero.days')}
              className="bee-rise-in"
              style={{ animationDelay: '330ms' }}
            >
              <div className="mt-0.5 font-mono text-xl font-bold tabular-nums leading-tight">
                {days.toLocaleString()}
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">
                  {t('home.hero.daysUnit')}
                </span>
              </div>
            </HeroStat>
          </div>

          {/* 预算 + 异常归因 chip — 关键回顾信息一行带过,hover 出详情 */}
          <HeroInsightsRow
            budgets={budgets || []}
            budgetUsageById={budgetUsageById || {}}
            anomalyMonths={anomalyMonths || []}
            hasEnoughMonths={!!hasEnoughMonthsForAnomaly}
            currency={currency}
            ledgerMonthStartDay={ledgerMonthStartDay}
          />
        </div>

        {/* 右侧：sparkline，随 scope 变 */}
        <div className="flex min-w-0 flex-col gap-3 border-t border-border/60 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t('home.hero.trend').replace('{scope}', scopeLabel)}</span>
            {trendData.length > 0 ? (
              <span className="font-mono tabular-nums">
                {trendData.length}
                {scope === 'month'
                  ? t('home.hero.trendUnit.day')
                  : scope === 'year'
                    ? t('home.hero.trendUnit.month')
                    : t('home.hero.trendUnit.period')}
              </span>
            ) : null}
          </div>
          <div className="h-36 min-h-0 lg:h-auto lg:min-h-40 lg:flex-1">
            {trendData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={trendData}
                  margin={{ left: 0, right: 0, top: 4, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="homeHeroGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="5%"
                        stopColor="hsl(var(--primary))"
                        stopOpacity={0.55}
                      />
                      <stop
                        offset="95%"
                        stopColor="hsl(var(--primary))"
                        stopOpacity={0.02}
                      />
                    </linearGradient>
                  </defs>
                  <Tooltip
                    cursor={false}
                    contentStyle={{
                      background: 'hsl(var(--popover))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: 6,
                      fontSize: 11
                    }}
                    formatter={
                      ((v: number) => [
                        v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
                        t('home.hero.balanceAccum')
                      ]) as unknown as never
                    }
                    labelFormatter={(_label, payload) => {
                      const item = payload?.[0]?.payload as { bucket?: string }
                      return item?.bucket || ''
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    fill="url(#homeHeroGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : trendData.length === 1 ? (
              <div className="flex h-full flex-col justify-center gap-2 rounded-xl bg-background px-5">
                <p className="text-sm text-muted-foreground">{trendData[0].bucket}</p>
                <Amount value={trendData[0].v} currency={currency} showCurrency size="2xl" tone="default" bold />
                <p className="text-xs text-muted-foreground">{t('home.hero.singlePoint')}</p>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                {t('home.hero.noTx')}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ScopeSwitcher({
  value,
  onChange
}: {
  value: HeroScope
  onChange: (v: HeroScope) => void
}) {
  const t = useT()
  return (
    <div className="inline-flex rounded-xl bg-muted/65 p-1">
      {SCOPE_VALUES.map((scope) => {
        const active = scope === value
        return (
          <button
            key={scope}
            type="button"
            onClick={() => onChange(scope)}
            aria-pressed={active}
            className={`min-h-11 rounded-lg px-3 text-sm font-medium transition-colors ${
              active
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t(`home.scope.${scope}`)}
          </button>
        )
      })}
    </div>
  )
}

function HeroStat({
  icon,
  label,
  children,
  className,
  style
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      className={`min-w-0 rounded-xl bg-background px-3 py-3${className ? ` ${className}` : ''}`}
      style={style}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      {children}
    </div>
  )
}

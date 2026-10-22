import { Wallet, AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { ReactNode } from 'react'
import type {
  ReadBudget,
  WorkspaceAnalyticsAnomalyMonth,
} from '@beecount/api-client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, useT } from '@beecount/ui'
import type { BudgetUsage } from '@beecount/web-features'

import {
  AnomalyMonthsBody,
} from './AnomalyMonthsAttribution'
import {
  BudgetUsageBody,
  useBudgetUsageViewModel,
} from './BudgetUsagePanel'

interface Props {
  budgets: ReadBudget[]
  budgetUsageById: Record<string, BudgetUsage>
  anomalyMonths: WorkspaceAnalyticsAnomalyMonth[]
  hasEnoughMonths: boolean
  currency?: string
  ledgerMonthStartDay?: number
}

/**
 * Hero 卡片内的小型 chip row(预算 + 异常归因)。chip 显示关键数字 + 状态;
 * 点击或键盘打开共用弹窗，复用 BudgetUsageBody / AnomalyMonthsBody。
 *
 * 设计动机:之前两个独立 panel 太占首页空间,用户视觉一眼能看到的"本月情况"
 * 应该在 hero 内部一行带过,详情按需展开。
 *
 * 详情使用现有 Dialog 的焦点、关闭与滚动设施，触控无需模拟 hover。
 */
export function HeroInsightsRow({
  budgets,
  budgetUsageById,
  anomalyMonths,
  hasEnoughMonths,
  currency = 'CNY',
  ledgerMonthStartDay = 1,
}: Props) {
  const t = useT()
  const budgetVM = useBudgetUsageViewModel(budgets, budgetUsageById)
  const anomalyCount = anomalyMonths.length

  const showBudget = !budgetVM.isEmpty
  // 异常 chip 显示规则:有异常 → 红色;没异常但月份够 → 绿色 ✓;月份不足 → 不显示
  const showAnomaly = anomalyCount > 0 || hasEnoughMonths

  if (!showBudget && !showAnomaly) return null

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {showBudget && (
        <BudgetChip
          ratio={budgetVM.totalRatio}
          hasTotal={budgetVM.total != null}
          categoryOverCount={budgetVM.summary.over}
          categoryCount={budgetVM.categoryBudgets.length}
        >
          <div className="min-w-0">
            <BudgetUsageBody
              viewModel={budgetVM}
              usageById={budgetUsageById}
              currency={currency}
              ledgerMonthStartDay={ledgerMonthStartDay}
            />
          </div>
        </BudgetChip>
      )}

      {showAnomaly && (
        <AnomalyChip count={anomalyCount}>
          <div className="min-w-0">
            <AnomalyMonthsBody
              anomalyMonths={anomalyMonths}
              hasEnoughMonths={hasEnoughMonths}
              currency={currency}
            />
          </div>
        </AnomalyChip>
      )}

      <span className="text-xs text-muted-foreground">
        {t('home.insights.hint')}
      </span>
    </div>
  )
}

function chipBaseClass(active: boolean) {
  return [
    'inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 py-2',
    'text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
    active
      ? 'border-expense/40 bg-expense/10 text-expense hover:bg-expense/15'
      : 'border-border/60 bg-background/70 text-foreground hover:bg-accent/40',
  ].join(' ')
}

function InsightChip({ active, title, icon, badge, children }: {
  active: boolean; title: string; icon: ReactNode; badge?: ReactNode; children: ReactNode
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button" className={chipBaseClass(active)}>
          {icon}<span>{title}</span>{badge}
        </button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}

function BudgetChip({
  ratio,
  hasTotal,
  categoryOverCount,
  categoryCount,
  children,
}: {
  ratio: number
  hasTotal: boolean
  categoryOverCount: number
  categoryCount: number
  children: React.ReactNode
}) {
  const t = useT()
  // 总预算无 → 用 category 状态决定 chip 显示;有 total → ratio 主导
  const totalOver = hasTotal && ratio >= 1
  const totalNear = hasTotal && ratio >= 0.9 && ratio < 1
  const isAlert = totalOver || categoryOverCount > 0
  const pct = hasTotal ? `${Math.round(ratio * 100)}%` : null

  const title = hasTotal
          ? t('home.insights.budgetChipTotal').replace('{pct}', pct ?? '0%')
          : t('home.insights.budgetChipCatOnly').replace(
              '{count}',
              String(categoryCount),
            )
  return (
    <InsightChip active={isAlert} title={title} icon={<Wallet className="h-3.5 w-3.5" aria-hidden />}
      badge={<>{categoryOverCount > 0 && (
        <span className="ml-0.5 inline-flex items-center gap-0.5 rounded-full bg-expense/20 px-1.5 py-px text-[10px] text-expense">
          ⚠ {categoryOverCount}
        </span>
      )}
      {totalNear && !categoryOverCount && (
        <span className="ml-0.5 text-[10px] text-orange-500">●</span>
      )}</>}>
      {children}
    </InsightChip>
  )
}

function AnomalyChip({
  count,
  children,
}: {
  count: number
  children: React.ReactNode
}) {
  const t = useT()
  const has = count > 0

  return (
    <InsightChip active={has} title={has
          ? t('home.insights.anomalyChip').replace('{count}', String(count))
          : t('home.insights.anomalyChipClean')}
      icon={has ? (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <CheckCircle2 className="h-3.5 w-3.5 text-green-600" aria-hidden />
      )}>
      {children}
    </InsightChip>
  )
}

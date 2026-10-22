import type {
  ReadBudget,
  WorkspaceAccount,
  WorkspaceAnalytics,
  WorkspaceAnalyticsSeriesItem,
  WorkspaceAnalyticsSummary,
  WorkspaceLedgerCounts,
  WorkspaceTag
} from '@beecount/api-client'
import { useT } from '@beecount/ui'
import type { BudgetUsage } from '@beecount/web-features'

import { useLedgers } from '../../context/LedgersContext'
import {
  dispatchOpenDetailAccount,
  dispatchOpenDetailTag,
} from '../../lib/txDialogEvents'
import { HomeHero } from '../dashboard/HomeHero'
import { HomeHabitStats } from '../dashboard/HomeHabitStats'
import { HomeYearHeatmap } from '../dashboard/HomeYearHeatmap'
import { HomeMonthCategoryDonut } from '../dashboard/HomeMonthCategoryDonut'
import { HomeTopTags } from '../dashboard/HomeTopTags'
import { HomeTopAccounts } from '../dashboard/HomeTopAccounts'
import { AssetCompositionDonut } from '../dashboard/AssetCompositionDonut'
import { ChannelAccountsSummary } from '../ChannelAccountsSummary'
import { useAuth } from '../../context/AuthContext'
import { readOcrPreferences } from '../../lib/ocr-preferences'
import { MonthlyTrendBars } from '../dashboard/MonthlyTrendBars'
import { TopCategoriesList } from '../dashboard/TopCategoriesList'

interface Props {
  accounts: WorkspaceAccount[]
  tags: WorkspaceTag[]
  currentMonthSummary: WorkspaceAnalyticsSummary | null
  currentMonthSeries: WorkspaceAnalyticsSeriesItem[]
  currentMonthCategoryRanks: WorkspaceAnalytics['category_ranks']
  currentYearSummary: WorkspaceAnalyticsSummary | null
  currentYearSeries: WorkspaceAnalyticsSeriesItem[]
  allTimeSummary: WorkspaceAnalyticsSummary | null
  allTimeSeries: WorkspaceAnalyticsSeriesItem[]
  analyticsData: WorkspaceAnalytics | null
  analyticsIncomeRanks: WorkspaceAnalytics['category_ranks']
  ledgerCounts: WorkspaceLedgerCounts | null
  /** 当前账本预算 + 各 budget 当周期 used。空数组 → BudgetUsagePanel 不显示。 */
  budgets: ReadBudget[]
  budgetUsageById: Record<string, BudgetUsage>
  onJumpToTransactionsWithQuery: (query: string) => void
  /** Top 卡片点击分类名时的钩子 — page 端反查 WorkspaceCategory 后派发详情。
   *  没传则 Top 卡片回退到 onJumpToTransactionsWithQuery。 */
  onCategoryClickFromTop?: (name: string, kind: 'expense' | 'income') => void
}

/**
 * 首页 overview dashboard —— 从 AppPage.tsx 抽出独立组件。
 *
 * 渲染顺序对应 mobile 首页对标 + Web 独有扩展分析:
 *   - HomeHero:核心指标(本月/本年/全期)+ 账本列表 hero
 *   - HomeHabitStats:习惯画像(连续记账天数等)
 *   - [扩展分析分割线]
 *   - HomeMonthCategoryDonut + HomeYearHeatmap 并排
 *   - AssetCompositionDonut + MonthlyTrendBars 并排
 *   - TopCategoriesList(支出 + 收入)并排
 *   - HomeTopTags + HomeTopAccounts 并排
 */
export function OverviewSection({
  accounts,
  tags,
  currentMonthSummary,
  currentMonthSeries,
  currentMonthCategoryRanks,
  currentYearSummary,
  currentYearSeries,
  allTimeSummary,
  allTimeSeries,
  analyticsData,
  analyticsIncomeRanks,
  ledgerCounts,
  budgets,
  budgetUsageById,
  onJumpToTransactionsWithQuery,
  onCategoryClickFromTop,
}: Props) {
  const t = useT()
  const { ledgers, activeLedgerId, currency } = useLedgers()
  const { profileMe } = useAuth()
  const channelPrefs = readOcrPreferences(profileMe?.ai_config, activeLedgerId || '')
  const channelMode = channelPrefs.accounting_mode === 'channel'

  // 预算 + 异常归因被合并进 HomeHero 顶部 chip(hover 出详情),不再独占
  // 卡片占首页空间。月份够算 baseline 的判定跟 server 算法一致(已发生月份 ≥ 3)。
  const yearOccurredMonths = (analyticsData?.series || []).filter(
    (s) => s.expense > 0,
  ).length

  return (
    <div className="space-y-4">
      <HomeHero
        ledgers={ledgers}
        currentLedgerId={activeLedgerId || undefined}
        monthSummary={currentMonthSummary || undefined}
        monthSeries={currentMonthSeries}
        yearSummary={currentYearSummary || undefined}
        yearSeries={currentYearSeries}
        allSummary={allTimeSummary || undefined}
        allSeries={allTimeSeries}
        ledgerCounts={ledgerCounts || undefined}
        budgets={budgets}
        budgetUsageById={budgetUsageById}
        anomalyMonths={analyticsData?.anomaly_months || []}
        hasEnoughMonthsForAnomaly={yearOccurredMonths >= 3}
      />

      <HomeHabitStats
        monthSummary={currentMonthSummary || undefined}
        ledgerCounts={ledgerCounts || undefined}
        currency={currency}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <HomeMonthCategoryDonut ranks={currentMonthCategoryRanks} currency={currency} />
        {channelMode ? <ChannelAccountsSummary accounts={accounts} primaryIds={[channelPrefs.wechat_account_id, channelPrefs.alipay_account_id]} onSelectAccount={acc => dispatchOpenDetailAccount(acc, { defaultScope: 'current' })} />
          : <HomeTopAccounts accounts={accounts} currency={currency} onSelectAccount={(acc) => dispatchOpenDetailAccount(acc, { defaultScope: 'current' })} />}
      </div>

      <details className="rounded-2xl border border-border/70 bg-card">
        <summary className="cursor-pointer rounded-2xl px-5 py-4 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t('analytics.ext.title')}</summary>
        <div className="space-y-4 border-t border-border/60 p-4">
        <HomeYearHeatmap yearSeries={currentYearSeries} currency={currency} />

      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        {channelMode ? null : <AssetCompositionDonut accounts={accounts} />}
        <MonthlyTrendBars data={analyticsData?.series || []} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <TopCategoriesList
          ranks={analyticsData?.category_ranks || []}
          variant="expense"
          title={t('analytics.expenseTop5')}
          onClickCategory={
            onCategoryClickFromTop
              ? (name) => onCategoryClickFromTop(name, 'expense')
              : onJumpToTransactionsWithQuery
          }
        />
        <TopCategoriesList
          ranks={analyticsIncomeRanks}
          variant="income"
          title={t('analytics.incomeTop5')}
          onClickCategory={
            onCategoryClickFromTop
              ? (name) => onCategoryClickFromTop(name, 'income')
              : onJumpToTransactionsWithQuery
          }
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <HomeTopTags
          tags={tags}
          currency={currency}
          onSelectTag={(tag) =>
            dispatchOpenDetailTag(tag, { defaultScope: 'current' })
          }
        />
      </div>
        </div>
      </details>
    </div>
  )
}

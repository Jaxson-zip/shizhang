import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../../i18n'
import { HomeHero } from './HomeHero'
import { HomeHabitStats } from './HomeHabitStats'

const counts = { tx_count: 5, distinct_days: 2, days_since_first_tx: 3, first_tx_at: '2026-10-15T04:00:00Z' }
function text(child: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(LocaleProvider, {
    dictionaries: { ...dictionaries, en: dictionaries['zh-CN'] },
  }, child)).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
}

it('labels actual local transaction dates as logged days, excluding intervening days without records', () => {
  expect(text(createElement(HomeHero, { ledgers: [], ledgerCounts: counts }))).toContain('记账天数 2 天')
})

it('makes the calendar span used by the lifetime daily average explicit', () => {
  const result = text(createElement(HomeHabitStats, { ledgerCounts: counts }))
  expect(result).toContain('1.67 笔 / 天')
  expect(result).toContain('累计 5 笔 · 首笔至今 3 天')
})

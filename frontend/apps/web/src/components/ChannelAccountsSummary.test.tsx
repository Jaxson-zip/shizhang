import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import type { WorkspaceAccount } from '@beecount/api-client'
import { dictionaries } from '../i18n'
import { ChannelAccountsSummary } from './ChannelAccountsSummary'

it('sums native channel flows once, ignores initial balances and does not invent a third account', () => {
  const accounts = [
    { id: 'w', name: '微信', currency: 'CNY', initial_balance: 10000, balance: 9990, income_total: 5, expense_total: 15 },
    { id: 'a', name: '支付宝', currency: 'CNY', initial_balance: 50000, balance: 49980, income_total: 7, expense_total: 27 },
  ] as WorkspaceAccount[]
  const html = renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, createElement(ChannelAccountsSummary, { accounts })))
  expect(html).toContain('12.00')
  expect(html).toContain('42.00')
  expect(html).toContain('-30.00')
  expect(html).not.toContain('10,000')
  expect(html).not.toContain('50,000')
  expect(html).toContain('微信')
  expect(html).toContain('支付宝')
})

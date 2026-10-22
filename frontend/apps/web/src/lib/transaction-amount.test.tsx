import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import type { ReadTransaction, WorkspaceTransaction } from '@beecount/api-client'
import { LocaleProvider } from '@beecount/ui'
import { TransactionRow, transactionAmountDisplay } from '@beecount/web-features'
import { dictionaries } from '../i18n'
import { DayTxList } from '../pages/sections/CalendarPage'
import { OverviewRecentTransactions } from '../components/dashboard/OverviewRecentTransactions'
import { TransactionDetailAmount } from '../components/dialogs/TransactionDetailDialog'

function syntheticTransaction(amount: number, tx_type: ReadTransaction['tx_type'] = 'expense'): WorkspaceTransaction {
  return { id: 'synthetic', tx_index: 1, tx_type, amount, happened_at: '2026-10-17T08:00:00Z',
    note: null, category_name: 'Synthetic category', category_kind: tx_type, account_name: 'Synthetic wallet',
    from_account_name: null, to_account_name: null, tags: null, tags_list: [], attachments: [], last_change_id: 0,
    ledger_id: 'synthetic-ledger', ledger_name: 'Synthetic ledger', created_by_user_id: null, created_by_email: null }
}

function renderRow(row: ReadTransaction) {
  return renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, createElement(TransactionRow, { row })))
}

it('shows a signed expense refund as money returned, with one positive sign and income tone', () => {
  const html = renderRow(syntheticTransaction(-1.25))
  expect(html).toMatch(/text-income[^>]*>\+1\.25</)
  expect(html).not.toContain('--1.25')
})

it('shows the same expense refund direction in the calendar and recent entries', () => {
  const tx = syntheticTransaction(-1.25)
  const render = (child: ReturnType<typeof createElement>) => renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, child))
  expect(render(createElement(DayTxList, { txs: [tx], loading: false, currency: 'CNY' })))
    .toMatch(/text-\[rgb\(var\(--income-rgb\)\)\][^>]*>\+CNY 1\.25</)
  expect(render(createElement(OverviewRecentTransactions, { transactions: [tx] })))
    .toMatch(/text-income[^>]*>\+1\.25</)
})

it('keeps refund direction in the detail amount and its converted amount snapshot', () => {
  const tx = { ...syntheticTransaction(-1.25), currency_code: 'USD', native_amount: -8.75 }
  const html = renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, createElement(TransactionDetailAmount, { tx })))
  expect(html).toMatch(/text-income[^>]*>\+1\.25/)
  expect(html).toContain('≈ +8.75')
  expect(renderRow(tx)).toContain('≈+8.75')
})

it.each([
  ['expense', 12.5, '-', 'negative'], ['expense', -12.5, '+', 'positive'],
  ['income', 12.5, '+', 'positive'], ['income', -12.5, '-', 'negative'],
  ['transfer', 12.5, '', 'default'], ['expense', -0, '', 'default'],
  ['income', 0.001, '', 'default'], ['expense', 0.001, '', 'default'],
] as const)('keeps the native %s / %s direction and does not imply income for transfers', (type, value, sign, tone) => {
  expect(transactionAmountDisplay(type, value)).toEqual({ magnitude: Math.abs(value), sign, tone })
  const html = renderRow(syntheticTransaction(value, type))
  const toneClass = tone === 'positive' ? 'text-income' : tone === 'negative' ? 'text-expense' : 'text-foreground'
  const escapedSign = sign === '+' ? '\\+' : sign
  expect(html).toMatch(new RegExp(`${toneClass}[^>]*>${escapedSign}${Math.abs(value).toFixed(2)}<`))
})

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { txDefaults } from '@beecount/web-features'
import { canSummarizeOcrForm, OcrReviewSummary } from './OcrReviewSummary'

const form = { ...txDefaults(), amount: '3.00', happened_at: '2026-10-16T20:33:25+08:00',
  category_name: '其他支出', account_name: '微信', note: '合成收款人' }

it('shows a signed, read-only payment summary and an edit action without exposing another input form', () => {
  const html = renderToStaticMarkup(<OcrReviewSummary form={form} onEdit={() => {}} />)
  expect(html).toContain('−¥3.00')
  expect(html).toContain('微信')
  expect(html).toContain('2026/10/16')
  expect(html).toContain('20:33:25')
  expect(html).toContain('修改信息')
  expect(html).not.toContain('<input')
  expect(renderToStaticMarkup(<OcrReviewSummary form={{ ...form, tx_type: 'income' }} onEdit={() => {}} />)).toContain('+¥3.00')
})

it('requires the full editor for missing or ambiguous facts, and leaves account transfers explicit', () => {
  expect(canSummarizeOcrForm(form)).toBe(true)
  for (const patch of [{ amount: '' }, { amount: '-3' }, { amount: '3.OO' }, { amount: '0' },
    { account_name: '' }, { category_name: '' }, { happened_at: '' }, { happened_at: 'not a date' },
    { tx_type: 'transfer' as const }]) expect(canSummarizeOcrForm({ ...form, ...patch })).toBe(false)
  const flagged = renderToStaticMarkup(<OcrReviewSummary form={{ ...form, exclude_from_stats: true }} onEdit={() => {}} />)
  expect(flagged).toContain('暂不计入收支统计')
})

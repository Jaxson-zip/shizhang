import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { OcrInboxPanel } from './OcrInboxPanel'
import { dictionaries } from '../i18n'
import { captureGaps, ocrInboxForm, type OcrInboxItem } from '../lib/ocr-inbox'
import { captureReviewNotice } from './GlobalEditDialogs'

const item: OcrInboxItem = { id: 'capture', ledger_id: 'ledger', created_at: '2026-10-18T02:00:00Z',
  status: 'pending', revision: '0'.repeat(64),
  reason: '请稍后核对用途', entity_id: 'tx', request_key: 'key',
  draft: { type: 'income', amount: 48, happened_at: '', note: '合成收款', account_name: '零钱', category_name: '' } }
function render(items: OcrInboxItem[], error = '', view: 'pending' | 'ignored' = 'pending', ignoredTotal = 0) {
  return renderToStaticMarkup(<LocaleProvider dictionaries={dictionaries}><OcrInboxPanel items={items} total={items.length} loading={false} error={error} view={view} pendingTotal={view === 'pending' ? items.length : 0} ignoredTotal={view === 'ignored' ? items.length : ignoredTotal} onViewChange={() => {}} onChangeState={() => {}} onRetry={() => {}} onMore={() => {}} onReview={() => {}} /></LocaleProvider>)
}
it('distinguishes positive recorded income from an unbooked unknown capture without a fake zero', () => {
  const html = render([item, { ...item, id: 'unknown', entity_id: null, draft: null }])
  expect(html).toContain('+¥48.00')
  expect(html).toContain('已有关联账目 · 待核对')
  expect(html).toContain('已收下 · 尚未入账')
  expect(html).toContain('金额待核对')
  expect(html).not.toContain('¥0.00')
})
it('has distinct empty and read-failed states instead of claiming there is nothing to check', () => {
  expect(render([])).toContain('暂无待核对内容')
  expect(render([], '读取失败')).toContain('role="alert"')
})
it('keeps unknown amount/time empty and preserves the captured incoming account endpoint', () => {
  expect(ocrInboxForm({ ...item, draft: null }, 'income')).toMatchObject({ amount: '', happened_at: '', tx_type: 'income' })
  expect(ocrInboxForm(item, 'transfer')).toMatchObject({ to_account_name: '零钱', from_account_name: '' })
})

it('preserves deliberate saving exclusions in both complete and incomplete review prefills', () => {
  expect(ocrInboxForm({ ...item, draft: { ...item.draft!, exclude_from_stats: true, exclude_from_budget: true } }, 'expense'))
    .toMatchObject({ exclude_from_stats: true, exclude_from_budget: true })
  expect(ocrInboxForm({ ...item, draft: null, accounting_flags: { exclude_from_stats: true, exclude_from_budget: true } }, 'expense'))
    .toMatchObject({ amount: '', happened_at: '', exclude_from_stats: true, exclude_from_budget: true })
})

it('offers ignore only for unbooked captures, and a recoverable ignored view after the pending list is empty', () => {
  expect(render([item])).not.toContain('忽略这次采集')
  expect(render([{ ...item, entity_id: null, draft: null }])).toContain('忽略这次采集')
  const ignored = render([{ ...item, entity_id: null, draft: null }], '', 'ignored')
  expect(ignored).toContain('恢复待核对')
  expect(ignored).not.toContain('补记支出')
  expect(ignored).toContain('尚未入账')
  expect(render([], '', 'pending', 1)).toContain('已忽略')
})

it('shows picture-only evidence and does not render OCR text even if a stale caller includes it', () => {
  const legacySource = { id: item.id, text: '<script>synthetic source</script>', loading: false }
  const html = renderToStaticMarkup(<LocaleProvider dictionaries={dictionaries}><OcrInboxPanel
    items={[{ ...item, entity_id: null, draft: null }]} total={1} pendingTotal={0} ignoredTotal={1}
    view="ignored" loading={false} error="" onRetry={() => {}} onMore={() => {}} onReview={() => {}}
    onViewSource={() => {}} source={legacySource}
  /></LocaleProvider>)
  expect(html).toContain('收起截图')
  expect(html).toContain('截图未上传或已清理')
  expect(html).not.toContain('synthetic source')
  expect(html).not.toContain('<script>synthetic source</script>')
  expect(html).toContain('北京时间')
})

it('offers review rather than a second booking when a linked entry has no parsed draft', () => {
  const html = render([{ ...item, draft: null }])
  expect(html).toContain('核对这笔')
  expect(html).not.toContain('补记支出')
  expect(html).not.toContain('忽略这次采集')
})

it('shows temporary image expiry and reread only for unbooked records, without inventing an image for old captures', () => {
  const picture = { available: true, expires_at: '2026-10-25T04:00:00Z' }
  const html = renderToStaticMarkup(<LocaleProvider dictionaries={dictionaries}><OcrInboxPanel
    items={[{ ...item, entity_id: null, draft: null, image: picture }]} total={1}
    loading={false} error="" onRetry={() => {}} onMore={() => {}} onReview={() => {}} onReread={() => {}}
    source={{ id: item.id, loading: false, imageUrl: 'blob:synthetic' }}
  /></LocaleProvider>)
  expect(html).toContain('用截图重新识别')
  expect(html).toContain('临时截图保留至')
  expect(html).toContain('blob:synthetic')
  expect(render([{ ...item, image: { available: false, expires_at: null } }])).toContain('未上传或已清理')
  expect(render([{ ...item, image: picture }])).not.toContain('用截图重新识别')
})

it('separates unbooked, provisional, counted and deleted entries instead of calling them all booked', () => {
  const provisional = render([{ ...item, entry: { exists: true, exclude_from_stats: true } }])
  expect(provisional).toContain('已记临时账目 · 暂不计收支统计')
  expect(provisional).not.toContain('已入账')
  expect(render([{ ...item, entry: { exists: true, exclude_from_stats: false } }])).toContain('已入账并计入统计')
  const gone = render([{ ...item, entry: { exists: false, exclude_from_stats: false } }])
  expect(gone).toContain('关联账目已删除或不可见')
  expect(gone).toContain('忽略这次采集')     // the only way out once the user deleted the entry
  expect(gone).not.toContain('核对这笔')
  expect(render([{ ...item, entity_id: null, entry: null }])).toContain('已收下 · 尚未入账')
})

it('names the fields an unbooked capture still lacks, without a category gate', () => {
  const partial = { ...item, entity_id: null, draft: { ...item.draft!, happened_at: '', account_name: '', category_name: '' } }
  expect(captureGaps(partial)).toEqual(['付款时间', '账户'])
  expect(render([partial])).toContain('待补：付款时间、账户')
  expect(render([{ ...item, entity_id: null, draft: null }])).toContain('待补：金额、收支方向、付款时间、账户')
  expect(render([{ ...item, entity_id: null, draft: { ...item.draft!, happened_at: '2026-10-18T02:00:00Z' } }])).not.toContain('待补')
  expect(render([{ ...item, draft: { ...item.draft!, happened_at: '' } }])).not.toContain('待补')  // linked entry: review it there
})

it('tells the reviewer whether confirming updates the existing entry or records the only one', () => {
  expect(captureReviewNotice('provisional')).toContain('更新原账目，不会另记一笔')
  expect(captureReviewNotice('provisional')).toContain('暂不计收支统计')
  expect(captureReviewNotice('counted')).toContain('已入账')
  expect(captureReviewNotice('none')).toContain('尚未入账')
  expect(captureReviewNotice('none')).toContain('只记这一笔')
})

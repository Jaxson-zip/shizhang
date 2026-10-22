import { describe, expect, it, vi } from 'vitest'
import { txDefaults } from '@beecount/web-features'
import { captureOcrReview, consumeOcrReview, ocrReviewForm, ocrReviewTypes, ocrReviewTypeChange } from './ocr-review'

const now = 1_790_000_000_000
const payload = { version: 1, user_id: 'synthetic-user', ledger_id: 'ledger-test',
  review_id: 'ocr-review-11111111-1111-4111-8111-111111111111', expires_at: now + 15 * 60_000,
  amount: .01, happened_at: '2026-10-17T15:11:02+08:00', note: '合成商家', account_name: '微信零钱', category_name: '其他' }
function fixture(value: Record<string, unknown> = payload) {
  const memory = new Map<string, string>()
  const storage = { getItem: (key: string) => memory.get(key) ?? null, setItem: (key: string, value: string) => { memory.set(key, value) }, removeItem: (key: string) => { memory.delete(key) } }
  const hash = '#ocr-review=' + Buffer.from(JSON.stringify(value)).toString('base64url')
  return { win: { location: { hash, pathname: '/app/overview', search: '' }, history: { replaceState: vi.fn() }, sessionStorage: storage }, storage }
}
describe('OCR review handoff', () => {
  it('cleans private fields out of the URL and keeps a one-use review across login in the same tab', () => {
    const { win, storage } = fixture()
    captureOcrReview(win, now)
    expect(win.history.replaceState).toHaveBeenCalledWith(null, '', '/app/overview')
    expect(consumeOcrReview(storage, payload.user_id, null, now)).toBeNull()
    expect(consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'owner' }], now)).toEqual(payload)
    expect(consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'owner' }], now)).toBeNull()
  })
  it('does not hand an already logged-in different account the captured fields', () => {
    const { win, storage } = fixture()
    captureOcrReview(win, now)
    expect(() => consumeOcrReview(storage, 'different-user', [], now)).toThrow('INVALID')
    expect(consumeOcrReview(storage, payload.user_id, [], now)).toBeNull()
  })
  it.each(['viewer', 'missing'])('refuses a %s target without falling back to another writable ledger', (role) => {
    const { win, storage } = fixture()
    captureOcrReview(win, now)
    expect(() => consumeOcrReview(storage, payload.user_id, [{ ledger_id: role === 'missing' ? 'another' : payload.ledger_id, role: role === 'missing' ? 'owner' : role }], now)).toThrow('INVALID')
  })
  it('expires display fields and does not use the current time or a remembered account for missing values', () => {
    const { win, storage } = fixture({ ...payload, happened_at: '', account_name: '' })
    captureOcrReview(win, now)
    const result = consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'editor' }], now)
    expect(result?.happened_at).toBe('')
    expect(result?.account_name).toBe('')
    captureOcrReview(win, now)
    expect(() => consumeOcrReview(storage, payload.user_id, [], now + 16 * 60_000)).toThrow('INVALID')
  })
  it.each([{ ...payload, amount: -1 }, { ...payload, amount: .001 }, { ...payload, amount: 1e20 }, { ...payload, review_id: 'arbitrary-key' }])('rejects invalid display or save identifiers', (value) => {
    const { win, storage } = fixture(value)
    captureOcrReview(win, now)
    expect(win.history.replaceState).toHaveBeenCalled()
    expect(() => consumeOcrReview(storage, payload.user_id, [], now)).toThrow('INVALID')
  })
  it('preserves incoming direction on v2 personal prefill without applying an expense category', () => {
    const personal = { ...payload, version: 2, tx_type: 'income', review_reason: 'personal_incoming', category_name: '' }
    const { win, storage } = fixture(personal)
    captureOcrReview(win, now)
    expect(consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'owner' }], now)).toEqual(personal)
  })
  it.each([
    { tx_type: 'income', review_reason: 'personal_incoming', destination: 'to_account_name', forbidden: 'expense' },
    { tx_type: 'expense', review_reason: 'group_payment', destination: 'from_account_name', forbidden: 'income' },
  ])('initializes $review_reason with direction, blank category and matching transfer endpoint', (kind) => {
    const { win, storage } = fixture({ ...payload, version: 2, ...kind, category_name: '' })
    captureOcrReview(win, now)
    const review = consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'owner' }], now)!
    expect(ocrReviewForm(review)).toMatchObject({ tx_type: kind.tx_type, category_kind: kind.tx_type,
      category_name: '', amount: '0.01', [kind.destination]: '微信零钱' })
    expect(ocrReviewTypes(review)).toEqual([kind.tx_type, 'transfer'])
    expect(ocrReviewTypes(review)).not.toContain(kind.forbidden)
    // Changing purpose and returning must keep the user's selected endpoint,
    // not restore an unrelated remembered account or swap from/to.
    const previous = { ...txDefaults(), ...ocrReviewForm(review), account_name: '用户核对的账户' }
    const transfer = ocrReviewTypeChange(review, previous, { ...previous, tx_type: 'transfer', account_name: '' })
    expect(transfer[kind.destination as 'from_account_name' | 'to_account_name']).toBe('用户核对的账户')
    const back = ocrReviewTypeChange(review, transfer, { ...previous, from_account_name: '', to_account_name: '', account_name: '' })
    expect(back.account_name).toBe('用户核对的账户')
  })
  it.each([
    { tx_type: 'expense', review_reason: 'personal_incoming', category_name: '' },
    { tx_type: 'income', review_reason: 'group_payment', category_name: '' },
    { tx_type: 'income', review_reason: 'personal_incoming', category_name: '消费分类' },
    { tx_type: 'transfer', review_reason: 'personal_incoming', category_name: '' },
    { tx_type: 'income', review_reason: 'unknown', category_name: '' },
  ])('rejects a v2 personal prefill that loses or contradicts direction: $review_reason / $tx_type', (fields) => {
    const { win, storage } = fixture({ ...payload, version: 2, ...fields })
    captureOcrReview(win, now)
    expect(() => consumeOcrReview(storage, payload.user_id, [{ ledger_id: payload.ledger_id, role: 'owner' }], now)).toThrow('INVALID')
  })
})

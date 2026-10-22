import type { TxForm } from '@beecount/web-features'

type ReviewFields = {
  user_id: string; ledger_id: string; review_id: string; expires_at: number
  amount: number; happened_at: string; note: string; account_name: string; category_name: string
}
export type OcrReview = ReviewFields & ({ version: 1 } | {
  version: 2; tx_type: 'income' | 'expense'; review_reason: 'personal_incoming' | 'group_payment'
})
type DirectionReview = { version: 1 } | { version: 2; tx_type: 'income' | 'expense' }
export function ocrReviewTypes(review: DirectionReview): TxForm['tx_type'][] {
  return review.version === 2 ? [review.tx_type, 'transfer'] : ['expense', 'income', 'transfer']
}
export function ocrReviewForm(review: OcrReview): Partial<TxForm> {
  const type = review.version === 2 ? review.tx_type : 'expense'
  return { tx_type: type, category_kind: type, amount: String(review.amount), currency: 'CNY',
    note: review.note, account_name: review.account_name, category_name: review.category_name,
    from_account_name: review.version === 2 && type === 'expense' ? review.account_name : '',
    to_account_name: review.version === 2 && type === 'income' ? review.account_name : '' }
}
export function ocrReviewTypeChange(review: DirectionReview, previous: TxForm, next: TxForm): TxForm {
  if (review.version === 1 || previous.tx_type === next.tx_type) return next
  if (!ocrReviewTypes(review).includes(next.tx_type)) return previous
  const account = previous.tx_type === 'transfer'
    ? review.tx_type === 'income' ? previous.to_account_name : previous.from_account_name
    : previous.account_name
  return next.tx_type === 'transfer'
    ? { ...next, from_account_name: review.tx_type === 'expense' ? account : '', to_account_name: review.tx_type === 'income' ? account : '' }
    : { ...next, account_name: account }
}
export const OCR_REVIEW_EVENT = 'shizhang:ocr-review'
type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem' | 'removeItem'>
type LaunchWindow = { location: Pick<Location, 'hash' | 'pathname' | 'search'>; history: Pick<History, 'replaceState'>; sessionStorage: Storage }
const KEY = 'shizhang.ocr-review.v1'
let memory: string | null = null
export const reviewStorage: Storage = {
  getItem: (key) => window.sessionStorage.getItem(key),
  setItem: (key, value) => window.sessionStorage.setItem(key, value),
  removeItem: (key) => window.sessionStorage.removeItem(key),
}
export function retainOcrReview(storage: Storage, review: OcrReview): void {
  const raw = JSON.stringify(review)
  memory = raw
  try { storage.setItem(KEY, raw); memory = null } catch { /* same-page fallback */ }
}
function validated(value: unknown, now: number): OcrReview {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('OCR_REVIEW_INVALID')
  const p = value as Record<string, unknown>
  for (const key of ['user_id', 'ledger_id', 'review_id', 'happened_at', 'note', 'account_name', 'category_name']) {
    if (typeof p[key] !== 'string' || (p[key] as string).length > 255) throw new Error('OCR_REVIEW_INVALID')
  }
  if (![1, 2].includes(p.version as number) || !p.user_id || !p.ledger_id || !/^ocr-review-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(p.review_id as string)
    || typeof p.expires_at !== 'number' || !Number.isFinite(p.expires_at) || p.expires_at <= now || p.expires_at > now + 16 * 60_000
    || typeof p.amount !== 'number' || !Number.isFinite(p.amount) || p.amount <= 0 || p.amount > 1_000_000_000
    || Math.abs(p.amount * 100 - Math.round(p.amount * 100)) > .000001) throw new Error('OCR_REVIEW_INVALID')
  if (p.happened_at && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(p.happened_at as string)
    || !Number.isFinite(Date.parse(p.happened_at as string)))) throw new Error('OCR_REVIEW_INVALID')
  // Pick known display fields only. This is an untrusted prefill, never authority to save.
  const fields = { user_id: p.user_id as string, ledger_id: p.ledger_id as string,
    review_id: p.review_id as string, expires_at: p.expires_at, amount: p.amount,
    happened_at: p.happened_at as string, note: p.note as string, account_name: p.account_name as string, category_name: p.category_name as string }
  if (p.version === 2) {
    if (p.category_name !== '' || !(p.review_reason === 'personal_incoming' && p.tx_type === 'income'
      || p.review_reason === 'group_payment' && p.tx_type === 'expense')) throw new Error('OCR_REVIEW_INVALID')
    return { ...fields, version: 2, tx_type: p.tx_type, review_reason: p.review_reason }
  }
  return { ...fields, version: 1 }
}
/** The fragment is not sent in HTTP requests; remove it before any auth redirect. */
export function captureOcrReview(win: LaunchWindow, now = Date.now()): void {
  if (!win.location.hash.startsWith('#ocr-review=')) return
  let raw = '{"invalid":true}'
  try {
    const encoded = win.location.hash.slice('#ocr-review='.length)
    if (encoded.length > 12_000 || !/^[A-Za-z0-9_-]+$/.test(encoded)) throw new Error('OCR_REVIEW_INVALID')
    const bytes = Uint8Array.from(atob(encoded.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0))
    raw = JSON.stringify(validated(JSON.parse(new TextDecoder().decode(bytes)), now))
  } catch { /* clear malformed/expired links too; show a bounded notice after login */ }
  memory = raw
  try { win.sessionStorage.setItem(KEY, raw); memory = null } catch { /* same-page memory still survives login navigation */ }
  win.history.replaceState(null, '', win.location.pathname + win.location.search)
}
export function consumeOcrReview(storage: Storage, userId: string, ledgers: { ledger_id: string; role: string }[] | null, now = Date.now()): OcrReview | null {
  let raw = memory
  try { raw ||= storage.getItem(KEY) } catch { /* use captured memory */ }
  if (!raw) return null
  const clear = () => { memory = null; try { storage.removeItem(KEY) } catch { /* unavailable */ } }
  try {
    const review = validated(JSON.parse(raw), now)
    if (review.user_id !== userId) throw new Error('OCR_REVIEW_INVALID')
    if (ledgers === null) return null
    if (!ledgers.some((l) => l.ledger_id === review.ledger_id && (l.role === 'owner' || l.role === 'editor'))) throw new Error('OCR_REVIEW_INVALID')
    clear()
    return review
  } catch (error) { clear(); throw error }
}

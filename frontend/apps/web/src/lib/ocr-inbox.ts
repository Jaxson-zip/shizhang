import { ApiError, authedGet, authedGetBlob, authedPost } from '@beecount/api-client'
import type { TxForm } from '@beecount/web-features'

export type OcrInboxItem = {
  id: string; ledger_id: string; created_at: string; reason: string; entity_id: string | null
  request_key: string
  status: 'pending' | 'ignored' | 'confirmed'; revision: string
  image?: { available: boolean; expires_at: string | null }
  accounting_flags?: { exclude_from_stats: boolean; exclude_from_budget: boolean }
  /** Linked native entry: null when unbooked; absent from older servers. */
  entry?: { exists: boolean; exclude_from_stats: boolean } | null
  draft: { type: 'income' | 'expense'; amount: number; happened_at: string;
    note: string; account_name: string; category_name: string; exclude_from_stats?: boolean; exclude_from_budget?: boolean } | null
}
export type OcrInboxView = 'pending' | 'ignored'
/** What the list says about money: unbooked, a provisional entry outside stats, or a counted one. */
export function captureEntryState(item: Pick<OcrInboxItem, 'entity_id' | 'entry'>) {
  if (!item.entity_id) return 'unbooked' as const
  if (!item.entry) return 'linked' as const
  if (!item.entry.exists) return 'missing' as const
  return item.entry.exclude_from_stats ? 'provisional' as const : 'counted' as const
}
/** Fields the capture could not establish; the review form asks for them. Category falls back to the default. */
export function captureGaps(item: Pick<OcrInboxItem, 'draft'>): string[] {
  if (!item.draft) return ['金额', '收支方向', '付款时间', '账户']
  return [[!item.draft.happened_at, '付款时间'], [!item.draft.account_name, '账户']]
    .filter(([missing]) => missing).map(([, label]) => label as string)
}
export type OcrInboxPage = { total: number; pending_total: number; ignored_total: number; items: OcrInboxItem[] }
export const OCR_INBOX_CHANGED = 'shizhang:ocr-inbox-changed'
export async function fetchCaptureImage(token: string, id: string) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15_000)
  try {
    const blob = await authedGetBlob(`/ai/ocr-inbox/${encodeURIComponent(id)}/image`, token, controller.signal)
    if (!['image/png', 'image/jpeg'].includes(blob.type) || blob.size > 1024 * 1024) throw new Error('INVALID_CAPTURE_IMAGE')
    return blob
  } finally { clearTimeout(timeout) }
}
export async function rereadCaptureImage(token: string, item: OcrInboxItem) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 30_000)
  try {
    const result = await authedPost<OcrInboxItem & { message: string }>(`/ai/ocr-inbox/${encodeURIComponent(item.id)}/reread`, token,
      { expected_revision: item.revision, action_id: crypto.randomUUID() }, undefined, controller.signal)
    if (result?.id !== item.id || result.ledger_id !== item.ledger_id || !/^[0-9a-f]{64}$/.test(result.revision)) throw new Error('REREAD_UNCONFIRMED')
    return result
  } finally { clearTimeout(timeout) }
}
export function fetchOcrInbox(token: string, ledgerId: string, offset = 0, state: OcrInboxView = 'pending'): Promise<OcrInboxPage> {
  return authedGet(`/ai/ocr-inbox?ledger_id=${encodeURIComponent(ledgerId)}&offset=${offset}&limit=20&state=${state}`, token)
}
export async function changeOcrCaptureState(token: string, item: OcrInboxItem, status: OcrInboxView) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 20_000)
  try {
    const result = await authedPost<{ status: OcrInboxView; revision: string }>(`/ai/ocr-inbox/${encodeURIComponent(item.id)}/state`, token,
      { status, expected_revision: item.revision, action_id: crypto.randomUUID() }, undefined, controller.signal)
    if (result?.status !== status || !/^[0-9a-f]{64}$/.test(result.revision)) throw new Error('CAPTURE_STATE_UNCONFIRMED')
    return result
  } finally { clearTimeout(timeout) }
}
export async function resolveOcrCapture(token: string, id: string, entityId: string, version: number, signal?: AbortSignal): Promise<void> {
  try {
    const result = await authedPost<{ status: string }>(`/ai/ocr-inbox/${encodeURIComponent(id)}/resolve`, token,
      { entity_id: entityId, expected_change_id: version }, undefined, signal)
    if (result?.status !== 'confirmed') throw new Error('CAPTURE_REVIEW_UNCONFIRMED')
  } catch (error) {
    // Native save may already have committed. Keep an HTTP refusal's status so the writer can tell
    // a definitive refusal (entry changed/deleted, capture handled) from a lost response.
    throw Object.assign(new Error('CAPTURE_REVIEW_UNCONFIRMED'), { status: error instanceof ApiError ? error.status : undefined })
  }
  window.dispatchEvent(new Event(OCR_INBOX_CHANGED))
}
export function ocrInboxForm(item: OcrInboxItem, type: TxForm['tx_type']): Partial<TxForm> {
  const draft = item.draft
  return { tx_type: type, category_kind: type === 'income' ? 'income' : 'expense',
    amount: draft ? String(draft.amount) : '', happened_at: draft?.happened_at || '', currency: 'CNY',
    note: draft?.note || '', category_name: draft?.category_name || '', account_name: draft?.account_name || '',
    exclude_from_stats: draft?.exclude_from_stats === true || item.accounting_flags?.exclude_from_stats === true,
    exclude_from_budget: draft?.exclude_from_budget === true || item.accounting_flags?.exclude_from_budget === true,
    from_account_name: type === 'transfer' && draft?.type === 'expense' ? draft.account_name : '',
    to_account_name: type === 'transfer' && draft?.type === 'income' ? draft.account_name : '' }
}

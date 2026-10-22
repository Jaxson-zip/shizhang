import { ApiError, type TxPayload } from '@beecount/api-client'

export type ManualTxDraft = {
  ledgerId: string
  editingId?: string
  expectedVersion?: number
  requestKey?: string
  captureId?: string
  payload: TxPayload
}
export type ManualTxAttempt = ManualTxDraft & { key: string; base: number; createdAt: number }
type Dependencies<T> = {
  read: () => string | null
  store: (value: string | null) => void
  now: () => number
  key: () => string
  loadBase: (ledgerId: string) => Promise<number>
  loadVersion: (ledgerId: string, txId: string) => Promise<number | null>
  send: (attempt: ManualTxAttempt) => Promise<T>
  afterWrite?: (result: T, attempt: ManualTxAttempt) => Promise<void>
}

const RECOVERY_WINDOW_MS = 23 * 60 * 60 * 1000

function definitiveRejection(error: unknown) {
  const status = (error as { status?: unknown } | null)?.status
  return typeof status === 'number' && status >= 400 && status < 500 && status !== 408 && status !== 429
}

/** Reuses native CAS and Idempotency-Key; no automatic write retry or offline queue. */
export class ManualTxWriter<T> {
  constructor(private deps: Dependencies<T>) {}

  pending(): ManualTxAttempt | null {
    const raw = this.deps.read()
    if (!raw) return null
    const value = JSON.parse(raw) as ManualTxAttempt
    if (!value.key || !value.ledgerId || !Number.isFinite(value.base) || !Number.isFinite(value.createdAt)
      || !value.payload || !Number.isFinite(value.payload.amount)) throw new Error('RECOVERY_INVALID')
    return value
  }

  async save(draft: ManualTxDraft): Promise<T> {
    if (this.pending()) throw new Error('SAVE_PENDING')
    if (draft.requestKey && (draft.editingId || !/^ocr-review-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(draft.requestKey))) throw new Error('RECOVERY_INVALID')
    // Read head BEFORE entity version: a change during/after the latter is rejected by native CAS.
    const base = await this.deps.loadBase(draft.ledgerId)
    if (draft.editingId) {
      const latest = await this.deps.loadVersion(draft.ledgerId, draft.editingId)
      if (latest === null || latest !== draft.expectedVersion) {
        throw new ApiError('Draft differs from the latest record', { status: 409, code: 'DRAFT_CONFLICT' })
      }
    }
    if (this.pending()) throw new Error('SAVE_PENDING')
    const attempt: ManualTxAttempt = JSON.parse(JSON.stringify({
      ...draft, base, key: draft.requestKey || this.deps.key(), createdAt: this.deps.now(),
    }))
    // Persist exact body/base/key BEFORE the first write; never send if persistence fails.
    this.deps.store(JSON.stringify(attempt))
    return this.dispatch(attempt)
  }

  /** Native keys expire after 24h; past this safety margin a replay could create a second entry. */
  expired(): boolean {
    const attempt = this.pending()
    if (!attempt) return false
    const elapsed = this.deps.now() - attempt.createdAt
    return elapsed < 0 || elapsed >= RECOVERY_WINDOW_MS
  }

  async recover(): Promise<T> {
    if (!this.pending()) throw new Error('NO_PENDING_SAVE')
    // Expired requests require manual reconciliation against the entry list.
    if (this.expired()) throw new Error('RECOVERY_EXPIRED')
    return this.dispatch(this.pending()!, true)
  }

  /** Only once replay is no longer safe, after the user has checked the list themselves. */
  discardExpired(): void {
    if (!this.expired()) throw new Error('RECOVERY_NOT_EXPIRED')
    this.deps.store(null)
  }

  private async dispatch(attempt: ManualTxAttempt, recovering = false): Promise<T> {
    let acknowledged = false
    try {
      const result = await this.deps.send(attempt)
      acknowledged = true
      await this.deps.afterWrite?.(result, attempt)
      this.deps.store(null)
      return result
    } catch (error) {
      if (acknowledged && definitiveRejection(error)) {
        // The native write is settled (replays return the same entry); only the follow-up
        // confirmation was refused. Retrying cannot help and would block every later save.
        this.deps.store(null)
        throw Object.assign(new Error('SAVED_CAPTURE_UNCONFIRMED'), { refusal: error })
      }
      // Transport/parse/5xx errors may arrive after commit. Keep the exact request for explicit recovery.
      if (!acknowledged && error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408
        && (!recovering || error.code === 'WRITE_CONFLICT')) this.deps.store(null)
      throw error
    }
  }
}

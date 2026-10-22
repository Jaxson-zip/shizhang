import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@beecount/api-client'
import { ManualTxWriter, type ManualTxAttempt } from './manual-tx-write'

it('retains a review operation key across editor openings instead of minting another write key', async () => {
  const { deps, writer } = fixture()
  const requestKey = 'ocr-review-11111111-1111-4111-8111-111111111111'
  await writer.save({ ...draft, requestKey })
  expect(deps.send.mock.calls[0][0].key).toBe(requestKey)
  await new ManualTxWriter(deps).save({ ...draft, requestKey })
  expect(deps.send.mock.calls[1][0].key).toBe(requestKey)
})

function fixture() {
  let stored: string | null = null
  const deps = {
    read: () => stored,
    store: (value: string | null) => { stored = value },
    now: () => 1000,
    key: () => 'synthetic-attempt',
    loadBase: vi.fn(async () => 20),
    loadVersion: vi.fn(async () => 8),
    send: vi.fn(async (_attempt: ManualTxAttempt) => ({ entity_id: 'synthetic-tx', new_change_id: 21 })),
  }
  return { deps, writer: new ManualTxWriter(deps) }
}
const draft = { ledgerId: 'synthetic-ledger', payload: { tx_type: 'expense' as const, amount: 12.8, happened_at: '2026-10-16T10:00:00Z' } }

describe('manual transaction save recovery', () => {
  it('retains the original operation on HTTP 408 instead of allowing a new save', async () => {
    const { deps, writer } = fixture()
    deps.send.mockRejectedValueOnce(new ApiError('request timed out', { status: 408 }))
    await expect(writer.save(draft)).rejects.toMatchObject({ status: 408 })
    expect(writer.pending()?.key).toBe('synthetic-attempt')
    await expect(writer.save(draft)).rejects.toThrow('SAVE_PENDING')
    await writer.recover()
    expect(deps.send.mock.calls[1][0]).toEqual(deps.send.mock.calls[0][0])
    expect(writer.pending()).toBeNull()
  })
  it('retains one exact native request across a lost response and a new controller', async () => {
    const { deps, writer } = fixture()
    deps.send.mockRejectedValueOnce(new TypeError('connection lost'))
    await expect(writer.save(draft)).rejects.toThrow('connection lost')
    expect(writer.pending()?.key).toBe('synthetic-attempt')
    await expect(writer.save({ ...draft, payload: { ...draft.payload, amount: 99 } })).rejects.toThrow('PENDING')
    expect(deps.send).toHaveBeenCalledTimes(1)
    const resumed = new ManualTxWriter(deps)
    await resumed.recover()
    expect(deps.send.mock.calls[1][0]).toEqual(deps.send.mock.calls[0][0])
    expect(resumed.pending()).toBeNull()
  })
  it('rejects an outdated edited record without issuing a write', async () => {
    const { deps, writer } = fixture()
    await expect(writer.save({ ...draft, editingId: 'tx', expectedVersion: 7 })).rejects.toMatchObject({ code: 'DRAFT_CONFLICT' })
    expect(deps.send).not.toHaveBeenCalled()
    expect(writer.pending()).toBeNull()
  })
  it('does not refresh the version and resend after a CAS conflict', async () => {
    const { deps, writer } = fixture()
    deps.send.mockRejectedValueOnce(new ApiError('conflict', { status: 409, code: 'WRITE_CONFLICT' }))
    await expect(writer.save({ ...draft, editingId: 'tx', expectedVersion: 8 })).rejects.toMatchObject({ status: 409 })
    expect(deps.send).toHaveBeenCalledTimes(1)
    expect(deps.loadBase).toHaveBeenCalledTimes(1)
    expect(writer.pending()).toBeNull()
  })
  it('does not call the API if its preflight or recovery storage fails', async () => {
    const { deps, writer } = fixture()
    deps.loadBase.mockRejectedValueOnce(new TypeError('read failed'))
    await expect(writer.save(draft)).rejects.toThrow('read failed')
    deps.store = () => { throw new Error('storage unavailable') }
    await expect(writer.save(draft)).rejects.toThrow('storage unavailable')
    expect(deps.send).not.toHaveBeenCalled()
  })
  it('does not replay once the native 24-hour deduplication window may have expired', async () => {
    const { deps, writer } = fixture()
    deps.send.mockRejectedValueOnce(new TypeError('lost'))
    await expect(writer.save(draft)).rejects.toThrow()
    deps.now = () => 1000 + 24 * 60 * 60 * 1000
    await expect(writer.recover()).rejects.toThrow('EXPIRED')
    expect(deps.send).toHaveBeenCalledTimes(1)
    expect(writer.pending()).not.toBeNull()
  })
  it('keeps an uncertain original save when recovery cannot authenticate', async () => {
    const { deps, writer } = fixture()
    deps.send.mockRejectedValueOnce(new TypeError('lost'))
    await expect(writer.save(draft)).rejects.toThrow()
    deps.send.mockRejectedValueOnce(new ApiError('expired session', { status: 401 }))
    await expect(writer.recover()).rejects.toMatchObject({ status: 401 })
    expect(writer.pending()).not.toBeNull()
  })
  it('allows only one prepared request when two submissions race', async () => {
    const { deps, writer } = fixture()
    let resolve!: (value: { entity_id: string; new_change_id: number }) => void
    deps.send.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const first = writer.save(draft)
    const second = writer.save(draft)
    await expect(second).rejects.toThrow('PENDING')
    resolve({ entity_id: 'synthetic-tx', new_change_id: 21 })
    await first
    expect(deps.send).toHaveBeenCalledTimes(1)
  })
})

it('keeps the exact committed write when capture confirmation is rejected, then resolves without a second entry', async () => {
  const { deps } = fixture()
  const records = new Map<string, { entity_id: string; new_change_id: number }>()
  const send = vi.fn(async (attempt: ManualTxAttempt) => {
    if (!records.has(attempt.key)) records.set(attempt.key, { entity_id: 'only-row', new_change_id: 21 })
    return records.get(attempt.key)!
  })
  // A lost confirmation response (no HTTP status) is retried through the same recovery.
  const afterWrite = vi.fn().mockRejectedValueOnce(new TypeError('confirmation response lost')).mockResolvedValue(undefined)
  const writer = new ManualTxWriter({ ...deps, send, afterWrite })
  await expect(writer.save({ ...draft, captureId: 'synthetic-capture' })).rejects.toThrow('confirmation response lost')
  expect(writer.pending()?.key).toBe('synthetic-attempt')
  await writer.recover()
  expect(records.size).toBe(1)
  expect(send.mock.calls[1][0]).toEqual(send.mock.calls[0][0])
  expect(afterWrite).toHaveBeenCalledTimes(2)
  expect(writer.pending()).toBeNull()
})

it('settles an acknowledged save whose capture confirmation is definitively refused, so later saves are not blocked', async () => {
  const { deps } = fixture()
  const records = new Map<string, { entity_id: string; new_change_id: number }>()
  const send = vi.fn(async (attempt: ManualTxAttempt) => {
    if (!records.has(attempt.key)) records.set(attempt.key, { entity_id: 'only-row', new_change_id: 21 })
    return records.get(attempt.key)!
  })
  // e.g. the entry was edited elsewhere: resolve answers 409 every time.
  const afterWrite = vi.fn(async (_result: unknown, attempt: ManualTxAttempt) => {
    if (attempt.captureId) throw Object.assign(new Error('CAPTURE_REVIEW_UNCONFIRMED'), { status: 409 })
  })
  const writer = new ManualTxWriter({ ...deps, send, afterWrite })
  await expect(writer.save({ ...draft, captureId: 'synthetic-capture' })).rejects.toThrow('SAVED_CAPTURE_UNCONFIRMED')
  expect(writer.pending()).toBeNull()
  expect(records.size).toBe(1)
  await writer.save({ ...draft, payload: { ...draft.payload, amount: 3 } })   // the next, independent save
  expect(send).toHaveBeenCalledTimes(2)
})

it('keeps the request for a transient confirmation failure after an acknowledged save', async () => {
  const { deps } = fixture()
  const afterWrite = vi.fn().mockRejectedValueOnce(Object.assign(new Error('CAPTURE_REVIEW_UNCONFIRMED'), { status: undefined }))
  const writer = new ManualTxWriter({ ...deps, afterWrite })
  await expect(writer.save({ ...draft, captureId: 'synthetic-capture' })).rejects.toThrow('CAPTURE_REVIEW_UNCONFIRMED')
  expect(writer.pending()).not.toBeNull()
})

it('lets an expired unconfirmed save be discarded only after the replay window, never before', async () => {
  const { deps, writer } = fixture()
  deps.send.mockRejectedValueOnce(new TypeError('lost'))
  await expect(writer.save(draft)).rejects.toThrow()
  expect(writer.expired()).toBe(false)
  expect(() => writer.discardExpired()).toThrow('RECOVERY_NOT_EXPIRED')
  expect(writer.pending()).not.toBeNull()
  deps.now = () => 1000 + 23 * 60 * 60 * 1000
  expect(writer.expired()).toBe(true)
  writer.discardExpired()
  expect(writer.pending()).toBeNull()
  await writer.save({ ...draft, payload: { ...draft.payload, amount: 4 } })   // a new save is no longer blocked
  expect(deps.send).toHaveBeenCalledTimes(2)
})

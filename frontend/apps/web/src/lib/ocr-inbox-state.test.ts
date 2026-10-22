import { afterEach, expect, it, vi } from 'vitest'
import { changeOcrCaptureState, fetchCaptureImage, rereadCaptureImage, type OcrInboxItem } from './ocr-inbox'

const item: OcrInboxItem = { id: 'unbooked', ledger_id: 'synthetic', created_at: '', reason: '',
  entity_id: null, draft: null, request_key: 'original-intent', status: 'pending', revision: 'a'.repeat(64) }
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('sends the capture revision to its state endpoint and requires the requested server state', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ status: 'pending', revision: 'b'.repeat(64) })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ignored', revision: 'b'.repeat(64) })))
  vi.stubGlobal('fetch', fetch)
  await expect(changeOcrCaptureState('synthetic-token', item, 'ignored')).rejects.toThrow('CAPTURE_STATE_UNCONFIRMED')
  const result = await changeOcrCaptureState('synthetic-token', item, 'ignored')
  expect(result.status).toBe('ignored')
  expect(fetch.mock.calls[1][0]).toContain('/ai/ocr-inbox/unbooked/state')
  const request = fetch.mock.calls[1][1]
  expect(request.method).toBe('POST')
  const body = JSON.parse(request.body)
  expect(body).toMatchObject({ status: 'ignored', expected_revision: item.revision })
  expect(body.action_id).toMatch(/^[0-9a-f-]{36}$/)
})

it('cancels an unacknowledged state change without automatically issuing a second write', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('synthetic timeout', 'AbortError')))
  }))
  vi.stubGlobal('fetch', fetch)
  const operation = changeOcrCaptureState('synthetic-token', item, 'ignored')
  const rejection = expect(operation).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(20_000)
  await rejection
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('fetches a private image without putting the token in a URL or enabling browser caching', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(new Blob(['synthetic'], { type: 'image/jpeg' })))
  vi.stubGlobal('fetch', fetch)
  expect((await fetchCaptureImage('synthetic-token', item.id)).type).toBe('image/jpeg')
  expect(fetch.mock.calls[0][0]).not.toContain('synthetic-token')
  expect(fetch.mock.calls[0][1].cache).toBe('no-store')
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-token')
})

it('rereads the same capture with revision protection instead of posting a new transaction', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...item, revision: 'b'.repeat(64), message: '尚未新增账目' })))
  vi.stubGlobal('fetch', fetch)
  expect((await rereadCaptureImage('synthetic-token', item)).id).toBe(item.id)
  expect(fetch.mock.calls[0][0]).toContain('/ocr-inbox/unbooked/reread')
  expect(JSON.parse(fetch.mock.calls[0][1].body).expected_revision).toBe(item.revision)
  expect(fetch).toHaveBeenCalledTimes(1)
})

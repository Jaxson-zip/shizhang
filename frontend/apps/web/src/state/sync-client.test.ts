import { afterEach, expect, it, vi } from 'vitest'
import { drainPull, startPoller } from './sync-client'
import { configureHttp } from '@beecount/api-client'

afterEach(() => { configureHttp({}); vi.unstubAllGlobals(); vi.useRealTimers() })
function storage() {
  const items = new Map()
  vi.stubGlobal('window', { localStorage: { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => items.set(k, v) } })
}
it('does not report a rejected pull as completed and preserves delivered partial changes', async () => {
  storage()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ changes: [{ change_id: 1 }], server_cursor: 1, has_more: true })))
    .mockResolvedValueOnce(new Response('{}', { status: 401 })))
  expect(await drainPull('test', 'user', null)).toMatchObject({ complete: false, errorStatus: 401, cursor: 1, changes: [{ change_id: 1 }] })
})
it('reports a completed empty pull and does not call it a write acknowledgement', async () => {
  storage()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ changes: [], server_cursor: 0, has_more: false }))))
  expect(await drainPull('test', 'user', null)).toEqual({ changes: [], cursor: 0, complete: true })
})
it('reports poll failure and stops callbacks after unmount', async () => {
  storage()
  vi.useFakeTimers()
  const onResult = vi.fn(), onError = vi.fn()
  let resolve!: (response: Response) => void
  const pending = { promise: new Promise<Response>(done => { resolve = done }), resolve: (response: Response) => resolve(response) }
  vi.stubGlobal('fetch', vi.fn(() => pending.promise))
  const poller = startPoller({ token: 'test', userId: 'user', deviceId: null, onChanges: vi.fn(), onResult, onError })
  poller.stop()
  pending.resolve(new Response('{}', { status: 503 }))
  await pending.promise
  await vi.advanceTimersByTimeAsync(0)
  expect(onResult).not.toHaveBeenCalled()
  expect(onError).not.toHaveBeenCalled()
})
it('surfaces a failed background check instead of swallowing it', async () => {
  storage()
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
  const onResult = vi.fn()
  const poller = startPoller({ token: 'test', userId: 'user', deviceId: null, onChanges: vi.fn(), onResult })
  await vi.advanceTimersByTimeAsync(0)
  expect(onResult).toHaveBeenCalledWith({ changes: [], cursor: 0, complete: false, errorStatus: 503 })
  poller.stop()
})
it('bounds a stuck native pull request', async () => {
  storage()
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('timeout'))))))
  const result = drainPull('test', 'user', null)
  await vi.advanceTimersByTimeAsync(15_000)
  expect(await result).toEqual({ changes: [], cursor: 0, complete: false })
})
it('delivers an earlier page even if the next page loses its response', async () => {
  storage()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ changes: [{ change_id: 1 }], server_cursor: 1, has_more: true })))
    .mockRejectedValueOnce(new Error('network interrupted')))
  expect(await drainPull('test', 'user', null)).toEqual({ changes: [{ change_id: 1 }], cursor: 1, complete: false })
})
it('uses native single-flight token refresh before declaring the session expired', async () => {
  storage()
  const refreshToken = vi.fn(async () => 'fresh-token'), onLogout = vi.fn()
  configureHttp({ refreshToken, onLogout })
  const request = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ changes: [], server_cursor: 0, has_more: false })))
  vi.stubGlobal('fetch', request)
  expect(await drainPull('old-token', 'user', null)).toEqual({ changes: [], cursor: 0, complete: true })
  expect(refreshToken).toHaveBeenCalledTimes(1)
  expect(request.mock.calls[1][1].headers.Authorization).toBe('Bearer fresh-token')
  expect(onLogout).not.toHaveBeenCalled()
})
it('does not log out a refreshed session just because the next read loses its network', async () => {
  storage()
  const onLogout = vi.fn()
  configureHttp({ refreshToken: async () => 'fresh-token', onLogout })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('{}', { status: 401 })).mockRejectedValueOnce(new Error('network')))
  expect(await drainPull('old-token', 'user', null)).toEqual({ changes: [], cursor: 0, complete: false })
  expect(onLogout).not.toHaveBeenCalled()
})

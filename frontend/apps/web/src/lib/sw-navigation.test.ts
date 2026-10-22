import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { expect, it, vi } from 'vitest'

it.each([200, 502])('revalidates navigation and only caches successful shells (%s)', async (status) => {
  const listeners: Record<string, (event: any) => void> = {}
  const put = vi.fn()
  const fetch = vi.fn(async (_request: unknown, _init: RequestInit) => new Response('synthetic shell', { status }))
  runInNewContext(readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8'), {
    URL, fetch, console,
    self: { location: { origin: 'https://synthetic.invalid' }, addEventListener: (key: string, fn: any) => { listeners[key] = fn } },
    caches: { open: async () => ({ put }), match: async () => undefined },
  })
  let response!: Promise<Response>
  listeners.fetch({ request: { url: 'https://synthetic.invalid/app/overview', mode: 'navigate', method: 'GET' }, respondWith: (r: Promise<Response>) => { response = r } })
  await response
  expect(fetch.mock.calls[0][1]).toEqual({ cache: 'no-cache' })
  expect(put).toHaveBeenCalledTimes(status === 200 ? 1 : 0)
})

import { afterEach, expect, it, vi } from 'vitest'
import { fetchWorkspaceLedgerCounts } from '@beecount/api-client'

afterEach(() => vi.unstubAllGlobals())

it.each([-300, 0, 480])('passes the explicit local calendar offset %i to ledger counts', async (offset) => {
  const request = vi.fn(async (_url: string) => new Response(JSON.stringify({ tx_count: 0, distinct_days: 0 })))
  vi.stubGlobal('fetch', request)
  await fetchWorkspaceLedgerCounts('synthetic-token', { ledgerId: 'synthetic', tzOffsetMinutes: offset })
  const url = new URL(request.mock.calls[0][0], 'https://example.invalid')
  expect(url.searchParams.get('ledger_id')).toBe('synthetic')
  expect(url.searchParams.get('tz_offset_minutes')).toBe(String(offset))
})

it('keeps the native UTC default available for clients without an offset', async () => {
  const request = vi.fn(async (_url: string) => new Response(JSON.stringify({ tx_count: 0 })))
  vi.stubGlobal('fetch', request)
  await fetchWorkspaceLedgerCounts('synthetic-token', { ledgerId: 'synthetic' })
  expect(new URL(request.mock.calls[0][0], 'https://example.invalid').searchParams.has('tz_offset_minutes')).toBe(false)
})

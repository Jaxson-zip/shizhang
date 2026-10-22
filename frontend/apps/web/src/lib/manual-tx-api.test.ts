import { afterEach, expect, it, vi } from 'vitest'
import { configureHttp, createTransaction, updateTransaction } from '@beecount/api-client'
import { ManualTxWriter } from './manual-tx-write'
afterEach(() => { vi.unstubAllGlobals(); configureHttp({}) })

it('passes stable native idempotency keys and per-entry versions to the write API', async () => {
  const request = vi.fn(async (_url: string, init: RequestInit) => new Response(JSON.stringify({
    ledger_id: 'ledger', entity_id: init.method === 'PATCH' ? 'tx' : 'synthetic',
    base_change_id: JSON.parse(init.body as string).base_change_id, new_change_id: 12,
    server_timestamp: '2026-10-18T02:00:00Z', idempotency_replayed: false,
  })))
  vi.stubGlobal('fetch', request)
  const payload = { tx_type: 'expense' as const, amount: 12.8, happened_at: '2026-10-16T12:00:00Z' }
  await createTransaction('synthetic-token', 'ledger', 10, payload, 'key-create')
  await updateTransaction('synthetic-token', 'ledger', 'tx', 11, { ...payload, expected_change_id: 7 }, 'key-edit')
  expect((request.mock.calls[0][1].headers as Record<string, string>)['Idempotency-Key']).toBe('key-create')
  expect((request.mock.calls[1][1].headers as Record<string, string>)['Idempotency-Key']).toBe('key-edit')
  expect(JSON.parse(request.mock.calls[1][1].body as string)).toMatchObject({ base_change_id: 11, expected_change_id: 7 })
})

it.each([
  { ledger_id: 'other-ledger' }, { entity_id: null }, { entity_id: '' },
  { new_change_id: '11' }, { new_change_id: 9 }, { base_change_id: -1 },
  { server_timestamp: 'invalid' }, { idempotency_replayed: 'true' },
])('rejects mismatched or malformed transaction confirmation: %j', async (override) => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    ledger_id: 'ledger', entity_id: 'tx', base_change_id: 10, new_change_id: 11,
    server_timestamp: '2026-10-18T02:00:00Z', idempotency_replayed: false, ...override,
  }))))
  await expect(createTransaction('token', 'ledger', 10, {
    tx_type: 'expense', amount: 1, happened_at: '2026-10-18T02:00:00Z',
  }, 'stable-key')).rejects.toThrow('WRITE_RECEIPT_INVALID')
})

it('does not accept another transaction as confirmation of an edit', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    ledger_id: 'ledger', entity_id: 'other-tx', base_change_id: 10, new_change_id: 11,
    server_timestamp: '2026-10-18T02:00:00Z', idempotency_replayed: false,
  }))))
  await expect(updateTransaction('token', 'ledger', 'tx', 10, { amount: 2 }, 'stable-key'))
    .rejects.toThrow('WRITE_RECEIPT_INVALID')
})

it('retains the original write body and key during session refresh', async () => {
  const request = vi.fn(async (_url: string, _init: RequestInit) => new Response(JSON.stringify({
    ledger_id: 'ledger', entity_id: 'tx', base_change_id: 10, new_change_id: 11,
    server_timestamp: '2026-10-18T02:00:00Z', idempotency_replayed: false,
  })))
  request.mockImplementationOnce(async () => new Response('{}', { status: 401 }))
  vi.stubGlobal('fetch', request)
  const refresh = vi.fn(async () => 'fresh-token'), logout = vi.fn()
  configureHttp({ refreshToken: refresh, onLogout: logout })
  await createTransaction('old-token', 'ledger', 10, {
    tx_type: 'income', amount: 2, happened_at: '2026-10-18T02:00:00Z',
  }, 'stable-key')
  expect(request).toHaveBeenCalledTimes(2)
  expect(refresh).toHaveBeenCalledTimes(1)
  expect(logout).not.toHaveBeenCalled()
  expect(request.mock.calls[1][1].body).toBe(request.mock.calls[0][1].body)
  expect(request.mock.calls[1][1].headers).toMatchObject({ Authorization: 'Bearer fresh-token', 'Idempotency-Key': 'stable-key' })
})

it('keeps the exact operation when a 200 response does not confirm a committed transaction', async () => {
  const committed = { ledger_id: 'ledger', entity_id: 'synthetic', base_change_id: 10,
    new_change_id: 11, server_timestamp: '2026-10-18T02:00:00Z', idempotency_replayed: true }
  const request = vi.fn(async (_url: string, _init: RequestInit) => new Response(JSON.stringify(committed)))
  request.mockImplementationOnce(async () => new Response('{}'))
  vi.stubGlobal('fetch', request)
  let stored: string | null = null
  const writer = new ManualTxWriter({ read: () => stored, store: value => { stored = value },
    key: () => 'same-operation', now: () => 1000, loadBase: async () => 10, loadVersion: async () => 1,
    send: a => createTransaction('synthetic-token', a.ledgerId, a.base, a.payload, a.key),
  })
  await expect(writer.save({ ledgerId: 'ledger', payload: {
    tx_type: 'expense', amount: 1.23, happened_at: '2026-10-18T02:00:00Z',
  } })).rejects.toThrow('WRITE_RECEIPT_INVALID')
  expect(writer.pending()?.key).toBe('same-operation')
  await expect(writer.recover()).resolves.toEqual(committed)
  expect(writer.pending()).toBeNull()
  expect(request.mock.calls[1][1].body).toBe(request.mock.calls[0][1].body)
  expect(request.mock.calls[1][1].headers).toEqual(request.mock.calls[0][1].headers)
})

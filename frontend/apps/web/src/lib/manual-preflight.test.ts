import { afterEach, expect, it, vi } from 'vitest'
import { readWithin } from './manual-preflight'
import { ManualTxWriter } from './manual-tx-write'

afterEach(() => vi.useRealTimers())
it('does not send a write when a preparation read eventually completes after timeout', async () => {
  vi.useFakeTimers()
  let resolve!: (value: number) => void
  const delayed = new Promise<number>(done => { resolve = done })
  const send = vi.fn(), store = vi.fn()
  const writer = new ManualTxWriter({ read: () => null, store, key: () => 'key', now: () => 0,
    loadBase: () => readWithin(() => delayed), loadVersion: async () => 1, send })
  const outcome = writer.save({ ledgerId: 'fixture', payload: { tx_type: 'expense', amount: 1, happened_at: '' } }).catch(error => error.message)
  await vi.advanceTimersByTimeAsync(15_000)
  expect(await outcome).toBe('PREPARATION_TIMEOUT')
  resolve(1)
  await vi.advanceTimersByTimeAsync(0)
  expect(store).not.toHaveBeenCalled()
  expect(send).not.toHaveBeenCalled()
})

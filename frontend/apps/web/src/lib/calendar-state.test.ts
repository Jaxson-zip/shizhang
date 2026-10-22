import { describe, expect, it } from 'vitest'
import { compactCalendarNet, createCalendarRead, exactCalendarNet } from './calendar-state'

describe('calendar financial display', () => {
  it('keeps the sign and cents in the exact daily balance', () => {
    expect(exactCalendarNet(-61.41, 'CNY')).toBe('-CNY 61.41')
    expect(exactCalendarNet(61.41, 'CNY')).toBe('+CNY 61.41')
    expect(exactCalendarNet(0, 'CNY')).toBe('CNY 0.00')
  })
  it('never rounds a cent-level expense to zero in a compact cell', () => {
    expect(compactCalendarNet(-0.01, true)).toBe('-0.01')
    expect(compactCalendarNet(0.01, true)).toBe('+0.01')
  })
  it('marks rounded overviews and preserves income/expense direction', () => {
    expect(compactCalendarNet(-61.41, true)).toBe('≈-61')
    expect(compactCalendarNet(1234, false)).toBe('≈+1.2k')
    expect(compactCalendarNet(-12000, true)).toBe('≈-1.2万')
    expect(compactCalendarNet(0, false)).toBe('0')
  })
  it('does not display floating point residue or negative zero as a real expense', () => {
    expect(exactCalendarNet(0.3 - 0.1 - 0.2, 'CNY')).toBe('CNY 0.00')
    expect(compactCalendarNet(0.3 - 0.1 - 0.2, true)).toBe('0')
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

describe('calendar read lifecycle', () => {
  it('keeps the last successful data after a refresh failure and permits retry', async () => {
    const reader = createCalendarRead([61.41])
    await reader.load(async () => { throw new Error('offline') })
    expect(reader.getSnapshot()).toMatchObject({ status: 'error', data: [61.41] })
    await reader.load(async () => [62.41])
    expect(reader.getSnapshot()).toEqual({ status: 'ready', data: [62.41], error: null })
  })
  it('does not turn a first-load failure into an empty successful result', async () => {
    const reader = createCalendarRead<number[]>()
    await reader.load(async () => { throw new Error('offline') })
    expect(reader.getSnapshot()).toMatchObject({ status: 'error', data: null })
  })
  it('ignores an older response that arrives after the latest response', async () => {
    const reader = createCalendarRead<string>()
    const old = deferred<string>()
    const latest = deferred<string>()
    const cached: string[] = []
    const first = reader.load(() => old.promise, (data) => cached.push(data))
    const second = reader.load(() => latest.promise, (data) => cached.push(data))
    latest.resolve('selected day')
    await second
    old.resolve('previous day')
    await first
    expect(reader.getSnapshot().data).toBe('selected day')
    expect(cached).toEqual(['selected day'])
  })
  it('ignores an old error without settling a newer pending request', async () => {
    const reader = createCalendarRead<string>()
    const old = deferred<string>()
    const latest = deferred<string>()
    const first = reader.load(() => old.promise)
    const second = reader.load(() => latest.promise)
    old.reject(new Error('old failure'))
    await first
    expect(reader.getSnapshot().status).toBe('loading')
    latest.resolve('new day')
    await second
    expect(reader.getSnapshot()).toEqual({ status: 'ready', data: 'new day', error: null })
  })
  it('invalidates a request when its period is left; a different reader starts without its data', async () => {
    const reader = createCalendarRead('old month')
    const old = deferred<string>()
    const first = reader.load(() => old.promise)
    reader.cancel()
    old.resolve('late month')
    await first
    expect(reader.getSnapshot().data).toBe('old month')
    expect(createCalendarRead<string>().getSnapshot()).toMatchObject({ status: 'loading', data: null })
  })
})

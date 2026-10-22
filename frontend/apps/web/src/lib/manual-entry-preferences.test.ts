import { describe, expect, it } from 'vitest'
import { readEntryPreferences, rememberEntryPreferences, entryPreferenceKey } from './manual-entry-preferences'

describe('confirmed manual entry shortcuts', () => {
  it('scopes the last account and recent categories by user, server, ledger and kind', () => {
    const data = new Map<string, string>()
    const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) } }
    const key = entryPreferenceKey('/api', 'user-a', 'ledger-a')
    rememberEntryPreferences(store, key, { tx_type: 'expense', amount: 5, happened_at: '', account_name: '钱包', category_name: '餐饮' })
    const accounts = [{ name: '钱包', hidden: false }]
    const categories = [{ name: '餐饮', kind: 'expense' }]
    expect(readEntryPreferences(store, key, 'expense', accounts, categories)).toEqual({ accountName: '钱包', categories: ['餐饮'] })
    for (const other of [entryPreferenceKey('/other', 'user-a', 'ledger-a'), entryPreferenceKey('/api', 'user-b', 'ledger-a'), entryPreferenceKey('/api', 'user-a', 'ledger-b')]) {
      expect(readEntryPreferences(store, other, 'expense', accounts, categories)).toEqual({ categories: [] })
    }
    expect(readEntryPreferences(store, key, 'income', accounts, categories)).toEqual({ categories: [] })
    expect(entryPreferenceKey('/api', null, 'ledger-a')).toBeNull()
  })
  it('does not reuse hidden, deleted or ambiguous names and remembers choosing no account', () => {
    let raw: string | null = null
    const store = { getItem: () => raw, setItem: (_: string, v: string) => { raw = v } }
    const payload = { tx_type: 'expense' as const, amount: 5, happened_at: '', account_name: '钱包', category_name: '餐饮' }
    rememberEntryPreferences(store, 'key', payload)
    expect(readEntryPreferences(store, 'key', 'expense', [{ name: '钱包', hidden: true }], [])).toEqual({ categories: [] })
    expect(readEntryPreferences(store, 'key', 'expense', [{ name: '钱包' }, { name: '钱包' }], [])).toEqual({ categories: [] })
    rememberEntryPreferences(store, 'key', { ...payload, account_name: null })
    expect(readEntryPreferences(store, 'key', 'expense', [{ name: '钱包' }], [])).toEqual({ accountName: '', categories: [] })
  })
  it('bounds recent categories, ignores transfers and tolerates disabled storage', () => {
    let raw: string | null = null
    const store = { getItem: () => raw, setItem: (_: string, v: string) => { raw = v } }
    for (const category_name of ['餐饮', '交通', '购物', '娱乐', '交通']) {
      rememberEntryPreferences(store, 'key', { tx_type: 'expense', amount: 5, happened_at: '', category_name })
    }
    const before = raw
    rememberEntryPreferences(store, 'key', { tx_type: 'transfer', amount: 5, happened_at: '' })
    expect(raw).toBe(before)
    expect(readEntryPreferences(store, 'key', 'expense', [], ['餐饮','交通','购物','娱乐'].map(name => ({ name, kind: 'expense' })))).toEqual({ accountName: '', categories: ['交通', '娱乐', '购物'] })
    const blocked = { getItem: () => { throw Error('blocked') }, setItem: () => { throw Error('blocked') } }
    expect(() => rememberEntryPreferences(blocked, 'key', { tx_type: 'expense', amount: 1, happened_at: '' })).not.toThrow()
    expect(readEntryPreferences(blocked, 'key', 'expense', [], [])).toEqual({ categories: [] })
  })
})

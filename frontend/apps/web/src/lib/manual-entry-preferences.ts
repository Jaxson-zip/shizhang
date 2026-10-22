import type { TxPayload } from '@beecount/api-client'

type StoragePort = Pick<Storage, 'getItem' | 'setItem'>
type Choice = { accountName: string; categories: string[] }
type Preferences = Partial<Record<'expense' | 'income', Choice>>

export function entryPreferenceKey(server: string, userId: string | null, ledgerId: string): string | null {
  return userId && ledgerId ? `shizhang.entry-choice.v1:${JSON.stringify([server, userId, ledgerId])}` : null
}
function load(store: StoragePort, key: string): Preferences {
  const raw = JSON.parse(store.getItem(key) || '{}')
  const out: Preferences = {}
  for (const kind of ['expense', 'income'] as const) {
    const row = raw?.[kind]
    if (typeof row?.accountName === 'string' && Array.isArray(row.categories)) {
      out[kind] = { accountName: row.accountName, categories: row.categories.filter((s: unknown): s is string => typeof s === 'string').slice(0, 3) }
    }
  }
  return out
}

/** Local shortcuts only. A broken preference must never turn a confirmed save into a failure. */
export function rememberEntryPreferences(store: StoragePort, key: string | null, payload: TxPayload): void {
  if (!key || (payload.tx_type !== 'expense' && payload.tx_type !== 'income')) return
  try {
    const prefs = load(store, key)
    const category = payload.category_name?.trim()
    prefs[payload.tx_type] = { accountName: payload.account_name?.trim() || '',
      categories: [...(category ? [category] : []), ...(prefs[payload.tx_type]?.categories || []).filter(name => name !== category)].slice(0, 3) }
    store.setItem(key, JSON.stringify(prefs))
  } catch { /* optional convenience; native save/recovery remains authoritative */ }
}

export function readEntryPreferences(store: StoragePort, key: string | null, kind: string,
  accounts: { name: string; hidden?: boolean | null }[], categories: { name: string; kind: string }[],
): { accountName?: string; categories: string[] } {
  if (!key || (kind !== 'expense' && kind !== 'income')) return { categories: [] }
  try {
    const choice = load(store, key)[kind]
    if (!choice) return { categories: [] }
    const validAccount = choice.accountName === '' || accounts.filter(a => a.name === choice.accountName).length === 1
      && accounts.some(a => a.name === choice.accountName && !a.hidden)
    return { ...(validAccount ? { accountName: choice.accountName } : {}),
      categories: choice.categories.filter(name => categories.filter(c => c.name === name && c.kind === kind).length === 1) }
  } catch { return { categories: [] } }
}

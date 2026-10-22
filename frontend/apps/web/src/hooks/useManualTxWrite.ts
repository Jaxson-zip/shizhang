import { useMemo, useState } from 'react'
import { API_BASE, ApiError, createTransaction, updateTransaction, fetchReadLedgerDetail, fetchWorkspaceTransactions } from '@beecount/api-client'
import { useT } from '@beecount/ui'
import { useAuth } from '../context/AuthContext'
import { ManualTxWriter, type ManualTxDraft } from '../lib/manual-tx-write'
import { localizeError } from '../i18n/errors'
import { entryPreferenceKey, readEntryPreferences, rememberEntryPreferences } from '../lib/manual-entry-preferences'
import { readWithin } from '../lib/manual-preflight'
import { resolveOcrCapture } from '../lib/ocr-inbox'

export function useManualTxWrite() {
  const { token, sessionUserId } = useAuth()
  const t = useT()
  const [, tick] = useState(0)
  const [issue, setIssue] = useState('')
  const writer = useMemo(() => {
    const storageKey = `shizhang.manual-save.v1:${API_BASE}:${sessionUserId}`
    return new ManualTxWriter({
      read: () => sessionStorage.getItem(storageKey),
      store: (value) => value === null ? sessionStorage.removeItem(storageKey) : sessionStorage.setItem(storageKey, value),
      now: Date.now,
      key: () => crypto.randomUUID(),
      loadBase: (ledgerId) => readWithin(async () => (await fetchReadLedgerDetail(token, ledgerId)).source_change_id),
      loadVersion: async (ledgerId, txId) => {
        const page = await readWithin(() => fetchWorkspaceTransactions(token, { ledgerId, txSyncId: txId, limit: 1 }))
        return page.items.find((row) => row.id === txId)?.entry_change_id ?? null
      },
      send: async (a) => {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 20_000)
        try {
          const result = a.editingId
            ? await updateTransaction(token, a.ledgerId, a.editingId, a.base, { ...a.payload, expected_change_id: a.expectedVersion }, a.key, controller.signal)
            : await createTransaction(token, a.ledgerId, a.base, a.payload, a.key, controller.signal)
          return result
        } finally { clearTimeout(timeout) }
      },
      afterWrite: async (result, a) => {
        if (!a.captureId) return
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 20_000)
        try { await resolveOcrCapture(token, a.captureId, result.entity_id!, result.new_change_id, controller.signal) }
        finally { clearTimeout(timeout) }
      },
    })
  }, [token, sessionUserId])
  let pending = null
  let pendingExpired = false
  try { pending = writer.pending(); pendingExpired = writer.expired() } catch { /* save/recover surfaces invalid storage without sending */ }
  const messageFor = (error: unknown): string => {
    if (error instanceof ApiError && (error.code === 'DRAFT_CONFLICT' || error.code === 'WRITE_CONFLICT')) return t('manual.conflict')
    if (error instanceof Error && error.message === 'RECOVERY_EXPIRED') return t('manual.expired')
    if (error instanceof Error && error.message === 'SAVED_CAPTURE_UNCONFIRMED') return t('manual.savedCaptureUnconfirmed')
    try { if (writer.pending()) return t('manual.unknown') } catch { return t('manual.storageError') }
    if (error instanceof ApiError && error.status < 500) return localizeError(error, t)
    return t('manual.notSent')
  }
  const run = async <T,>(fn: () => Promise<T>) => {
    setIssue('')
    try { return await fn() } catch (error) { setIssue(messageFor(error)); throw error }
    finally { tick((n) => n + 1) }
  }
  return {
    pending,
    pendingExpired,
    issue: issue || (pendingExpired ? t('manual.expired') : pending ? t('manual.unknown') : ''),
    discardExpired: () => { writer.discardExpired(); setIssue(''); tick((n) => n + 1) },
    clearIssue: () => setIssue(''),
    messageFor,
    entryChoices: (ledgerId: string, kind: string, accounts: { name: string; hidden?: boolean | null }[], categories: { name: string; kind: string }[]) => {
      try { return readEntryPreferences(localStorage, entryPreferenceKey(API_BASE, sessionUserId, ledgerId), kind, accounts, categories) }
      catch { return { categories: [] } }
    },
    save: (draft: ManualTxDraft) => run(async () => {
      const result = await writer.save(draft)
      try { if (!draft.editingId) rememberEntryPreferences(localStorage, entryPreferenceKey(API_BASE, sessionUserId, draft.ledgerId), draft.payload) } catch { /* optional storage may be unavailable */ }
      return result
    }),
    recover: () => run(async () => {
      const attempt = writer.pending()
      const result = await writer.recover()
      try { if (attempt && !attempt.editingId) rememberEntryPreferences(localStorage, entryPreferenceKey(API_BASE, sessionUserId, attempt.ledgerId), attempt.payload) } catch { /* optional */ }
      return result
    }),
  }
}

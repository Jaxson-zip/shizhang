import { useEffect, useRef, useState } from 'react'
import { fetchProfileMe, fetchWorkspaceAccounts, fetchWorkspaceCategories, patchProfileMe,
  type WorkspaceAccount, type WorkspaceCategory } from '@beecount/api-client'
import { Button, Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'
import { useAuth } from '../context/AuthContext'
import { useLedgers } from '../context/LedgersContext'
import { mergeOcrPreferences, readOcrPreferences, type OcrPreferences } from '../lib/ocr-preferences'

/** Reuses native profile storage and native account/category candidates. */
export function OcrPreferencesSection() {
  const t = useT()
  const { token, profileMe, sessionUserId, refreshProfile } = useAuth()
  const { activeLedgerId, currentLedger } = useLedgers()
  const [prefs, setPrefs] = useState(() => readOcrPreferences(null, ''))
  const [accounts, setAccounts] = useState<WorkspaceAccount[]>([])
  const [categories, setCategories] = useState<WorkspaceCategory[]>([])
  const [loading, setLoading] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('')
  const scopeRef = useRef('')

  useEffect(() => {
    const scope = `${sessionUserId}:${activeLedgerId}`
    if (scopeRef.current === scope && dirty) return
    scopeRef.current = scope
    setPrefs(readOcrPreferences(profileMe?.ai_config, activeLedgerId || ''))
    setDirty(false)
  }, [sessionUserId, activeLedgerId, profileMe, dirty])

  useEffect(() => {
    if (!activeLedgerId) return
    let alive = true
    setLoading(true)
    setStatus('')
    setAccounts([])
    setCategories([])
    Promise.all([
      fetchWorkspaceAccounts(token, { ledgerId: activeLedgerId, limit: 200 }),
      fetchWorkspaceCategories(token, { ledgerId: activeLedgerId, limit: 500 }),
    ]).then(([wallets, cats]) => {
      if (!alive) return
      setAccounts(wallets.filter(a => !a.hidden && (a.currency || 'CNY') === 'CNY'))
      setCategories(cats.filter(c => !cats.some(child => child.kind === c.kind && child.parent_name === c.name)))
    }).catch(() => { if (alive) setStatus(t('ocrPreferences.error')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [activeLedgerId, token, t])

  const change = (patch: Partial<OcrPreferences>) => {
    setPrefs(old => ({ ...old, ...patch }))
    setDirty(true)
    setStatus('')
  }

  const save = async () => {
    if (!activeLedgerId || saving) return
    setSaving(true)
    setStatus('')
    try {
      // PATCH has whole-snapshot semantics: preserve every unrelated native key.
      const latest = await fetchProfileMe(token)
      await patchProfileMe(token, { ai_config: mergeOcrPreferences(latest.ai_config, activeLedgerId, prefs) })
      const confirmed = await fetchProfileMe(token)
      if (JSON.stringify(readOcrPreferences(confirmed.ai_config, activeLedgerId)) !== JSON.stringify(prefs)) {
        throw new Error('Preference readback differs')
      }
      await refreshProfile()
      setDirty(false)
      setStatus(t('ocrPreferences.saved'))
    } catch {
      setStatus(t('ocrPreferences.error'))
    } finally {
      setSaving(false)
    }
  }

  const options = (label: string, value: string, onChange: (id: string) => void,
    rows: Array<{ id: string; name: string }>) => (
    <label className="flex min-w-0 flex-col gap-2 text-sm">
      {label}
      <select className="h-11 min-w-0 w-full rounded-md border border-input bg-background px-3 text-base"
        value={value} onChange={e => onChange(e.target.value)} disabled={loading || saving}>
        <option value="">{t('ocrPreferences.notSet')}</option>
        {value && !rows.some(row => row.id === value) ? <option value={value}>{t(loading ? 'ocrPreferences.loading' : 'ocrPreferences.unavailable')}</option> : null}
        {rows.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select>
    </label>
  )

  return (
    <Card id="ocr-preferences">
      <CardHeader>
        <CardTitle>{t('ocrPreferences.title')}</CardTitle>
        <p className="text-sm leading-relaxed text-muted-foreground">{t('ocrPreferences.intro')}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!activeLedgerId ? <p>{t('ocrPreferences.noLedger')}</p> : <>
          <p className="text-sm text-muted-foreground">{currentLedger?.ledger_name}</p>
          {loading ? <p role="status">{t('ocrPreferences.loading')}</p> : null}
          <label className="flex min-w-0 flex-col gap-2 text-sm">
            {t('ocrPreferences.mode')}
            <select className="h-11 w-full rounded-md border border-input bg-background px-3 text-base"
              value={prefs.accounting_mode} disabled={loading || saving}
              onChange={e => change({ accounting_mode: e.target.value === 'channel' ? 'channel' : 'funding' })}>
              <option value="funding">{t('ocrPreferences.modeFunding')}</option>
              <option value="channel">{t('ocrPreferences.modeChannel')}</option>
            </select>
            {prefs.accounting_mode === 'channel' ? <span className="text-muted-foreground">{t('ocrPreferences.channelHint')}</span> : null}
          </label>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {options(t(prefs.accounting_mode === 'channel' ? 'ocrPreferences.wechatChannel' : 'ocrPreferences.wechat'), prefs.wechat_account_id, id => change({ wechat_account_id: id }), accounts)}
            {options(t(prefs.accounting_mode === 'channel' ? 'ocrPreferences.alipayChannel' : 'ocrPreferences.alipay'), prefs.alipay_account_id, id => change({ alipay_account_id: id }), accounts)}
            {options(t('ocrPreferences.category'), prefs.default_expense_category_id, id => change({ default_expense_category_id: id }), categories.filter(c => c.kind === 'expense'))}
            {options(t('ocrPreferences.incomeCategory'), prefs.default_income_category_id, id => change({ default_income_category_id: id }), categories.filter(c => c.kind === 'income'))}
          </div>
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm leading-relaxed">
            <input type="checkbox" className="h-4 w-4 shrink-0 accent-primary"
              checked={prefs.campus_topup_as_expense} disabled={saving}
              onChange={e => change({ campus_topup_as_expense: e.target.checked })} />
            {t('cmdk.parseTx.campusTopupAsExpense')}
          </label>
          <Button className="min-h-11" disabled={loading || saving || !dirty} onClick={save}>{t('ocrPreferences.save')}</Button>
        </>}
        {status ? <p role="status" className="text-sm leading-relaxed">{status}</p> : null}
      </CardContent>
    </Card>
  )
}

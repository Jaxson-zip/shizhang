export type OcrPreferences = {
  wechat_account_id: string
  alipay_account_id: string
  default_expense_category_id: string
  default_income_category_id: string
  accounting_mode: 'funding' | 'channel'
  campus_topup_as_expense: boolean
}

function record(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

export function readOcrPreferences(config: unknown, ledgerId: string): OcrPreferences {
  const value = record(record(record(record(config).ocr_rules).ledgers)[ledgerId])
  const id = (key: string) => typeof value[key] === 'string' ? value[key] : ''
  return {
    wechat_account_id: id('wechat_account_id'),
    alipay_account_id: id('alipay_account_id'),
    default_expense_category_id: id('default_expense_category_id'),
    default_income_category_id: id('default_income_category_id'),
    accounting_mode: value.accounting_mode === 'channel' ? 'channel' : 'funding',
    campus_topup_as_expense: value.campus_topup_as_expense === true,
  }
}

export function defaultEntryCategory(config: unknown, ledgerId: string, kind: string,
  categories: { id: string; name: string; kind: string; parent_name?: string | null }[], current: string): string {
  if (current || !['income', 'expense'].includes(kind)) return current
  const prefs = readOcrPreferences(config, ledgerId)
  if (prefs.accounting_mode !== 'channel') return current
  const id = kind === 'income' ? prefs.default_income_category_id : prefs.default_expense_category_id
  const row = categories.find(c => c.id === id && c.kind === kind)
  return row && categories.filter(c => c.name === row.name && c.kind === kind).length === 1
    && !categories.some(c => c.kind === kind && c.parent_name === row.name) ? row.name : current
}

/** Old unresolved drafts keep their original evidence; only the editor prefill follows an opted-in rename. */
export function legacyChannelAccount(config: unknown, ledgerId: string,
  accounts: { id: string; name: string; hidden?: boolean | null }[], current: string): string {
  const prefs = readOcrPreferences(config, ledgerId)
  if (prefs.accounting_mode !== 'channel' || accounts.some(a => a.name === current && !a.hidden)) return current
  const id = ['零钱', '微信零钱'].includes(current) ? prefs.wechat_account_id
    : ['余额', '支付宝余额'].includes(current) ? prefs.alipay_account_id : ''
  const matches = accounts.filter(a => id && a.id === id && !a.hidden)
  return matches.length === 1 && accounts.filter(a => a.name === matches[0].name).length === 1 ? matches[0].name : current
}

/** Native profile PATCH replaces ai_config: always merge a fresh full snapshot. */
export function mergeOcrPreferences(config: unknown, ledgerId: string, prefs: OcrPreferences): Record<string, any> & {
  ocr_rules: Record<string, any> & { ledgers: Record<string, any> }
} {
  const current = record(config)
  const rules = record(current.ocr_rules)
  const ledgers = record(rules.ledgers)
  return { ...current, ocr_rules: { ...rules, ledgers: {
    ...ledgers, [ledgerId]: { ...record(ledgers[ledgerId]), ...prefs },
  } } }
}

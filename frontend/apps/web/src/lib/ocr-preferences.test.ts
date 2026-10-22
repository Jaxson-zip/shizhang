import { describe, expect, it } from 'vitest'
import { defaultEntryCategory, legacyChannelAccount, mergeOcrPreferences, readOcrPreferences } from './ocr-preferences'

describe('OCR native profile preferences', () => {
  it('preserves provider configuration, unknown fields and other ledgers', () => {
    const current = { providers: [{ id: 'keep' }], future: 42,
      ocr_rules: { future: true, ledgers: { other: { wechat_account_id: 'other-wallet' } } } }
    const prefs = { wechat_account_id: 'mine', alipay_account_id: '', default_expense_category_id: 'category', default_income_category_id: 'income', accounting_mode: 'channel' as const, campus_topup_as_expense: true }
    const next = mergeOcrPreferences(current, 'ledger', prefs)
    expect(next.providers).toEqual(current.providers)
    expect(next.future).toBe(42)
    expect(next.ocr_rules.ledgers.other).toEqual(current.ocr_rules.ledgers.other)
    expect(next.ocr_rules.future).toBe(true)
    expect(readOcrPreferences(next, 'ledger')).toEqual(prefs)
    expect(current.ocr_rules.ledgers).not.toHaveProperty('ledger')
  })

  it('defaults categories by direction and never replaces a chosen category or guesses a transfer category', () => {
    const config = mergeOcrPreferences({}, 'ledger', { ...readOcrPreferences(null, 'ledger'),
      accounting_mode: 'channel', default_expense_category_id: 'exp', default_income_category_id: 'inc' })
    const cats = [{ id: 'exp', name: '其他支出', kind: 'expense' }, { id: 'inc', name: '其他收入', kind: 'income' }]
    expect(defaultEntryCategory(config, 'ledger', 'expense', cats, '')).toBe('其他支出')
    expect(defaultEntryCategory(config, 'ledger', 'income', cats, '')).toBe('其他收入')
    expect(defaultEntryCategory(config, 'ledger', 'income', cats, '工资')).toBe('工资')
    expect(defaultEntryCategory(config, 'ledger', 'transfer', cats, '')).toBe('')
    expect(defaultEntryCategory(config, 'other', 'expense', cats, '')).toBe('')
    expect(defaultEntryCategory(config, 'ledger', 'expense', [...cats, { id: 'child', name: 'child', kind: 'expense', parent_name: '其他支出' }], '')).toBe('')
  })

  it('rejects malformed preference values and keeps ledger defaults isolated', () => {
    const value = { ocr_rules: { ledgers: { one: { wechat_account_id: 123, campus_topup_as_expense: 'true' } } } }
    expect(readOcrPreferences(value, 'one').wechat_account_id).toBe('')
    expect(readOcrPreferences(value, 'one').campus_topup_as_expense).toBe(false)
    expect(readOcrPreferences(value, 'two').default_expense_category_id).toBe('')
    expect(readOcrPreferences(null, 'one').campus_topup_as_expense).toBe(false)
  })

  it('prefills a legacy wallet name using the configured channel ID, leaving unrelated accounts untouched', () => {
    const prefs = { ...readOcrPreferences(null, 'l'), accounting_mode: 'channel' as const, wechat_account_id: 'w' }
    const config = mergeOcrPreferences({}, 'l', prefs)
    expect(legacyChannelAccount(config, 'l', [{ id: 'w', name: '微信' }], '微信零钱')).toBe('微信')
    expect(legacyChannelAccount(config, 'l', [{ id: 'w', name: '微信' }], '银行卡')).toBe('银行卡')
    expect(legacyChannelAccount(config, 'l', [{ id: 'w', name: '微信', hidden: true }], '零钱')).toBe('零钱')
    expect(legacyChannelAccount(config, 'other', [{ id: 'w', name: '微信' }], '零钱')).toBe('零钱')
  })
})

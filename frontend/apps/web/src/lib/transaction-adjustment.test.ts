import { expect, it } from 'vitest'
import { isTransactionAmountValid, setTransactionAdjustment, updateTransactionMagnitude } from '@beecount/web-features'

it('accepts native refunds and income reversals, while keeping transfers and OCR confirmation positive', () => {
  expect(isTransactionAmountValid('-12.50', 'expense')).toBe(true)
  expect(isTransactionAmountValid('-12.50', 'income')).toBe(true)
  expect(isTransactionAmountValid('-12.50', 'transfer')).toBe(false)
  expect(isTransactionAmountValid('-12.50', 'expense', true)).toBe(false)
  expect(isTransactionAmountValid('0', 'expense')).toBe(false)
  expect(isTransactionAmountValid('NaN', 'expense')).toBe(false)
  expect(isTransactionAmountValid('12.50', 'transfer')).toBe(true)
})

it('keeps the financial direction explicit while the user edits the unsigned magnitude', () => {
  expect(setTransactionAdjustment('12.50', true)).toBe('-12.50')
  expect(setTransactionAdjustment('-12.50', false)).toBe('12.50')
  expect(setTransactionAdjustment('', true)).toBe('-')
  expect(updateTransactionMagnitude('-', '8.20')).toBe('-8.20')
  expect(updateTransactionMagnitude('-8.20', '')).toBe('-')
  expect(updateTransactionMagnitude('8.20', '-9.30')).toBe('-9.30')
})

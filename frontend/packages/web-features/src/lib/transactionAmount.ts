import type { ReadTransaction } from '@beecount/api-client'

/** Display the existing signed amount contract; never change the stored transaction type. */
export function transactionAmountDisplay(type: ReadTransaction['tx_type'], amount: number) {
  const magnitude = Math.abs(amount)
  const effect = type === 'expense' ? -amount : amount
  // No directional sign or colour for an amount displayed as zero cents.
  const zero = magnitude.toFixed(2) === '0.00'
  const sign = zero ? '' : effect < 0 ? '-' : type === 'transfer' ? '' : '+'
  const tone = zero || type === 'transfer' ? 'default' : effect < 0 ? 'negative' : 'positive'
  return { magnitude, sign, tone } as const
}

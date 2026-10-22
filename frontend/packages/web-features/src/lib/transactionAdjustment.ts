import type { TxForm } from '../forms'

/** Native refunds are negative expenses; returned income is negative income. */
export function isTransactionAmountValid(value: string | number, kind: TxForm['tx_type'], positiveOnly = false): boolean {
  const amount = Number(value)
  return Number.isFinite(amount) && amount !== 0 && (!(positiveOnly || kind === 'transfer') || amount > 0)
}

export function setTransactionAdjustment(value: string, adjustment: boolean): string {
  const magnitude = value.trim().replace(/^[+-]/, '')
  return adjustment ? `-${magnitude}` : magnitude
}

export function updateTransactionMagnitude(previous: string, next: string): string {
  const input = next.trim()
  if (/^[+-]/.test(input)) return input
  return previous.trim().startsWith('-') ? `-${input}` : input
}

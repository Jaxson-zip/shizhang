import { afterEach, expect, it, vi } from 'vitest'
import { applyPrimaryColor, DEFAULT_PRIMARY_COLOR } from '@beecount/ui'

afterEach(() => vi.unstubAllGlobals())

function contrast(a: string, b: string) {
  const luminance = (hex: string) => {
    const values = hex.match(/[\da-f]{2}/gi)!.map((part) => parseInt(part, 16) / 255)
      .map((n) => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4)
    return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
  }
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

it('keeps the Shizhang primary action readable in both themes', () => {
  const properties = new Map<string, string>()
  vi.stubGlobal('document', { documentElement: { style: { setProperty: (k: string, v: string) => properties.set(k, v) } } })
  applyPrimaryColor(DEFAULT_PRIMARY_COLOR)
  expect(DEFAULT_PRIMARY_COLOR).toBe('#24624F')
  expect(properties.get('--primary-user-light')).not.toBe(properties.get('--primary-user-dark'))
  expect(contrast(DEFAULT_PRIMARY_COLOR, '#FFFFFF')).toBeGreaterThanOrEqual(4.5)
  expect(contrast('#8CC6B0', '#15251F')).toBeGreaterThanOrEqual(4.5)
  expect(properties.get('--primary-fg-light')).toBe('0 0% 100%')
  expect(properties.get('--primary-fg-dark')).toBe('156 28% 11%')
})

it('retains a chosen custom colour and gives its primary button a readable label', () => {
  const properties = new Map<string, string>()
  vi.stubGlobal('document', { documentElement: { style: { setProperty: (k: string, v: string) => properties.set(k, v) } } })
  applyPrimaryColor('#F59E0B')
  expect(properties.get('--primary-user-light')).toBe(properties.get('--primary-user-dark'))
  expect(properties.get('--primary-fg-light')).toBe('0 0% 0%')
  expect(contrast('#F59E0B', '#000000')).toBeGreaterThanOrEqual(4.5)
})

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, expect, it, vi } from 'vitest'
import { LocaleProvider } from '@beecount/ui'

import { dictionaries } from '../i18n'
import { PhoneUseSection } from './PhoneUseSection'

afterEach(() => vi.unstubAllGlobals())

it('explains HTTP limitations and the separate iPhone capture setup without promising automatic capture', () => {
  const nav = { onLine: true }
  vi.stubGlobal('window', {
    navigator: nav,
    isSecureContext: false,
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => 'zh-CN' },
  })
  vi.stubGlobal('navigator', nav)
  const html = renderToStaticMarkup(
    createElement(LocaleProvider, { dictionaries }, createElement(PhoneUseSection)),
  )
  expect(html).toContain('手机使用')
  expect(html).toContain('HTTP')
  expect(html).toContain('HTTPS')
  expect(html).toContain('完整链路仍待手机验证')
  expect(html).toContain('不会自动监听微信或支付宝付款')
})

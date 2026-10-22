import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi, afterEach } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../i18n'
import { connectionMessage, SyncStatusView } from './SyncStatusNotice'

afterEach(() => vi.unstubAllGlobals())
it('prioritizes offline, denied and failed pull over an open socket', () => {
  const base = { online: true, socket: 'connected', pull: 'checked', checkedAt: 1 }
  expect(connectionMessage(base)).toBe('syncState.connected')
  expect(connectionMessage({ ...base, online: false })).toBe('syncState.offline')
  expect(connectionMessage({ ...base, pull: 'error' })).toBe('syncState.error')
  expect(connectionMessage({ ...base, pull: 'auth' })).toBe('syncState.auth')
  expect(connectionMessage({ ...base, socket: 'disconnected' })).toBe('syncState.reconnecting')
})
it('explains offline data and does not offer an offline submit or blanket sync claim', () => {
  vi.stubGlobal('window', { localStorage: { getItem: () => 'zh-CN' } })
  const html = renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, createElement(SyncStatusView, {
    state: { online: false, socket: 'connected', pull: 'checked', checkedAt: null }, checkNow: () => {}, login: () => {},
  })))
  expect(html).toContain('当前离线')
  expect(html).toContain('不会离线入账')
  expect(html).toContain('disabled')
  expect(html).not.toContain('全部已同步')
})

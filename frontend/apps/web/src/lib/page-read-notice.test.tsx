import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../i18n'
import { PageReadNotice } from '../components/PageReadNotice'

function render(ready: boolean, pending: boolean, failed: boolean) {
  return renderToStaticMarkup(createElement(LocaleProvider, { dictionaries },
    createElement(PageReadNotice, { ready, pending, failed, retry: () => {} })))
}
it('labels the initial read as unconfirmed rather than an empty collection', () => {
  expect(render(false, true, false)).toContain('role="status"')
  expect(render(false, true, false)).toContain('Loading data')
})
it('offers a retry and distinguishes first failure from retained data', () => {
  expect(render(false, false, true)).toContain('Retry')
  expect(render(true, false, true)).toContain('last successful result')
})
it('does not cover a confirmed view during a routine background refresh', () => {
  expect(render(true, true, false)).toBe('')
})

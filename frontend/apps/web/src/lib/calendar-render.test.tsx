import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../i18n'
import { CalendarReadNotice, DayDetailHeader } from '../pages/sections/CalendarPage'

function render(node: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, node))
}

it('renders a negative daily balance with its sign and cents', () => {
  const html = render(createElement(DayDetailHeader, { dateKey: '2026-10-15', currency: 'CNY',
    bucket: { dateKey: '2026-10-15', income: 0, expense: 61.41, net: -61.41, txCount: 4 },
    pending: false, unavailable: false, hasTransactions: true, onAdd: () => {} }))
  expect(html).toContain('-CNY 61.41')
})

it.each([
  { pending: true, unavailable: false, text: 'Loading' },
  { pending: false, unavailable: true, text: 'Daily totals are unavailable' },
])('does not present unconfirmed data as an empty day: $text', ({ pending, unavailable, text }) => {
  const html = render(createElement(DayDetailHeader, { dateKey: '2026-10-15', currency: 'CNY',
    bucket: undefined, pending, unavailable, hasTransactions: false, onAdd: () => {} }))
  expect(html).toContain(text)
  expect(html).not.toContain('No transactions on this day')
})

it('labels retained data as stale and provides a retry button', () => {
  const html = render(createElement(CalendarReadNotice, { label: 'Daily entries could not be loaded', hasData: true, retry: () => {} }))
  expect(html).toContain('role="alert"')
  expect(html).toContain('last successful result')
  expect(html).toContain('Retry')
})

it('shows the server day total separately from a capped list', () => {
  const html = render(createElement(DayDetailHeader, { dateKey: '2026-10-15', currency: 'CNY',
    bucket: undefined, pending: false, unavailable: false, hasTransactions: true, onAdd: () => {},
    entryTotal: 248, entryShown: 200, entriesPending: false, entriesUnavailable: false }))
  expect(html).toContain('248 entries')
  expect(html).toContain('Showing 200 of 248')
})

it.each([
  { entriesPending: true, entriesUnavailable: false },
  { entriesPending: false, entriesUnavailable: true },
])('does not present a retained total as a current count: $entriesPending/$entriesUnavailable', (readState) => {
  const html = render(createElement(DayDetailHeader, { dateKey: '2026-10-15', currency: 'CNY',
    bucket: undefined, pending: false, unavailable: false, hasTransactions: true, onAdd: () => {},
    entryTotal: 248, entryShown: 200, ...readState }))
  expect(html).not.toContain('248 entries')
})

it('shows a confirmed empty day count without inferring it from an empty loading list', () => {
  const html = render(createElement(DayDetailHeader, { dateKey: '2026-10-15', currency: 'CNY',
    bucket: undefined, pending: false, unavailable: false, hasTransactions: false, onAdd: () => {},
    entryTotal: 0, entryShown: 0, entriesPending: false, entriesUnavailable: false }))
  expect(html).toContain('0 entries')
})

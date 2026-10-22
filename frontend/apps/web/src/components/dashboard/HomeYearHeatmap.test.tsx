import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../../i18n'
import { HomeYearHeatmap } from './HomeYearHeatmap'

it('provides selectable months and one exact, currency-labelled detail region', () => {
  const now = new Date()
  const bucket = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const html = renderToStaticMarkup(createElement(LocaleProvider, { dictionaries },
    createElement(HomeYearHeatmap, { currency: 'CNY', yearSeries: [
      { bucket, income: 0, expense: 61.41, balance: -61.41 },
    ] })))
  expect(html.match(/aria-pressed="(?:true|false)"/g)).toHaveLength(12)
  expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  expect(html.match(/role="region"/g)).toHaveLength(1)
  expect(html).toContain('-¥61.41')
  expect(html).toContain('CNY')
})

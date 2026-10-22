import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { dictionaries } from '../../i18n'
import { HomeHero } from './HomeHero'

function render(series: Array<{ bucket: string; income: number; expense: number }>) {
  return renderToStaticMarkup(createElement(LocaleProvider, { dictionaries },
    createElement(HomeHero, { ledgers: [], monthSeries: series.map((item) => ({ ...item, balance: item.income - item.expense })) })))
}

it('does not describe one day of actual transactions as an empty ledger', () => {
  expect(render([{ bucket: '2026-10-15', income: 0, expense: 18.6 }])).not.toContain('No transactions')
})

it('retains the empty explanation when there are no trend entries', () => {
  expect(render([])).toContain('No transactions')
})

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import { AccountsPanel, TagsPanel, accountDefaults, tagDefaults } from '@beecount/web-features'
import { dictionaries } from '../i18n'

const noop = () => {}
function render(child: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(LocaleProvider, { dictionaries }, child))
}

it('makes the account detail action reachable by keyboard', () => {
  const html = render(createElement(AccountsPanel, { form: accountDefaults(), canManage: true,
    rows: [{ id: 'test', name: 'Synthetic wallet', account_type: 'wechat', currency: 'CNY', initial_balance: 10, last_change_id: 0 }],
    onFormChange: noop, onSave: () => true, onReset: noop, onEdit: noop, onDelete: noop, onClickAccount: noop }))
  expect(html).toContain('role="button" tabindex="0"')
})

it('makes tag details reachable by keyboard without making its actions submit a form', () => {
  const html = render(createElement(TagsPanel, { form: tagDefaults(), canManage: true,
    rows: [{ id: 'test', name: 'Synthetic tag', color: '#fde68a', last_change_id: 0 }],
    onFormChange: noop, onSave: () => true, onReset: noop, onEdit: noop, onDelete: noop, onClickTag: noop }))
  expect(html).toContain('role="button" tabindex="0"')
})

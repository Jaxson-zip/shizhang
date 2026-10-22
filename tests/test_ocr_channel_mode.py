"""Opt-in channel bookkeeping uses native dictionaries, not bank balances."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_trigger import setup_trigger

from src.main import app


@pytest.mark.parametrize('kind, sample', [('income', INCOMING), ('expense', GROUP)])
def test_personal_review_has_matching_default_category_without_auto_accepting_purpose(kind, sample):
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'channel-personal@example.invalid')
        income = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
            json={'base_change_id': 0, 'name': '其他收入', 'kind': 'income'}).json()['entity_id']
        config = {'ocr_rules': {'ledgers': {ledger: {
            'accounting_mode': 'channel', 'wechat_account_id': account,
            'default_expense_category_id': expense, 'default_income_category_id': income}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H:%M:%S')
        import re
        text = re.sub(r'2026年10月17日 \d\d:\d\d:\d\d', now, sample)
        text = text.replace('转账说明 微信转账', '转账说明 合成借款')
        text = text.replace('收款详情 查看', '收款详情 合成借款')
        body = {'text': text, 'ledger_id': ledger, 'review_policy': 'deferred', 'request_id': str(uuid4())}
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 202, response.text
        assert response.json()['recorded'] is True
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == kind
        assert rows[0]['category_id'] == (income if kind == 'income' else expense)
        assert rows[0]['exclude_from_stats'] is True
        page = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert page['pending_total'] == 1
        assert '本次未写入账目' not in page['items'][0]['reason']
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('mode, channel, expected', [
    ('funding', '微信支付', ''), ('channel', '支付宝', 'alipay'),
    ('channel', '未知支付', ''), ('channel', '支付宝\n微信支付', ''),
])
def test_channel_routing_is_opt_in_and_needs_unambiguous_channel_evidence(mode, channel, expected):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'channel-evidence@example.invalid')
        alipay = client.post('/api/v1/write/ledgers/' + ledger + '/accounts', headers=headers,
            json={'base_change_id': 0, 'name': '支付宝', 'account_type': 'alipay', 'currency': 'CNY'}).json()['entity_id']
        cfg = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': mode,
            'wechat_account_id': account, 'alipay_account_id': alipay, 'default_expense_category_id': category}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': cfg}).status_code == 200
        # No remaining WeChat evidence from the synthetic input.
        body['text'] = channel + '\n' + body['text'].replace('微信支付\n', '').replace('微信零钱', '合成银行卡').replace('零钱', '合成银行卡')
        response = client.post('/api/v1/ai/parse-tx-text', headers=headers,
            json={'engine': 'rules', 'ledger_id': ledger, 'text': body['text']})
        if expected:
            assert response.status_code == 200, response.text
            assert response.json()['tx_drafts'][0]['account_name'] == '支付宝'
        elif response.status_code == 200:
            assert response.json()['tx_drafts'][0]['account_name'] == ''
        else:
            assert response.status_code == 422
        assert client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('marker', ['', '财付通\n支付宝'])
def test_channel_mode_never_treats_a_bare_funding_label_as_channel_evidence(marker):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'channel-unknown@example.invalid')
        cfg = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel',
            'wechat_account_id': account, 'default_expense_category_id': category}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': cfg}).status_code == 200
        response = client.post('/api/v1/ai/parse-tx-text', headers=headers,
            json={'engine': 'rules', 'ledger_id': ledger, 'text': body['text'].replace('微信支付', marker)})
        assert response.status_code == 200, response.text
        assert response.json()['tx_drafts'][0]['account_name'] == ''
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_channel_mode_bank_payment_uses_configured_channel_and_default_category():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'channel-bank@example.invalid')
        profile = client.get('/api/v1/profile/me', headers=headers).json()
        config = profile.get('ai_config') or {}
        config['ocr_rules'] = {'ledgers': {ledger: {
            'accounting_mode': 'channel', 'wechat_account_id': account,
            'default_expense_category_id': category}}}
        saved = client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config})
        assert saved.status_code == 200, saved.text
        body.pop('category_name')
        body['text'] = '微信支付\n' + body['text'].replace('零钱', '合成银行储蓄卡(1234)')
        body.update(review_policy='deferred')
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 200, response.text
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['account_id'] == account
        assert rows[0]['category_id'] == category and rows[0]['exclude_from_stats'] is False
        again = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert again.status_code == 200 and again.json()['entity_id'] == response.json()['entity_id']
        assert len(client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

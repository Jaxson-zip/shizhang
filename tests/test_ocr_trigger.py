"""One intentional Shortcut run is one operation, independent of order labels."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client, _register_and_login
from test_ocr_phone_capture_20261017 import CAPTURE

from src.main import app


def setup_trigger(client, email='ocr-trigger@example.invalid'):
    token, _ = _register_and_login(client, email)
    headers = {'Authorization':'Bearer '+token}
    ledger = client.post('/api/v1/write/ledgers',headers=headers,
                         json={'base_change_id':0,'ledger_name':'Synthetic trigger','currency':'CNY'}).json()['ledger_id']
    base = '/api/v1/write/ledgers/'+ledger
    account = client.post(base+'/accounts',headers=headers,
                          json={'base_change_id':0,'name':'微信零钱','account_type':'wechat','currency':'CNY'}).json()['entity_id']
    category = client.post(base+'/categories',headers=headers,
                           json={'base_change_id':0,'name':'其他','kind':'expense'}).json()['entity_id']
    stamp = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
    body = {'text':CAPTURE.replace('2026-10-17 15:11:02',stamp.strftime('%Y-%m-%d %H:%M:%S')),
            'ledger_id':ledger,'category_name':'其他','allow_review':True,'request_id':str(uuid4())}
    return headers, ledger, account, category, body


def test_missing_order_direct_write_replays_same_run_but_preserves_a_new_intentional_run():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client)
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint,headers=headers,json=body)
        assert first.status_code == 200, first.text
        again = client.post(endpoint,headers=headers,json=body)
        assert again.status_code == 200 and again.json()['idempotency_replayed'] is True
        assert again.json()['entity_id'] == first.json()['entity_id']
        next_run = client.post(endpoint,headers=headers,json={**body,'request_id':str(uuid4())})
        assert next_run.status_code == 200 and next_run.json()['entity_id'] != first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert len(rows) == 2 and all(r['amount'] == .01 for r in rows)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_native_choice_returns_existing_options_without_writing_and_explicit_selection_saves():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-trigger-choice@example.invalid')
        body['text'] = body['text'].replace('零钱','未知扣款账户')
        body.pop('category_name')
        endpoint = '/api/v1/ai/record-ocr-text'
        waiting = client.post(endpoint,headers=headers,json=body)
        assert waiting.status_code == 422
        choices = waiting.json()['shortcut_choices']
        assert choices['account_labels'] == ['微信零钱']
        assert choices['account_ids'] == {'微信零钱':account}
        assert choices['category_labels'] == ['其他']
        assert choices['category_ids'] == {'其他':category}
        assert '0.01' in choices['summary'] and '付款时间' in choices['summary']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
        rejected = client.post(endpoint,headers=headers,json={**body,'account_id':'missing','category_id':category})
        assert rejected.status_code == 422
        chosen = {**body,'account_id':account,'category_id':category}
        saved = client.post(endpoint,headers=headers,json=chosen)
        assert saved.status_code == 200, saved.text
        replay = client.post(endpoint,headers=headers,json=chosen)
        assert replay.status_code == 200 and replay.json()['entity_id'] == saved.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert len(rows) == 1 and rows[0]['account_id'] == account and rows[0]['category_id'] == category
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_request_identity_never_merges_two_runs_with_an_order_and_changed_same_key_is_refused():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client,'ocr-trigger-order@example.invalid')
        body['text'] += '\n交易单号：SYNTHETIC_TRIGGER_ORDER_001'
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint,headers=headers,json=body)
        assert first.status_code == 200
        changed = client.post(endpoint,headers=headers,json={**body,'text':body['text'].replace('· 0.01','· 0.02')})
        assert changed.status_code == 409
        second = client.post(endpoint,headers=headers,json={**body,'request_id':str(uuid4())})
        assert second.status_code == 200 and second.json()['entity_id'] != first.json()['entity_id']
        assert len(client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()) == 2
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('change', ['invalid-request','missing-time','old-time','ambiguous-money','failed-payment','foreign-account','foreign-category'])
def test_trigger_validation_and_explicit_choices_do_not_bypass_payment_or_dictionary_checks(change):
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client,'ocr-trigger-guard@example.invalid')
        if change == 'invalid-request':
            body['request_id'] = 'short'
        elif change == 'missing-time':
            body['text'] = '\n'.join(line for line in body['text'].splitlines() if not line.startswith('交易时间'))
        elif change == 'old-time':
            body['text'] = '\n'.join('交易时间:2020-01-01 12:00:00' if line.startswith('交易时间') else line for line in body['text'].splitlines())
        elif change == 'ambiguous-money':
            body['text'] = body['text'].replace('· 0.01','· 0.O1')
        elif change == 'failed-payment':
            body['text'] = body['text'].replace('支付成功','支付失败')
        else:
            _, _, foreign_account, foreign_category, _ = setup_trigger(client,'ocr-trigger-foreign@example.invalid')
            body['account_id' if change == 'foreign-account' else 'category_id'] = foreign_account if change == 'foreign-account' else foreign_category
        refused = client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body)
        assert refused.status_code == 422
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
        if change in ('missing-time','old-time','ambiguous-money','failed-payment'):
            assert 'shortcut_choices' not in refused.json()
        if change.startswith('foreign-'):
            choices = refused.json()['shortcut_choices']
            assert foreign_account not in choices['account_ids'].values()
            assert foreign_category not in choices['category_ids'].values()
    finally:
        client.close()
        app.dependency_overrides.clear()

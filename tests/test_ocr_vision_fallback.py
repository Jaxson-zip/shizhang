"""Vision is a fallback transcriber, never a second financial write engine."""
from unittest.mock import AsyncMock, patch

import pytest
from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_trigger import setup_trigger

from src.main import app

# A synthetic tiny PNG; no user's payment screenshot is sent to a provider.
IMAGE = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='


def test_unclear_ocr_uses_vision_then_keeps_a_provisional_entry_for_review():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-chain@example.invalid')
        uid = client.get('/api/v1/profile/me', headers=headers).json()['user_id']
        _seed_ai_config(uid, vision_model='glm-4.6v-flash')
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        model = AsyncMock(return_value={'text': original, 'transaction_count': 1})
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert response.status_code == 202, response.text
            saved = response.json()['entity_id']
            assert saved and response.json()['recorded'] is True
            replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert replay.status_code == 202 and replay.json()['entity_id'] == saved
        assert model.await_count == 1
        options = model.await_args.kwargs
        assert options['max_retries'] == 0 and options['timeout'] == 20
        assert options['thinking'] is False and options['redact_content'] is True
        assert options['config'].model == 'glm-4.6v-flash'
        assert options['messages'][1]['content'][0]['image_url']['url'].startswith('data:image/png;base64,')
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == .01 and rows[0]['tx_type'] == 'expense'
        # A model reading is provisional: excluded from stats until the user confirms it.
        assert rows[0]['exclude_from_stats'] is True
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['pending_total'] == 1
        item = inbox['items'][0]
        assert item['entity_id'] == saved and '视觉' in item['reason'] and item['image']['available'] is True
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('case', ['clear', 'failure', 'popup', 'foreign-ledger', 'no-provider',
                                  'multiple', 'bad-json', 'timeout', 'invalid-image'])
def test_only_uncertain_authorized_captures_can_call_a_model_and_failures_are_retained(case):
    from src.services.ai.provider_client import ChatProviderError
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-'+case+'@example.invalid')
        if case != 'no-provider':
            _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        if case == 'clear':
            body['text'] = original
        if case == 'failure':
            body['text'] = original.replace('支付成功', '支付失败')
        if case == 'popup':
            body['text'] = '入账未通过\n服务器返回：错误\n'+original
        if case == 'foreign-ledger':
            _, foreign, _, _, _ = setup_trigger(client, 'foreign-vision-owner@example.invalid')
            body['ledger_id'] = foreign
        if case == 'invalid-image':
            body['image_base64'] = 'aHRtbCBub3QgYW4gaW1hZ2U='
        result = {'text': original, 'transaction_count': 2 if case == 'multiple' else 1}
        if case == 'bad-json':
            result = {'tx_drafts': [{'amount': 999}]}
        model = AsyncMock(return_value=result, side_effect=ChatProviderError('synthetic timeout') if case == 'timeout' else None)
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            if case == 'foreign-ledger':
                assert response.status_code in (403, 404)
            elif case == 'clear':
                assert response.status_code == 200
            else:
                assert response.status_code == 202 and not response.json().get('entity_id'), response.text
                assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['total'] == 1
            if case in {'clear', 'failure', 'popup', 'foreign-ledger', 'no-provider', 'invalid-image'}:
                assert model.await_count == 0
            else:
                assert model.await_count == 1
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == (1 if case == 'clear' else 0)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_failed_provisional_write_is_atomic_and_retry_keeps_the_capture_without_recalling_model(monkeypatch):
    from uuid import uuid4

    from src.routers.write import transactions
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-atomic@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        real_guard = transactions.capture_write_guard
        def fail(*args):
            replay, bind = real_guard(*args)
            def failed(receipt):
                bind(receipt)
                raise RuntimeError('synthetic before commit')
            return replay, failed
        monkeypatch.setattr(transactions, 'capture_write_guard', fail)
        model = AsyncMock(return_value={'text': original, 'transaction_count': 1})
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            with pytest.raises(RuntimeError, match='synthetic before commit'):
                client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
            monkeypatch.setattr(transactions, 'capture_write_guard', real_guard)
            # The capture was kept before the write; a retry returns it for review
            # instead of re-asking the model or inventing a second entry.
            resumed = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert resumed.status_code == 202 and not resumed.json()['entity_id']
            assert model.await_count == 1
            new = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={**body, 'request_id': str(uuid4())})
            assert new.status_code == 202 and new.json()['entity_id']
            assert model.await_count == 2
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['exclude_from_stats'] is True
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['total'] == 2
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_existing_v8_pending_request_hash_remains_compatible():
    import hashlib
    import json

    from src.routers.ai.parse_tx_text import RecordOcrTextRequest
    from src.services.ocr_capture import request_hash
    req = RecordOcrTextRequest(text='synthetic existing v8 capture', ledger_id='ledger_synthetic',
                              request_id='existing-capture-intent-123', review_policy='deferred')
    old = req.model_dump(mode='json', exclude={'vision_fallback', 'image_base64'})
    legacy_hash = hashlib.sha256(json.dumps(old, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert request_hash(req) == legacy_hash


def test_concurrent_attempt_that_already_retained_uncertainty_is_not_overwritten(monkeypatch):
    import src.routers.ai.parse_tx_text as route
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-race@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        real_retain = route.retain_capture
        def race(db, user, ledger_id, req, draft, reason):
            real_retain(db, user, ledger_id, req, None, 'synthetic concurrent uncertainty')
            return real_retain(db, user, ledger_id, req, draft, reason)
        monkeypatch.setattr(route, 'retain_capture', race)
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={'text': original, 'transaction_count': 1})):
            response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 202 and not response.json().get('entity_id')
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('field,changed', [('amount', '99.00'), ('sign', '+0.01'),
                                          ('time', '2025-01-01 01:01:01'), ('funding', '余额')])
def test_partial_ocr_facts_cannot_be_replaced_when_only_merchant_is_missing(field, changed):
    client = _make_client()
    try:
        headers, ledger, account, _, body = setup_trigger(client, 'vision-facts-'+field+'@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        # A real signed bill style makes direction explicit, even if the merchant label is unreadable.
        signed = original.replace('实付金额\n· 0.01', '-0.01')
        body.update(text=signed.replace('商家名称:', '读不清字段:'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE, account_id=account)
        if field == 'amount':
            model_text = original.replace('· 0.01', changed)
        elif field == 'sign':
            import re

            from test_ocr_personal_receipts import INCOMING
            stamp = re.search(r'交易时间:(.*)', original)[1]
            model_text = re.sub(r'\+48\.00', changed, INCOMING)
            model_text = re.sub(r'20\d{2}年\d+月\d+日 \d+:\d+:\d+', stamp, model_text)
        elif field == 'time':
            import re
            model_text = re.sub(r'交易时间:.*', '交易时间:'+changed, original)
        else:
            model_text = original.replace('零钱', changed)
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={'text': model_text, 'transaction_count': 1})):
            response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 202 and not response.json().get('entity_id'), response.text
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_fallback_cannot_change_a_clear_amount_when_ocr_only_missed_the_merchant():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-conflict@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        body.update(text=original.replace('商家名称:', '读不清字段:'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        changed = original.replace('· 0.01', '20.00')
        preview = client.post('/api/v1/ai/parse-tx-text', headers=headers,
                              json={'text': changed, 'ledger_id': ledger, 'engine': 'rules'})
        assert preview.status_code == 200 and preview.json()['tx_drafts'][0]['amount'] == 20
        model = AsyncMock(return_value={'text': changed, 'transaction_count': 1})
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 202 and not result.json().get('entity_id')
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()

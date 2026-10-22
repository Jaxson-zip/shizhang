"""User-opted Alipay saving outflows remain entries without inflating consumption."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_receipts import DISCOUNT, SAVING, configure
from test_ocr_vision_fallback import IMAGE

from src.main import app


def opt_in(client, headers, ledger):
    config = client.get('/api/v1/profile/me', headers=headers).json()['ai_config']
    config['ocr_rules']['ledgers'][ledger]['alipay_saving_as_excluded_expense'] = True
    config.update(providers=[{'id': 'synthetic', 'baseUrl': 'https://example.invalid/v4',
                              'apiKey': 'synthetic-key', 'visionModel': 'glm-4.6v-flashx'}],
                  binding={'visionProviderId': 'synthetic'})
    assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200


def test_opted_saving_is_one_excluded_expense_without_review_and_normal_purchases_keep_counting():
    client = _make_client()
    try:
        headers, ledger, account, *_ = configure(client, 'saving-excluded')
        opt_in(client, headers, ledger)
        budget = client.post('/api/v1/write/ledgers/' + ledger + '/budgets', headers=headers,
            json={'base_change_id': 0, 'type': 'total', 'amount': 100, 'start_day': 1})
        assert budget.status_code == 200
        body = {'ledger_id': ledger, 'text': SAVING, 'request_id': str(uuid4()), 'review_policy': 'deferred'}
        endpoint = '/api/v1/ai/record-ocr-text'
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock()) as model:
            first = client.post(endpoint, headers=headers, json=body)
            assert first.status_code == 200, first.text
            replay = client.post(endpoint, headers=headers, json=body)
            assert replay.status_code == 200 and replay.json()['entity_id'] == first.json()['entity_id']
            assert model.await_count == 0
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 5 and rows[0]['tx_type'] == 'expense'
        assert rows[0]['account_id'] == account
        assert rows[0]['exclude_from_stats'] is True and rows[0]['exclude_from_budget'] is True
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['pending_total'] == 0
        analytics = client.get('/api/v1/read/workspace/analytics', headers=headers,
            params={'ledger_id': ledger, 'scope': 'month', 'period': '2026-10', 'tz_offset_minutes': 480}).json()
        assert analytics['summary']['expense_total'] == 0
        usage = client.get('/api/v1/read/ledgers/' + ledger + '/budgets/usage', headers=headers)
        assert usage.status_code == 200 and usage.json()['items'][0]['used'] == 0
        assert client.get('/api/v1/read/workspace/ledger-counts', headers=headers,
            params={'ledger_id': ledger}).json()['tx_count'] == 1
        normal = client.post(endpoint, headers=headers, json={**body, 'request_id': str(uuid4()), 'text': DISCOUNT})
        assert normal.status_code == 200
        analytics = client.get('/api/v1/read/workspace/analytics', headers=headers,
            params={'ledger_id': ledger, 'scope': 'month', 'period': '2026-10', 'tz_offset_minutes': 480}).json()
        assert analytics['summary']['expense_total'] == 5.07
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('model_text,recorded', [(SAVING, True), (
    SAVING.replace('支付宝小荷包', '合成商户').replace('自动攒', '普通扣款').replace('账户存取', '日用百货'), False)])
def test_visual_recovery_must_preserve_saving_purpose_and_its_exclusions(model_text, recorded):
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'saving-vision-' + str(recorded).lower())
        opt_in(client, headers, ledger)
        body = {'ledger_id': ledger, 'text': SAVING.replace('09:50:39', '09:5?:39'),
                'request_id': str(uuid4()), 'review_policy': 'deferred', 'vision_fallback': True,
                'image_base64': IMAGE}
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={
                'transaction_count': 1, 'text': model_text})) as model:
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 202, result.text
        assert model.await_count == 1
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        if recorded:
            # Provisional for review; confirming keeps the saving exclusions from the draft.
            assert len(rows) == 1 and rows[0]['exclude_from_stats'] is True and rows[0]['exclude_from_budget'] is True
            detail = client.get('/api/v1/ai/ocr-inbox/' + result.json()['capture_id'], headers=headers).json()
            assert detail['status'] == 'pending' and detail['draft']['exclude_from_stats'] is True
        else:
            assert rows == []
            detail = client.get('/api/v1/ai/ocr-inbox/' + result.json()['capture_id'], headers=headers).json()
            assert detail['draft'] is None
            assert detail['accounting_flags'] == {'exclude_from_stats': True, 'exclude_from_budget': True}
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Captures carry structural diagnostics only: enums, field labels and flags, never bill content."""
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import select
from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_alipay_receipts import DISCOUNT, configure
from test_ocr_trigger import setup_trigger
from test_ocr_vision_fallback import IMAGE

from src.main import app


def stored_capture(condition):
    # The test client's in-memory database, via its overridden dependency.
    from src.database import get_db
    from src.services.ocr_capture import OcrCapture
    sessions = app.dependency_overrides[get_db]()
    db = next(sessions)
    try:
        return db.scalar(select(OcrCapture).where(*condition(OcrCapture)))
    finally:
        sessions.close()


def stored_diag(capture_id):
    return stored_capture(lambda row: (row.id == capture_id,)).draft['_diag']


def assert_no_bill_content(diag, *secrets):
    raw = json.dumps(diag, ensure_ascii=False)
    for secret in secrets:
        assert secret not in raw


def test_rules_failure_then_vision_review_records_channel_layout_and_stages():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'diag-vision')
        config = client.get('/api/v1/profile/me', headers=headers).json()['ai_config']
        config.update(providers=[{'id': 'synthetic', 'baseUrl': 'https://example.invalid/v4',
                                  'apiKey': 'synthetic-key', 'visionModel': 'glm-4.6v-flashx'}],
                      binding={'visionProviderId': 'synthetic'})
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        body = {'ledger_id': ledger, 'text': DISCOUNT.replace('12:33:16', '12:3?:16'), 'request_id': str(uuid4()),
                'review_policy': 'deferred', 'vision_fallback': True, 'image_base64': IMAGE}
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={
                'transaction_count': 1, 'text': DISCOUNT.replace('余额宝 >', '余额宝')})):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 202, result.text
        diag = stored_diag(result.json()['capture_id'])
        assert diag['channel'] == 'alipay' and diag['stage'] == 'rules' and diag['layout'] == 'unrecognized'
        assert diag['vision'] == 'recovered' and diag['vision_layout'] == 'alipay_detail'
        assert diag['vision_stage'] == 'vision_review'
        assert_no_bill_content(diag, '5.07', '合成药店', '2026-10-12', '余额宝', 'synthetic-key')
        # Diagnostics stay out of the inbox view.
        item = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['items'][0]
        assert '_diag' not in json.dumps(item)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_automatic_entry_records_auto_stage():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'diag-auto')
        from datetime import datetime, timezone
        body = {'ledger_id': ledger, 'text': DISCOUNT, 'request_id': str(uuid4()), 'review_policy': 'deferred',
                'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()}
        result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 200, result.text
        diag = stored_capture(lambda row: (row.request_id == body['request_id'],)).draft['_diag']
        assert diag['stage'] == 'auto' and diag['layout'] == 'alipay_detail' and diag['vision'] == 'disabled'
        assert_no_bill_content(diag, '5.07', '合成药店')
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_unmatched_account_records_match_stage_and_which_side_failed():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'diag-match@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        body.update(text=body['text'].replace('零钱', '合成银行卡(9999)'), review_policy='deferred')
        result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 202, result.text
        diag = stored_diag(result.json()['capture_id'])
        assert diag['stage'] == 'match' and diag['missing'] == ['account'] and diag['channel'] == 'wechat'
        assert_no_bill_content(diag, '9999', '0.01')
    finally:
        client.close()
        app.dependency_overrides.clear()

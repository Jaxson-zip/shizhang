"""Observed OCR recovery never turns uncertain glyphs into automatic writes."""
import base64
import json
from datetime import datetime, timedelta, timezone

from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger
from test_ocr_wechat_examples import QR_BILL

from src.main import app


def test_recovered_glyphs_require_review_even_with_valid_time_and_explicit_accounts():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'recovered-layout@example.invalid')
        stamp = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        text = QR_BILL.replace('-1.23', '一 1 · 23').replace('2026年10月17日 10:01:02', stamp.strftime('%Y年%m月%d日 %H:%M:%S'))
        body.update(text=text, account_id=account, category_id=category, allow_review=True)
        endpoint = '/api/v1/ai/record-ocr-text'
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 422, response.text
        result = response.json()
        assert 'entity_id' not in result and 'shortcut_choices' not in result
        payload = json.loads(base64.urlsafe_b64decode(result['review_payload']+'='*(-len(result['review_payload']) % 4)))
        assert payload['version'] == 1 and payload['amount'] == 1.23
        assert payload['happened_at'] == stamp.isoformat()
        retry = client.post(endpoint, headers=headers, json=body).json()
        repeated = json.loads(base64.urlsafe_b64decode(retry['review_payload']+'='*(-len(retry['review_payload']) % 4)))
        assert repeated['review_id'] == payload['review_id']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        disabled = client.post(endpoint, headers=headers, json={**body, 'allow_review': False})
        assert disabled.status_code == 422 and 'review_payload' not in disabled.json()
    finally:
        client.close()
        app.dependency_overrides.clear()

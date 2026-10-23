"""Ambiguous synthetic Alipay inputs must stay unbooked, including transport retries."""
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_checkout_glyph import CAPTURED
from test_ocr_alipay_detail_columns import FIVE
from test_ocr_alipay_receipts import configure

from src.main import app


@pytest.mark.parametrize('sample,text', [
    ('amount', CAPTURED.replace('· 139.00', '· 12.00')),
    ('time', FIVE.replace('2026-10-22 21:00:01', '完成时间\n2026-10-22 21:00:01')),
    ('wallet', FIVE.replace('合成商品', '充值到支付宝余额')),
])
def test_ambiguous_alipay_capture_is_unbooked_and_retry_does_not_duplicate(sample, text):
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-guard-'+sample)
        body = {'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred'}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 202, first.text
        assert first.json()['capture_status'] == 'pending' and not first.json()['recorded']
        retry = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert retry.status_code == 202 and retry.json()['capture_id'] == first.json()['capture_id']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['pending_total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

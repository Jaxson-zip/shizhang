"""Displaced field labels are not immutable funding evidence against vision."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_receipts import DISCOUNT, SAVING, configure
from test_ocr_saving_expense import opt_in
from test_ocr_vision_fallback import IMAGE

from src.main import app


@pytest.mark.parametrize('text,label,amount,saving', [
    (DISCOUNT, '商品说明', 5.07, False),
    (SAVING, '理由', 5, True),
])
def test_column_ocr_automatically_uses_vision_before_returning_a_pending_capture(text, label, amount, saving):
    client = _make_client()
    try:
        headers, ledger, account, *_ = configure(client, 'alipay-funding-column-' + str(saving).lower())
        opt_in(client, headers, ledger)
        # The two adjacent labels precede the column of values in phone OCR.
        column_ocr = text.replace('付款方式 余额宝 >\n' + label + ' ',
                                  '付款方式\n' + label + '\n余额宝 >\n')
        assert column_ocr != text
        body = {'ledger_id': ledger, 'text': column_ocr, 'request_id': str(uuid4()),
                'review_policy': 'deferred', 'vision_fallback': True, 'image_base64': IMAGE}
        model = AsyncMock(return_value={'transaction_count': 1, 'text': text})
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert model.await_count == 1
            assert result.status_code == 202 and result.json()['entity_id'], result.text
            replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert replay.status_code == 202 and replay.json()['entity_id'] == result.json()['entity_id']
            assert model.await_count == 1
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == amount and rows[0]['tx_type'] == 'expense'
        assert rows[0]['account_id'] == account
        # Provisional until reviewed; the stored draft keeps saving exclusions for confirmation.
        assert rows[0]['exclude_from_stats'] is True and rows[0]['exclude_from_budget'] is True
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['pending_total'] == 1
        assert inbox['items'][0]['draft'].get('exclude_from_stats', False) is saving
    finally:
        client.close()
        app.dependency_overrides.clear()

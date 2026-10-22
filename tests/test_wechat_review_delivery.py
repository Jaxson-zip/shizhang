"""Native save recovery of anonymous WeChat personal review receipts, not device OCR."""
import base64
import json
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_trigger import setup_trigger

from src.main import app


@pytest.mark.parametrize('text,direction', [(INCOMING, 'income'), (GROUP, 'expense')])
def test_review_delivery_preserves_direction_and_count_across_auth_loss_and_separate_captures(text, direction):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'delivery-'+direction+'@example.invalid')
        base = '/api/v1/write/ledgers/'+ledger
        if direction == 'income':
            created = client.post(base+'/categories', headers=headers, json={
                'base_change_id': 0, 'name': '合成往来收入', 'kind': 'income'})
            assert created.status_code == 200
            category, category_name = created.json()['entity_id'], '合成往来收入'
        else:
            category_name = '其他'
        original_key = None
        for intent in range(2):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
                **body, 'text': text, 'request_id': str(uuid4()), 'allow_review': True})
            assert result.status_code == 422 and 'entity_id' not in result.json()
            encoded = result.json()['review_payload']
            review = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded) % 4)))
            assert review['version'] == 2 and review['tx_type'] == direction
            key = review['review_id']
            if original_key is not None:
                assert key != original_key  # a second capture remains a separate intention
            original_key = key
            save = {'base_change_id': 0, 'tx_type': direction, 'amount': review['amount'],
                    'happened_at': review['happened_at'], 'note': review['note'],
                    'account_id': account, 'account_name': '微信零钱', 'category_id': category,
                    'category_name': category_name, 'category_kind': direction}
            save_headers = {**headers, 'Idempotency-Key': key}
            saved = client.post(base+'/transactions', headers=save_headers, json=save)
            assert saved.status_code == 200
            receipt = saved.json()
            assert receipt['ledger_id'] == ledger and receipt['entity_id']
            assert isinstance(receipt['new_change_id'], int) and receipt['server_timestamp']
            # The client could have lost the above response. Expired credentials
            # cannot confirm it or add another row; a valid session can replay it.
            refused = client.post(base+'/transactions', headers={
                'Authorization': 'Bearer invalid-session', 'Idempotency-Key': key}, json=save)
            assert refused.status_code == 401
            resumed = client.post(base+'/transactions', headers=save_headers, json=save)
            assert resumed.status_code == 200 and resumed.json()['idempotency_replayed'] is True
            assert resumed.json()['entity_id'] == receipt['entity_id']
            rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
            assert len(rows) == intent+1
            assert all(row['tx_type'] == direction and row['amount'] == review['amount'] for row in rows)
            balances = client.get('/api/v1/read/workspace/accounts', headers=headers,
                                  params={'ledger_id': ledger}).json()
            expected = review['amount']*(intent+1)*(1 if direction == 'income' else -1)
            assert balances[0]['balance'] == pytest.approx(expected)
    finally:
        client.close()
        app.dependency_overrides.clear()

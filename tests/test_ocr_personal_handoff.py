"""Personal receipts only return authenticated review fields; never unattended expense writes."""
import base64
import json

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_trigger import setup_trigger

from src.main import app


@pytest.mark.parametrize('text,kind,direction', [(INCOMING, 'personal_incoming', 'income'), (GROUP, 'group_payment', 'expense')])
def test_personal_handoff_requires_manual_save_even_with_complete_shortcut_dictionary_choices(text, kind, direction):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'personal-'+kind+'@example.invalid')
        endpoint = '/api/v1/ai/record-ocr-text'
        body.update(text=text, allow_review=True, account_id=account, category_id=category,
                    result_time_policy='submission')
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 422, response.text
        result = response.json()
        assert 'entity_id' not in result and 'shortcut_choices' not in result
        payload = json.loads(base64.urlsafe_b64decode(result['review_payload']+'='*(-len(result['review_payload']) % 4)))
        assert payload['tx_type'] == direction and payload['review_reason'] == kind
        assert payload['version'] == 2  # old expense-only prefill must reject
        assert payload['amount'] > 0 and payload['category_name'] == ''
        assert 'password' not in payload and 'access_token' not in payload and 'text' not in payload
        assert payload['happened_at'].endswith('+08:00')
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        repeated = client.post(endpoint, headers=headers, json=body).json()
        repeated_payload = json.loads(base64.urlsafe_b64decode(repeated['review_payload']+'='*(-len(repeated['review_payload']) % 4)))
        assert repeated_payload['review_id'] == payload['review_id']
        disabled = client.post(endpoint, headers=headers, json={**body, 'allow_review': False})
        assert disabled.status_code == 422 and 'review_payload' not in disabled.json()
        # A separate intentional capture is a separate key, not content deduplication.
        another = client.post(endpoint, headers=headers, json={**body, 'request_id': 'another-intent-1234567890'}).json()
        another_payload = json.loads(base64.urlsafe_b64decode(another['review_payload']+'='*(-len(another['review_payload']) % 4)))
        assert another_payload['review_id'] != payload['review_id']
        # The explicit browser Save remains the native write contract. Verify
        # both directions and same-operation replay in an isolated database.
        base = '/api/v1/write/ledgers/'+ledger
        if direction == 'income':
            created = client.post(base+'/categories', headers=headers, json={
                'base_change_id': 0, 'name': '合成往来收入', 'kind': 'income'})
            assert created.status_code == 200
            save_category = created.json()['entity_id']
            category_name = '合成往来收入'
        else:
            save_category, category_name = category, '其他'
        save = {'base_change_id': 0, 'tx_type': direction, 'amount': payload['amount'],
                'happened_at': payload['happened_at'], 'note': payload['note'],
                'account_id': account, 'account_name': '微信零钱',
                'category_id': save_category, 'category_name': category_name, 'category_kind': direction}
        save_headers = {**headers, 'Idempotency-Key': payload['review_id']}
        saved = client.post(base+'/transactions', headers=save_headers, json=save)
        assert saved.status_code == 200, saved.text
        replay = client.post(base+'/transactions', headers=save_headers, json=save)
        assert replay.status_code == 200 and replay.json()['entity_id'] == saved.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == direction and rows[0]['amount'] == payload['amount']
        balance = client.get('/api/v1/read/workspace/accounts', headers=headers, params={'ledger_id': ledger}).json()[0]['balance']
        assert balance == (payload['amount'] if direction == 'income' else -payload['amount'])
    finally:
        client.close()
        app.dependency_overrides.clear()

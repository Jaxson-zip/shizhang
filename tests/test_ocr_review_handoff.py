"""Unattended OCR may hand off a review without weakening native writes."""
import base64
import json
from datetime import datetime, timedelta, timezone

from test_ai_parse_tx import _make_client, _register_and_login
from test_ocr_phone_capture_20261017 import CAPTURE

from src.main import app


def test_opt_in_handoff_prefills_missing_order_review_without_creating_a_record():
    client = _make_client()
    try:
        token, user_id = _register_and_login(client, 'ocr-review@example.invalid')
        headers = {'Authorization': 'Bearer ' + token}
        ledger = client.post('/api/v1/write/ledgers', headers=headers,
                             json={'base_change_id': 0, 'ledger_name': 'Synthetic review', 'currency': 'CNY'}).json()['ledger_id']
        base = '/api/v1/write/ledgers/' + ledger
        assert client.post(base + '/accounts', headers=headers,
                           json={'base_change_id': 0, 'name': '微信零钱', 'account_type': 'wechat', 'currency': 'CNY'}).status_code == 200
        assert client.post(base + '/categories', headers=headers,
                           json={'base_change_id': 0, 'name': '其他', 'kind': 'expense'}).status_code == 200
        stamp = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        text = CAPTURE.replace('2026-10-17 15:11:02', stamp.strftime('%Y-%m-%d %H:%M:%S'))
        body = {'text': text, 'ledger_id': ledger, 'category_name': '其他'}
        endpoint = '/api/v1/ai/record-ocr-text'
        refused = client.post(endpoint, headers=headers, json=body)
        assert refused.status_code == 422 and 'review_path' not in refused.json()
        response = client.post(endpoint, headers=headers, json={**body, 'allow_review': True})
        assert response.status_code == 422, response.text
        path = response.json()['review_path']
        assert path.startswith('/app/overview#ocr-review=') and '?' not in path
        encoded = path.split('#ocr-review=', 1)[1]
        assert response.json()['review_payload'] == encoded
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        assert payload['user_id'] == str(user_id) and payload['ledger_id'] == ledger
        assert payload['amount'] == .01 and payload['note'] == '[合成测试]手机OCR验证'
        assert payload['account_name'] == '微信零钱' and payload['category_name'] == '其他'
        assert datetime.fromisoformat(payload['happened_at']) == stamp
        assert payload['review_id'].startswith('ocr-review-')
        assert 0 < payload['expires_at'] - datetime.now(timezone.utc).timestamp() * 1000 <= 15 * 60 * 1000
        assert 'password' not in payload and 'access_token' not in payload and 'text' not in payload
        assert client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json() == []
        for raw in [text.replace('· 0.01', '· 0.O1'), text + '\n商家名称：另一家合成商户']:
            uncertain = client.post(endpoint, headers=headers, json={**body, 'text': raw, 'allow_review': True})
            assert uncertain.status_code == 422 and 'review_path' not in uncertain.json()
        # Missing time/account remain empty in the handoff, never guessed.
        for raw, empty in [(text.replace('交易时间:' + stamp.strftime('%Y-%m-%d %H:%M:%S') + '\n', ''), 'happened_at'),
                           (text.replace('零钱', '未配置银行卡'), 'account_name')]:
            partial = client.post(endpoint, headers=headers, json={**body, 'text': raw, 'allow_review': True})
            assert partial.status_code == 422
            data = partial.json()['review_payload']
            assert json.loads(base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)))[empty] == ''
        other, _ = _register_and_login(client, 'ocr-review-outsider@example.invalid')
        forbidden = client.post(endpoint, headers={'Authorization': 'Bearer ' + other}, json={**body, 'allow_review': True})
        assert forbidden.status_code == 404 and 'review_path' not in forbidden.json()
        # A later explicit Save uses the existing native endpoint and stable
        # operation key. A repeated link cannot mint a second native write key.
        save_body = {'base_change_id': 0, 'tx_type': 'expense', 'amount': payload['amount'],
                     'happened_at': payload['happened_at'], 'note': payload['note'],
                     'account_name': payload['account_name'], 'category_name': payload['category_name']}
        save_headers = {**headers, 'Idempotency-Key': payload['review_id']}
        saved = client.post(base + '/transactions', headers=save_headers, json=save_body)
        assert saved.status_code == 200, saved.text
        replay = client.post(base + '/transactions', headers=save_headers, json=save_body)
        assert replay.status_code == 200 and replay.json()['entity_id'] == saved.json()['entity_id']
        changed = client.post(base + '/transactions', headers=save_headers, json={**save_body, 'amount': .02})
        assert changed.status_code == 409
        assert len(client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

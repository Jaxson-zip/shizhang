"""Shortcut rejection identifies the missing field without exposing OCR text."""
from datetime import datetime, timedelta, timezone

from test_ai_parse_tx import _make_client, _register_and_login
from test_ocr_field_boundaries import RECEIPT

from src.main import app


def test_missing_record_fields_are_specific_and_never_write_a_transaction():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, 'ocr-missing-fields@example.invalid')
        headers = {'Authorization': 'Bearer ' + token}
        created = client.post('/api/v1/write/ledgers', headers=headers,
                              json={'base_change_id': 0, 'ledger_name': 'Synthetic OCR fields', 'currency': 'CNY'})
        ledger = created.json()['ledger_id']
        base = '/api/v1/write/ledgers/' + ledger
        assert client.post(base + '/accounts', headers=headers,
                           json={'base_change_id': 0, 'name': '微信零钱', 'account_type': 'wechat', 'currency': 'CNY'}).status_code == 200
        assert client.post(base + '/categories', headers=headers,
                           json={'base_change_id': 0, 'name': '其他', 'kind': 'expense'}).status_code == 200
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        text = RECEIPT.replace('2026-10-17 09:20:30', stamp)
        cases = [(text.replace('交易单号\n', ''), {'交易单号'}),
                 (text.replace('交易时间\n' + stamp + '\n', ''), {'付款时间'}),
                 (text.replace('零钱', '未配置银行卡'), {'付款账户'})]
        for raw, expected in cases:
            response = client.post('/api/v1/ai/record-ocr-text', headers=headers,
                                   json={'text': raw, 'ledger_id': ledger, 'category_name': '其他'})
            assert response.status_code == 422, response.text
            message = response.json()['detail']
            mentioned = {name for name in ('交易单号', '付款时间', '付款账户') if name in message}
            assert mentioned == expected
            assert '合成商家' not in message and '420000SYNTHETIC0001' not in message
        read = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers)
        assert read.status_code == 200 and read.json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()

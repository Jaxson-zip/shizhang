"""Clear evidence in the opted-in simple ledger must not mean mandatory review."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_service_actions import SCAN_HINT_COLUMNS
from test_ocr_trigger import setup_trigger
from test_ocr_wechat_examples import (
    CAMPUS_BILL,
    MERCHANT_BILL,
    MERCHANT_CHAT,
    PLATFORM_CHAT,
    QR_BILL,
)

from src.main import app


def setup_simple(client, email='decisive@example.invalid'):
    headers, ledger, account, category, body = setup_trigger(client, email)
    income = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
        json={'base_change_id': 0, 'name': '其他收入', 'kind': 'income'}).json()['entity_id']
    cfg = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel',
        'wechat_account_id': account, 'default_expense_category_id': category,
        'default_income_category_id': income, 'campus_topup_as_expense': True}}}}
    assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': cfg}).status_code == 200
    body.pop('category_name')
    body['review_policy'] = 'deferred'
    return headers, ledger, account, category, income, body


def test_an_explicit_old_payment_date_is_not_uncertainty_and_retry_is_durable(monkeypatch):
    client = _make_client()
    try:
        headers, ledger, account, category, _, body = setup_simple(client)
        body['text'] = '\n'.join('交易时间:2020-01-02 12:34:56' if line.startswith('交易时间')
                                 else line for line in body['text'].splitlines())
        endpoint = '/api/v1/ai/record-ocr-text'
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 200, response.text
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['account_id'] == account and rows[0]['category_id'] == category
        assert rows[0]['happened_at'].startswith('2020-01-02T04:34:56')
        assert rows[0]['exclude_from_stats'] is False
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['pending_total'] == 0
        from src.routers.write import _shared
        future = datetime.now(timezone.utc) + timedelta(days=3)
        monkeypatch.setattr(_shared, '_utcnow', lambda: future)
        again = client.post(endpoint, headers=headers, json=body)
        assert again.status_code == 200 and again.json()['entity_id'] == response.json()['entity_id']
        assert again.json()['idempotency_replayed'] is True
        # Two deliberate captures still mean two entries, even without an order number.
        next_run = client.post(endpoint, headers=headers, json={**body, 'request_id': str(uuid4())})
        assert next_run.status_code == 200 and next_run.json()['entity_id'] != response.json()['entity_id']
        assert len(client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()) == 2
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('text', [
    '财付通\n' + QR_BILL.replace('-1.23', '一 1 · 23'),
    INCOMING.replace('+48.00', '48.00'),
    '财付通\n' + QR_BILL.replace('2026年10月17日', '2099年10月17日'),
])
def test_uncertain_money_direction_or_future_time_is_retained_without_fabricating_a_transaction(text):
    client = _make_client()
    try:
        headers, ledger, _, _, _, body = setup_simple(client, 'decisive-uncertain@example.invalid')
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={**body, 'text': text})
        assert response.status_code == 202, response.text
        assert response.json()['recorded'] is False
        assert client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json() == []
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['pending_total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('text, kind, amount', [
    (INCOMING, 'income', 48), (GROUP, 'expense', 2.49),
    ('财付通\n' + SCAN_HINT_COLUMNS, 'expense', 1),
    ('财付通\n' + QR_BILL, 'expense', 1.23),
    ('财付通\n' + MERCHANT_BILL, 'expense', 2.34),
    ('财付通\n' + MERCHANT_CHAT, 'expense', 3.45),
    ('财付通\n' + CAMPUS_BILL, 'expense', 2.34),
    ('财付通\n' + PLATFORM_CHAT, 'expense', 4.56),
])
def test_clear_personal_and_complete_restored_columns_auto_book_with_correct_direction(text, kind, amount):
    client = _make_client()
    try:
        headers, ledger, _, expense, income, body = setup_simple(client, 'decisive-shapes@example.invalid')
        body['text'] = text
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 200, response.text
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == kind and rows[0]['amount'] == amount
        assert rows[0]['category_id'] == (income if kind == 'income' else expense)
        assert rows[0]['exclude_from_stats'] is False
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['pending_total'] == 0
    finally:
        client.close()
        app.dependency_overrides.clear()

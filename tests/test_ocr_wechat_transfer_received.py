"""WeChat page shown right after accepting a transfer. Synthetic values, not a user's capture."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text, payment_channel

INLINE = '''13:15
<
你已收款,资金已存入零钱
¥48.00
零钱余额
转账时间 2026年10月17日 10:01:02
收款时间 2026年10月17日 12:03:04
账单详情'''

# Apple OCR often emits the label column before its values.
COLUMNS = '''你已收款，资金已存入零钱
¥48.00
零钱余额
转账时间
收款时间
2026年10月17日 10:01:02
2026年10月17日 12:03:04
账单详情'''

SPLIT_STATUS = INLINE.replace('你已收款,资金已存入零钱', '你已收款\n资金已存入零钱')


def parse(text):
    return parse_payment_text(text, accounts=[('微信零钱', 'CNY')],
                              funding_aliases={'零钱': '微信零钱'}, default_category='默认消费分类')


@pytest.mark.parametrize('text', [INLINE, COLUMNS, SPLIT_STATUS])
def test_accepted_transfer_page_is_an_income_with_received_time(text):
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert result['receipt_kind'] == 'personal_incoming'
    assert draft['type'] == 'income' and draft['amount'] == 48
    # Received time, never the sender's transfer time.
    assert draft['happened_at'] == '2026-10-17T12:03:04+08:00'
    assert draft['account_name'] == '微信零钱'
    assert draft['category_name'] == ''
    assert payment_channel(text) == 'wechat'


def test_column_labels_in_the_other_order_keep_their_own_values():
    swapped = COLUMNS.replace('转账时间\n收款时间', '收款时间\n转账时间').replace(
        '2026年10月17日 10:01:02\n2026年10月17日 12:03:04', '2026年10月17日 12:03:04\n2026年10月17日 10:01:02')
    assert parse(swapped)['tx_drafts'][0]['happened_at'] == '2026-10-17T12:03:04+08:00'


def test_missing_received_time_stays_missing_rather_than_using_transfer_time():
    text = INLINE.replace('收款时间 2026年10月17日 12:03:04\n', '')
    assert parse(text)['tx_drafts'][0]['happened_at'] == ''


@pytest.mark.parametrize('text', [
    INLINE.replace('¥48.00', '¥48.00\n¥12.00'),                    # two amounts
    INLINE.replace('¥48.00', '+48.00\n¥48.00'),                    # mixed signed headline
    INLINE.replace('¥48.00\n', ''),                                # no amount
    INLINE + '\n已退还',                                            # refunded
    INLINE.replace('你已收款,资金已存入零钱', '待收款'),              # not yet received
    INLINE.replace('收款时间 2026年10月17日 12:03:04', '收款时间 2026年10月17日 12:03:04\n收款时间 2026年10月17日 12:04:05'),
])
def test_ambiguous_or_unfinished_received_pages_are_not_booked(text):
    with pytest.raises(PaymentTextError):
        parse(text)


def test_bare_wallet_word_alone_is_still_not_channel_evidence():
    assert payment_channel('支付成功\n¥5.00\n零钱') is None


def test_channel_mode_books_the_received_transfer_once_as_counted_income():
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'wechat-received@example.invalid')
        income = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
            json={'base_change_id': 0, 'name': '其他收入', 'kind': 'income'}).json()['entity_id']
        config = {'ocr_rules': {'ledgers': {ledger: {
            'accounting_mode': 'channel', 'wechat_account_id': account,
            'default_expense_category_id': expense, 'default_income_category_id': income}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        now = datetime.now(timezone(timedelta(hours=8)))
        text = COLUMNS.replace('2026年10月17日 12:03:04', now.strftime('%Y年%m月%d日 %H:%M:%S')).replace(
            '2026年10月17日 10:01:02', (now - timedelta(hours=20)).strftime('%Y年%m月%d日 %H:%M:%S'))
        body = {'text': text, 'ledger_id': ledger, 'review_policy': 'deferred', 'request_id': str(uuid4())}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert replay.status_code == 200 and replay.json()['entity_id'] == first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1
        assert rows[0]['tx_type'] == 'income' and rows[0]['amount'] == 48
        assert rows[0]['category_id'] == income and rows[0]['exclude_from_stats'] is False
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers,
                          params={'ledger_id': ledger}).json()['pending_total'] == 0
    finally:
        client.close()
        app.dependency_overrides.clear()

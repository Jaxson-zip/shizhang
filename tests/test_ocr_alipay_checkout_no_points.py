"""Alipay success page with no 支付宝积分 line (small payment, 2026-10-22 capture; masked structure, values invented)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_checkout_glyph import CAPTURED
from test_ocr_alipay_receipts import CHECKOUT, configure

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text, payment_channel

NO_POINTS = '''21:30
5G
回首页
支付成功
·0.50
合成商户五
交易方式
· 0.50
余额宝(转出资金付款)
合成 合成
完成'''


def parse(text):
    return parse_payment_text(text, accounts=[('支付宝', 'CNY')], default_category='其他', channel_account='支付宝')


@pytest.mark.parametrize('text, amount, note', [
    (NO_POINTS, 0.5, '合成商户五'),
    (NO_POINTS.replace('余额宝(转出资金付款)', '花呗'), 0.5, '合成商户五'),
    (CAPTURED, 139.0, '合成商户名称八字'),          # points lines present: unchanged
    (CHECKOUT, 0.01, '合成摊位'),
])
def test_success_page_without_points_line_is_one_alipay_expense(text, amount, note):
    assert payment_channel(text) == 'alipay'
    draft = parse(text)['tx_drafts'][0]
    assert draft['type'] == 'expense' and draft['amount'] == amount and draft['note'] == note


@pytest.mark.parametrize('text', [
    NO_POINTS.replace('· 0.50', '· 0.60'),                         # payee-row amount disagrees
    NO_POINTS.replace('余额宝(转出资金付款)', '合成广告'),             # no payment method
    NO_POINTS.replace('支付成功', '支付失败'),
])
def test_ambiguous_no_points_pages_are_refused(text):
    with pytest.raises(PaymentTextError):
        parse(text)


def test_channel_mode_books_the_no_points_page_once():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-no-points')
        body = {'ledger_id': ledger, 'text': NO_POINTS, 'request_id': str(uuid4()), 'review_policy': 'deferred',
                'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 0.5
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Alipay payment-success page from a 2026-10-22 capture (masked structure only; values invented).

Apple OCR read the ¥ before both amounts as '·', and listed the 交易方式 label before the
points/benefit lines, with its value (余额宝…) and the payee-row amount after them.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_receipts import CHECKOUT, configure

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text

CAPTURED = '''21:56 5G
回首页
支付成功
·139.00
合成商户名称八字
交易方式
支付宝积分+2
体验金+18
· 139.00
余额宝(转出资金付款)
合成活动
特价好物
大学生领红包合成广告文字十四个字
合成券
1.69元
完成'''


def parse(text):
    return parse_payment_text(text, accounts=[('支付宝', 'CNY')], default_category='其他', channel_account='支付宝')


@pytest.mark.parametrize('text', [CAPTURED, CAPTURED.replace('·139.00', '*139.00'), CHECKOUT])
def test_success_page_with_misread_yen_and_method_after_benefits_is_one_expense(text):
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert result['receipt_kind'] == 'payment_result'
    assert draft['type'] == 'expense' and draft['note'] in {'合成商户名称八字', '合成摊位'}
    assert draft['amount'] in {139.0, 0.01} and draft['account_name'] == '支付宝'


@pytest.mark.parametrize('text', [
    CAPTURED.replace('·139.00', '·139.00\n·12.00'),                     # two different amounts above the payee
    CAPTURED.replace('余额宝(转出资金付款)', '合成广告标题'),               # no recognizable method after the benefits
    CAPTURED.replace('支付成功', '支付失败'),                              # not a success page
])
def test_ambiguous_success_pages_are_still_refused(text):
    with pytest.raises(PaymentTextError):
        parse(text)


def test_channel_mode_books_the_success_page_once():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-checkout-glyph')
        body = {'ledger_id': ledger, 'text': CAPTURED, 'request_id': str(uuid4()), 'review_policy': 'deferred',
                'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['entity_id'] == first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 139 and rows[0]['tx_type'] == 'expense'
    finally:
        client.close()
        app.dependency_overrides.clear()

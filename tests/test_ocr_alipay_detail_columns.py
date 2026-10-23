"""Alipay bill-detail pages from 2026-10-22 captures (masked structure only; values invented).

Apple OCR put the field labels above the amount as one column, the values below 交易成功 as
another, and the status bar above 全部账单; long titles may wrap onto two lines.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_receipts import DISCOUNT, configure

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text

TAIL = '''更多~
账单管理
账单分类
标签
合成“合成”合成,合成
>
¥ 合成,合成
计入收支
备注
图 联系商家'''
FIVE = '''21:01
<
账单详情
100•
全部账单
支付时间
付款方式
商品说明
支付奖励
收款方全称
合成商户八个字名
-139.00
交易成功
2026-10-22 21:00:01
余额宝>
合成商品
积分奖励5合成
**合(合成)
''' + TAIL
THREE = '''21:02 5
<
账单详情
100,
全部账单
支付时间
付款方式
商品说明
合成
合成商户名
-6.00
交易成功
2026-10-22 21:02:03
余额宝>
合成•合成商品(合成规格六字)合成
件
支付奖励
积分5合成
''' + TAIL


def parse(text):
    return parse_payment_text(text, accounts=[('支付宝', 'CNY')], default_category='其他', channel_account='支付宝')


@pytest.mark.parametrize('text, amount, note, stamp', [
    (FIVE, 139.0, '合成商户八个字名', '2026-10-22T21:00:01+08:00'),
    (THREE, 6.0, '合成 合成商户名', '2026-10-22T21:02:03+08:00'),      # title wrapped onto two lines
    (DISCOUNT, 5.07, '合成药店', '2026-10-12T12:33:16+08:00'),           # ordinary inline layout unchanged
])
def test_alipay_detail_label_column_above_the_amount(text, amount, note, stamp):
    draft = parse(text)['tx_drafts'][0]
    assert draft['type'] == 'expense' and draft['amount'] == amount
    assert draft['note'] == note and draft['happened_at'] == stamp


@pytest.mark.parametrize('text', [
    FIVE.replace('合成商户八个字名', '甲\n乙方\n合成商户八个字名'),           # three title lines: not one payee
    FIVE.replace('-139.00', '-139.00\n-12.00'),                         # two debits
    FIVE.replace('交易成功', '退款成功'),                                  # refunded
])
def test_ambiguous_alipay_detail_columns_are_still_refused(text):
    with pytest.raises(PaymentTextError):
        parse(text)


def test_two_dates_below_the_status_leave_the_time_unset_for_review():
    text = FIVE.replace('余额宝>', '余额宝>\n2026-10-22 22:00:00')
    assert parse(text)['tx_drafts'][0]['happened_at'] == ''


def test_channel_mode_books_the_column_detail_once():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-detail-columns')
        now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        body = {'ledger_id': ledger, 'text': FIVE.replace('2026-10-22 21:00:01', now),
                'request_id': str(uuid4()), 'review_policy': 'deferred'}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['entity_id'] == first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 139 and rows[0]['tx_type'] == 'expense'
    finally:
        client.close()
        app.dependency_overrides.clear()

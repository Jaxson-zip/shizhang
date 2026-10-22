"""Anonymous reconstruction of a QR-payment detail layout, not phone OCR output."""
from datetime import datetime, timedelta, timezone

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text

QR = '''交易详情
-1.23
扫二维码付款-给合成餐饮商户
当前状态 支付成功
收款方备注 二维码收款
支付方式 零钱
转账时间 2026年10月17日 18:58:41
转账单号 1000000000202610170000000000000
交易服务
对订单有疑惑
发起群收款
本服务由财付通提供'''


@pytest.mark.parametrize('stacked', [False, True])
def test_explicit_qr_payment_with_transfer_named_metadata_remains_an_expense(stacked):
    receipt = QR
    if stacked:
        for label in ('当前状态', '收款方备注', '支付方式', '转账时间', '转账单号'):
            receipt = receipt.replace(label+' ', label+'\n')
    parsed = parse_payment_text(receipt, accounts=[('微信零钱','CNY')],
                                funding_aliases={'零钱':'微信零钱'})
    draft = parsed['tx_drafts'][0]
    assert draft['type'] == 'expense' and draft['amount'] == 1.23
    assert draft['note'] == '合成餐饮商户' and draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-17T18:58:41+08:00'
    assert parsed['source_id']


@pytest.mark.parametrize('receipt', [
    QR.replace('扫二维码付款-给合成餐饮商户', '转账给合成个人'),
    QR.replace('支付成功', '支付失败'),
    QR+'\n退款成功',
    QR+'\n转账给另一合成人',
    QR+'\n-2.34',
    QR+'\n扫二维码付款-给另一商户',
])
def test_qr_metadata_exception_does_not_accept_transfers_failures_or_ambiguous_receipts(receipt):
    with pytest.raises(PaymentTextError):
        parse_payment_text(receipt, accounts=[])


def test_qr_payment_with_zoned_client_clock_uses_bill_time_and_native_idempotency():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'qr-clock@example.invalid')
        local = timezone(timedelta(hours=8))
        payment = (datetime.now(local)-timedelta(minutes=2)).replace(microsecond=0)
        body.update(text=QR.replace('2026年10月17日 18:58:41', payment.strftime('%Y年%m月%d日 %H:%M:%S')),
                    submitted_at=datetime.now(local).replace(microsecond=0).isoformat(),
                    result_time_policy='submission', account_id=account, category_id=category)
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint, headers=headers, json=body)
        assert first.status_code == 200, first.text
        second = client.post(endpoint, headers=headers, json=body)
        assert second.status_code == 200 and second.json()['entity_id'] == first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 1.23
        assert datetime.fromisoformat(rows[0]['happened_at'].replace('Z', '+00:00')) == payment
    finally:
        client.close()
        app.dependency_overrides.clear()

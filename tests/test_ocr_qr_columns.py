"""Bounded OCR order/spacing variants consistent with observed phone counters."""
import pytest
from test_ocr_qr_payment import QR

from src.services.payment_rules import PaymentTextError, parse_payment_text

COLUMNS = QR.replace('''当前状态 支付成功
收款方备注 二维码收款
支付方式 零钱
转账时间 2026年10月17日 18:58:41
转账单号 1000000000202610170000000000000''', '''当前状态
收款方备注
支付方式
转账时间
转账单号
支付成功
二维码收款
零钱
2026年10月17日 18:58:41
1000000000202610170000000000000''')


@pytest.mark.parametrize('receipt', [COLUMNS, QR.replace('当前状态 支付成功', '当 前 状 态：支 付 成 功')])
def test_qr_table_column_or_spaced_status_preserves_all_field_values(receipt):
    parsed = parse_payment_text(receipt, accounts=[('微信零钱', 'CNY')], funding_aliases={'零钱': '微信零钱'})
    draft = parsed['tx_drafts'][0]
    assert draft['amount'] == 1.23 and draft['note'] == '合成餐饮商户'
    assert draft['account_name'] == '微信零钱' and draft['happened_at'] == '2026-10-17T18:58:41+08:00'
    assert parsed['source_id']


@pytest.mark.parametrize('receipt', [
    COLUMNS.replace('支付成功', '支付失败'),
    COLUMNS.replace('扫二维码付款-给合成餐饮商户', '转账给合成个人'),
    COLUMNS.replace('支付方式\n转账时间', '转账时间\n支付方式'),
    COLUMNS.replace('二维码收款\n零钱', '退款成功\n零钱'),
    COLUMNS+'\n转账给其他人',
])
def test_column_reconstruction_does_not_guess_unknown_orders_or_accept_real_transfers(receipt):
    with pytest.raises(PaymentTextError):
        parse_payment_text(receipt, accounts=[])

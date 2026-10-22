"""Public synthetic receipt captured by the user's actual iPhone on 2026-10-17."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

CAPTURE = """微信支付
支付成功
实付金额
· 0.01
商家名称:[合成测试]手机OCR验证
付款方式:零钱
交易时间:2026-10-17 15:11:02
TSTMVC259YM1H
"""


def test_observed_middle_dot_currency_preserves_digits_but_not_a_missing_order_label():
    result = parse_payment_text(CAPTURE, accounts=[('微信零钱', 'CNY')])
    draft = result['tx_drafts'][0]
    assert draft['amount'] == .01 and draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-17T15:11:02+08:00'
    assert result['source_id'] is None


@pytest.mark.parametrize('changed', [
    CAPTURE.replace('实付金额\n', ''),
    CAPTURE.replace('实付金额', '付款金额'),
    CAPTURE.replace('· 0.01', '·0.01'),
    CAPTURE.replace('· 0.01', '· 0.O1'),
    CAPTURE.replace('· 0.01', '· 0.001'),
])
def test_middle_dot_cannot_repair_unlabelled_or_unclear_money(changed):
    with pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[])

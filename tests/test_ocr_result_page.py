"""Sanitized reconstruction of the supplied payment-result layout, not iOS OCR output."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

RESULT = """16:33
支付 成功
合成收款人（**人）
￥0.02
完成
"""


def test_spaced_success_and_masked_recipient_result_remain_a_reviewable_payment():
    result = parse_payment_text(RESULT, accounts=[('微信零钱', 'CNY')])
    draft = result['tx_drafts'][0]
    assert result['receipt_kind'] == 'payment_result'
    assert draft['amount'] == .02 and draft['note'] == '合成收款人(**人)'
    assert draft['happened_at'] == '' and draft['account_name'] == ''
    assert result['source_id'] is None


@pytest.mark.parametrize('changed', [
    RESULT.replace('支付 成功','支付失败'), RESULT.replace('支付 成功',''),
    RESULT.replace('支付 成功','退款成功'), RESULT.replace('￥0.02','￥0.O2'),
    RESULT+'\n￥0.03', RESULT.replace('完成',''),
    RESULT.replace('合成收款人（**人）','合成收款人'),
    RESULT.replace('合成收款人（**人）','合成收款人（**人）\n另一收款人（**人）'),
    RESULT+'\n服务器返回：未识别到成功付款状态',
])
def test_ambiguous_or_failed_result_does_not_guess_a_successful_expense(changed):
    with pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[])

"""Regression from a physical iPhone synthetic receipt, not guessed digits."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

RECEIPT = '''微信支付
支付成功
实付金额
* 0.01
商家名称
合成测试商家
付款方式
零钱
交易时间
2026-10-16 08:53:00
交易单号
TSTIOSGLYPH00001
'''

def test_iphone_currency_star_in_explicit_paid_field_keeps_the_actual_digits():
    result = parse_payment_text(RECEIPT, accounts=[('微信零钱','CNY')])
    draft = result['tx_drafts'][0]
    assert draft['amount'] == 0.01
    assert draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-16T08:53:00+08:00'
    assert result['source_id']

@pytest.mark.parametrize('amount', ['****0.01','*0.01','* 0.O1','* 0.0','* 0.001','2 * 0.01','* -0.01'])
def test_masks_missing_digits_arithmetic_and_letters_still_need_review(amount):
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT.replace('* 0.01',amount),accounts=[])

def test_star_does_not_become_a_general_unlabelled_currency_prefix():
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT.replace('实付金额\n',''),accounts=[])
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT.replace('实付金额','付款金额'),accounts=[])

def test_star_does_not_bypass_multi_amount_or_foreign_currency_guards():
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT+'\n实付金额\n* 0.02',accounts=[])
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT+'\nUSD',accounts=[])

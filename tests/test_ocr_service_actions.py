"""A payment's service action is not its transaction status."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

RECEIPT = """微信支付
支付成功
实付金额
￥18.60
商家名称
合成商家
付款方式
零钱
交易时间
2026-10-17 16:00:00
"""


def test_apply_for_refund_action_in_bill_service_does_not_turn_success_into_a_refund():
    text = RECEIPT + '\n账单服务\n申请退款\n联系商家\n在此商户的交易'
    draft = parse_payment_text(text, accounts=[('微信零钱', 'CNY')])['tx_drafts'][0]
    assert draft['amount'] == 18.6 and draft['type'] == 'expense'
    assert draft['note'] == '合成商家'


@pytest.mark.parametrize('state', ['退款成功', '退款中', '已退款', '交易关闭', '支付失败', '转账'])
def test_service_action_does_not_override_real_refund_failure_or_transfer(state):
    text = RECEIPT.replace('支付成功', state) + '\n账单服务\n申请退款'
    with pytest.raises(PaymentTextError):
        parse_payment_text(text, accounts=[])


def test_only_the_known_service_action_is_excluded_and_remaining_footer_still_counts():
    for tail in ('申请退款', '账单服务\n退款成功', '账单服务\n申请退款\n转账'):
        with pytest.raises(PaymentTextError):
            parse_payment_text(RECEIPT + '\n' + tail, accounts=[])


def test_standalone_scan_refund_support_hint_is_not_a_refund_status():
    result = parse_payment_text(RECEIPT+'\n可在支持的商户扫码退款', accounts=[('微信零钱','CNY')])
    assert result['tx_drafts'][0]['amount'] == 18.6
    assert result['tx_drafts'][0]['type'] == 'expense'


SCAN_HINT_COLUMNS = '''账单
全部账单
合成便利店
-1.00
当前状态
支付时间
商品
商户全称
收单机构
支付方式
交易单号
商户单号
支付成功
2026年10月18日 09:02:46
合成便利店
合成商户
合成支付服务有限公司
零钱
420000SYNTHETIC0001
可在支持的商户扫码退款
MERCHANT0000002
账单服务
对订单有疑惑
'''


def test_scan_refund_hint_between_order_values_does_not_break_the_known_column_table():
    result = parse_payment_text(SCAN_HINT_COLUMNS, accounts=[('微信零钱','CNY')],
                                funding_aliases={'零钱':'微信零钱'})
    assert result['receipt_kind'] == 'layout_review'
    assert result['requires_confirmation'] is True
    draft = result['tx_drafts'][0]
    assert draft['amount'] == 1 and draft['type'] == 'expense'
    assert draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-18T09:02:46+08:00'


@pytest.mark.parametrize('state', ['退款成功', '支付失败', '已退款', '转账'])
def test_scan_refund_support_hint_never_cancels_an_actual_negative_status(state):
    with pytest.raises(PaymentTextError):
        parse_payment_text(SCAN_HINT_COLUMNS.replace('支付成功',state), accounts=[])


def test_only_the_exact_standalone_support_hint_is_excluded():
    with pytest.raises(PaymentTextError):
        parse_payment_text(RECEIPT+'\n退款说明:可在支持的商户扫码退款', accounts=[])

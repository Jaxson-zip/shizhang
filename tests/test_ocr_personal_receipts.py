"""Anonymous personal-receipt shapes, not actual iPhone OCR output."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

INCOMING = '''零钱明细
转账-来自合成好友
+48.00
当前状态 已存入零钱
转账说明 微信转账
转账时间 2026年10月17日 10:01:02
收款时间 2026年10月17日 12:03:04
转账单号 PERSONALTEST00000001
零钱余额 49.50
账单服务
定位到聊天位置
申请转账电子凭证
查看往来转账'''

GROUP = '''零钱明细
群收款-转给合成群成员
-2.49
当前状态 支付成功
收款详情 查看
支付时间 2026年10月17日 12:04:05
支付方式 零钱
交易单号 GROUPTEST00000001
商户单号 GROUPSHOP00000001
零钱余额 25.33
账单服务
对订单有疑惑'''


def parse(text):
    return parse_payment_text(text, accounts=[('微信零钱', 'CNY')],
                              funding_aliases={'零钱': '微信零钱'}, default_category='默认消费分类')


def test_incoming_uses_received_time_and_positive_review_direction_not_payment_expense_defaults():
    result = parse(INCOMING)
    draft = result['tx_drafts'][0]
    assert result['receipt_kind'] == 'personal_incoming'
    assert draft['type'] == 'income' and draft['amount'] == 48
    assert draft['note'] == '合成好友' and draft['category_name'] == ''
    assert draft['happened_at'] == '2026-10-17T12:03:04+08:00'
    assert draft['account_name'] == '微信零钱'


@pytest.mark.parametrize('stacked', [False, True])
def test_group_payment_uses_counterparty_not_merchant_and_never_wallet_balance(stacked):
    text = GROUP
    if stacked:
        for label in ('当前状态', '支付时间', '支付方式'):
            text = text.replace(label+' ', label+'\n')
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert result['receipt_kind'] == 'group_payment'
    assert draft['type'] == 'expense' and draft['amount'] == 2.49
    assert draft['note'] == '合成群成员' and draft['category_name'] == ''
    assert draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-17T12:04:05+08:00'


def test_missing_received_time_is_not_replaced_by_sender_time_or_now():
    draft = parse(INCOMING.replace('收款时间 2026年10月17日 12:03:04\n', ''))['tx_drafts'][0]
    assert draft['happened_at'] == ''
    unknown = parse(INCOMING.replace('已存入零钱', '已收款'))['tx_drafts'][0]
    assert unknown['account_name'] == ''


@pytest.mark.parametrize('receipt,labels', [
    (INCOMING, ['当前状态', '转账说明', '转账时间', '收款时间', '转账单号', '零钱余额']),
    (GROUP, ['当前状态', '收款详情', '支付时间', '支付方式', '交易单号', '商户单号', '零钱余额']),
])
def test_complete_known_personal_table_columns_preserve_direction_and_fields(receipt, labels):
    rows = receipt.splitlines()
    values = [next(line[len(label)+1:] for line in rows if line.startswith(label+' ')) for label in labels]
    block = '\n'.join(label+' '+value for label, value in zip(labels, values, strict=True))
    columns = '\n'.join(labels+values)
    result = parse(receipt.replace(block, columns))
    assert result == parse(receipt)


@pytest.mark.parametrize('text', [
    INCOMING.replace('+48.00', '-48.00'), GROUP.replace('-2.49', '+2.49'),
    INCOMING+'\n+2.00', GROUP+'\n¥2.00', INCOMING.replace('+48.00', '+48.001'),
    INCOMING.replace('已存入零钱', '待收款'), GROUP.replace('支付成功', '支付失败'),
    INCOMING+'\n退款成功', GROUP+'\n转账-来自另一个人\n+8.00',
    INCOMING.replace('12:03:04', '99:03:04'), INCOMING+'\nUSD',
])
def test_personal_review_never_guesses_direction_multiple_amounts_or_incomplete_status(text):
    with pytest.raises(PaymentTextError):
        parse(text)

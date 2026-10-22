"""Anonymous variants derived from local offline OCR, not iPhone equivalence."""
import re

import pytest
from test_ocr_wechat_examples import QR_BILL

from src.services.payment_rules import PaymentTextError, parse_payment_text


def parse(text):
    return parse_payment_text(text, accounts=[('微信零钱', 'CNY')], funding_aliases={'零钱': '微信零钱'})


def test_spaced_control_fields_and_observed_money_glyphs_are_review_only():
    text = re.sub(r'[\u4e00-\u9fff]', lambda m: m[0]+' ', QR_BILL)
    text = text.replace('-1.23', '一 1 · 23')
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert draft['amount'] == 1.23 and draft['type'] == 'expense'
    assert draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-17T10:01:02+08:00'
    assert result['receipt_kind'] == 'layout_review'


@pytest.mark.parametrize('bad', ['一 1·234', '一 O·23', '一 1 · 2', '一 1 23'])
def test_glyph_compatibility_never_invents_digits_or_decimal_places(bad):
    with pytest.raises(PaymentTextError):
        parse(QR_BILL.replace('-1.23', bad))


def test_label_column_before_header_and_value_column_after_header_is_review_only():
    text = '''当前状态
收款方备注
支付方式
转账时间
转账单号
账单
扫二维码付款-给合成收款人
-1.23
支付成功
二维码收款
零钱
2026年10月17日 10:01:02
QRTEST000000012345
账单服务
申请电子凭证'''
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert draft['amount'] == 1.23 and draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-17T10:01:02+08:00'
    assert result['receipt_kind'] == 'layout_review'


def test_platform_column_keeps_unlabelled_product_text_without_using_it_as_payment_facts():
    text = '''当前状态
支付时间
收单机构
支付方式
交易单号
商户单号
交易详情
-2.34
合成平台
支付成功
2026年10月17日 10:01:02
合成商品-平台App-
PRODUCT00000001234
合成收单支付有限公司
零钱
PAYMENT00000001234
SHOP000000012345
交易服务'''
    result = parse(text)
    draft = result['tx_drafts'][0]
    assert draft['amount'] == 2.34 and draft['note'] == '合成平台'
    assert draft['account_name'] == '微信零钱' and draft['happened_at'].endswith('+08:00')
    assert result['receipt_kind'] == 'layout_review'
    with pytest.raises(PaymentTextError):
        parse(text.replace('合成商品-平台App-', '退款成功-平台App-'))


def test_footer_receiving_party_service_is_not_another_payee_and_original_direct_shape_is_unchanged():
    text = QR_BILL+'\n收 款 方 服 务\n向 收 款 方 留 言'
    result = parse(text)
    assert result['tx_drafts'][0]['note'] == '合成收款人'
    assert result.get('receipt_kind') is None
    with pytest.raises(PaymentTextError):
        parse(QR_BILL+'\n收款方 另一合成收款人')


def test_one_displaced_qr_time_remains_original_and_requires_review():
    text = QR_BILL.replace('转账时间 2026年10月17日 10:01:02', '2026年10月17日 10:01:02\n转账时间')
    result = parse(text)
    assert result['tx_drafts'][0]['happened_at'] == '2026-10-17T10:01:02+08:00'
    assert result['receipt_kind'] == 'layout_review'

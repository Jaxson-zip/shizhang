"""Observed physical-iPhone layout; missing order labels must stay missing."""
import hashlib

import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

PHONE_LAYOUT = """微信支付
支付成功
实付金额
* 0.01
商家名称[合成测试]手机OCR验证
付款方式 零钱
交易时间 2026-10-16 16:38:43
TSTMVAPU603T2
此页只生成识别样例,不会自动写入账本。运行已配置的采集快捷指令后,才能检验是否入账。
刷新会产生新测试单号。验证重复识别时,请使用同一张截图。
返回账目列表
<
192.0.2.123
凸
"""


def test_observed_joined_merchant_keeps_funding_time_and_missing_order():
    result = parse_payment_text(PHONE_LAYOUT, accounts=[('微信零钱', 'CNY')])
    draft = result['tx_drafts'][0]
    assert draft['note'] == '[合成测试]手机OCR验证'
    assert draft['amount'] == .01
    assert draft['account_name'] == '微信零钱'
    assert draft['happened_at'] == '2026-10-16T16:38:43+08:00'
    # Never infer an order from an unlabelled alphanumeric line or page URL.
    assert result['source_id'] is None


@pytest.mark.parametrize('label', ['商家名称', '商户全称'])
def test_joined_explicit_merchant_and_labelled_order_preserve_identity(label):
    text = PHONE_LAYOUT.replace('商家名称', label).replace('TSTMVAPU603T2', '交易单号：TSTMVAPU603T2')
    result = parse_payment_text(text, accounts=[('微信零钱', 'CNY')])
    assert result['tx_drafts'][0]['note'] == '[合成测试]手机OCR验证'
    assert result['source_id'] == 'ocr-' + hashlib.sha256(b'wechat:TSTMVAPU603T2').hexdigest()


@pytest.mark.parametrize('extra', [
    '\n商家名称另一家合成商户',
    '\n商户全称\n另一家合成商户',
    '\n商家：另一家合成商户',
])
def test_joined_merchant_does_not_hide_a_second_merchant(extra):
    with pytest.raises(PaymentTextError, match='商家'):
        parse_payment_text(PHONE_LAYOUT + extra, accounts=[])


@pytest.mark.parametrize('label', ['商家小程序', '商家服务', '商家'])
def test_missing_delimiter_does_not_enable_generic_merchant_prefixes(label):
    with pytest.raises(PaymentTextError, match='商家'):
        parse_payment_text(PHONE_LAYOUT.replace('商家名称', label), accounts=[])

"""Explicit payment fields keep their meaning across OCR layout changes."""
import hashlib

import pytest

from src.services.payment_rules import parse_payment_text

RECEIPT = """微信支付
支付成功
实付金额
￥18.60
商家名称
合成商家
付款方式
零钱
交易时间
2026-10-17 09:20:30
交易单号
420000SYNTHETIC0001
"""


@pytest.mark.parametrize('label', ['交易单号', '交易号', '订单号'])
def test_joined_full_order_label_has_same_identity_as_separate_label(label):
    joined = RECEIPT.replace('交易单号\n', label)
    expected = 'ocr-' + hashlib.sha256(b'wechat:420000SYNTHETIC0001').hexdigest()
    assert parse_payment_text(joined, accounts=[])['source_id'] == expected
    assert parse_payment_text(RECEIPT, accounts=[])['source_id'] == expected


@pytest.mark.parametrize('stamp', ['2026年1月7日 09:20:30', '2026-1-7 9:20:30', '2026/1/7 09:20:30'])
def test_explicit_single_digit_calendar_components_keep_payment_time(stamp):
    text = RECEIPT.replace('2026-10-17 09:20:30', stamp)
    assert parse_payment_text(text, accounts=[])['tx_drafts'][0]['happened_at'] == '2026-01-07T09:20:30+08:00'


@pytest.mark.parametrize('field', [
    '420000SYNTHETIC0001', '商户单号420000SYNTHETIC0001',
    '交易单420000SYNTHETIC0001', '交易单号42000 SYNTHETIC0001',
    '交易单号420000SYNTHETIC0001\n交易单号420000SYNTHETIC0002',
    '交易单号420000SYNTHETIC0001 订单号420000SYNTHETIC0002',
])
def test_unlabelled_broken_or_multiple_order_fields_remain_review_only(field):
    text = RECEIPT.replace('交易单号\n420000SYNTHETIC0001', field)
    assert parse_payment_text(text, accounts=[])['source_id'] is None


@pytest.mark.parametrize('stamp', ['2026年2月30日 09:20:30', '2026-1-7', '2026-1-7 9:2:30', '2026-1-7 9:2O:30'])
def test_invalid_or_incomplete_calendar_time_is_not_repaired(stamp):
    text = RECEIPT.replace('2026-10-17 09:20:30', stamp)
    result = parse_payment_text(text, accounts=[])
    assert result['tx_drafts'][0]['happened_at'] == ''
    assert any('时间' in warning for warning in result['warnings'])

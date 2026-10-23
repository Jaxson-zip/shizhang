"""Classify a rejected OCR layout without logging its payment values."""
import json
import logging

import pytest
from test_ocr_qr_payment import QR

from src.services.payment_rules import PaymentTextError, parse_payment_text


@pytest.mark.parametrize('changed, expected', [
    # An unsigned debit stays unrecognized. (The Unicode minus used here before is now read as the
    # debit sign, 2026-10-23, so it no longer exercises the rejection log.)
    (QR.replace('-1.23', '1.23'), {'qr_debit_count': 0, 'qr_status_count': 1}),
    (QR.replace('当前状态 支付成功', '当前状态\n收款方备注\n支付成功'), {'qr_debit_count': 1, 'qr_status_count': 0}),
])
def test_rejected_layout_logs_only_structural_features(changed, expected, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[])
    messages = [r.getMessage() for r in caplog.records if 'ocr.rules.guard_rejected shape=' in r.getMessage()]
    assert len(messages) == 1
    shape = json.loads(messages[0].split('shape=', 1)[1])
    assert shape['qr_title_count'] == 1 and shape['success_count'] == 1
    assert shape['negative_types'] == ['转账']
    assert all(shape[k] == v for k,v in expected.items())
    assert '合成餐饮商户' not in messages[0] and '1.23' not in messages[0]
    assert '18:58:41' not in messages[0] and '100000000020261017' not in messages[0]

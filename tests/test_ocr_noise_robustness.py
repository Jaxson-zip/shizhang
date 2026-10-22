"""Semantics-preserving iPhone OCR noise must not change parsed facts; displaced columns may
be rejected or leave facts missing, but must never pair a label with a different value."""
import re

import pytest
from test_ocr_alipay_receipts import DISCOUNT, ESCROW
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_qr_payment import QR
from test_ocr_trigger import CAPTURE

from src.services.payment_rules import PaymentTextError, parse_payment_text

ACCOUNTS = [('微信零钱', 'CNY'), ('零钱', 'CNY'), ('余额宝', 'CNY')]
SAMPLES = {'wechat': CAPTURE, 'alipay': DISCOUNT, 'escrow': ESCROW, 'group': GROUP, 'incoming': INCOMING, 'qr': QR}
LABEL = r'(支付时间|付款时间|交易时间|创建时间|支付方式|付款方式|商品说明|商品|商家名称|商户全称|收款方|当前状态|交易单号|商户单号|订单号|收单机构)'


def facts(text):
    draft = parse_payment_text(text, accounts=ACCOUNTS)['tx_drafts'][0]
    return draft['type'], draft['amount'], draft['happened_at'], draft['account_name']


NOISE = {
    'spaced_labels': lambda t: re.sub('(?m)^' + LABEL, lambda m: ' '.join(m[1]), t),
    'split_label_value': lambda t: re.sub('(?m)^' + LABEL + r'[ \t:：]+(\S.*)$', r'\1\n\2', t),
    'date_slash': lambda t: re.sub(r'(\d{4})-(\d{1,2})-(\d{1,2})', r'\1/\2/\3', t),
    'date_cn': lambda t: re.sub(r'(\d{4})-(\d{1,2})-(\d{1,2})', r'\1年\2月\3日', t),
    'trailing_spaces': lambda t: '\n'.join(line + '  ' for line in t.splitlines()) + '\n\n',
    'blank_lines': lambda t: t.replace('\n', '\n\n'),
    'crlf': lambda t: t.replace('\n', '\r\n'),
    'chevron': lambda t: re.sub(r'(?m)^((?:支付方式|付款方式)[ \t:：]*[^\s>]\S*)$', r'\1 >', t),
}


@pytest.mark.parametrize('noise', sorted(NOISE))
@pytest.mark.parametrize('sample', sorted(SAMPLES))
def test_common_ocr_noise_keeps_amount_direction_time_and_funding(sample, noise):
    text = SAMPLES[sample]
    assert facts(NOISE[noise](text)) == facts(text)


def column_block(text):
    out, run = [], []

    def flush():
        out.extend([m[1] for m in run] + [m[2] for m in run] if len(run) >= 3 else [m[0] for m in run])
        run.clear()
    for line in text.splitlines():
        match = re.fullmatch(LABEL + r'[ \t:：]+(\S.*)', line)
        if match:
            run.append((line, match[1], match[2]))
        else:
            flush()
            out.append(line)
    flush()
    return '\n'.join(out)


@pytest.mark.parametrize('sample', sorted(SAMPLES))
def test_displaced_label_columns_are_rejected_or_incomplete_never_mispaired(sample):
    text = SAMPLES[sample]
    displaced = column_block(text)
    try:
        got = facts(displaced)
    except PaymentTextError:
        return
    assert all(value in ('', expected) for value, expected in zip(got, facts(text), strict=True))

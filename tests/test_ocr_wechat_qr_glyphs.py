"""WeChat QR transaction detail from a 2026-10-23 capture (masked structure only; values invented).

Apple OCR read the debit's minus as an em dash and the 年/月/日 of the payment date as one digit and two
letters, so the column table could not be restored and the transfer labels looked like a transfer.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

NOW = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0) - timedelta(minutes=3)
GARBLED = f'{NOW.year}4{NOW.month}H{NOW.day}E {NOW:%H:%M:%S}'
CAPTURED = f'''21:10
<
合成三
〇合成
合成
C 交易详情
—6.00
扫二维码付款-给合成店
当前状态
收款方备注
支付方式
转账时间
转账单号
支付成功
合成五个字
零钱
{GARBLED}
10000000000000000000000000000001
交易服务
1 对订单有疑惑
十 发起群收款
本服务由财付通提供'''


def parse(text):
    return parse_payment_text(text, accounts=[('微信零钱', 'CNY')], funding_aliases={'零钱': '微信零钱'},
                              channel_account='微信零钱')


@pytest.mark.parametrize('dash', ['—', '–', '−', '-'])
def test_dash_variants_and_garbled_date_still_read_the_qr_payment(dash):
    draft = parse(CAPTURED.replace('—6.00', dash + '6.00'))['tx_drafts'][0]
    assert draft['type'] == 'expense' and draft['amount'] == 6
    assert draft['note'] == '合成店' and draft['happened_at'] == NOW.isoformat()


@pytest.mark.parametrize('date', [
    f'{NOW.year}4{NOW.month}H{NOW.day}',            # no time: not a payment timestamp
    f'{NOW.year - 1}4{NOW.month}H{NOW.day}E {NOW:%H:%M:%S}',   # more than 30 days away
    f'{NOW.year}413H{NOW.day}E {NOW:%H:%M:%S}',     # month 13 is not a date
])
def test_unrecoverable_garbled_dates_are_not_guessed(date):
    with pytest.raises(PaymentTextError):
        parse(CAPTURED.replace(GARBLED, date))


def test_a_dash_inside_other_text_is_not_a_debit():
    with pytest.raises(PaymentTextError):
        parse(CAPTURED.replace('—6.00', '合成—6.00'))


@pytest.mark.parametrize('line', [
    f'{NOW.year}.{NOW.month}.{NOW.day} 12:00:00',        # dot date: must never become a different day
    f'{NOW.year}-{NOW.month}{NOW.day:02d} 12:00:00',     # missing separator
    f'{NOW.year}41{NOW.month}7{NOW.day}E 12:00:00',      # two digit separators: too ambiguous
])
def test_date_repair_never_invents_a_different_day(line):
    from src.services.payment_rules import _repair_garbled_date
    assert _repair_garbled_date(line) == line


@pytest.mark.parametrize('line', ['—1', '— 2026', '–12'])
def test_a_lone_dash_number_without_cents_is_not_a_debit(line):
    from src.services.payment_rules import _normalize_ocr_lines
    assert not _normalize_ocr_lines(line)[0].startswith('-')

"""WeChat bill-detail layouts from 2026-10-22 captures (masked structure only; every value here is invented).

Apple OCR lists the field labels as one column and the values as another; long values may wrap or
glue to the next value, and the merchant appears only as the title above the debit.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text

T = '2026年10月22日 20:49:01'
TX = '4200000000202610220000000001'
MCH = '1000000000202610220000000001'
FOOT = '账单服务\n1 对订单有疑惑\n合成合成合成合成\n十 发起群收款\n( 申请电子凭证\n本服务由财付通提供'
C1 = f'20:49\n账单\n100\n全部账单\n合成小吃店铺名称\n-12.50\n当前状态\n支付时间\n收单机构\n支付方式\n交易单号\n商户单号\n支付成功\n{T}\n财付通支付科技有限公司\n零钱\n{TX}\n{MCH}\n订单详情\n{FOOT}'
C4 = f'20:49 5\n图\n账单\nの\n100)\n全部账单\n扫码\n合成小吃店铺名称\n-8.00\n当前状态\n支付时间\n收单机构\n支付方式\n交易单号\n商户单号\n支付成功\n{T}\n财付通支付科技有限公司\n零钱\n{TX}\n{MCH}\n订单详情\n{FOOT}'
C5 = (f'20:50 M\n图\n账单\n(100,\n全部账单\nABC\n合成快餐店\n-23.00\n当前状态\n支付时间\n商品\n商户全称\n收单机构\n支付方式\n交易单号\n商户单号\n支付成功\n{T}\n'
      f'合成套餐名\n合成餐饮管理有限公司名称\n合成支付科技有限公司\n零钱\n{TX}\n合成第二行文字十一个字\n1000000000000001\n账单服务\n# 合成合成合成\n图 合成合成合成合\n合成合成合成\n申请电子凭证\n本服务由财付通提供')
C6 = (f'20:50\n账单\n100\n全部账单\n合成商户名称八字\n-15.00\n当前状态\n支付时间\n商品\n商户全称\n收单机构\n支付方式\n交易单号\n商户单号\n支付成功\n2026年10月22日20:50:01\n'
      f'Order:12345678901234567890;合成商品\n件\n合成商户名称八字\n财付通支付科技有限公司\n零钱\n{TX}\n10000000002026102200000000000001\n商家小程序\nAB 合成合成合>\n{FOOT}')
C3 = (f'20:50\n图\n账单\n(100\'\n全部账单\n合成商户名称八(合成店)\n-30.00\n当前状态\n支付时间\n商品\n商户全称\n收单机构\n支付方式\n交易单号\n商户单号\n支付成功\n'
      f'2026年10月22日20:50:02合成商品名称\n商户_合成店\n合成商户全称九个字\n招商银行储蓄卡(1234)\n{TX}\n10000000002026102200\n商家小程序\nAB 合成合成〉\n账单服务\n1 对订单有疑惑\n图 合成合成合成合\n合成合成合成\n# 申请电子凭证\n本服务由财付通提供')


def parse(text):
    return parse_payment_text(text, accounts=[('微信零钱', 'CNY')], funding_aliases={'零钱': '微信零钱'},
                              default_category='其他', channel_account='微信零钱')


@pytest.mark.parametrize('text, amount, note, stamp', [
    (C1, 12.5, '合成小吃店铺名称', '2026-10-22T20:49:01+08:00'),       # labels column restorable; title-only merchant
    (C4, 8.0, '扫码 合成小吃店铺名称', '2026-10-22T20:49:01+08:00'),    # extra short line above the title
    (C5, 23.0, 'ABC 合成快餐店', '2026-10-22T20:49:01+08:00'),          # a value wrapped onto an extra line
    (C6, 15.0, '合成商户名称八字', '2026-10-22T20:50:01+08:00'),        # product wraps; date has no space
    (C3, 30.0, '合成商户名称八(合成店)', '2026-10-22T20:50:02+08:00'),  # date glued to the next value
])
def test_wechat_bill_columns_book_the_headline_debit_title_and_only_time(text, amount, note, stamp):
    draft = parse(text)['tx_drafts'][0]
    assert draft['type'] == 'expense' and draft['amount'] == amount
    assert draft['note'] == note and draft['happened_at'] == stamp
    assert draft['account_name'] == '微信零钱'


@pytest.mark.parametrize('text', [
    C5.replace('-23.00', '-23.00\n-5.00'),                              # two debits
    C5.replace('支付成功', '已全额退款'),                                 # refunded
    C5 + '\n交易失败',                                                   # failure anywhere
])
def test_ambiguous_or_unsuccessful_column_bills_are_still_refused(text):
    with pytest.raises(PaymentTextError):
        parse(text)


def test_two_datetimes_in_a_wrapped_column_bill_leave_the_time_unset():
    text = C5.replace('合成第二行文字十一个字', '2026年10月22日 21:00:00')
    assert parse(text)['tx_drafts'][0]['happened_at'] == ''


def test_second_datetime_glued_to_a_value_still_makes_payment_time_ambiguous():
    text = C5.replace(T, T+'商品有效期2026年10月23日21:00:00')
    assert parse(text)['tx_drafts'][0]['happened_at'] == ''


def test_only_a_datetime_embedded_in_product_text_is_not_a_payment_time():
    text = C5.replace(T, '日期无法识别').replace('合成第二行文字十一个字', '商品有效期2026年10月23日21:00:00')
    assert parse(text)['tx_drafts'][0]['happened_at'] == ''


@pytest.mark.parametrize('other_time', ['创建时间', '完成时间'])
@pytest.mark.parametrize('location', ['labels', 'values'])
def test_other_time_cannot_replace_an_unreadable_payment_time(other_time, location):
    text = C5.replace(T, '日期无法识别')
    if location == 'labels':
        text = text.replace('商户单号\n支付成功', '商户单号\n'+other_time+'\n支付成功')
        value = '2026年10月21日 18:00:00'
    else:
        value = other_time+'\n2026年10月21日 18:00:00'
    text = text.replace('合成第二行文字十一个字', value)
    with pytest.raises(PaymentTextError):
        parse(text)


def test_more_than_two_title_lines_are_not_joined_into_a_merchant():
    with pytest.raises(PaymentTextError):
        parse(C1.replace('合成小吃店铺名称', '甲方\n乙方\n合成小吃店铺名称'))


@pytest.mark.parametrize('sample', ['C5', 'C1'])
def test_channel_mode_books_a_wrapped_wechat_bill_once(sample):
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, f'bill-columns-{sample.lower()}@example.invalid')
        config = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel', 'wechat_account_id': account,
                                                       'default_expense_category_id': expense}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H:%M:%S')
        text = globals()[sample].replace('2026年10月22日 20:49:01', now)
        body = {'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred'}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['entity_id'] == first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == 'expense' and rows[0]['exclude_from_stats'] is False
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('sample', ['other_time', 'two_times'])
def test_channel_mode_keeps_ambiguous_payment_times_unbooked_on_retry(sample):
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, f'time-guard-{sample}@example.invalid')
        config = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel', 'wechat_account_id': account,
                                                       'default_expense_category_id': expense}}}}
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        if sample == 'other_time':
            text = (C5.replace('商户单号\n支付成功', '商户单号\n创建时间\n支付成功')
                    .replace(T, '日期无法识别')
                    .replace('合成第二行文字十一个字', '2026年10月21日 18:00:00'))
        else:
            text = C5.replace(T, T+'商品有效期2026年10月23日21:00:00')
        body = {'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred'}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 202, first.text
        assert first.json()['capture_status'] == 'pending' and not first.json()['recorded']
        retry = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert retry.status_code == 202 and retry.json()['capture_id'] == first.json()['capture_id']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert rows == []
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['pending_total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Sanitized Alipay layouts supplied by the user; never actual bills or identifiers."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger
from test_ocr_vision_fallback import IMAGE

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text, payment_channel

CHECKOUT = '''支付成功
回首页
￥0.01
合成摊位
￥0.01
交易方式 余额宝(转出资金付款)
支付宝积分+2
体验金+18
哈啰顺风车券
3元
生活缴费红包
1元
特价好物
低至1.9元起
完成'''
DISCOUNT = '''账单详情
全部账单
合成药店
-5.07
交易成功
订单金额 5.50
碰一下立减 -0.43
支付时间 2026-10-12 12:33:16
付款方式 余额宝 >
商品说明 合成扫码
收单机构 合成收单银行股份有限公司
清算机构 中国银联股份有限公司
收款方全称 合成医药有限公司
更多
账单管理
账单分类 医疗健康
计入收支'''
INCOMING = '''账单详情
全部账单
synthetic-friend >
+150.00
交易成功
创建时间 2026-10-15 08:51:11
转账备注 转账
对方账户 synthetic-friend 153******20
更多
账单管理
账单分类 转账红包
计入收支
查看往来记录
申请电子回单'''
ESCROW = '''账单详情
全部账单
合成卖家***2
-220.00
等待确认收货
支付时间 2026-10-18 20:39:49
付款方式 余额宝 >
商品说明 合成开发板
支付奖励 立即领取13积分
订单号 2026101823001198321439467145
商家订单号 T200P3316963837038027756
账单管理
账单分类 日用百货
计入收支'''
SAVING = '''账单详情
全部账单
支付宝小荷包(合成攒钱计划)
-5.00
自动扣款成功
管理自动扣款 自动扣款 免密支付
创建时间 2026-10-19 09:50:39
付款方式 余额宝 >
理由 自动攒
对方账户 支付宝小荷包(合成攒钱计划)
服务详情
支付宝小荷包-自动攒
账单管理
账单分类 账户存取
计入收支'''


@pytest.mark.parametrize('text,amount,kind,stamp', [
    (CHECKOUT, .01, 'expense', ''),
    (DISCOUNT, 5.07, 'expense', '2026-10-12T12:33:16+08:00'),
    (INCOMING, 150, 'income', '2026-10-15T08:51:11+08:00'),
    (ESCROW, 220, 'expense', '2026-10-18T20:39:49+08:00'),
])
def test_alipay_visible_amount_direction_time_and_channel(text, amount, kind, stamp):
    parsed = parse_payment_text(text, accounts=[], default_category='其他支出', channel_account='支付宝')
    draft = parsed['tx_drafts'][0]
    assert (draft['amount'], draft['type'], draft['happened_at'], draft['account_name']) == (amount, kind, stamp, '支付宝')
    assert payment_channel(text) == 'alipay'
    if text == CHECKOUT:
        assert parsed['receipt_kind'] == 'payment_result' and parsed['source_id'] is None
    if text == INCOMING:
        assert parsed['receipt_kind'] == 'personal_incoming'


def test_saving_is_not_a_consumer_expense_even_with_an_explicit_debit():
    with pytest.raises(PaymentTextError, match='小荷包|划转'):
        parse_payment_text(SAVING, accounts=[], channel_account='支付宝')


@pytest.mark.parametrize('text,amount', [
    (CHECKOUT.replace('回首页\n', ''), .01),
    (ESCROW.replace('账单管理', '账单管理 已解锁日用百货贴纸，去兑换好礼 >'), 220),
])
def test_visible_control_omission_and_management_badge_do_not_change_payment_facts(text, amount):
    parsed = parse_payment_text(text, accounts=[], channel_account='支付宝')
    assert parsed['tx_drafts'][0]['amount'] == amount
    assert payment_channel(text) == 'alipay'


def test_checkout_same_row_payee_amount_is_not_a_second_payment_or_part_of_the_name():
    text = CHECKOUT.replace('合成摊位\n￥0.01', '合成摊位 ￥0.01')
    parsed = parse_payment_text(text, accounts=[], channel_account='支付宝')
    assert parsed['tx_drafts'][0]['note'] == '合成摊位'
    with pytest.raises(PaymentTextError):
        parse_payment_text(text.replace('合成摊位 ￥0.01', '合成摊位 ￥0.02'), accounts=[])


def test_visual_crosscheck_uses_paid_header_not_discount_and_ignores_only_the_funding_chevron():
    from src.services.ai.payment_vision import agrees_with_visible_facts
    transcript = DISCOUNT.replace('余额宝 >', '余额宝')
    parsed = parse_payment_text(transcript, accounts=[], channel_account='支付宝')
    assert agrees_with_visible_facts(DISCOUNT, parsed, transcript)
    assert not agrees_with_visible_facts(DISCOUNT + '\n微信支付', parsed, transcript)
    parsed['tx_drafts'][0]['amount'] = 5.50
    assert not agrees_with_visible_facts(DISCOUNT, parsed, transcript)


@pytest.mark.parametrize('text', [
    DISCOUNT.replace('交易成功', '交易失败'), DISCOUNT + '\n退款成功',
    DISCOUNT.replace('-5.07', '-5.50'), DISCOUNT.replace('-0.43', '-0.44'),
    DISCOUNT.replace('-5.07', '+5.07'), DISCOUNT.replace('-5.07', '-5.07\n-2.00'),
    DISCOUNT.replace('2026-10-12', '2026-02-30'), DISCOUNT.replace('-5.07', '-5.O7'),
    DISCOUNT.replace('-5.07', '-5.07 USD'),
    ESCROW.replace('等待确认收货', '等待付款'), ESCROW.replace('订单号 2026101823001198321439467145\n', ''),
    INCOMING.replace('交易成功', '等待收款'),
    CHECKOUT.replace('￥0.01\n交易方式', '￥0.02\n交易方式'),
    CHECKOUT + '\n' + CHECKOUT, DISCOUNT + '\n微信支付',
])
def test_ambiguous_headers_discounts_failure_refund_and_unpaid_statuses_never_turn_into_clear_expenses(text):
    with pytest.raises(PaymentTextError):
        parse_payment_text(text, accounts=[], channel_account='支付宝')


def configure(client, suffix):
    headers, ledger, _, expense, _ = setup_trigger(client, suffix + '@example.invalid')
    account = client.post('/api/v1/write/ledgers/' + ledger + '/accounts', headers=headers,
        json={'base_change_id': 0, 'name': '支付宝', 'account_type': 'alipay', 'currency': 'CNY'}).json()['entity_id']
    income = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
        json={'base_change_id': 0, 'name': '其他收入', 'kind': 'income'}).json()['entity_id']
    config = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel', 'alipay_account_id': account,
        'default_expense_category_id': expense, 'default_income_category_id': income}}}}
    assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
    return headers, ledger, account, expense, income


@pytest.mark.parametrize('text,amount,kind', [(CHECKOUT,.01,'expense'),(DISCOUNT,5.07,'expense'),
                                            (INCOMING,150,'income'),(ESCROW,220,'expense')])
def test_clear_alipay_capture_books_once_without_a_model_and_distinct_runs_remain_distinct(text, amount, kind):
    client = _make_client()
    try:
        headers, ledger, account, expense, income = configure(client, 'alipay-' + kind + str(amount))
        stamp = datetime.now(timezone.utc).isoformat()
        body = {'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred',
                'result_time_policy': 'submission', 'submitted_at': stamp}
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock()) as model:
            first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert first.status_code == 200, first.text
            replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert replay.status_code == 200 and replay.json()['entity_id'] == first.json()['entity_id']
            second = client.post('/api/v1/ai/record-ocr-text', headers=headers,
                json={**body, 'request_id': str(uuid4())})
            assert second.status_code == 200 and second.json()['entity_id'] != first.json()['entity_id']
            assert model.await_count == 0
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 2
        assert all(r['amount'] == amount and r['tx_type'] == kind and r['account_id'] == account
                   and r['category_id'] == (income if kind == 'income' else expense)
                   and not r['exclude_from_stats'] for r in rows)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_explicit_saving_purpose_cannot_be_erased_by_vision_and_creates_no_financial_entry():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-saving')
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={
                'transaction_count': 1, 'text': DISCOUNT})) as model:
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
                'ledger_id': ledger, 'text': SAVING, 'request_id': str(uuid4()), 'review_policy': 'deferred',
                'vision_fallback': True, 'image_base64': IMAGE})
        assert result.status_code == 202 and result.json()['recorded'] is False
        assert model.await_count == 0
        assert client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json() == []
        detail = client.get('/api/v1/ai/ocr-inbox/' + result.json()['capture_id'], headers=headers).json()
        assert '小荷包' in detail['reason'] and detail['draft'] is None
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('text,label', [
    (DISCOUNT, '医疗健康'), (DISCOUNT.replace('账单分类 医疗健康', '账单分类\n医疗健康'), '医疗健康'),
    (ESCROW.replace('账单管理', '账单管理 已解锁日用百货贴纸，去兑换好礼 >'), '日用百货'),
    (DISCOUNT.replace('账单分类 医疗健康\n', ''), ''), (DISCOUNT + '\n账单分类 餐饮美食', ''),
    (CHECKOUT, ''),
])
def test_only_the_single_displayed_alipay_bill_category_is_read(text, label):
    assert parse_payment_text(text, accounts=[], channel_account='支付宝')['visible_category'] == label


def record_discount(client, headers, ledger, text=DISCOUNT):
    return client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
        'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred',
        'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()})


@pytest.mark.parametrize('names,expected', [
    (['医疗'], '医疗'), (['医疗健康', '医疗'], '医疗健康'), (['餐饮'], None), ([], None),
])
def test_displayed_bill_category_maps_to_an_existing_leaf_or_falls_back_to_default(names, expected):
    client = _make_client()
    try:
        headers, ledger, account, default, _ = configure(client, 'alipay-category-' + '-'.join(names))
        created = {name: client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
            json={'base_change_id': 0, 'name': name, 'kind': 'expense'}).json()['entity_id'] for name in names}
        result = record_discount(client, headers, ledger)
        assert result.status_code == 200, result.text
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 5.07 and rows[0]['account_id'] == account
        assert rows[0]['category_id'] == (created[expected] if expected else default)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_a_parent_category_is_not_chosen_and_unlisted_labels_keep_the_default():
    client = _make_client()
    try:
        headers, ledger, _, default, _ = configure(client, 'alipay-category-parent')
        base = '/api/v1/write/ledgers/' + ledger + '/categories'
        client.post(base, headers=headers, json={'base_change_id': 0, 'name': '医疗', 'kind': 'expense'})
        child = client.post(base, headers=headers, json={'base_change_id': 0, 'name': '药品', 'kind': 'expense',
                                                       'level': 2, 'parent_name': '医疗'})
        assert child.status_code == 200, child.text
        client.post(base, headers=headers, json={'base_change_id': 0, 'name': '转账红包', 'kind': 'expense'})
        assert record_discount(client, headers, ledger).status_code == 200
        assert record_discount(client, headers, ledger,
                               DISCOUNT.replace('医疗健康', '转账红包')).status_code == 200
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 2 and all(row['category_id'] == default for row in rows)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_unclear_alipay_date_uses_vision_then_keeps_one_provisional_entry_with_the_paid_header():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'alipay-vision-bridge')
        config = client.get('/api/v1/profile/me', headers=headers).json()['ai_config']
        config.update(providers=[{'id': 'synthetic', 'baseUrl': 'https://example.invalid/v4',
                                  'apiKey': 'synthetic-key', 'visionModel': 'glm-4.6v-flashx'}],
                      binding={'visionProviderId': 'synthetic'})
        assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200
        body = {'ledger_id': ledger, 'text': DISCOUNT.replace('12:33:16', '12:3?:16'),
                'request_id': str(uuid4()), 'review_policy': 'deferred', 'vision_fallback': True,
                'image_base64': IMAGE}
        with patch('src.services.ai.payment_vision.call_chat_json', AsyncMock(return_value={
                'transaction_count': 1, 'text': DISCOUNT.replace('余额宝 >', '余额宝')})) as model:
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert result.status_code == 202 and result.json()['entity_id'], result.text
            replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
            assert replay.status_code == 202 and replay.json()['entity_id'] == result.json()['entity_id']
            assert model.await_count == 1
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == 5.07 and rows[0]['tx_type'] == 'expense'
        assert rows[0]['account_name'] == '支付宝' and rows[0]['exclude_from_stats'] is True
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers,
                          params={'ledger_id': ledger}).json()['pending_total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

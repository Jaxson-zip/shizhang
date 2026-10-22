"""Automatic OCR categories use only the user's existing leaves and never block booking."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_alipay_receipts import DISCOUNT, configure

from src.main import app
from src.services.payment_rules import keyword_category


@pytest.mark.parametrize('texts,names,expected', [
    (['合成药店'], {'医疗'}, '医疗'),
    (['瑞幸咖啡(合成店)'], {'餐饮', '医疗'}, '餐饮'),
    (['合成摊位', '一杯咖啡'], {'餐饮'}, '餐饮'),               # product line, not only merchant
    (['合成药店'], {'餐饮'}, ''),                               # no such category: nothing guessed
    (['超市里的药店'], {'医疗', '日用'}, ''),                    # two rules disagree: ambiguous
    (['合成商户'], {'餐饮', '医疗'}, ''),
    ([''], {'餐饮'}, ''),
])
def test_keyword_rules_pick_one_existing_category_or_nothing(texts, names, expected):
    assert keyword_category(texts, lambda name: name in names) == expected


def record(client, headers, ledger, text=DISCOUNT):
    response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
        'ledger_id': ledger, 'text': text, 'request_id': str(uuid4()), 'review_policy': 'deferred',
        'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()})
    assert response.status_code == 200, response.text
    return response.json()


def category(client, headers, ledger, name):
    return client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
        json={'base_change_id': 0, 'name': name, 'kind': 'expense'}).json()['entity_id']


def rows(client, headers, ledger):
    return client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()


def test_keyword_category_applies_when_the_page_shows_no_bill_category():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'category-keyword')
        medical = category(client, headers, ledger, '医疗')
        record(client, headers, ledger, DISCOUNT.replace('账单分类 医疗健康\n', ''))
        assert rows(client, headers, ledger)[0]['category_id'] == medical
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_a_manual_correction_is_remembered_for_the_same_merchant_over_bill_category_and_keywords():
    client = _make_client()
    try:
        headers, ledger, _, default, _ = configure(client, 'category-memory')
        medical, daily = category(client, headers, ledger, '医疗'), category(client, headers, ledger, '日用')
        first = record(client, headers, ledger)
        assert rows(client, headers, ledger)[0]['category_id'] == medical
        corrected = client.patch('/api/v1/write/ledgers/' + ledger + '/transactions/' + first['entity_id'],
            headers=headers, json={'base_change_id': 0, 'expected_change_id': first['new_change_id'],
                                   'category_id': daily})
        assert corrected.status_code == 200, corrected.text
        second = record(client, headers, ledger)
        by_id = {row['id']: row for row in rows(client, headers, ledger)}
        assert by_id[second['entity_id']]['category_id'] == daily
        # Moving the merchant back to the default clears the memory; later tiers apply again.
        latest = client.patch('/api/v1/write/ledgers/' + ledger + '/transactions/' + second['entity_id'],
            headers=headers, json={'base_change_id': 0, 'expected_change_id': second['new_change_id'],
                                   'category_id': default})
        assert latest.status_code == 200, latest.text
        third = record(client, headers, ledger)
        by_id = {row['id']: row for row in rows(client, headers, ledger)}
        assert by_id[third['entity_id']]['category_id'] == medical
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_a_deleted_remembered_category_falls_back_without_blocking_booking():
    client = _make_client()
    try:
        headers, ledger, _, default, _ = configure(client, 'category-memory-deleted')
        temporary = category(client, headers, ledger, '临时分类')
        first = record(client, headers, ledger)
        assert client.patch('/api/v1/write/ledgers/' + ledger + '/transactions/' + first['entity_id'],
            headers=headers, json={'base_change_id': 0, 'expected_change_id': first['new_change_id'],
                                   'category_id': temporary}).status_code == 200
        # A sibling leaf under the remembered name makes it a parent, so it is no longer usable.
        child = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers, json={
            'base_change_id': 0, 'name': '临时子类', 'kind': 'expense', 'level': 2, 'parent_name': '临时分类'})
        assert child.status_code == 200, child.text
        second = record(client, headers, ledger)
        by_id = {row['id']: row for row in rows(client, headers, ledger)}
        assert by_id[second['entity_id']]['category_id'] == default
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('origin', ['other_ledger', 'income', 'excluded'])
def test_merchant_memory_does_not_learn_from_unrelated_or_unconfirmed_entries(origin):
    client = _make_client()
    try:
        headers, ledger, account, _, _ = configure(client, 'memory-boundary-' + origin)
        medical = category(client, headers, ledger, '医疗')
        daily = category(client, headers, ledger, '日用')
        source_ledger = ledger
        source_category = daily
        if origin == 'other_ledger':
            created = client.post('/api/v1/write/ledgers', headers=headers, json={
                'base_change_id': 0, 'ledger_name': 'Synthetic unrelated ledger', 'currency': 'CNY'})
            assert created.status_code == 200, created.text
            source_ledger = created.json()['ledger_id']
        elif origin == 'income':
            created = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
                json={'base_change_id': 0, 'name': '合成收入', 'kind': 'income'})
            assert created.status_code == 200, created.text
            source_category = created.json()['entity_id']
        seeded = client.post('/api/v1/write/ledgers/' + source_ledger + '/transactions', headers=headers,
            json={'base_change_id': 0, 'tx_type': 'income' if origin == 'income' else 'expense',
                  'amount': 1, 'happened_at': datetime.now(timezone.utc).isoformat(),
                  'account_id': account, 'category_id': source_category, 'note': '合成药店',
                  'exclude_from_stats': origin == 'excluded',
                  'exclude_from_budget': origin == 'excluded'})
        assert seeded.status_code == 200, seeded.text
        result = record(client, headers, ledger)
        by_id = {row['id']: row for row in rows(client, headers, ledger)}
        assert by_id[result['entity_id']]['category_id'] == medical
        assert by_id[result['entity_id']]['amount'] == 5.07
        assert by_id[result['entity_id']]['tx_type'] == 'expense'
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_explicit_shortcut_category_wins_and_transport_replay_keeps_one_entry():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'category-explicit-replay')
        category(client, headers, ledger, '医疗')
        daily = category(client, headers, ledger, '日用')
        body = {'ledger_id': ledger, 'text': DISCOUNT, 'category_id': daily,
                'request_id': str(uuid4()), 'review_policy': 'deferred',
                'result_time_policy': 'submission', 'submitted_at': datetime.now(timezone.utc).isoformat()}
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert first.status_code == 200, first.text
        replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert replay.status_code == 200, replay.text
        assert replay.json()['entity_id'] == first.json()['entity_id']
        saved = rows(client, headers, ledger)
        assert len(saved) == 1 and saved[0]['category_id'] == daily
    finally:
        client.close()
        app.dependency_overrides.clear()


# BeeCount's own "two-level" default expense tree (zh), parents excluded: only leaves are usable.
# Source: upstream mobile seed (hierarchical mode). Parents such as 餐饮/交通/娱乐/教育 have children.
BEECOUNT_TWO_LEVEL_LEAVES = {
    '早餐', '午餐', '晚餐', '美团外卖', '饿了么外卖', '京东外卖', '餐厅', '美食',
    '奶茶', '咖啡', '果汁', '汽水', '矿泉水', '服装', '鞋帽', '包包', '配饰', '日用百货',
    '地铁', '公交', '出租车', '网约车', '停车费', '加油',
    '学费', '培训费', '书籍', '文具', '办公用品', '电影', 'KTV', '游乐场', '酒吧', '其他娱乐',
    '护肤品', '化妆品', '美容美发', '美甲', '其他支出',
}
# BeeCount's flat default list keeps one level; earlier behaviour there must not change.
BEECOUNT_FLAT = {'餐饮', '交通', '购物', '娱乐', '医疗', '教育', '通讯', '美容', '外卖', '打车', '地铁',
                 '停车', '饮料', '快递', '日用品'}


@pytest.mark.parametrize('texts,expected', [
    (['瑞幸咖啡(合成店)'], '咖啡'),
    (['合成奶茶店', '蜜雪冰城'], '奶茶'),
    (['合成面馆'], '美食'),
    (['美团外卖'], '美团外卖'),          # the longer keyword wins over the generic 外卖
    (['饿了么'], '饿了么外卖'),
    (['合成地铁', '地铁乘车'], '地铁'),
    (['滴滴出行'], '网约车'),
    (['合成加油站'], '加油'),
    (['合成影城'], '电影'),
    (['合成培训'], '培训费'),
    (['合成超市'], '日用百货'),
    (['合成药店'], ''),                  # no medical leaf in that tree: still nothing guessed
    (['咖啡餐厅'], ''),                  # two different leaves: ambiguous, falls back
])
def test_keyword_rules_reach_leaves_of_a_two_level_tree(texts, expected):
    assert keyword_category(texts, lambda name: name in BEECOUNT_TWO_LEVEL_LEAVES) == expected


@pytest.mark.parametrize('texts,expected', [
    (['瑞幸咖啡(合成店)'], '餐饮'), (['美团外卖'], '餐饮'), (['滴滴出行'], '交通'),
    (['合成影城'], '娱乐'), (['合成培训'], '教育'), (['合成药店'], '医疗'),
])
def test_flat_default_categories_keep_their_previous_choice(texts, expected):
    assert keyword_category(texts, lambda name: name in BEECOUNT_FLAT) == expected


def test_alipay_bill_category_reaches_a_two_level_leaf():
    from src.services.alipay_rules import CATEGORY_CANDIDATES
    usable = BEECOUNT_TWO_LEVEL_LEAVES.__contains__
    assert next(name for name in CATEGORY_CANDIDATES['餐饮美食'] if usable(name)) == '美食'
    assert next(name for name in CATEGORY_CANDIDATES['休闲娱乐'] if usable(name)) == '其他娱乐'


def test_captured_coffee_uses_the_leaf_under_a_parent_category():
    client = _make_client()
    try:
        headers, ledger, *_ = configure(client, 'category-two-level')
        for parent, children in (('饮品', ('奶茶', '咖啡')), ('餐饮', ('美食',))):
            category(client, headers, ledger, parent)
            for child in children:
                made = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers, json={
                    'base_change_id': 0, 'name': child, 'kind': 'expense', 'level': 2, 'parent_name': parent})
                assert made.status_code == 200, made.text
        coffee = next(row['id'] for row in client.get('/api/v1/read/ledgers/' + ledger + '/categories',
                      headers=headers).json() if row['name'] == '咖啡')
        text = DISCOUNT.replace('合成药店', '瑞幸咖啡(合成店)').replace('账单分类 医疗健康\n', '')
        result = record(client, headers, ledger, text)
        by_id = {row['id']: row for row in rows(client, headers, ledger)}
        assert by_id[result['entity_id']]['category_id'] == coffee
        assert len(by_id) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Vision must not be skipped/rejected because of service actions or OCR labels."""
from unittest.mock import AsyncMock, patch

import pytest
from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_trigger import setup_trigger
from test_ocr_vision_fallback import IMAGE

from src.main import app
from src.services.ai.payment_vision import agrees_with_visible_facts
from src.services.payment_rules import parse_payment_text


@pytest.mark.parametrize('case', ['field-label', 'refund-action'])
def test_missing_merchant_can_use_visual_fallback_despite_ocr_layout_or_service_action(case):
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-route-'+case+'@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        original = body['text']
        uncertain = original.replace('商家名称:', '读不清字段:')
        if case == 'field-label':
            uncertain = uncertain.replace('付款方式:零钱', '付款方式\n交易单号\n零钱')
        else:
            uncertain += '\n账单服务\n申请退款\n联系商家'
        body.update(text=uncertain, review_policy='deferred', vision_fallback=True, image_base64=IMAGE)
        model = AsyncMock(return_value={'text': original, 'transaction_count': 1})
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert model.await_count == 1
        assert result.status_code == 202 and result.json()['entity_id'], result.text
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == .01 and rows[0]['tx_type'] == 'expense'
        assert rows[0]['exclude_from_stats'] is True
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('tail', ['申请退款', '账单服务\n退款成功', '账单服务\n申请退款\n支付失败'])
def test_refund_or_failure_evidence_outside_exact_action_still_blocks_model(tail):
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'vision-negative-'+str(len(tail))+'@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me', headers=headers).json()['user_id'])
        body.update(text=body['text'].replace('商家名称:', '读不清字段:')+'\n'+tail,
                    review_policy='deferred', vision_fallback=True, image_base64=IMAGE)
        model = AsyncMock()
        with patch('src.services.ai.payment_vision.call_chat_json', model):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert model.await_count == 0
        assert result.status_code == 202 and not result.json().get('entity_id')
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_complete_column_table_still_preserves_known_funding_when_vision_changes_it():
    from test_ocr_service_actions import SCAN_HINT_COLUMNS
    recovered_text = '''微信支付
支付成功
实付金额:￥1.00
商家名称:合成商家
支付方式:余额
支付时间:2026年10月18日 09:02:46
'''
    draft = parse_payment_text(recovered_text, accounts=[])
    assert not agrees_with_visible_facts(SCAN_HINT_COLUMNS, draft, recovered_text)
    same = recovered_text.replace('余额', '零钱')
    assert agrees_with_visible_facts(SCAN_HINT_COLUMNS, parse_payment_text(same, accounts=[]), same)

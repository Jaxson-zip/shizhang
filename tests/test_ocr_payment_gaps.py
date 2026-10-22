"""Synthetic reproductions of the three post-reset WeChat gaps; no real bill data."""
from unittest.mock import AsyncMock, patch

import pytest
from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_trigger import setup_trigger
from test_ocr_vision_fallback import IMAGE

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text, payment_channel

CAMPUS = '''账单
全部账单
合成校园大学
-20.00
当前状态
支付时间
商品
商户全称
收单机构
支付方式
交易单号
商户单号
支付成功
2026年10月17日 15:22:19
0vD1cr:17921353317140098745;卡通充值合成校园大学
财付通支付科技有限公司
零钱
4500000573202610167591920627
2610160000011416132010070902023
商家小程序
合成一卡通>
账单服务
对订单有疑惑
'''

MERCHANT = '''服务
交易详情
-12.99
合成外卖
当前状态
支付时间
商品
收单机构
支付方式
交易单号
商户单号
支付成功
2026年10月17日 18:21:00
合成商品
北京钱袋宝支付技术有限公司
零钱
4500000578202610156310088765
20261015182052U72791888282737456
交易服务
对订单有疑惑
发起群收款
'''

QR = '''交易详情
-3.00
扫二维码付款-给合成收款人
当前状态
收款方备注
支付方式
转账时间
转账单号
支付成功
二维码收款
零钱
2026#1017E 18:58:41
10001073012026101701351128065516
交易服务
本服务由财付通提供
'''


@pytest.mark.parametrize('text,amount', [(CAMPUS,20),(MERCHANT,12.99)])
def test_complete_bounded_wechat_receipts_book_without_model_or_review(text, amount):
    client = _make_client()
    try:
        headers,ledger,account,category,body=setup_trigger(client,'gaps-'+str(amount)+'@example.invalid')
        cfg={'ocr_rules':{'ledgers':{ledger:{'accounting_mode':'channel','wechat_account_id':account,
            'default_expense_category_id':category,'campus_topup_as_expense':True}}}}
        assert client.patch('/api/v1/profile/me',headers=headers,json={'ai_config':cfg}).status_code==200
        body.update(text=text,review_policy='deferred')
        with patch('src.services.ai.payment_vision.call_chat_json',AsyncMock()) as model:
            response=client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body)
        assert response.status_code==200,response.text
        assert model.await_count==0
        rows=client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert len(rows)==1 and rows[0]['amount']==amount and rows[0]['tx_type']=='expense'
        assert rows[0]['account_id']==account and rows[0]['exclude_from_stats'] is False
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_qr_bad_date_reports_date_problem_and_never_guesses_calendar():
    with pytest.raises(PaymentTextError,match='时间|日期'):
        parse_payment_text(QR,accounts=[])


@pytest.mark.parametrize('code,word',[('1113','余额不足'),('1305','繁忙')])
def test_failed_visual_read_explains_provider_failure_instead_of_only_asking_user_to_review(code,word):
    from src.services.ai.provider_client import ChatProviderError
    client=_make_client()
    try:
        headers,ledger,_,_,body=setup_trigger(client,'gaps-error-'+code+'@example.invalid')
        _seed_ai_config(client.get('/api/v1/profile/me',headers=headers).json()['user_id'])
        body.update(text=QR,review_policy='deferred',vision_fallback=True,image_base64=IMAGE)
        error=ChatProviderError('synthetic private upstream body omitted')
        error.status_code=429
        error.provider_code=code
        with patch('src.services.ai.payment_vision.call_chat_json',AsyncMock(side_effect=error)):
            response=client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body)
        assert response.status_code==202 and not response.json().get('entity_id')
        detail=client.get('/api/v1/ai/ocr-inbox/'+response.json()['capture_id'],headers=headers).json()
        assert word in detail['reason']
        assert 'synthetic private' not in detail['reason']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()==[]
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_new_template_does_not_identify_arbitrary_wallet_text_or_cross_channel_receipt():
    assert payment_channel('支付成功\n支付方式 零钱') is None
    assert payment_channel(MERCHANT.replace('交易服务','未知服务')) is None
    assert payment_channel(MERCHANT+'\n支付宝') is None


@pytest.mark.parametrize('text', [CAMPUS.replace('合成校园大学\n-20.00','另一个合成学校\n-20.00'),
    CAMPUS.replace('合成一卡通>','其他充值>'),CAMPUS.replace('支付成功','支付失败')])
def test_campus_recovery_needs_exact_duplicate_title_and_card_context(text):
    with pytest.raises(PaymentTextError):
        parse_payment_text(text,accounts=[],campus_topup_as_expense=True)


def test_real_provider_error_retains_safe_code_without_secret_response_text():
    import asyncio

    import httpx

    from src.services.ai.provider_client import (
        ChatProviderConfig,
        ChatProviderError,
        call_chat_json,
    )

    async def fake_post(self, url, **kwargs):
        return httpx.Response(429,json={'error':{'code':'1113','message':'synthetic secret must not persist'}})
    cfg=ChatProviderConfig(provider_id='synthetic',base_url='https://example.invalid/v4',api_key='synthetic-key',model='glm-4.6v-flashx')
    with patch('httpx.AsyncClient.post',fake_post), pytest.raises(ChatProviderError) as caught:
        asyncio.run(call_chat_json(config=cfg,messages=[{'role':'user','content':'synthetic'}],max_retries=0,redact_content=True))
    assert caught.value.provider_code=='1113' and caught.value.status_code==429
    assert 'secret' not in str(caught.value) and 'synthetic-key' not in str(caught.value)

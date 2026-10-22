"""Anonymous screenshot-layout reconstructions; these are not device OCR text."""
import pytest

from src.services.payment_rules import PaymentTextError, parse_payment_text

QR_BILL = '''账单
全部账单
扫二维码付款-给合成收款人
-1.23
当前状态 支付成功
收款方备注 二维码收款
支付方式 零钱
转账时间 2026年10月17日 10:01:02
转账单号 QRTEST000000012345
账单服务
对订单有疑惑
申请电子凭证'''

MERCHANT_BILL = '''账单
全部账单
合成面点店
-2.34
当前状态 支付成功
支付时间 2026年10月17日 10:02:03
商品 合成面点店
商户全称 合成餐饮经营部
收单机构 合成支付机构
支付方式 零钱
交易单号 SALE000000012345
商户单号 SHOP000000012345
商家小程序
收钱入口
账单服务
在此商户的交易
申请电子凭证'''

MERCHANT_CHAT = '''合成茶饮店
留言
首页
交易详情
-3.45
合成茶饮店
当前状态 支付成功
收单机构 合成支付机构
支付时间 2026年10月17日 10:03:04
支付方式 零钱
交易单号 CHAT000000012345
经营单号 TRADE000000012345
交易服务
对订单有疑惑
发起群收款'''

CAMPUS_BILL = MERCHANT_BILL.replace('合成面点店', '合成学校').replace('合成餐饮经营部', '合成学校').replace('商品 合成学校', '商品 SYNTHETIC-ITEM;一卡通充值')

PLATFORM_CHAT = '''合成外卖平台
喜欢
小程序
服务
交易详情
-4.56
合成外卖平台
当前状态 支付成功
支付时间 2026年10月17日 10:04:05
商品 合成饮品-合成平台App-
PRODUCT00000012345
收单机构 合成支付机构
支付方式 零钱
交易单号 PLATFORM00000012345
商户单号 SHOP000000012345
交易服务
在此商户的交易
申请电子凭证'''


@pytest.mark.parametrize('text, amount, name', [
    (QR_BILL, 1.23, '合成收款人'),
    (MERCHANT_BILL, 2.34, '合成餐饮经营部'),
    (MERCHANT_CHAT, 3.45, '合成茶饮店'),
    (MERCHANT_CHAT+'\n商户全称合成茶饮经营部', 3.45, '合成茶饮经营部'),
    (CAMPUS_BILL, 2.34, '合成学校'),
    (PLATFORM_CHAT, 4.56, '合成外卖平台'),
])
def test_supplied_consumer_layout_family_keeps_payment_facts(text, amount, name):
    result = parse_payment_text(text, accounts=[('微信零钱','CNY')],
                                funding_aliases={'零钱':'微信零钱'}, campus_topup_as_expense=True)
    draft = result['tx_drafts'][0]
    assert draft['amount'] == amount and draft['note'] == name
    assert draft['account_name'] == '微信零钱' and draft['happened_at'].endswith('+08:00')
    assert result['source_id']


@pytest.mark.parametrize('text', [
    MERCHANT_CHAT+'\n-5.67',
    MERCHANT_CHAT.replace('支付成功', '待支付'),
    MERCHANT_CHAT+'\n退款成功',
    MERCHANT_CHAT.replace('合成茶饮店\n当前状态', '合成茶饮店\n另一合成商户\n当前状态'),
])
def test_display_title_fallback_does_not_hide_ambiguous_or_unpaid_receipts(text):
    with pytest.raises(PaymentTextError):
        parse_payment_text(text, accounts=[])


def test_campus_charge_still_requires_explicit_preference():
    with pytest.raises(PaymentTextError, match='充值'):
        parse_payment_text(CAMPUS_BILL, accounts=[])

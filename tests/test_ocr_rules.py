"""OCR text uses the native parse/review/write path without model configuration."""
from datetime import datetime, timedelta, timezone

import pytest
from test_ai_parse_tx import _make_client, _register_and_login

from src.main import app
from src.services.payment_rules import PaymentTextError, parse_payment_text

RECEIPT = """微信支付
支付成功
实付金额
￥18.60
商家名称
测试咖啡店
付款方式
零钱
交易时间
2026-10-15 09:20:30
交易单号
420000TEST000001
"""


def test_rules_parse_does_not_require_configured_model():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-rules@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/v1/write/ledgers", headers=headers,
                              json={"base_change_id": 0, "ledger_name": "OCR test", "currency": "CNY"})
        assert created.status_code == 200, created.text
        response = client.post("/api/v1/ai/parse-tx-text", headers=headers,
                               json={"text": RECEIPT, "engine": "rules", "ledger_id": created.json()["ledger_id"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["engine"] == "rules"
        draft = result["tx_drafts"][0]
        assert draft["amount"] == 18.60
        assert draft["currency"] == "CNY"
        assert draft["note"] == "测试咖啡店"
        assert draft["happened_at"] == "2026-10-15T09:20:30+08:00"
        assert result["requires_confirmation"] is True
    finally:
        app.dependency_overrides.clear()


def test_one_unlabelled_rmb_amount_on_success_page():
    result = parse_payment_text(RECEIPT.replace("实付金额\n", ""), accounts=[("微信零钱", "CNY")])
    assert result["tx_drafts"][0]["amount"] == 18.60
    assert result["tx_drafts"][0]["account_name"] == "微信零钱"


# Synthetic reconstruction of the visible iPhone failure, not a transcription
# of the user's complete private payment details.
SIGNED_HEADER_RECEIPT = RECEIPT.replace(
    "支付成功\n实付金额\n￥18.60", "-30.00\n当前状态\n支付成功"
)


@pytest.mark.parametrize("amount", ["-30.00", "-３０．００", "-¥30.00", "¥-30.00"])
def test_success_detail_signed_header_is_expense_magnitude(amount):
    result = parse_payment_text(SIGNED_HEADER_RECEIPT.replace("-30.00", amount),
                                accounts=[("微信零钱", "CNY")])
    draft = result["tx_drafts"][0]
    assert draft["type"] == "expense"
    assert draft["amount"] == 30.00
    assert draft["account_name"] == "微信零钱"
    assert result["requires_confirmation"] is True


@pytest.mark.parametrize("changed", [
    SIGNED_HEADER_RECEIPT.replace("当前状态\n", ""),
    SIGNED_HEADER_RECEIPT.replace("-30.00", "+30.00"),
    SIGNED_HEADER_RECEIPT.replace("-30.00", "30.00"),
    SIGNED_HEADER_RECEIPT.replace("-30.00", "-0.00"),
    SIGNED_HEADER_RECEIPT.replace("-30.00", "-30.001"),
    SIGNED_HEADER_RECEIPT + "\n-50.00",
    SIGNED_HEADER_RECEIPT + "\n￥50.00",
    SIGNED_HEADER_RECEIPT + "\n-50.00\n当前状态\n支付成功",
    SIGNED_HEADER_RECEIPT.replace("支付成功", "退款成功"),
    SIGNED_HEADER_RECEIPT.replace("支付成功", "转账成功"),
])
def test_signed_header_keeps_ambiguous_income_and_non_expense_blocked(changed):
    with pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[("微信零钱", "CNY")])


# Sanitized structure from the phone report; no real merchant or order IDs.
CAMPUS_TOPUP_RECEIPT = """16:064
账单
86
全部账单
合成校园商户
-30.00
当前状态
支付成功
支付时间
2026年10月15日 12:04:11
商品
测试订单；一卡通充
值
商户全称
合成校园商户
收单机构
财付通支付科技有限公司
支付方式
零钱
交易单号
SYNTHETIC_CAMPUS_0001
商户单号
SYNTHETIC_MERCHANT_0001
商家小程序
测试校园小程序
账单服务
本服务由财付通提供
"""


def test_split_campus_topup_requires_explicit_policy():
    with pytest.raises(PaymentTextError, match="充值"):
        parse_payment_text(CAMPUS_TOPUP_RECEIPT, accounts=[])


def test_explicit_campus_topup_policy_uses_merchant_label_and_spaced_date():
    result = parse_payment_text(CAMPUS_TOPUP_RECEIPT, accounts=[], campus_topup_as_expense=True)
    draft = result["tx_drafts"][0]
    assert draft["amount"] == 30 and draft["type"] == "expense"
    assert draft["note"] == "合成校园商户"
    assert draft["happened_at"] == "2026-10-15T12:04:11+08:00"
    # 财付通 is not sufficient to silently infer a particular user account.
    assert draft["account_name"] == ""
    assert any("重复" in warning for warning in result["warnings"])


@pytest.mark.parametrize("changed", [
    CAMPUS_TOPUP_RECEIPT.replace("一卡通充\n值", "话费充值"),
    CAMPUS_TOPUP_RECEIPT.replace("支付成功", "退款成功"),
    CAMPUS_TOPUP_RECEIPT + "\n转账",
])
def test_campus_topup_policy_does_not_enable_other_topups_or_refunds(changed):
    with pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[], campus_topup_as_expense=True)


def test_merchant_field_does_not_consume_miniprogram_label_prefix():
    text = SIGNED_HEADER_RECEIPT.replace("商家名称\n测试咖啡店", "商户全称\n合成商户\n商家小程序\n另一个名称")
    assert parse_payment_text(text, accounts=[])["tx_drafts"][0]["note"] == "合成商户"
    with pytest.raises(PaymentTextError, match="商家"):
        parse_payment_text(text.replace("商户全称\n合成商户\n", ""), accounts=[])


def test_campus_topup_api_requires_explicit_policy():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-campus@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        ledger = client.post("/api/v1/write/ledgers", headers=headers,
                             json={"base_change_id": 0, "ledger_name": "Synthetic campus", "currency": "CNY"}).json()["ledger_id"]
        body = {"text": CAMPUS_TOPUP_RECEIPT, "ledger_id": ledger, "engine": "rules"}
        assert client.post("/api/v1/ai/parse-tx-text", headers=headers, json=body).status_code == 422
        enabled = client.post("/api/v1/ai/parse-tx-text", headers=headers,
                              json={**body, "campus_topup_as_expense": True})
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["tx_drafts"][0]["amount"] == 30
    finally:
        app.dependency_overrides.clear()


def test_saved_native_profile_defaults_remove_repeated_category_and_wallet_selection():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-defaults@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        ledger = client.post("/api/v1/write/ledgers", headers=headers,
                             json={"base_change_id": 0, "ledger_name": "Synthetic defaults", "currency": "CNY"}).json()["ledger_id"]
        base = f"/api/v1/write/ledgers/{ledger}"
        account = client.post(base + "/accounts", headers=headers,
                              json={"base_change_id": 0, "name": "微信零钱", "account_type": "wechat", "currency": "CNY"}).json()["entity_id"]
        category = client.post(base + "/categories", headers=headers,
                               json={"base_change_id": 0, "name": "其他", "kind": "expense"}).json()["entity_id"]
        config = {"custom_prompt": "Keep existing native configuration", "ocr_rules": {"ledgers": {
            ledger: {"wechat_account_id": account, "default_expense_category_id": category,
                     "campus_topup_as_expense": True},
        }}}
        patched = client.patch("/api/v1/profile/me", headers=headers, json={"ai_config": config})
        assert patched.status_code == 200
        assert client.get("/api/v1/profile/me", headers=headers).json()["ai_config"] == config
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y年%m月%d日 %H:%M:%S")
        text = CAMPUS_TOPUP_RECEIPT.replace("2026年10月15日 12:04:11", stamp)
        body = {"text": text, "ledger_id": ledger, "engine": "rules"}
        response = client.post("/api/v1/ai/parse-tx-text", headers=headers, json=body)
        assert response.status_code == 200, response.text
        draft = response.json()["tx_drafts"][0]
        assert draft["account_name"] == "微信零钱"
        assert draft["category_name"] == "其他"
        # A per-request opt-out beats the saved preference.
        assert client.post("/api/v1/ai/parse-tx-text", headers=headers,
                           json={**body, "campus_topup_as_expense": False}).status_code == 422
        # A wallet alias must never default a different funding source.
        other = client.post("/api/v1/ai/parse-tx-text", headers=headers,
                            json={**body, "text": text.replace("零钱", "未配置银行卡")})
        assert other.status_code == 200 and other.json()["tx_drafts"][0]["account_name"] == ""
        saved = client.post("/api/v1/ai/record-ocr-text", headers=headers,
                            json={"text": text, "ledger_id": ledger})
        assert saved.status_code == 200, saved.text
        replay = client.post("/api/v1/ai/record-ocr-text", headers=headers,
                             json={"text": text, "ledger_id": ledger})
        assert replay.status_code == 200 and replay.json()["entity_id"] == saved.json()["entity_id"]
        # A deleted/stale account ID cannot silently choose another account.
        config["ocr_rules"]["ledgers"][ledger]["wechat_account_id"] = "missing-account"
        assert client.patch("/api/v1/profile/me", headers=headers, json={"ai_config": config}).status_code == 200
        missing = client.post("/api/v1/ai/parse-tx-text", headers=headers, json=body)
        assert missing.status_code == 200 and missing.json()["tx_drafts"][0]["account_name"] == ""
    finally:
        app.dependency_overrides.clear()


def test_shortcut_campus_policy_forwards_to_native_write_and_replay():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-campus-write@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        ledger = client.post("/api/v1/write/ledgers", headers=headers,
                             json={"base_change_id": 0, "ledger_name": "Synthetic campus write", "currency": "CNY"}).json()["ledger_id"]
        base = f"/api/v1/write/ledgers/{ledger}"
        assert client.post(base + "/accounts", headers=headers,
                           json={"base_change_id": 0, "name": "零钱", "account_type": "cash", "currency": "CNY"}).status_code == 200
        assert client.post(base + "/categories", headers=headers,
                           json={"base_change_id": 0, "name": "其他", "kind": "expense"}).status_code == 200
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y年%m月%d日 %H:%M:%S")
        body = {"text": CAMPUS_TOPUP_RECEIPT.replace("2026年10月15日 12:04:11", stamp),
                "ledger_id": ledger, "category_name": "其他"}
        endpoint = "/api/v1/ai/record-ocr-text"
        assert client.post(endpoint, headers=headers, json=body).status_code == 422
        enabled = {**body, "campus_topup_as_expense": True}
        saved = client.post(endpoint, headers=headers, json=enabled)
        assert saved.status_code == 200, saved.text
        replay = client.post(endpoint, headers=headers, json=enabled)
        assert replay.status_code == 200 and replay.json()["idempotency_replayed"] is True
        assert replay.json()["entity_id"] == saved.json()["entity_id"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("changed", [
    RECEIPT.replace("支付成功", status) for status in
    ["支付失败", "等待付款", "退款成功", "转账成功", "未支付", "交易关闭"]
] + [
    RECEIPT.replace("18.60", value) for value in ["0.00", "-18.60", "1.234", "NaN", "1e3"]
] + [
    RECEIPT + "\n实付金额: 28.60",
    RECEIPT.replace("￥18.60", "USD 18.60"),
    RECEIPT.replace("测试咖啡店", ""),
    RECEIPT + "\n商家: 另一家店",
    RECEIPT + "\n支付宝",
])
def test_uncertain_or_non_expense_input_does_not_produce_a_draft(changed):
    with pytest.raises(PaymentTextError):
        parse_payment_text(changed, accounts=[])


def test_discount_uses_actual_paid_and_card_is_not_wallet_balance():
    text = RECEIPT.replace("实付金额\n￥18.60", "原价: 20.00\n优惠: 1.40\n实付金额: ￥18.60")
    text = text.replace("零钱", "招商银行储蓄卡(1234)")
    draft = parse_payment_text(text, accounts=[("微信零钱", "CNY")])["tx_drafts"][0]
    assert draft["amount"] == 18.60
    assert draft["account_name"] == ""


def test_alipay_multiline_and_unicode_punctuation():
    text = RECEIPT.replace("微信支付", "支付宝").replace("零钱", "余额").replace("18.60", "１，２３４．５０")
    result = parse_payment_text(text, accounts=[("支付宝余额", "CNY")])
    assert result["tx_drafts"][0]["amount"] == 1234.50
    assert result["tx_drafts"][0]["account_name"] == "支付宝余额"


def test_missing_date_is_visible_and_source_id_is_not_amount_based():
    missing = RECEIPT.replace("交易时间\n2026-10-15 09:20:30\n", "")
    result = parse_payment_text(missing, accounts=[])
    assert result["tx_drafts"][0]["happened_at"] == ""
    assert any("时间" in warning for warning in result["warnings"])
    assert result["source_id"] == parse_payment_text(RECEIPT, accounts=[])["source_id"]
    other = parse_payment_text(RECEIPT.replace("420000TEST000001", "420000TEST000002"), accounts=[])
    assert other["source_id"] != result["source_id"]


def test_rules_auth_and_ledger_isolation():
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-owner@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        ledger = client.post("/api/v1/write/ledgers", headers=headers,
                             json={"base_change_id": 0, "ledger_name": "Private", "currency": "CNY"}).json()["ledger_id"]
        body = {"text": RECEIPT, "engine": "rules", "ledger_id": ledger}
        assert client.post("/api/v1/ai/parse-tx-text", json=body).status_code == 401
        other, _ = _register_and_login(client, "ocr-other@example.invalid")
        assert client.post("/api/v1/ai/parse-tx-text", json=body,
                           headers={"Authorization": f"Bearer {other}"}).status_code == 404
        assert client.post("/api/v1/ai/parse-tx-text", headers=headers,
                           json={**body, "engine": "typo"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("amount_prefix", ["￥", "* "])
@pytest.mark.parametrize("merchant_layout", ["separate", "joined"])
@pytest.mark.parametrize("order_layout", ["separate", "joined"])
def test_shortcut_record_reuses_native_write_and_same_order_replay(amount_prefix, merchant_layout, order_layout):
    client = _make_client()
    try:
        token, _ = _register_and_login(client, "ocr-shortcut@example.invalid")
        headers = {"Authorization": f"Bearer {token}"}
        ledger = client.post("/api/v1/write/ledgers", headers=headers,
                             json={"base_change_id": 0, "ledger_name": "OCR shortcut", "currency": "CNY"}).json()["ledger_id"]
        base = f"/api/v1/write/ledgers/{ledger}"
        assert client.post(base + "/accounts", headers=headers,
                           json={"base_change_id": 0, "name": "微信零钱", "account_type": "wechat", "currency": "CNY"}).status_code == 200
        assert client.post(base + "/categories", headers=headers,
                           json={"base_change_id": 0, "name": "其他", "kind": "expense"}).status_code == 200
        now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        text = RECEIPT.replace("2026-10-15 09:20:30", now).replace("￥18.60", amount_prefix + "18.60")
        if merchant_layout == "joined":
            text = text.replace("商家名称\n测试咖啡店", "商家名称测试咖啡店")
        order_field = "交易单号\n420000TEST000001"
        if order_layout == "joined":
            text = text.replace(order_field, "交易单号420000TEST000001")
            order_field = "交易单号420000TEST000001"
        body = {"text": text, "ledger_id": ledger, "category_name": "其他"}
        endpoint = "/api/v1/ai/record-ocr-text"
        pat = client.post("/api/v1/profile/pats", headers=headers,
                          json={"name": "OCR shortcut", "scopes": ["mcp:write"], "expires_in_days": 1})
        assert pat.status_code == 201, pat.text
        pat_headers = {"Authorization": f"Bearer {pat.json()['token']}"}
        readonly_pat = client.post("/api/v1/profile/pats", headers=headers,
                                   json={"name": "Read only", "scopes": ["mcp:read"], "expires_in_days": 1})
        assert client.post(endpoint, headers={"Authorization": f"Bearer {readonly_pat.json()['token']}"}, json=body).status_code == 403
        # Preserve upstream PAT/MCP boundary; shortcut uses native JWT login/refresh.
        assert client.post(endpoint, headers=pat_headers, json=body).status_code == 403
        saved = client.post(endpoint, headers=headers, json=body)
        assert saved.status_code == 200, saved.text
        replay = client.post(endpoint, headers=headers, json={**body, "text": text.replace("\n", "\r\n")})
        assert replay.status_code == 200, replay.text
        assert replay.json()["entity_id"] == saved.json()["entity_id"]
        assert replay.json()["idempotency_replayed"] is True
        relabelled = client.post(endpoint, headers=headers, json={
            **body, "text": text.replace(order_field, "交易单号：420000TEST000001"),
        })
        assert relabelled.status_code == 200, relabelled.text
        assert relabelled.json()["entity_id"] == saved.json()["entity_id"]
        assert relabelled.json()["idempotency_replayed"] is True
        changed = client.post(endpoint, headers=headers, json={**body, "text": text.replace("18.60", "28.60")})
        assert changed.status_code == 409
        for invalid in [
            text.replace(order_field, ""),
            # An OCR-dropped label cannot be replaced by guessing a bare ID.
            text.replace(order_field, "420000TEST000001"),
            text.replace(now, "2020-01-01 00:00:00"),
            text.replace("零钱", "未匹配银行卡"),
        ]:
            assert client.post(endpoint, headers=headers, json={**body, "text": invalid}).status_code == 422
        read = client.get(f"/api/v1/read/ledgers/{ledger}/transactions", headers=headers)
        assert read.status_code == 200
        rows = read.json()
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("transactions", []))
        assert len(rows) == 1
        assert rows[0]["amount"] == 18.60
        assert rows[0]["account_name"] == "微信零钱"
        assert rows[0]["category_name"] == "其他"
    finally:
        app.dependency_overrides.clear()

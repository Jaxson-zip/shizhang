"""POST /api/v1/ai/parse-tx-text — B3 文字记账。

设计:.docs/web-cmdk-ai-paste-text.md。

跟 parse-tx-image 同套流程,差别:
- 输入是 JSON body 的 text(不是 multipart image)
- 用 chat provider(textProviderId)而不是 vision
- 不需要缓存(没图)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator
from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.orm import Session

from ...database import get_db
from ...deps import get_current_user, require_any_scopes
from ...ledger_access import ROLE_EDITOR, ROLE_OWNER, require_accessible_ledger_by_external_id
from ...models import (
    ReadTxProjection,
    User,
    UserAccountProjection,
    UserCategoryProjection,
    UserProfile,
)
from ...schemas import WriteTransactionCreateRequest
from ...security import SCOPE_APP_WRITE, SCOPE_WEB_WRITE
from ...services.ai import (
    ChatProviderError,
    JsonParseFailedError,
    NoChatProviderError,
    build_parse_tx_text_messages,
    call_chat_json,
    get_user_custom_prompt,
    resolve_chat_provider,
)
from ...services.ai.payment_vision import (
    MAX_IMAGE_BASE64,
    agrees_with_visible_facts,
    transcribe_payment,
)
from ...services.ocr_capture import (
    OcrCapture,
    capture_ack,
    existing_capture,
    inbox_revision,
    retain_capture,
)
from ...services.payment_rules import (
    PaymentTextError,
    load_ocr_preferences,
    parse_payment_text,
    payment_status_evidence,
)
from ..write._shared import _WRITE_SCOPE_DEP
from ..write.transactions import create_tx
from .parse_tx_image import SchemaInvalidError, _load_ledger_context, _normalize_drafts

logger = logging.getLogger(__name__)
router = APIRouter()

_PARSE_SCOPE_DEP = require_any_scopes(SCOPE_APP_WRITE, SCOPE_WEB_WRITE)

_MAX_TEXT_CHARS = 5000


class ParseTxTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    ledger_id: str | None = None
    locale: str = Field(default="zh", pattern=r"^(zh|zh-CN|zh-TW|en)$")
    engine: Literal["ai", "rules"] = "ai"
    campus_topup_as_expense: bool | None = None


@router.post("/parse-tx-text")
async def parse_tx_text(
    req: ParseTxTextRequest,
    _scopes: set[str] = Depends(_PARSE_SCOPE_DEP),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步返回 `{tx_drafts: [...]}`。"""

    if req.engine == "rules":
        if not req.ledger_id:
            raise HTTPException(status_code=422, detail="请先选择账本")
        ledger, _ = require_accessible_ledger_by_external_id(
            db, user_id=current_user.id, ledger_external_id=req.ledger_id,
        )
        if (ledger.currency or "CNY").upper() != "CNY":
            raise HTTPException(status_code=422, detail="当前 OCR 规则只支持人民币账本")
        _, accounts, _ = _load_ledger_context(db, req.ledger_id, ledger.user_id)
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        prefs = load_ocr_preferences(profile.ai_config_json if profile else None, req.ledger_id)
        account_rows = db.scalars(select(UserAccountProjection).where(
            UserAccountProjection.user_id == ledger.user_id,
            UserAccountProjection.hidden.is_(False),
        )).all()
        aliases = {}
        for label, key in (("零钱", "wechat_account_id"), ("余额", "alipay_account_id")):
            matches = [row for row in account_rows if row.sync_id == prefs.get(key)
                       and (row.currency or "CNY") == "CNY" and (row.name, row.currency) in accounts]
            if len(matches) == 1:
                aliases[label] = matches[0].name
        category_rows = db.scalars(select(UserCategoryProjection).where(
            UserCategoryProjection.user_id == ledger.user_id,
        )).all()
        def unique_leaf(row, kind):
            return (row.kind == kind
                    and not any(child.parent_name == row.name and child.kind == kind for child in category_rows)
                    and sum(cat.name == row.name and cat.kind == kind for cat in category_rows) == 1)

        def default_category_for(kind):
            for row in category_rows:
                if row.sync_id == prefs.get(f"default_{kind}_category_id") and unique_leaf(row, kind):
                    return row.name
            return ""

        def usable(name, kind):
            return any(row.name == name and unique_leaf(row, kind) for row in category_rows)

        def visible_category_for(kind, label):
            # Only the user's own existing leaf; never creates or guesses a category.
            from ...services.alipay_rules import CATEGORY_CANDIDATES
            return next((name for name in CATEGORY_CANDIDATES.get(label or '', ()) if usable(name, kind)), "")

        def remembered_category_for(kind, note):
            # The user's latest counted entry for this exact merchant, so a manual
            # correction applies to the next capture. A default there means "no memory".
            note = (note or '').strip()
            if not note:
                return ""
            latest = db.scalar(select(ReadTxProjection.category_sync_id).where(
                ReadTxProjection.ledger_id == ledger.id, ReadTxProjection.tx_type == kind,
                ReadTxProjection.note == note, ReadTxProjection.exclude_from_stats.is_(False),
                ReadTxProjection.category_sync_id.is_not(None),
            ).order_by(ReadTxProjection.happened_at.desc(), ReadTxProjection.source_change_id.desc()).limit(1))
            if not latest or latest == prefs.get(f"default_{kind}_category_id"):
                return ""
            row = next((row for row in category_rows if row.sync_id == latest), None)
            return row.name if row is not None and unique_leaf(row, kind) else ""
        channel_account = ""
        if prefs.get('accounting_mode') == 'channel':
            from ...services.payment_rules import payment_channel
            channel = payment_channel(req.text)
            matches = [row for row in account_rows if channel and row.sync_id == prefs.get(channel + '_account_id')
                       and (row.currency or 'CNY') == 'CNY' and (row.name, row.currency) in accounts]
            if len(matches) == 1 and sum(row.name == matches[0].name for row in account_rows) == 1:
                channel_account = matches[0].name
        campus_topup = (req.campus_topup_as_expense if req.campus_topup_as_expense is not None
                        else prefs.get("campus_topup_as_expense") is True)
        try:
            parsed = parse_payment_text(req.text, accounts=accounts,
                                      campus_topup_as_expense=campus_topup,
                                      alipay_saving_as_excluded_expense=(prefs.get('accounting_mode') == 'channel'
                                          and prefs.get('alipay_saving_as_excluded_expense') is True),
                                      funding_aliases=aliases, default_category=default_category_for('expense'),
                                      channel_account=channel_account)
            if prefs.get('accounting_mode') == 'channel':
                draft = parsed['tx_drafts'][0]
                # Channel mode must not fall back to a wallet alias when the
                # platform is missing/ambiguous or the selected channel ID is stale.
                draft['account_name'] = channel_account
                # Order: the user's own last choice for this merchant, the bill category
                # the payment app shows, merchant/product keywords, then the default.
                # An unmatched category falls back to the default; it never blocks booking.
                source, chosen = 'default', ''
                if draft['type'] == 'expense' and parsed.get('receipt_kind') not in {
                        'personal_incoming', 'group_payment', 'alipay_saving'}:
                    from ...services.payment_rules import keyword_category
                    products = re.findall(r'(?m)^(?:商品说明|商品)[ \t:：]*(\S.*)$', req.text)
                    tiers = (
                        ('memory', lambda: remembered_category_for('expense', draft['note'])),
                        ('bill_category', lambda: visible_category_for('expense', parsed.get('visible_category'))
                         if parsed.get('receipt_kind') == 'alipay_detail' else ''),
                        ('keyword', lambda: keyword_category([draft['note'], *products],
                                                             lambda name: usable(name, 'expense'))))
                    source, chosen = next(((name, found) for name, tier in tiers if (found := tier())),
                                          ('default', ''))
                draft['category_name'] = chosen or default_category_for(draft['type'])
                parsed['category_source'] = source
                if chosen:
                    parsed['warnings'] = [*parsed.get('warnings', []), {
                        'memory': f"分类沿用你上次给这个商家选的：{chosen}",
                        'bill_category': f"分类按支付宝账单分类「{parsed.get('visible_category')}」采用已有分类：{chosen}",
                        'keyword': f"分类按商家/商品关键词采用已有分类：{chosen}，可在账目中修改",
                    }[source]]
                if parsed.get('receipt_kind') in {'personal_incoming', 'group_payment'}:
                    parsed['warnings'] = ['按简化收支约定采用默认收入/支出分类；借还款或内部划转仍待核对']
            return parsed
        except PaymentTextError as exc:
            raise HTTPException(status_code=422, detail={
                "error_code": "OCR_NEEDS_CONFIRMATION", "message": str(exc),
            }) from exc

    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    try:
        chat_cfg = resolve_chat_provider(current_user, profile)
    except NoChatProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "AI_NO_CHAT_PROVIDER", "message": str(exc)},
        )

    cats, accts, ledger_currency = _load_ledger_context(db, req.ledger_id, current_user.id)
    logger.debug(
        "ai.parse_tx_text ledger_context cats=%d accts=%d base=%s sample_cats=%s",
        len(cats), len(accts), ledger_currency, cats[:10],
    )

    custom = get_user_custom_prompt(profile, key="parseTxTextPrompt")
    messages = build_parse_tx_text_messages(
        text=req.text,
        categories=cats,
        accounts=accts,
        ledger_currency=ledger_currency,
        now=datetime.now(timezone.utc),
        locale=req.locale,
        custom_prompt_template=custom,
    )

    logger.info(
        "ai.parse_tx_text user=%s lang=%s text_len=%d provider=%s",
        current_user.id, req.locale, len(req.text), chat_cfg.provider_id,
    )

    try:
        result = await call_chat_json(config=chat_cfg, messages=messages)
    except JsonParseFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "AI_PARSE_FAILED",
                "message": str(exc)[:200],
                "raw": exc.raw_content[:1000],
            },
        )
    except ChatProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "AI_PROVIDER_ERROR", "message": str(exc)[:200]},
        )

    try:
        drafts = _normalize_drafts(result)
    except SchemaInvalidError as exc:
        import json as _json
        raw_dump = _json.dumps(result, ensure_ascii=False)[:1000]
        logger.warning(
            "ai.parse_tx_text schema invalid: %s; raw=%s",
            exc, raw_dump,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "AI_SCHEMA_INVALID",
                "message": str(exc),
                "raw": raw_dump,
            },
        )
    return {"tx_drafts": drafts}


class RecordOcrTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)
    ledger_id: str = Field(min_length=1, max_length=255)
    # Explicit shortcut configuration; never inferred from the merchant.
    category_name: str | None = Field(default=None, min_length=1, max_length=255)
    campus_topup_as_expense: bool | None = None
    allow_review: bool = False
    # Generated once by the Shortcut for each intentional run, reused only
    # when that same operation is retried. Legacy shortcuts remain compatible.
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{20,100}$")
    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: str | None = Field(default=None, min_length=1, max_length=255)
    captured_at: AwareDatetime | None = None
    confirm_capture_time: bool = False
    confirm_result_expense: bool = False
    result_time_policy: Literal["confirm_capture", "submission"] = "confirm_capture"
    submitted_at: AwareDatetime | None = None
    review_policy: Literal['immediate', 'deferred'] = 'immediate'
    vision_fallback: bool = False
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_BASE64, repr=False)

    @model_validator(mode="wrap")
    @classmethod
    def log_rejected_fields(cls, value, handler):
        try:
            return handler(value)
        except ValidationError as exc:
            # Field names and Pydantic codes only. Never log rejected inputs,
            # OCR text, ledger values, validation context or credentials.
            issues = [
                {"field": error["loc"][0] if error["loc"] and error["loc"][0] in cls.model_fields else "request",
                 "type": error["type"]}
                for error in exc.errors(include_input=False, include_context=False, include_url=False)
            ]
            logger.warning("ocr.record.validation_rejected issues=%s", json.dumps(issues))
            raise


@router.post("/record-ocr-text")
async def record_ocr_text(
    req: RecordOcrTextRequest,
    request: Request,
    _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Device OCR -> rules -> native write, with strict unattended-write guards.

    Twelve-hour freshness is narrower than native 24h idempotency retention.
    Old/ambiguous receipts remain review-only; this endpoint creates no auth,
    storage, sync, worker, or idempotency infrastructure of its own.
    """
    ledger, _ = require_accessible_ledger_by_external_id(
        db, user_id=current_user.id, ledger_external_id=req.ledger_id,
        roles={ROLE_OWNER, ROLE_EDITOR},
    )
    deferred = req.review_policy == 'deferred'
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    preferences = load_ocr_preferences(profile.ai_config_json if profile else None, req.ledger_id)
    simple_auto = deferred and preferences.get('accounting_mode') == 'channel'
    saving_enabled = simple_auto and preferences.get('alipay_saving_as_excluded_expense') is True
    if req.vision_fallback and (not deferred or not req.request_id or not req.image_base64):
        raise HTTPException(status_code=422, detail='视觉兜底需要截图、采集编号及稍后核对模式')
    from ...services.payment_rules import payment_channel
    # Structural diagnostics only: enums, field labels and flags. Never OCR text,
    # amounts, names, dates or identifiers, so failures can be located later.
    diag = {'v': 1, 'channel': payment_channel(req.text) or 'unknown', 'layout': '', 'stage': '',
            'missing': [], 'vision': 'not_needed' if req.vision_fallback else 'disabled', 'flags': []}

    def with_diag(draft):
        logger.info('ocr.capture.diag %s', json.dumps(diag, ensure_ascii=False))
        return {**(draft or {}), '_diag': dict(diag)}

    async def resume_auto(row):
        if row.receipt is not None:
            return JSONResponse(status_code=200, content={**row.receipt, 'idempotency_replayed': True})
        return await create_tx(ledger_id=req.ledger_id,
            req=WriteTransactionCreateRequest.model_validate(row.draft['_auto_request']),
            request=request, idempotency_key='ocr-review-'+row.id, device_id='ocr-rules',
            _scopes=_scopes, current_user=current_user, db=db)

    if deferred:
        if not req.request_id:
            raise HTTPException(status_code=422, detail='稍后核对需要本次采集编号')
        previous = existing_capture(db, current_user.id, ledger.id, req)
        if previous is not None:
            if (previous.draft or {}).get('_auto_request'):
                return await resume_auto(previous)
            return JSONResponse(status_code=202, content=capture_ack(previous))

    async def rules(text):
        return await parse_tx_text(
            ParseTxTextRequest(text=text, ledger_id=req.ledger_id, engine="rules",
                               campus_topup_as_expense=req.campus_topup_as_expense),
            _scopes=_scopes, current_user=current_user, db=db)

    from ...services.ai.payment_vision import visual_failure_reason
    vision_failure = ''

    async def try_vision(original):
        nonlocal vision_failure
        if not req.vision_fallback:
            return None
        from ...services.alipay_rules import alipay_internal_reason
        diag['vision'] = 'blocked'
        if alipay_internal_reason(req.text) and not saving_enabled:
            return None  # A model cannot decide whether moving savings is consumption.
        # A second reader must not erase explicit failure, refund or foreign
        # currency evidence, nor contradict known financial facts.
        compact = re.sub(r'\s+', '', payment_status_evidence(req.text))
        if re.search(r'(?m)^(?:入账未通过$|服务器返回[:：]|请先核对账本)', req.text):
            return None
        if re.search(r'支付失败|付款失败|交易失败|待支付|待付款|未支付|交易关闭|退款|已退还|已退回|USD|EUR|HKD|JPY|美元|欧元|港币|日元|\$|€', compact, re.I):
            return None
        if original and original.get('receipt_kind') in {'personal_incoming', 'group_payment'}:
            facts = original['tx_drafts'][0]
            if facts['happened_at'] and (facts['account_name'] or req.account_id) and not (
                    simple_auto and (original.get('evidence') or {}).get('amount_symbol_repaired')):
                return None  # A model cannot discover the user's financial purpose.
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        try:
            text = await transcribe_payment(req.image_base64, current_user, profile)
            recovered = await rules(text)
        except (ChatProviderError, ValueError, HTTPException) as exc:
            if isinstance(exc, HTTPException) and exc.status_code != 422:
                raise
            logger.info('ocr.vision_fallback_unresolved kind=%s', type(exc).__name__)
            diag['vision'] = 'rules_rejected' if isinstance(exc, HTTPException) else 'failed:' + type(exc).__name__
            vision_failure = visual_failure_reason(exc)
            return None
        diag['vision'] = 'conflict'
        diag['vision_layout'] = recovered.get('receipt_kind') or 'unknown'
        if not agrees_with_visible_facts(req.text, recovered, text):
            vision_failure = '视觉补读与已明确的金额、方向、时间或付款方式不一致'
            return None
        if alipay_internal_reason(req.text) and recovered.get('receipt_kind') != 'alipay_saving':
            vision_failure = '视觉补读未保留小荷包资金划转用途'
            return None
        if original is not None:
            before, after = original['tx_drafts'][0], recovered['tx_drafts'][0]
            if before['type'] != after['type'] or before['amount'] != after['amount']:
                return None
            for field in ('happened_at', 'account_name'):
                if before[field] and before[field] != after[field]:
                    return None
            if original.get('receipt_kind') in {'personal_incoming', 'group_payment'}:
                if recovered.get('receipt_kind') != original['receipt_kind']:
                    return None
        diag['vision'] = 'recovered'
        return recovered

    async def process(parsed, from_vision=False):
        draft = parsed["tx_drafts"][0]
        if not from_vision:
            diag['layout'] = parsed.get('receipt_kind') or 'unknown'
        diag['flags'] = sorted(key for key, value in (parsed.get('evidence') or {}).items() if value is True)
        diag['empty'] = [key for key in ('happened_at', 'account_name', 'category_name', 'note') if not draft.get(key)]
        diag['category_source'] = parsed.get('category_source', 'none')

        def mark(stage, missing=()):
            # The OCR stage stays as first observed; a vision pass records its own.
            diag['vision_stage' if from_vision else 'stage'] = stage
            if missing:
                diag['missing'] = list(missing)
        personal_kind = parsed.get("receipt_kind") if parsed.get("receipt_kind") in {"personal_incoming", "group_payment"} else None
        layout_review = parsed.get("receipt_kind") == "layout_review"
        result_page = parsed.get("receipt_kind") == "payment_result"
        submission_mode = bool(result_page and req.request_id and req.result_time_policy == "submission")
        result_expense_required = result_page and not submission_mode
        submission_time_used = False
        if not draft["happened_at"] and submission_mode and req.submitted_at:
            submit_age = datetime.now(timezone.utc) - req.submitted_at
            if -timedelta(minutes=5) <= submit_age <= timedelta(minutes=5):
                draft = {**draft, "happened_at": req.submitted_at.isoformat()}
                submission_time_used = True
        capture_candidate = None
        capture_time_required = not draft["happened_at"]
        if capture_time_required and not submission_mode and req.request_id and req.captured_at:
            clock_age = datetime.now(timezone.utc) - req.captured_at
            if -timedelta(minutes=5) <= clock_age <= timedelta(minutes=5):
                capture_candidate = req.captured_at
                if req.confirm_capture_time:
                    draft = {**draft, "happened_at": req.captured_at.isoformat()}
        confirmation_required = (capture_candidate is not None and not req.confirm_capture_time
                                 or result_expense_required and not req.confirm_result_expense)

        async def reject_or_review(message: str, shortcut_choices: dict | None = None):
            if deferred:
                if not from_vision:
                    recovered = await try_vision(parsed)
                    if recovered is not None:
                        return await process(recovered, from_vision=True)
                return await record_for_later(message)
            # An opt-in handoff carries display fields, never an auth token or a
            # write permission. The web editor still requires login and a Save click.
            if not req.allow_review:
                raise HTTPException(status_code=422, detail=message)
            category = "" if personal_kind else req.category_name or draft["category_name"]
            if any(len(value) > 255 for value in (draft["note"], draft["account_name"], category)):
                raise HTTPException(status_code=422, detail=message)
            review_namespace = 'personal-ocr' if personal_kind else 'layout-ocr'
            review_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{review_namespace}:{current_user.id}:{req.ledger_id}:{req.request_id}") if (personal_kind or layout_review) and req.request_id else uuid.uuid4()
            payload = {
                # Cached clients accepting only v1 must refuse personal receipts,
                # rather than silently initialize an incoming amount as expense.
                "version": 2 if personal_kind else 1, "user_id": str(current_user.id), "ledger_id": req.ledger_id,
                "review_id": "ocr-review-" + str(review_id),
                "expires_at": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp() * 1000),
                "amount": draft["amount"], "happened_at": draft["happened_at"],
                "note": draft["note"], "account_name": draft["account_name"], "category_name": category,
                **({"tx_type": draft["type"], "review_reason": personal_kind} if personal_kind else {}),
            }
            encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
            content = {
                "detail": message, "review_path": "/app/overview#ocr-review=" + encoded, "review_payload": encoded,
            }
            if shortcut_choices is not None:
                content["shortcut_choices"] = shortcut_choices
            return JSONResponse(status_code=422, content=content)

        async def record_for_later(message: str):
            # The legacy immediate-review error says nothing was written. Deferred
            # capture may create an excluded provisional entry, so do not retain that claim.
            reason = re.sub(r'[；，。]?本次未写入账目[。]?', '', message)
            if vision_failure:
                reason += '；' + vision_failure
            row, fresh = retain_capture(db, current_user.id, ledger.id, req, with_diag(draft),
                reason + '；稍后核对，核对前暂不计收支统计')
            # An incomplete capture is durable, but it is not a fabricated transaction.
            # Only explicit amount/direction/time/funding evidence permits a native entry.
            not_future = bool(draft['happened_at'] and datetime.fromisoformat(draft['happened_at'])
                <= datetime.now(timezone.utc) + timedelta(minutes=5))
            evidence = parsed.get('evidence') or {}
            facts_clear = not (evidence.get('amount_symbol_repaired') or evidence.get('time_label_recovered'))
            if fresh and facts_clear and not_future and (draft['account_name'] or req.account_id):
                matching_accounts = db.scalars(select(UserAccountProjection).where(
                    UserAccountProjection.user_id == ledger.user_id,
                    (UserAccountProjection.sync_id == req.account_id) if req.account_id else
                    (UserAccountProjection.name == draft['account_name']),
                    UserAccountProjection.hidden.is_(False),
                    (UserAccountProjection.currency == 'CNY') | UserAccountProjection.currency.is_(None))).all()
                if len(matching_accounts) == 1:
                    matching_categories = db.scalars(select(UserCategoryProjection).where(
                        UserCategoryProjection.user_id == ledger.user_id,
                        UserCategoryProjection.name == draft['category_name'],
                        UserCategoryProjection.kind == draft['type'])).all()
                    category_fields = {}
                    if len(matching_categories) == 1 and not db.scalar(select(UserCategoryProjection.sync_id).where(
                            UserCategoryProjection.user_id == ledger.user_id,
                            UserCategoryProjection.kind == draft['type'],
                            UserCategoryProjection.parent_name == matching_categories[0].name).limit(1)):
                        category_fields = {'category_id': matching_categories[0].sync_id,
                                           'category_name': matching_categories[0].name}
                    provisional = WriteTransactionCreateRequest(base_change_id=0, tx_type=draft['type'],
                        amount=draft['amount'], happened_at=datetime.fromisoformat(draft['happened_at']),
                        note=draft['note'], account_id=matching_accounts[0].sync_id,
                        account_name=matching_accounts[0].name, currency_code='CNY', native_amount=draft['amount'],
                        category_kind=draft['type'], exclude_from_stats=True,
                        exclude_from_budget=draft['type'] == 'expense', **category_fields)
                    await create_tx(ledger_id=req.ledger_id, req=provisional, request=request,
                        idempotency_key='ocr-review-'+row.id, device_id='ocr-rules',
                        _scopes=_scopes, current_user=current_user, db=db)
                    db.refresh(row)
            return JSONResponse(status_code=202, content=capture_ack(row))

        from ...services.payment_rules import payment_review_reason
        review_reason = payment_review_reason(parsed, req.text, simplified=simple_auto)
        if review_reason:
            mark('review_rule')
            return await reject_or_review(review_reason)

        missing = [label for label, value in (
            ("交易单号", req.request_id or parsed["source_id"]), ("付款时间", draft["happened_at"] or capture_candidate),
            ("付款账户", req.request_id or draft["account_name"]),
        ) if not value]
        if missing:
            mark('missing_fields', missing)
            return await reject_or_review(
                "自动入账未通过：未明确识别或匹配" + "、".join(missing)
                + "。请保留字段名称及完整内容，或用草稿核对；本次未写入账目。"
            )
        stamp = datetime.fromisoformat(draft["happened_at"]) if draft["happened_at"] else capture_candidate
        age = datetime.now(timezone.utc) - stamp
        if age < -timedelta(minutes=5) or (age > timedelta(hours=12) and not simple_auto):
            mark('time_window')
            return await reject_or_review("自动入账仅接受最近 12 小时且非未来的付款；请核对日期后手动保存，本次未写入账目")
        accounts = db.scalars(select(UserAccountProjection).where(
            UserAccountProjection.user_id == ledger.user_id,
            (UserAccountProjection.sync_id == req.account_id) if req.account_id else
            (UserAccountProjection.name == draft["account_name"]),
            UserAccountProjection.hidden.is_(False),
            (UserAccountProjection.currency == "CNY") | UserAccountProjection.currency.is_(None),
        )).all()
        category_name = req.category_name or draft["category_name"]
        categories = db.scalars(select(UserCategoryProjection).where(
            UserCategoryProjection.user_id == ledger.user_id,
            (UserCategoryProjection.sync_id == req.category_id) if req.category_id else
            (UserCategoryProjection.name == category_name),
            UserCategoryProjection.kind == draft['type'],
        )).all()
        children = db.scalar(select(UserCategoryProjection.sync_id).where(
            UserCategoryProjection.user_id == ledger.user_id,
            UserCategoryProjection.parent_name == (categories[0].name if len(categories) == 1 else category_name),
        ).limit(1))
        if len(accounts) != 1 or len(categories) != 1 or children or confirmation_required:
            choices = None
            if req.request_id:
                account_options = db.scalars(select(UserAccountProjection).where(
                    UserAccountProjection.user_id == ledger.user_id,
                    UserAccountProjection.hidden.is_(False),
                    (UserAccountProjection.currency == "CNY") | UserAccountProjection.currency.is_(None),
                ).order_by(UserAccountProjection.name, UserAccountProjection.sync_id)).all()
                category_options = db.scalars(select(UserCategoryProjection).where(
                    UserCategoryProjection.user_id == ledger.user_id,
                    UserCategoryProjection.kind == "expense",
                ).order_by(UserCategoryProjection.name, UserCategoryProjection.sync_id)).all()
                parents = {row.parent_name for row in category_options if row.parent_name}
                category_options = [row for row in category_options if row.name not in parents]

                def option_map(rows):
                    # Duplicate names remain explicit choices rather than silently
                    # selecting an arbitrary dictionary entry.
                    counts = {}
                    for row in rows:
                        counts[row.name] = counts.get(row.name, 0) + 1
                    return {(row.name if counts[row.name] == 1 else f"{row.name} · {row.sync_id}"): row.sync_id for row in rows}

                account_map = option_map(account_options) if len(accounts) != 1 else {}
                category_map = option_map(category_options) if len(categories) != 1 or children else {}
                if (len(accounts) == 1 or account_map) and (len(categories) == 1 and not children or category_map) and max(len(account_map), len(category_map)) <= 100:
                    local_time = stamp.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    choices = {
                        "summary": f"支出 ¥{draft['amount']:.2f} · {draft['note']}\n"
                        + (f"记账时间采用本次提交时间 {local_time}（北京时间）" if submission_time_used
                           else f"本页没有付款时间，确认后使用本次截图时间 {local_time}（北京时间）；旧账请取消并手动核对。" if capture_time_required
                           else f"付款时间 {local_time}（北京时间）")
                        + ("\n请确认这是你的支出，而非借还款或自己账户间转账。" if result_expense_required else ""),
                        "account_labels": list(account_map), "account_ids": account_map,
                        "category_labels": list(category_map), "category_ids": category_map,
                        "account_id": accounts[0].sync_id if len(accounts) == 1 else "",
                        "category_id": categories[0].sync_id if len(categories) == 1 and not children else "",
                        "confirmation_required": bool(confirmation_required),
                        "confirm_capture_time": capture_time_required,
                        "confirm_result_expense": result_expense_required,
                    }
            message = ("请确认这笔付款按支出记录，并核对时间、扣款账户和分类；本次未写入账目" if confirmation_required
                       else "付款账户或指定支出分类未唯一匹配，请选择已有账户和分类；本次未写入账目")
            mark('confirmation' if confirmation_required else 'match', [label for label, failed in (
                ('account', len(accounts) != 1), ('category', len(categories) != 1 or bool(children))) if failed])
            return await reject_or_review(message, choices)
        native_request = WriteTransactionCreateRequest(
            base_change_id=0, tx_type=draft['type'], amount=draft["amount"],
            happened_at=stamp, note=draft["note"],
            account_id=accounts[0].sync_id, account_name=accounts[0].name,
            category_id=categories[0].sync_id, category_name=categories[0].name,
            category_kind=draft['type'], currency_code="CNY", native_amount=draft["amount"],
            exclude_from_stats=bool(saving_enabled and parsed.get('receipt_kind') == 'alipay_saving'),
            exclude_from_budget=bool(saving_enabled and parsed.get('receipt_kind') == 'alipay_saving'),
        )
        if from_vision:
            # User decision 2026-10-19: a model reading is never final on its own.
            # Keep a provisional entry (excluded from stats) plus the screenshot for review.
            mark('vision_review')
            return await record_for_later('视觉模型补读结果，请对照截图核对后确认')
        if simple_auto:
            # Freeze the exact native request before writing, so a transport retry
            # never creates another transaction.
            mark('auto')
            row, _ = retain_capture(db, current_user.id, ledger.id, req,
                with_diag({**draft, '_auto_request': native_request.model_dump(mode='json')}),
                '付款信息明确，按简化记账规则自动入账')
            if not (row.draft or {}).get('_auto_request'):
                # A concurrent attempt may already have retained uncertainty.
                # Do not overwrite its decision or create a second capture.
                return JSONResponse(status_code=202, content=capture_ack(row))
            return await resume_auto(row)
        operation = "run:" + req.request_id if req.request_id else str(parsed['source_id'])
        key = "ocr-" + hashlib.sha256(f"{req.ledger_id}:{operation}".encode()).hexdigest()
        return await create_tx(
            ledger_id=req.ledger_id, req=native_request, request=request,
            idempotency_key=key, device_id="ocr-rules",
            _scopes=_scopes, current_user=current_user, db=db,
        )

    try:
        parsed = await rules(req.text)
    except HTTPException as exc:
        if not deferred or exc.status_code != 422:
            raise
        diag.update(stage='rules', layout='unrecognized')
        recovered = await try_vision(None)
        if recovered is not None:
            return await process(recovered, from_vision=True)
        message = exc.detail.get('message', '') if isinstance(exc.detail, dict) else str(exc.detail)
        reason = message or '金额、方向或付款信息未明确，请稍后对照截图补全'
        if vision_failure:
            reason += '；' + vision_failure
        from ...services.alipay_rules import alipay_internal_reason
        retained = {'_saving_exclusions': True} if saving_enabled and alipay_internal_reason(req.text) else None
        row, _ = retain_capture(db, current_user.id, ledger.id, req, with_diag(retained), reason)
        return JSONResponse(status_code=202, content=capture_ack(row))

    return await process(parsed)


def _linked_entries(db: Session, rows) -> dict:
    """Linked entry state by sync_id, so the inbox can say whether it is still provisional."""
    ids = {(row.ledger_id, row.entity_id) for row in rows if row.entity_id}
    found = {}
    for ledger_id in {ledger for ledger, _ in ids}:
        for sync_id, excluded in db.execute(select(ReadTxProjection.sync_id, ReadTxProjection.exclude_from_stats).where(
                ReadTxProjection.ledger_id == ledger_id,
                ReadTxProjection.sync_id.in_([entity for ledger, entity in ids if ledger == ledger_id]))).all():
            found[(ledger_id, sync_id)] = bool(excluded)
    return found


def _inbox_item(row: OcrCapture, external_ledger_id: str, entries: dict | None = None) -> dict:
    from ...services import ocr_images
    draft = {k: v for k, v in (row.draft or {}).items() if not k.startswith('_')}
    key = (row.ledger_id, row.entity_id)
    entry = None if not row.entity_id or entries is None else {
        'exists': key in entries, 'exclude_from_stats': entries.get(key, False)}
    return {'id': row.id, 'ledger_id': external_ledger_id, 'entry': entry,
        **({'accounting_flags': {'exclude_from_stats': True, 'exclude_from_budget': True}}
           if (row.draft or {}).get('_saving_exclusions') is True else {}),
        'created_at': row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        'reason': row.reason, 'draft': draft or None, 'entity_id': row.entity_id,
        'status': row.status, 'revision': inbox_revision(row),
        'request_key': 'ocr-review-'+row.id, 'image': ocr_images.availability(row.id, row.user_id)
        if ocr_images.keeps_picture(row) else {'available': False, 'expires_at': None}}


@router.get('/ocr-inbox')
def ocr_inbox(ledger_id: str, limit: int = Query(default=20, ge=1, le=100),
              offset: int = Query(default=0, ge=0, le=10000),
              state: Literal['pending', 'ignored', 'recent'] = Query(default='pending'),
              _scopes: set[str] = Depends(_PARSE_SCOPE_DEP), current_user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    ledger, _ = require_accessible_ledger_by_external_id(db, user_id=current_user.id,
        ledger_external_id=ledger_id, roles={ROLE_OWNER, ROLE_EDITOR})
    owner = (OcrCapture.user_id == current_user.id, OcrCapture.ledger_id == ledger.id)
    counts = dict(db.execute(select(OcrCapture.status, func.count()).where(*owner).group_by(OcrCapture.status)).all())
    # Auto-booked captures of the last 48h, while their screenshot is kept. Bounded set,
    # so the private draft marker is checked in Python rather than with JSON SQL.
    recent = [row for row in db.scalars(select(OcrCapture).where(*owner, OcrCapture.status == 'confirmed',
              OcrCapture.created_at >= datetime.now(timezone.utc) - timedelta(hours=48)).order_by(
              OcrCapture.created_at.desc(), OcrCapture.id)).all() if (row.draft or {}).get('_auto_request')]
    if state == 'recent':
        total, rows = len(recent), recent[offset:offset + limit]
    else:
        filters = (*owner, OcrCapture.status == state)
        total = db.scalar(select(func.count()).select_from(OcrCapture).where(*filters))
        rows = db.scalars(select(OcrCapture).where(*filters).order_by(
            OcrCapture.created_at.desc(), OcrCapture.id).offset(offset).limit(limit)).all()
    entries = _linked_entries(db, rows)
    return {'total': total, 'pending_total': counts.get('pending', 0), 'ignored_total': counts.get('ignored', 0),
            'recent_total': len(recent), 'items': [_inbox_item(row, ledger_id, entries) for row in rows]}


def _owned_capture(db: Session, user: User, capture_id: str):
    row = db.scalar(select(OcrCapture).where(OcrCapture.id == capture_id, OcrCapture.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail='没有找到这次采集')
    from ...models import Ledger
    ledger = db.get(Ledger, row.ledger_id)
    if ledger is None:
        raise HTTPException(status_code=404, detail='没有找到账本')
    require_accessible_ledger_by_external_id(db, user_id=user.id,
        ledger_external_id=ledger.external_id, roles={ROLE_OWNER, ROLE_EDITOR})
    if row.status == 'cleared':
        raise HTTPException(status_code=410, detail='这次采集已随账本数据清空')
    return row, ledger


@router.get('/ocr-inbox/{capture_id}')
def ocr_capture_detail(capture_id: str, _scopes: set[str] = Depends(_PARSE_SCOPE_DEP),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, ledger = _owned_capture(db, current_user, capture_id)
    return {**_inbox_item(row, ledger.external_id, _linked_entries(db, [row])), 'text': row.text, 'status': row.status}


@router.get('/ocr-inbox/{capture_id}/image')
def ocr_capture_image(capture_id: str, _scopes: set[str] = Depends(_PARSE_SCOPE_DEP),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    from ...services import ocr_images
    row, _ = _owned_capture(db, current_user, capture_id)
    picture = ocr_images.read(row.id, current_user.id) if ocr_images.keeps_picture(row) else None
    if picture is None:
        raise HTTPException(status_code=410, detail='临时截图未上传或已清理，文字与账目仍保留')
    return Response(picture['data'], media_type=picture['mime'], headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; sandbox"})


class ResolveCaptureRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=255)
    expected_change_id: int = Field(ge=1)


class ChangeCaptureStateRequest(BaseModel):
    status: Literal['pending', 'ignored']
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    action_id: uuid.UUID


class RereadCaptureRequest(BaseModel):
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    action_id: uuid.UUID


@router.post('/ocr-inbox/{capture_id}/reread')
async def reread_capture(capture_id: str, req: RereadCaptureRequest,
                         _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ...services import ocr_images
    row, ledger = _owned_capture(db, current_user, capture_id)
    action = {'id': str(req.action_id), 'before': req.expected_revision}
    last = (row.draft or {}).get('_vision_retry', {})
    if last.get('action') == action:
        return {**_inbox_item(row, ledger.external_id), 'message': last['message']}
    if row.status != 'pending' or row.entity_id or row.receipt:
        raise HTTPException(status_code=409, detail='只可重识别尚未入账的待核对采集，已入账请核对原记录')
    if inbox_revision(row) != req.expected_revision:
        raise HTTPException(status_code=409, detail='采集已变化，请刷新后再识别')
    picture = ocr_images.read(row.id, current_user.id)
    if picture is None:
        raise HTTPException(status_code=410, detail='临时截图未上传或已清理，无法重识别；原文字仍保留')
    from ...services.alipay_rules import alipay_internal_reason
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    preferences = load_ocr_preferences(profile.ai_config_json if profile else None, ledger.external_id)
    if alipay_internal_reason(row.text) and not (preferences.get('accounting_mode') == 'channel'
            and preferences.get('alipay_saving_as_excluded_expense') is True):
        raise HTTPException(status_code=422, detail='小荷包资金划转需要核对用途，视觉重识别不会将其改成消费')
    compact = re.sub(r'\s+', '', payment_status_evidence(row.text))
    if re.search(r'支付失败|付款失败|交易失败|待支付|待付款|未支付|交易关闭|退款|已退还|已退回|USD|EUR|HKD|JPY|美元|欧元|港币|日元|\$|€', compact, re.I):
        raise HTTPException(status_code=422, detail='原文存在退款、失败或不支持币种信息，请核对原图；不会让模型覆盖这些信息')
    if re.search(r'(?m)^(?:入账未通过$|服务器返回[:：]|请先核对账本)', row.text):
        raise HTTPException(status_code=422, detail='采集中包含上次报错弹窗，请重新采集干净的付款页面')
    original_draft = row.draft
    original_raw = db.scalar(select(cast(OcrCapture.draft, Text)).where(OcrCapture.id == row.id))
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    recovered = None
    message = '视觉识别暂不可用或结果仍不明确，原图在到期前保留；尚未新增账目'
    try:
        text = await transcribe_payment(base64.b64encode(picture['data']).decode(), current_user, profile)
        parsed = await parse_tx_text(ParseTxTextRequest(text=text, ledger_id=ledger.external_id, engine='rules'),
                                    _scopes=_scopes, current_user=current_user, db=db)
        if not agrees_with_visible_facts(row.text, parsed, text):
            raise ValueError('conflicting visible facts')
        if alipay_internal_reason(row.text) and parsed.get('receipt_kind') != 'alipay_saving':
            raise ValueError('saving purpose missing')
        recovered = parsed['tx_drafts'][0]
        known = {k: v for k, v in (original_draft or {}).items() if not k.startswith('_')}
        if known and any(known.get(key) and known[key] != recovered.get(key)
                         for key in ('type', 'amount', 'happened_at', 'account_name')):
            raise ValueError('conflicting existing draft')
        message = '已根据临时截图补全草稿，请核对后保存；尚未新增账目'
    except (ChatProviderError, ValueError, HTTPException) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 422:
            raise
        recovered = None
        logger.info('ocr.saved_image_reread_unresolved kind=%s', type(exc).__name__)
    # A remote model is nondeterministic. Persist this action result, using CAS
    # so a late model reply cannot undo an ignore or overwrite a manual save.
    draft = {**(original_draft or {}), **(recovered or {}), '_vision_retry': {
        'action': action, 'message': message, 'status': 'recovered' if recovered else 'unresolved'}}
    raw = cast(OcrCapture.draft, Text)
    changed = db.execute(update(OcrCapture).where(OcrCapture.id == row.id,
        OcrCapture.user_id == current_user.id, OcrCapture.status == 'pending',
        OcrCapture.entity_id.is_(None), OcrCapture.receipt.is_(None),
        raw.is_(None) if original_raw is None else raw == original_raw).values(draft=draft,
            reason='已补读截图，尚未入账；请核对金额、方向、时间及账户后保存' if recovered else row.reason),
        execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail='识别期间采集已变化，请刷新查看；未新增账目')
    db.commit()
    db.refresh(row)
    return {**_inbox_item(row, ledger.external_id), 'message': message}


@router.post('/ocr-inbox/{capture_id}/reparse')
async def reparse_capture(capture_id: str, req: RereadCaptureRequest,
                          _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
                          current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Free re-read of the stored OCR text with the current rules; no model. A decisive reading is
    booked like a fresh capture (user request 2026-10-22); otherwise only the draft is filled."""
    row, ledger = _owned_capture(db, current_user, capture_id)
    action = {'id': str(req.action_id), 'before': req.expected_revision}
    last = (row.draft or {}).get('_rules_retry', {})
    if last.get('action') == action:
        return {**_inbox_item(row, ledger.external_id), 'message': last['message']}
    if row.status == 'confirmed' and (row.draft or {}).get('_rules_rebook', {}).get('action') == action:
        return {**_inbox_item(row, ledger.external_id), 'message': '新规则识别明确，已自动入账'}
    if row.status != 'pending' or row.entity_id or row.receipt:
        raise HTTPException(status_code=409, detail='只可重新识别尚未入账的待核对采集，已入账请核对原记录')
    if inbox_revision(row) != req.expected_revision:
        raise HTTPException(status_code=409, detail='采集已变化，请刷新后再识别')
    if await rebook_capture(db, current_user, row, ledger, action=action) == 'booked':
        db.refresh(row)
        return {**_inbox_item(row, ledger.external_id), 'message': '新规则识别明确，已自动入账'}
    db.refresh(row)
    original_draft = row.draft
    original_raw = db.scalar(select(cast(OcrCapture.draft, Text)).where(OcrCapture.id == row.id))
    recovered = None
    message = '新规则仍无法识别这次采集，尚未新增账目；可用截图重新识别或手动补全'
    try:
        parsed = await parse_tx_text(ParseTxTextRequest(text=row.text, ledger_id=ledger.external_id, engine='rules'),
                                     _scopes=_scopes, current_user=current_user, db=db)
        recovered = parsed['tx_drafts'][0]
        known = {k: v for k, v in (original_draft or {}).items() if not k.startswith('_')}
        if known and any(known.get(key) and known[key] != recovered.get(key)
                         for key in ('type', 'amount', 'happened_at', 'account_name')):
            raise ValueError('conflicting existing draft')
        message = '已用新规则识别，尚未入账；请核对后保存'
    except (ValueError, HTTPException) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 422:
            raise
        recovered = None
        logger.info('ocr.rules_reparse_unresolved kind=%s', type(exc).__name__)
    draft = {**(original_draft or {}), **(recovered or {}), '_rules_retry': {
        'action': action, 'message': message, 'status': 'recovered' if recovered else 'unresolved'}}
    raw = cast(OcrCapture.draft, Text)
    changed = db.execute(update(OcrCapture).where(OcrCapture.id == row.id,
        OcrCapture.user_id == current_user.id, OcrCapture.status == 'pending',
        OcrCapture.entity_id.is_(None), OcrCapture.receipt.is_(None),
        raw.is_(None) if original_raw is None else raw == original_raw).values(draft=draft,
            reason='已用新规则识别，尚未入账；请核对金额、方向、时间及账户后保存' if recovered else row.reason),
        execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail='识别期间采集已变化，请刷新查看；未新增账目')
    db.commit()
    db.refresh(row)
    return {**_inbox_item(row, ledger.external_id), 'message': message}


@router.post('/ocr-inbox/{capture_id}/state')
def change_capture_state(capture_id: str, req: ChangeCaptureStateRequest,
                         _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, ledger = _owned_capture(db, current_user, capture_id)
    from ...concurrency import lock_ledger_for_materialize
    lock_ledger_for_materialize(db, ledger.id)
    # Read the model and its raw JSON together. Text comparison is portable to
    # PostgreSQL JSON (which has no equality operator), and prevents SQLite ABA races.
    row, draft_text = db.execute(select(OcrCapture, cast(OcrCapture.draft, Text).label('draft_text')).where(
        OcrCapture.id == row.id).execution_options(populate_existing=True)).one()
    action = {'id': str(req.action_id), 'status': req.status, 'before': req.expected_revision}
    # A linked entry the user has since deleted leaves nothing to review; the capture
    # may then be set aside like an unbooked one. A live linked entry is reviewed instead.
    linked = bool(row.entity_id or row.receipt)
    entry_gone = bool(row.entity_id) and (row.ledger_id, row.entity_id) not in _linked_entries(db, [row])
    if linked and not entry_gone or row.status not in ('pending', 'ignored'):
        raise HTTPException(status_code=409, detail='这次采集已关联账目或已核对，请到原账目处理，不能忽略')
    if (row.draft or {}).get('_inbox_action') == action and row.status == req.status:
        return {'status': row.status, 'revision': inbox_revision(row)}
    if inbox_revision(row) != req.expected_revision or row.status == req.status:
        raise HTTPException(status_code=409, detail='采集状态已经变化，请刷新后再操作')
    draft = {**(row.draft or {}), '_inbox_action': action}
    original = cast(OcrCapture.draft, Text)
    changed = db.execute(update(OcrCapture).where(OcrCapture.id == row.id,
        OcrCapture.user_id == current_user.id, OcrCapture.status == row.status,
        *((OcrCapture.entity_id == row.entity_id, OcrCapture.save_hash.is_(None) if row.save_hash is None
           else OcrCapture.save_hash == row.save_hash) if entry_gone
          else (OcrCapture.entity_id.is_(None), OcrCapture.receipt.is_(None))),
        original.is_(None) if draft_text is None else original == draft_text
    ).values(status=req.status, draft=draft), execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail='采集状态或账目已变化，请刷新后再操作')
    db.commit()
    db.refresh(row)
    if row.status == 'ignored':
        _discard_capture_image(row)
    return {'status': row.status, 'revision': inbox_revision(row)}


@router.post('/ocr-inbox/{capture_id}/resolve')
def resolve_capture(capture_id: str, req: ResolveCaptureRequest,
                    _scopes: set[str] = Depends(_WRITE_SCOPE_DEP),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, ledger = _owned_capture(db, current_user, capture_id)
    from ...concurrency import lock_ledger_for_materialize
    lock_ledger_for_materialize(db, ledger.id)
    db.refresh(row)
    if row.entity_id != req.entity_id:
        raise HTTPException(status_code=409, detail='采集与账目未关联，不能标记已核对')
    tx = db.scalar(select(ReadTxProjection).where(ReadTxProjection.ledger_id == ledger.id,
        ReadTxProjection.sync_id == req.entity_id))
    if tx is None or tx.source_change_id != req.expected_change_id:
        raise HTTPException(status_code=409, detail='账目已经变化或已删除，请重新读取后核对')
    row.status = 'confirmed'
    db.commit()
    _discard_capture_image(row)
    return {'status': 'confirmed'}


def _discard_capture_image(row):
    import sqlite3

    from ...services import ocr_images
    try:
        ocr_images.forget(row.id, row.user_id)
    except (OSError, sqlite3.Error):
        logger.warning('ocr.image_cleanup_deferred')  # hourly sweep retries cleanup


# --------------------------------------------------------------------------- automatic re-reading
# User request 2026-10-22: when the rules improve, captures still waiting for review are re-read
# automatically and booked like a fresh decisive capture, instead of waiting for a confirmation.
# Same guards as a fresh channel-mode capture; the capture's fixed key "ocr-review-<id>" and the
# capture-row CAS keep it to at most one entry. Vision-only readings are never booked here.

def _internal_request(method: str, path: str) -> Request:
    # The native write hashes method and path for idempotency and broadcasts through app.state.ws_manager.
    from ...main import app
    return Request({'type': 'http', 'method': method, 'path': path, 'headers': [], 'query_string': b'', 'app': app})


async def rebook_capture(db: Session, user: User, row: OcrCapture, ledger, *, action: dict | None = None) -> str:
    """Re-read one pending capture with the current rules and return an outcome label."""
    from ...schemas import WriteTransactionUpdateRequest
    from ...services.payment_rules import payment_review_reason
    from ..write.transactions import update_tx
    if row.status != 'pending':
        return 'not_pending'
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    prefs = load_ocr_preferences(profile.ai_config_json if profile else None, ledger.external_id)
    if prefs.get('accounting_mode') != 'channel':
        return 'not_channel'
    try:
        parsed = await parse_tx_text(ParseTxTextRequest(text=row.text, ledger_id=ledger.external_id, engine='rules'),
                                     _scopes=set(), current_user=user, db=db)
    except HTTPException:
        return 'rules_rejected'
    if payment_review_reason(parsed, row.text, simplified=True):
        return 'review'
    draft = parsed['tx_drafts'][0]
    stamp = draft['happened_at']
    if not stamp and parsed.get('receipt_kind') == 'payment_result':
        # A success page shows no time; a fresh capture uses its submission time, which is
        # when this capture row was created.
        stamp = row.created_at.replace(tzinfo=timezone.utc).isoformat()
    if not stamp:
        return 'no_time'
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone(timedelta(hours=8)))
    if when - datetime.now(timezone.utc) > timedelta(minutes=5):
        return 'future'
    accounts = db.scalars(select(UserAccountProjection).where(
        UserAccountProjection.user_id == ledger.user_id, UserAccountProjection.name == draft['account_name'],
        UserAccountProjection.hidden.is_(False),
        (UserAccountProjection.currency == 'CNY') | UserAccountProjection.currency.is_(None))).all()
    categories = db.scalars(select(UserCategoryProjection).where(
        UserCategoryProjection.user_id == ledger.user_id, UserCategoryProjection.name == draft['category_name'],
        UserCategoryProjection.kind == draft['type'])).all()
    children = len(categories) == 1 and db.scalar(select(UserCategoryProjection.sync_id).where(
        UserCategoryProjection.user_id == ledger.user_id, UserCategoryProjection.kind == draft['type'],
        UserCategoryProjection.parent_name == categories[0].name).limit(1))
    if len(accounts) != 1 or len(categories) != 1 or children:
        return 'account_or_category'
    saving = bool(prefs.get('alipay_saving_as_excluded_expense') is True and parsed.get('receipt_kind') == 'alipay_saving')
    base = f'/api/v1/write/ledgers/{ledger.external_id}/transactions'
    if row.entity_id is None and row.receipt is None:
        native = WriteTransactionCreateRequest(
            base_change_id=0, tx_type=draft['type'], amount=draft['amount'], happened_at=when, note=draft['note'],
            account_id=accounts[0].sync_id, account_name=accounts[0].name,
            category_id=categories[0].sync_id, category_name=categories[0].name, category_kind=draft['type'],
            currency_code='CNY', native_amount=draft['amount'], exclude_from_stats=saving, exclude_from_budget=saving)
        # Mark the capture as an automatic write first (CAS), so the native bind confirms it.
        raw = cast(OcrCapture.draft, Text)
        original_raw = db.scalar(select(raw).where(OcrCapture.id == row.id))
        public = {k: v for k, v in draft.items() if not k.startswith('_')}
        marked = {**(row.draft or {}), **public, '_auto_request': native.model_dump(mode='json'),
                  '_rules_rebook': {'at': datetime.now(timezone.utc).isoformat(), 'action': action}}
        changed = db.execute(update(OcrCapture).where(OcrCapture.id == row.id, OcrCapture.status == 'pending',
            OcrCapture.entity_id.is_(None), OcrCapture.receipt.is_(None),
            raw.is_(None) if original_raw is None else raw == original_raw).values(
                draft=marked, reason='新规则识别明确，已自动入账'), execution_options={'synchronize_session': False})
        if changed.rowcount != 1:
            db.rollback()
            return 'changed'
        db.commit()
        db.refresh(row)
        await create_tx(ledger_id=ledger.external_id, req=native, request=_internal_request('POST', base),
                        idempotency_key='ocr-review-' + row.id, device_id='ocr-rules',
                        _scopes=set(), current_user=user, db=db)
        logger.info('ocr.rules_rebook outcome=booked')
        return 'booked'
    # A provisional entry (excluded from stats, e.g. from a vision reading) that the rules now read
    # independently with the same direction and amount becomes a counted entry.
    tx = db.scalar(select(ReadTxProjection).where(ReadTxProjection.ledger_id == ledger.id,
                                                  ReadTxProjection.sync_id == row.entity_id))
    if tx is None or not tx.exclude_from_stats:
        return 'linked'
    if tx.tx_type != draft['type'] or abs(float(tx.amount) - float(draft['amount'])) > 0.005:
        return 'mismatch'
    change = WriteTransactionUpdateRequest(
        base_change_id=0, expected_change_id=tx.source_change_id, happened_at=when,
        category_id=categories[0].sync_id, category_name=categories[0].name, category_kind=draft['type'],
        exclude_from_stats=saving, exclude_from_budget=saving)
    await update_tx(ledger_id=ledger.external_id, tx_id=tx.sync_id, req=change,
                    request=_internal_request('PATCH', base + '/' + tx.sync_id),
                    idempotency_key=f'ocr-rebook-{row.id}-{tx.source_change_id}', device_id='ocr-rules',
                    _scopes=set(), current_user=user, db=db)
    confirmed = db.execute(update(OcrCapture).where(OcrCapture.id == row.id, OcrCapture.status == 'pending',
        OcrCapture.entity_id == tx.sync_id).values(status='confirmed', reason='新规则识别与临时账目一致，已自动计入'),
        execution_options={'synchronize_session': False})
    db.commit()
    if confirmed.rowcount == 1:
        _discard_capture_image(row)
    logger.info('ocr.rules_rebook outcome=confirmed')
    return 'confirmed'


async def rebook_pending(db: Session, *, days: int = 14, limit: int = 300) -> dict[str, int]:
    """Sweep recent pending captures; one failing capture never stops the others."""
    from ...models import Ledger
    rows = db.scalars(select(OcrCapture).where(
        OcrCapture.status == 'pending',
        OcrCapture.created_at >= datetime.now(timezone.utc) - timedelta(days=days)).order_by(
        OcrCapture.created_at).limit(limit)).all()
    outcomes: dict[str, int] = {}
    for row in rows:
        try:
            user, ledger = db.get(User, row.user_id), db.get(Ledger, row.ledger_id)
            outcome = await rebook_capture(db, user, row, ledger) if user and ledger else 'missing'
        except Exception as exc:  # noqa: BLE001 - logged by kind only, never capture content
            db.rollback()
            outcome = 'error'
            logger.warning('ocr.rules_rebook_failed kind=%s', type(exc).__name__)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if rows:
        logger.info('ocr.rules_rebook sweep=%s', json.dumps(outcomes, sort_keys=True))
    return outcomes

"""Bounded OCR-text payment parser. No image processing or model/network calls.

Extends the project's earlier personal-ledger/capture.py text adapter. Produces
reviewable drafts only; payment channel never substitutes for a funding account.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


class PaymentTextError(ValueError):
    pass


def without_payment_service_hints(text: str) -> str:
    """One observed standalone UI capability hint; never strip arbitrary prose."""
    return '\n'.join(line for line in text.splitlines()
                     if re.sub(r'\s+', '', unicodedata.normalize('NFKC', line)) != '可在支持的商户扫码退款')


def payment_status_evidence(text: str) -> str:
    """Share the parser's exact service-action exception with visual guards."""
    text = unicodedata.normalize('NFKC', text).replace('\r', '\n')
    text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    text, _ = _normalize_ocr_lines(without_payment_service_hints(text))
    head, section, footer = text.partition('\n账单服务\n')
    return head + section + '\n'.join(
        line for line in footer.splitlines() if line != '申请退款'
    ) if section else text


def payment_funding_evidence(text: str) -> list[str]:
    """Only actual bounded field values, never the following column label."""
    text = unicodedata.normalize('NFKC', text).replace('\r', '\n')
    text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    text, _ = _normalize_ocr_lines(without_payment_service_hints(text))
    text, _ = _restore_displaced_columns(text)
    return _funding_values(text)


def _funding_values(text: str) -> list[str]:
    # A trailing disclosure chevron ("零钱 >") is page chrome, not part of the funding name.
    return [re.sub(r'\s*[>〉›]+$', '', value) for value in _values(text, '支付方式|付款方式')]


def load_ocr_preferences(raw: str | None, ledger_id: str) -> dict:
    """Use the existing private user-profile config, scoped to this ledger."""
    try:
        config = json.loads(raw or "{}")
        rules = config.get("ocr_rules", {}) if isinstance(config, dict) else {}
        ledgers = rules.get("ledgers", {}) if isinstance(rules, dict) else {}
        prefs = ledgers.get(ledger_id, {}) if isinstance(ledgers, dict) else {}
        return prefs if isinstance(prefs, dict) else {}
    except (ValueError, TypeError):
        return {}


def payment_channel(text: str) -> str | None:
    """Only explicit channel evidence; a bare balance/card label is insufficient."""
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
    # The whole accepted-transfer status sentence is WeChat-only; a bare '零钱' label still is not.
    wechat = (any(marker in compact for marker in ('微信支付', '微信转账', '财付通', '零钱明细'))
              or bool(_ACCEPTED_TRANSFER.search('\n'.join(line.strip() for line in
                                                         unicodedata.normalize('NFKC', text).splitlines()))))
    if not wechat:
        normalized = unicodedata.normalize('NFKC', text)
        normalized = '\n'.join(line.strip() for line in normalized.splitlines() if line.strip())
        normalized, _ = _normalize_ocr_lines(without_payment_service_hints(normalized))
        normalized, _ = _restore_displaced_columns(normalized)
        # Complete WeChat detail card, not a generic wallet name. Some receipt
        # acquirers are not Tenpay; their company name is not the payment app.
        required = ('支付时间', '商品', '收单机构', '交易单号', '商户单号')
        wechat = ("交易详情" in compact and '交易服务' in normalized.splitlines()
            and _values(normalized, '当前状态') == ['支付成功']
            and _values(normalized, '支付方式') == ['零钱']
            and all(len(_values(normalized, label)) == 1 for label in required)
            and len(re.findall(r'(?m)^-\d+\.\d{2}$', normalized)) == 1
            and all(re.fullmatch(r'[A-Za-z0-9_-]{8,100}', _values(normalized, label)[0])
                    for label in ('交易单号', '商户单号')))
    from .alipay_rules import alipay_channel_evidence
    alipay = '支付宝' in compact or alipay_channel_evidence(text)
    return ('wechat' if wechat else 'alipay') if wechat != alipay else None


def payment_review_reason(parsed: dict, text: str, *, simplified: bool) -> str:
    """Evidence ambiguity, distinct from sorting a known complete OCR table."""
    kind = parsed.get('receipt_kind')
    personal = kind in {'personal_incoming', 'group_payment'}
    evidence = parsed.get('evidence') or {}
    if personal and simplified and re.search(
            r'借款|借出|借入|借还|还款|还钱|归还|转给自己|自己账户|本人账户|账户间|内部划转|提现',
            re.sub(r'\s+', '', text)):
        return '个人往来明确涉及借还款或内部划转，请稍后核对记账用途'
    if personal and not simplified:
        return '已识别个人收付款，请在拾账核对用途后保存；本次未写入账目'
    if kind == 'layout_review' or personal:
        if (not simplified or evidence.get('amount_symbol_repaired')
                or evidence.get('time_label_recovered')
                or kind == 'layout_review' and not evidence.get('field_order_restored')):
            return '金额符号或时间对应关系仍需确认，请稍后核对'
    return ''


def _values(text: str, labels: str) -> list[str]:
    values = re.findall(rf"(?m)^(?:{labels})(?:[ \t]*:[ \t]*(?:\n[ \t]*)?|[ \t]+|\n[ \t]*)([^\n]+)", text)
    # OCR may emit the label column before its values. Known Alipay labels
    # must not become funding/merchant/time facts that veto the visual reader.
    field = re.compile(r"^(?:收款方|收款商户|商户全称|商家名称|商家|支付方式|付款方式|交易时间|付款时间|支付时间|转账时间|收款时间|到账时间|转账单号|商户单号|经营单号|收单机构|商品|零钱余额|当前状态|收款方备注|转账说明|交易单号|交易号|订单号|实付金额|实际付款|实付|付款金额|支付金额|订单金额|碰一下立减|创建时间|商品说明|清算机构|收款方全称|转账备注|对方账户|支付奖励|商家订单号|理由|交易方式|管理自动扣款|服务详情|更多|账单管理|账单分类|计入收支)(?:\s*:.*)?$")
    return [value for value in values if not field.fullmatch(value)]


def _normalize_ocr_lines(text: str) -> tuple[str, bool]:
    """Normalize observed spacing/punctuation; uncertain money glyphs require review."""
    labels = sorted(['当前状态', '收款方备注', '收款详情', '转账说明', '支付方式', '付款方式',
                     '支付时间', '付款时间', '交易时间', '转账时间', '收款时间', '到账时间',
                     '交易单号', '转账单号', '商户单号', '经营单号', '订单号', '交易号',
                     '商户全称', '商家名称', '收款商户', '收款方', '收单机构', '商品',
                     '零钱余额', '实付金额', '实际付款', '实付', '付款金额', '支付金额',
                     '订单金额', '碰一下立减', '创建时间', '商品说明', '清算机构', '收款方全称',
                     '转账备注', '对方账户', '支付奖励', '商家订单号', '理由', '交易方式'], key=len, reverse=True)
    result = []
    money_repaired = False
    for line in text.splitlines():
        marker = re.sub(r'[ \t]+', '', line)
        if marker in {'账单服务', '交易服务', '收款方服务', '全部账单', '商家小程序', '零钱明细', '交易详情'}:
            line = marker
        # Preserve the field/value boundary before joining spaced Chinese words.
        for label in labels:
            pattern = '^' + r'[ \t]*'.join(label) + r'(?=$|[ \t:])'
            match = re.match(pattern, line)
            if match:
                value = line[match.end():].lstrip(' :\t')
                line = label + (':'+value if value else '')
                break
        line = re.sub(r'(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])', '', line)
        line = re.sub(r'(?<=\d)[ \t]*(?=[年月日:/-])|(?<=[年月:/-])[ \t]*(?=\d)', '', line)
        line = re.sub(r'^(扫码付款|扫二维码付款|群收款|转账)一(?=给|转给|来自)', r'\1-', line)
        line = re.sub(r'^[.·•][ \t]*(交易详情)$', r'\1', line)
        match = re.fullmatch(r'([+一-])[ \t]*(\d+)[ \t]*([.·])[ \t]*(\d{2})', line)
        integer = re.fullmatch(r'([+一-])[ \t]*(\d+)', line)
        if match or integer:
            sign = (match or integer)[1]
            money_repaired |= sign not in {'+', '-'} or bool(match and match[3] == '·')
            line = ('+' if sign == '+' else '-') + (match or integer)[2] + ('.'+match[4] if match else '')
        result.append(line.strip())
    return '\n'.join(result), money_repaired


def _restore_displaced_columns(text: str) -> tuple[str, bool]:
    """Restore only complete known tables; new displacement recovery is review-only."""
    schemas = [
        ['当前状态', '收款方备注', '支付方式', '转账时间', '转账单号'],
        ['当前状态', '支付时间', '商品', '商户全称', '收单机构', '支付方式', '交易单号', '商户单号'],
        ['当前状态', '收单机构', '支付时间', '支付方式', '交易单号', '经营单号'],
        ['当前状态', '支付时间', '商品', '收单机构', '支付方式', '交易单号', '商户单号'],
        ['当前状态', '转账说明', '转账时间', '收款时间', '转账单号', '零钱余额'],
        ['当前状态', '收款详情', '支付时间', '支付方式', '交易单号', '商户单号', '零钱余额'],
        ['当前状态', '支付时间', '收单机构', '支付方式', '交易单号', '商户单号'],
    ]
    all_labels = {label for schema in schemas for label in schema}
    lines = text.splitlines()
    # Observed OCR control-label typo. Only a complete known table can use it;
    # the replacement never supplies a merchant or an amount.
    if {'当前状态', '支付时间', '收单机构', '支付方式', '交易单号', '商户单号'}.issubset(lines):
        lines = ['商品' if line in {'商口', '口口'} else line for line in lines]
    labels = [(i, line) for i, line in enumerate(lines) if line in all_labels]
    schema = next((schema for schema in schemas if [v for _, v in labels] == schema), None)
    if not schema:
        return text, False
    states = [i for i, line in enumerate(lines) if line in {'支付成功', '付款成功', '交易成功', '已存入零钱', '已收款', '收款成功'}]
    if len(states) != 1 or states[0] <= labels[-1][0]:
        return text, False
    # Keep the prior QR/personal complete-column contract on its existing path.
    if (schema in (schemas[0], schemas[4], schemas[5]) and labels[-1][0]+1 == states[0]
            and [i for i, _ in labels] == list(range(labels[0][0], labels[0][0]+len(labels)))):
        return text, False
    pos = states[0]
    if schema == schemas[1] and '商家小程序' in lines:
        program = lines.index('商家小程序') + 1
        debits = [i for i, line in enumerate(lines[:pos]) if re.fullmatch(r'-\d+\.\d{2}', line)]
        if (program < len(lines) and re.search(r'一卡通|校园卡', lines[program])
                and len(debits) == 1 and debits[0] > 0 and pos+2 < len(lines)):
            title = lines[debits[0]-1]
            merged = lines[pos+2]
            if (2 <= len(title) <= 120 and merged.endswith(title)
                    and re.search(r'(?:一卡通|卡通|校园卡)充值$', merged[:-len(title)])):
                # Split only the exact duplicated visible title. No merchant
                # or OCR character is invented, and all typed fields below
                # must still pass before this becomes a complete table.
                lines[pos+2:pos+3] = [merged[:-len(title)], title]
    values = []
    consumed = []
    date_pattern = r'\d{4}(?:年|-|/)\d{1,2}(?:月|-|/)\d{1,2}日?[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?'
    for field_index, label in enumerate(schema):
        if pos >= len(lines):
            return text, False
        value = lines[pos]
        if label == '收单机构' and schema == schemas[-1]:
            # Some extraction drops the product label. Locate only the named
            # acquirer's company line; retain up to two unlabelled product lines
            # in the original text so negative statuses cannot be hidden.
            skipped = 0
            while not value.endswith('公司') and skipped < 2 and pos+1 < len(lines) and value not in all_labels:
                pos += 1
                skipped += 1
                value = lines[pos]
            if not value.endswith('公司'):
                return text, False
        consumed.append(pos)
        pos += 1
        if label.endswith('时间'):
            valid = bool(re.fullmatch(date_pattern, value))
        elif label.endswith('单号'):
            valid = bool(re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value))
            next_label = schema[field_index+1] if field_index+1 < len(schema) else ''
            if (valid and next_label.endswith('单号') and pos+1 < len(lines)
                    and re.fullmatch(r'\d{1,8}', lines[pos]) and re.fullmatch(r'[A-Za-z0-9_-]{8,100}', lines[pos+1])):
                value += lines[pos]
                consumed.append(pos)
                pos += 1
        elif label == '零钱余额':
            # Not a transaction fact; accept a digit-only OCR balance without
            # repairing it or using it as an amount/account balance update.
            valid = bool(re.fullmatch(r'\d+(?:[.·]\d{2})?', re.sub(r'\s+', '', value)))
        elif label == '当前状态':
            valid = value in {'支付成功', '付款成功', '交易成功', '已存入零钱', '已收款', '收款成功'}
        else:
            valid = (0 < len(value) <= 255 and bool(re.search(r'[\u4e00-\u9fffA-Za-z]', value))
                     and value not in all_labels and value not in {'支付成功', '付款成功', '交易成功'})
            if label == '商品' and pos < len(lines) and re.fullmatch(r'[A-Za-z0-9_-]{8,100}', lines[pos]):
                value += lines[pos]
                consumed.append(pos)
                pos += 1
        if not valid:
            return text, False
        values.append(label+':'+value)
    removed = {i for i, _ in labels} | set(consumed)
    restored = []
    for i, line in enumerate(lines):
        if i == states[0]:
            restored.extend(values)
        if i not in removed:
            restored.append(line)
    return '\n'.join(restored), True


# WeChat status shown right after accepting a transfer; NFKC turns the full-width comma into ','.
_ACCEPTED_TRANSFER = re.compile(r"(?m)^你已收款[ \t]*,?[ \t]*\n?[ \t]*资金已存入零钱$")
_PERSONAL_DATE = r"\d{4}(?:年|-|/)\d{1,2}(?:月|-|/)\d{1,2}日?[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?"


_BILL_LABELS = {'当前状态', '支付时间', '付款时间', '交易时间', '商品', '商户全称', '收单机构', '支付方式',
                '付款方式', '交易单号', '商户单号', '经营单号', '收款方备注', '收款详情'}
_BILL_DATETIME = re.compile(r"(\d{4}(?:年\d{1,2}月\d{1,2}日[ T]*|[-/]\d{1,2}[-/]\d{1,2}[ T]+)\d{1,2}:\d{2}(?::\d{2})?)")


def _wechat_bill_column(lines: list[str]) -> tuple[str, str] | None:
    """A labels-then-values WeChat bill whose values wrapped, so no table can be restored.

    Use only facts that do not depend on pairing a value with its label: the single success
    status, and the single date-time on the page when the label column has exactly one time
    field. Amount and payee still come from the headline debit and title.
    """
    if '当前状态' not in lines:
        return None
    start = lines.index('当前状态')
    end = start
    while end < len(lines) and lines[end] in _BILL_LABELS:
        end += 1
    block = lines[start:end]
    times = [label for label in block if label.endswith('时间')]
    if (len(block) < 4 or len(times) != 1 or end == len(lines)
            or lines[end] not in {'支付成功', '付款成功', '交易成功'}):
        return None
    # A readable creation/completion time elsewhere cannot stand in for a missing
    # payment value. Include unfamiliar time labels outside the restored block.
    page_times = [line for line in lines if re.match(r'^[\u4e00-\u9fff]{1,12}时间(?:[:\s\d]|$)', line)]
    if page_times != times:
        return None
    states = [line for line in lines if line in {'支付成功', '付款成功', '交易成功'}]
    stamps = [m[1] for line in lines for m in _BILL_DATETIME.finditer(line)]
    standalone_stamp = any(_BILL_DATETIME.match(line) for line in lines)
    if len(states) != 1 or lines.index(states[0]) < end:
        return None
    return states[0], stamps[0] if len(stamps) == 1 and standalone_stamp else ""  # otherwise review


def _personal_stamp(raw: str) -> str:
    raw = raw.replace('年', '-').replace('月', '-').replace('日', ' ').replace('/', '-')
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?=[ T])",
                 lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", raw)
    raw = re.sub(r"([ T])(\d)(?=:\d{2})", lambda m: m[1] + m[2].zfill(2), raw, count=1)
    try:
        stamp = datetime.fromisoformat(raw)
        if not re.search(r"\d{1,2}:\d{2}", raw):
            raise ValueError
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone(timedelta(hours=8)))).isoformat()
    except ValueError:
        raise PaymentTextError("个人收付款时间格式不明确，请核对详情") from None


def _accepted_transfer(text: str, accounts, funding_aliases) -> dict:
    """WeChat '你已收款，资金已存入零钱' page: one unsigned ¥ headline and a received time; no counterparty shown."""
    # Known two-label column: both labels first, then their values in the same order.
    text = re.sub(rf"(?m)^(转账时间|收款时间)\n(转账时间|收款时间)\n({_PERSONAL_DATE})\n({_PERSONAL_DATE})$",
                  lambda m: f"{m[1]} {m[3]}\n{m[2]} {m[4]}" if m[1] != m[2] else m[0], text)
    compact = re.sub(r"\s+", "", text)
    if re.search(r"失败|退款|待收款|未收款|已退还|已退回|交易关闭|USD|EUR|HKD|JPY|美元|欧元|港币|日元|\$|€", compact, re.I):
        raise PaymentTextError("个人收付款状态或币种不支持，请使用手动表单核对")
    # Apple OCR has read this headline ¥ as '*' (2026-10-22). Direction comes from the
    # '你已收款' status, not from the symbol, so the misread cannot flip it.
    amounts = re.findall(r"(?m)^[¥￥*][ \t]*(\d+(?:\.\d{1,2})?)$", text)
    signed = re.findall(r"(?m)^[+−-][ \t]*[¥￥]?[ \t]*\d", text)
    if len(amounts) != 1 or signed:
        raise PaymentTextError("收款金额不明确，请核对截图")
    amount = Decimal(amounts[0])
    if amount <= 0 or amount > 1_000_000_000:
        raise PaymentTextError("个人收付款金额超出支持范围")
    times = _values(text, "收款时间|到账时间")
    if len(times) > 1:
        raise PaymentTextError("个人收付款时间有多项，请核对详情")
    # The sender's transfer time is never a substitute for a missing received time.
    happened_at = _personal_stamp(times[0]) if times else ""
    wallet = (funding_aliases or {}).get("零钱", "零钱")  # explicit destination in the status line
    matched = [name for name, currency in accounts if wallet == name and (currency or 'CNY') == 'CNY']
    return {
        "engine": "rules", "requires_confirmation": True,
        "receipt_kind": "personal_incoming", "source_id": None,
        "warnings": ["个人往来用途需核对；不会自动作为消费或收入保存"],
        "tx_drafts": [{"type": "income", "amount": float(amount), "currency": "CNY",
                       "happened_at": happened_at, "category_name": "", "account_name": matched[0] if len(matched) == 1 else "",
                       "from_account_name": None, "to_account_name": None,
                       "note": "微信转账收款", "tags": [], "confidence": "medium"}],
    }


def _personal_review(text: str, accounts, funding_aliases) -> dict | None:
    """Two explicit personal receipt families, always reviewed, never unattended writes."""
    incoming = re.findall(r"(?m)^转账[ \t]*[-—][ \t]*来自([^\n:]{1,120})$", text)
    group = re.findall(r"(?m)^群收款[ \t]*[-—][ \t]*转给([^\n:]{1,120})$", text)
    if _ACCEPTED_TRANSFER.search(text):
        if incoming or group:
            raise PaymentTextError("发现多笔个人收付款，请一次采集一笔")
        return _accepted_transfer(text, accounts, funding_aliases)
    if not incoming and not group:
        return None
    if len(incoming) + len(group) != 1:
        raise PaymentTextError("发现多笔个人收付款，请一次采集一笔")
    # Same known-column alternative as the existing QR adapter. Match a whole
    # labelled table and typed values; unknown column orders stay unrecognized.
    date_value = r"\d{4}(?:年|-|/)\d{1,2}(?:月|-|/)\d{1,2}日?[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?"
    order_value = r"[A-Za-z0-9_-]{8,100}(?:\n\d{1,8})?"
    if incoming:
        labels = ['当前状态', '转账说明', '转账时间', '收款时间', '转账单号', '零钱余额']
        patterns = [r"已存入零钱|已收款|收款成功", r"[^\n]{1,255}", date_value, date_value, order_value, r"\d+(?:\.\d{1,2})?"]
    else:
        labels = ['当前状态', '收款详情', '支付时间', '支付方式', '交易单号', '商户单号', '零钱余额']
        patterns = [r"支付成功|付款成功|交易成功", r"[^\n]{1,255}", date_value, r"[^\n]{1,255}", order_value, order_value, r"\d+(?:\.\d{1,2})?"]
    table = r"(?m)^" + '\n'.join(labels) + '\n' + '\n'.join(f"(?P<v{i}>{p})" for i, p in enumerate(patterns)) + '$'
    text = re.sub(table, lambda m: '\n'.join(label+' '+m[f'v{i}'].replace('\n', '') for i, label in enumerate(labels)), text)
    compact = re.sub(r"\s+", "", text)
    if re.search(r"失败|退款|待支付|待付款|待收款|未支付|交易关闭|已退还|已退回|USD|EUR|HKD|JPY|美元|欧元|港币|日元|\$|€", compact, re.I):
        raise PaymentTextError("个人收付款状态或币种不支持，请使用手动表单核对")
    states = _values(text, "当前状态")
    expected_states = {"已存入零钱", "已收款", "收款成功"} if incoming else {"支付成功", "付款成功", "交易成功"}
    if len(states) != 1 or states[0] not in expected_states:
        raise PaymentTextError("未明确识别个人收付款的完成状态，请采集完整详情")
    # A signed transaction headline is mandatory. Never treat a wallet balance
    # or a standalone unsigned number as the transaction amount/direction.
    signed = re.findall(r"(?m)^([+−-])[ \t]*[¥￥]?[ \t]*(\d+(?:\.\d{1,2})?)$", text)
    currency_lines = re.findall(r"(?m)^[¥￥][^\n]+$", text)
    expected_sign = '+' if incoming else '-'
    if len(signed) != 1 or currency_lines or signed[0][0].replace('−', '-') != expected_sign:
        raise PaymentTextError("收付款方向或单笔金额不明确，请核对正负号")
    amount = Decimal(signed[0][1])
    if amount <= 0 or amount > 1_000_000_000:
        raise PaymentTextError("个人收付款金额超出支持范围")
    # Received time is not the sender's initiation time. Missing receipt time
    # remains missing and must be completed in the existing editor.
    times = _values(text, "收款时间|到账时间" if incoming else "支付时间|付款时间")
    happened_at = ""
    if len(times) > 1:
        raise PaymentTextError("个人收付款时间有多项，请核对详情")
    if times:
        raw = times[0].replace('年', '-').replace('月', '-').replace('日', ' ').replace('/', '-')
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?=[ T])",
                     lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", raw)
        raw = re.sub(r"([ T])(\d)(?=:\d{2})", lambda m: m[1] + m[2].zfill(2), raw, count=1)
        try:
            stamp = datetime.fromisoformat(raw)
            if not re.search(r"\d{1,2}:\d{2}", raw):
                raise ValueError
            happened_at = (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone(timedelta(hours=8)))).isoformat()
        except ValueError:
            raise PaymentTextError("个人收付款时间格式不明确，请核对详情") from None
    funding = _funding_values(text)
    if incoming and not funding and states[0] == "已存入零钱":
        funding = ["零钱"]  # Explicit destination in the status, not channel inference.
    wallet = (funding_aliases or {}).get(funding[0], funding[0]) if len(funding) == 1 else None
    matched = [name for name, currency in accounts if wallet == name and (currency or 'CNY') == 'CNY']
    return {
        "engine": "rules", "requires_confirmation": True,
        "receipt_kind": "personal_incoming" if incoming else "group_payment", "source_id": None,
        "warnings": ["个人往来用途需核对；不会自动作为消费或收入保存"],
        "tx_drafts": [{"type": "income" if incoming else "expense", "amount": float(amount), "currency": "CNY",
                       "happened_at": happened_at, "category_name": "", "account_name": matched[0] if len(matched) == 1 else "",
                       "from_account_name": None, "to_account_name": None,
                       "note": (incoming or group)[0], "tags": [], "confidence": "medium"}],
    }


def parse_payment_text(text: str, *, accounts: list[tuple[str, str | None]],
                       campus_topup_as_expense: bool = False,
                       alipay_saving_as_excluded_expense: bool = False,
                       funding_aliases: dict[str, str] | None = None,
                       default_category: str = "", channel_account: str = "") -> dict:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = without_payment_service_hints(text)
    text, glyph_review = _normalize_ocr_lines(text)
    amount_symbol_repaired = glyph_review
    time_label_recovered = False
    text, column_review = _restore_displaced_columns(text)
    if re.search(r"(?m)^(?:入账未通过$|服务器返回[:：]|请先核对账本)", text):
        raise PaymentTextError("截图包含记账报错弹窗，请关闭弹窗后采集原付款页面")
    # Canonicalize an entire success heading only. OCR may space its Chinese
    # characters; arbitrary prose mentioning success must not become a status.
    for phrase in ("支付成功", "付款成功", "交易成功"):
        text = re.sub(r"(?m)^" + r"[ \t\n]*".join(phrase) + r"[ \t]*$", phrase, text)
    from .alipay_rules import parse_alipay_text
    alipay = parse_alipay_text(text, accounts=accounts, funding_aliases=funding_aliases,
                              default_category=default_category, channel_account=channel_account,
                              error_type=PaymentTextError, saving_as_excluded_expense=alipay_saving_as_excluded_expense)
    if alipay is not None:
        return alipay
    personal = _personal_review(text, accounts, funding_aliases)
    if personal:
        if channel_account:
            personal['tx_drafts'][0]['account_name'] = channel_account
        personal['evidence'] = {'amount_symbol_repaired': amount_symbol_repaired,
                                'time_label_recovered': False, 'field_order_restored': column_review}
        return personal
    qr_merchants = re.findall(r"(?m)^(?:扫码|扫二维码)付款[ \t]*[-—][ \t]*给?([^\n]{1,120})$", text)
    qr_debits = re.findall(r"(?m)^(-[ \t]*[¥￥]?[ \t]*[\d,.]+)$", text)
    if len(qr_merchants) == len(qr_debits) == 1:
        # OCR can preserve the entire left table column before its right one.
        # Rebuild only the complete known label order and typed date/ID tail;
        # never attach a distant success word to an arbitrary table.
        table = (
            r"(?m)^当前状态\n收款方备注\n支付方式\n转账时间\n转账单号\n"
            r"(?P<state>支付成功|付款成功|交易成功)\n"
            r"(?P<remark>[^\n]{1,255})\n(?P<funding>[^\n]{1,255})\n"
            r"(?P<stamp>\d{4}(?:年|-|/)\d{1,2}(?:月|-|/)\d{1,2}日?[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)\n"
            r"(?P<order>[A-Za-z0-9_-]{8,100})$"
        )
        text = re.sub(table, lambda m: (
            "当前状态\n" + m["state"] + "\n收款方备注\n" + m["remark"]
            + "\n支付方式\n" + m["funding"] + "\n转账时间\n" + m["stamp"]
            + "\n转账单号\n" + m["order"]
        ), text)
        partial_table = (r'(?m)^当前状态\n收款方备注\n支付方式\n转账时间\n转账单号\n'
            r'(?:支付成功|付款成功|交易成功)\n二维码收款\n[^\n]{1,255}\n'
            r'(?P<stamp>[^\n]{1,100})\n[A-Za-z0-9_-]{8,100}$')
        if re.search(partial_table, text):
            raise PaymentTextError('扫码付款的日期字符无法读取，需要从截图补读；未采用当前时间')
        state_label = r"当[ \t]*前[ \t]*状[ \t]*态"
        success = "|".join(r"[ \t]*".join(p) for p in ("支付成功", "付款成功", "交易成功"))
        text = re.sub(rf"(?m)^{state_label}[ \t]*:?[ \t]*\n?({success})[ \t]*$",
                      lambda m: "当前状态\n" + re.sub(r"\s+", "", m[1]), text)
    compact = re.sub(r"\s+", "", text)
    qr_statuses = re.findall(r"(?m)^当前状态[ \t]*:?[ \t]*\n?(支付成功|付款成功|交易成功)$", text)
    qr_payment = len(qr_merchants) == len(qr_debits) == len(qr_statuses) == 1
    lines = text.splitlines()
    bill_states = _values(text, "当前状态")
    bill_debits = re.findall(r"(?m)^((?:-[ \t]*[¥￥]?|[¥￥][ \t]*-)[ \t]*[\d,.]+)$", text)
    bill_times = _values(text, "支付时间|付款时间|交易时间")
    column = _wechat_bill_column(lines) if not bill_states and not bill_times else None
    column_time = column[1] if column else ""
    if column:
        bill_states, bill_times = [column[0]], [column_time]
    paid_bill = (bool({"账单", "交易详情"}.intersection(lines))
                 and len(bill_debits) == len(bill_states) == 1
                 and bill_states[0] in {"支付成功", "付款成功", "交易成功"}
                 and (column is not None
                      or len(bill_times) == 1 and bool(re.search(r"\d{1,2}:\d{2}", bill_times[0]))))
    # A known action under the bill-service section is not a refund status.
    # Keep every other line, including refund/transfer status in the footer;
    # never discard an arbitrary footer or a previous error dialog.
    status_text = payment_status_evidence(text)
    if qr_payment:
        # An explicit QR debit receipt calls its metadata "transfer time/id".
        # Normalize only those field labels; retain actual transfer/refund text.
        status_text = re.sub(r"(?m)^转账(时间|单号)(?=[ \t:]|$)", r"付款\1", status_text)
    if re.search(r"支付失败|付款失败|交易失败|待支付|待付款|等待付款|退款|转账|提现|信用卡还款|未支付|交易关闭", re.sub(r"\s+", "", status_text)):
        # Structural counters only: no OCR lines, amounts, names, dates, IDs,
        # account values or request text. Diagnose layout without a bill dump.
        shape = {
            "qr_title_count": len(qr_merchants), "qr_debit_count": len(qr_debits),
            "qr_status_count": len(qr_statuses),
            "success_count": len(re.findall(r"支付成功|付款成功|交易成功", compact)),
            "negative_types": sorted(set(re.findall(r"支付失败|付款失败|交易失败|待支付|待付款|等待付款|退款|转账|提现|信用卡还款|未支付|交易关闭", re.sub(r"\s+", "", status_text)))),
            "unicode_debit_count": len(re.findall(r"(?m)^[−–—][ \t]*[¥￥]?[ \t]*[\d,.]+$", text)),
            "transfer_time_label_count": len(re.findall(r"转\s*账\s*时\s*间", text)),
            "transfer_id_label_count": len(re.findall(r"转\s*账\s*单\s*号", text)),
            "joined_transfer_time_count": len(re.findall(r"(?m)^转账时间\d", text)),
            "joined_transfer_id_count": len(re.findall(r"(?m)^转账单号[A-Za-z0-9]", text)),
            "status_label_count": len(re.findall(r"当\s*前\s*状\s*态", text)),
        }
        logging.getLogger(__name__).warning("ocr.rules.guard_rejected shape=%s", json.dumps(shape, ensure_ascii=False))
        raise PaymentTextError("当前仅支持成功消费；失败、退款和转账请用原生表单核对")
    products = _values(text, '商品')
    campus_program = re.search(r'(?m)^商家小程序\n[^\n]*(?:一卡通|校园卡)[^\n]*$', text)
    campus_topup = "充值" in compact and (bool(re.search(r"(?:一卡通|校园卡)充值", compact))
        or bool(campus_program and len(products) == 1 and re.search(r'(?:一卡通|卡通|校园卡)充值$', products[0])))
    if "充值" in compact and not (campus_topup and campus_topup_as_expense):
        raise PaymentTextError("识别到充值；一卡通充值如需计支出，请明确启用充值按支出选项，其他充值请用原生表单核对")
    if not re.search(r"支付成功|付款成功|交易成功", text):
        raise PaymentTextError("未识别到成功付款状态，请提供完整的支付详情文字")
    if re.search(r"USD|EUR|HKD|JPY|美元|欧元|港币|日元|美金|\$|€", text, re.I):
        raise PaymentTextError("当前规则只处理明确的人民币消费")
    if "微信支付" in text and "支付宝" in text:
        raise PaymentTextError("出现多个支付渠道，请一次提供一笔支付详情")

    actual_paid = _values(text, "实付金额|实际付款|实付")
    amounts = actual_paid or _values(text, "付款金额|支付金额")
    if not amounts:
        amounts = re.findall(r"(?m)^([¥￥][ \t]*[+-]?[\d,.]+(?:\s*元)?)$", text)
        # Some payment-detail pages show a signed debit before their status,
        # rather than an "actual paid" label. Only this explicit layout turns
        # a minus sign into an expense magnitude; never abs() arbitrary amounts.
        signed_line = r"(?:-[ \t]*[¥￥]?|[¥￥][ \t]*-)[ \t]*[\d,.]+"
        headers = re.findall(
            rf"(?m)^({signed_line})\n当前状态[ \t]*:?[ \t]*\n(?:支付成功|付款成功|交易成功)$", text,
        )
        if qr_payment and not headers:
            headers = qr_debits
        if paid_bill and not headers:
            headers = bill_debits
        if headers:
            signed_amounts = re.findall(rf"(?m)^({signed_line})$", text)
            if len(headers) != 1 or len(signed_amounts) != 1:
                raise PaymentTextError("出现多笔支出金额，请一次提供一笔完整支付详情")
            header_amount = re.sub(r"[-¥￥\s]", "", headers[0])
            # Keep any other standalone currency amounts for the ambiguity
            # check below, excluding the same signed header itself.
            amounts = [raw for raw in amounts if raw != headers[0]] + [header_amount]
    parsed = []
    for raw in amounts:
        # Observed iPhone synthetic receipts: ￥0.01 -> "* 0.01" / "· 0.01".
        # Only replace this separated symbol in an explicit actual-paid field.
        # Do not infer masked digits, accept bare stars, or repair letters.
        currency_glyph = re.fullmatch(r"[*·][ \t]+(\d+\.\d{2})", raw)
        if actual_paid and currency_glyph:
            raw = currency_glyph[1]
        match = re.fullmatch(r"[¥￥]?[ \t]*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:元|人民币|CNY)?", raw, re.I)
        if not match:
            raise PaymentTextError("金额格式不明确，请核对实付金额")
        try:
            value = Decimal(match[1].replace(",", ""))
        except InvalidOperation:
            raise PaymentTextError("金额无法读取") from None
        if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2 or value > 1_000_000_000:
            raise PaymentTextError("金额必须为正数且最多两位小数")
        parsed.append(value)
    if not parsed or len(set(parsed)) != 1:
        raise PaymentTextError("实付金额缺失或存在多笔金额，请核对支付详情")

    merchants = _values(text, "收款方|收款商户|商户全称|商家名称|商家")
    if qr_payment:
        merchants = [value for value in merchants if value not in {'留言', '向收款方留言'}]
        merchants += qr_merchants
    # Complete explicit labels take priority over an unlabelled display name.
    merchants += re.findall(r"(?m)^(?:商家名称|商户全称)([^\s:\n][^\n]*)$", text)
    if not merchants and paid_bill and "全部账单" in lines and bill_debits[0] in lines:
        # WeChat bill page: the payee is the title between 全部账单 and the debit.
        # OCR may wrap a long title onto two lines; more than that is not one name.
        top, debit_index = lines.index("全部账单"), lines.index(bill_debits[0])
        titles = [line for line in lines[top + 1:debit_index] if line not in {"收", "支"}]
        if 1 <= len(titles) <= 2 and all(
                len(t) <= 120 and len(re.findall(r"[\u4e00-\u9fffA-Za-z]", t)) >= 2
                and not re.match(r"^(?:当前状态|支付时间|付款时间|交易时间|支付方式|付款方式|交易单号|商户单号|账单|余额)", t)
                for t in titles):
            merchants = [" ".join(titles)]
    if not merchants and paid_bill and "交易详情" in lines:
        # A transaction-detail card can name the counterparty directly under
        # its debit, without a legal-merchant label. Require exactly one name
        # before the first status field; do not join multiple counterparties.
        debit_index = lines.index(bill_debits[0])
        status_indices = [i for i,line in enumerate(lines) if re.match(r"^当前状态(?:[ \t:]|$)", line)]
        if len(status_indices) == 1 and status_indices[0] > debit_index:
            candidates = lines[debit_index + 1:status_indices[0]]
            if (len(candidates) == 1 and 1 < len(candidates[0]) <= 120
                    and re.search(r"[\u4e00-\u9fffA-Za-z]", candidates[0])
                    and not re.match(r"^(?:账单|支付时间|付款时间|交易时间|支付方式|付款方式|交易单号|商户单号|余额)", candidates[0])):
                merchants = candidates
    payment_result = False
    if not merchants:
        # Supplied result-page shape: success heading, one masked payee,
        # one explicit RMB amount, and a Done action. The payee is review
        # data, never proof of merchant/category/account or funding source.
        lines = text.splitlines()
        statuses = [i for i, line in enumerate(lines) if line in {"支付成功", "付款成功", "交易成功"}]
        amounts_at = [i for i, line in enumerate(lines) if re.fullmatch(r"[¥￥][ \t]*\d+(?:\.\d{1,2})?", line)]
        if len(statuses) == len(amounts_at) == 1 and statuses[0] < amounts_at[0] and "完成" in lines[amounts_at[0] + 1:]:
            candidates = [line for line in lines[statuses[0] + 1:amounts_at[0]]
                          if re.fullmatch(r"[^():\n]{1,40}\s*\(\*{1,6}[\u4e00-\u9fffA-Za-z·]{1,10}\)", line)]
            if len(candidates) == 1:
                merchants = candidates
                payment_result = True
    if len(set(merchants)) != 1:
        raise PaymentTextError("收款商家缺失或存在多笔商家，请核对支付详情")
    merchant = merchants[0]
    warnings = []
    if campus_topup:
        warnings.append("已选择充值时计支出；以后校园卡刷卡请勿重复记支出，其他入口不会自动排除重复账目")
    times = _values(text, "交易时间|付款时间|支付时间")
    if not times and column_time:
        times = [column_time]
    if qr_payment:
        times += _values(text, "转账时间")
        if not times and text.splitlines().count('转账时间') == 1:
            candidates = re.findall(r'(?m)^\d{4}(?:年|-|/)\d{1,2}(?:月|-|/)\d{1,2}日?[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?$', text)
            if len(candidates) == 1:
                times = candidates
                glyph_review = True
                time_label_recovered = True
    happened_at = ""
    if len(set(times)) == 1:
        raw_time = times[0].replace("年", "-").replace("月", "-").replace("日", " ").replace("/", "-").strip()
        raw_time = re.sub(r"\s+", " ", raw_time)
        # A written calendar date may omit leading zeroes. Pad only complete
        # components, leaving invalid dates, missing minutes and OCR letters
        # for datetime validation rather than inventing missing digits.
        raw_time = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?=[ T])",
                          lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", raw_time)
        raw_time = re.sub(r"([ T])(\d)(?=:\d{2})", lambda m: m[1] + m[2].zfill(2), raw_time, count=1)
        try:
            stamp = datetime.fromisoformat(raw_time)
            if not re.search(r"\d{1,2}:\d{2}", raw_time):
                raise ValueError("time missing")
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
            happened_at = stamp.isoformat()
        except ValueError:
            warnings.append("付款时间无法读取，请在草稿中核对")
    else:
        warnings.append("付款时间缺失或有歧义，请在草稿中核对；未自动采用当前时间")

    funding = _funding_values(text)
    wallet = None
    if len(set(funding)) == 1:
        value = funding[0]
        if funding_aliases and value in funding_aliases:
            wallet = funding_aliases[value]
        elif value in {"零钱", "微信零钱"} and "微信支付" in text:
            wallet = "微信零钱"
        elif value in {"余额", "支付宝余额"} and "支付宝" in text:
            wallet = "支付宝余额"
        else:
            # A card name is accepted only as an exact existing account name.
            wallet = value
    matches = [name for name, currency in accounts
               if wallet and name == wallet and (currency or "CNY") == "CNY"]
    account = matches[0] if len(matches) == 1 else ""
    if not account:
        warnings.append("未唯一匹配已有付款账户，请手动选择；不会按支付渠道猜余额或新建账户")
    warnings.append(f"分类采用你设置的默认值：{default_category}" if default_category
                    else "分类请在原生草稿中选择；规则未按商家猜测分类")
    orders = _values(text, "交易单号|交易号|订单号")
    if qr_payment:
        orders += _values(text, "转账单号")
    # OCR may join a complete order label to its identifier. Keep the label,
    # character and length requirements; never promote a bare identifier.
    orders += re.findall(r"(?m)^(?:交易单号|交易号|订单号)([A-Za-z0-9_-]{8,100})$", text)
    source_id = None
    if len(set(orders)) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{8,100}", orders[0]):
        channel = "wechat" if "微信支付" in text else "alipay" if "支付宝" in text else "unknown"
        source_id = "ocr-" + hashlib.sha256(f"{channel}:{orders[0]}".encode()).hexdigest()
    return {
        "engine": "rules", "requires_confirmation": True, "warnings": warnings,
        "evidence": {'amount_symbol_repaired': amount_symbol_repaired,
                     'time_label_recovered': time_label_recovered, 'field_order_restored': column_review},
        **({"receipt_kind": "layout_review"} if glyph_review or column_review else {"receipt_kind": "payment_result"} if payment_result else {}),
        "source_id": source_id,
        "tx_drafts": [{
            "type": "expense", "amount": float(parsed[0]), "currency": "CNY",
            "happened_at": happened_at, "category_name": default_category, "account_name": channel_account or account,
            "from_account_name": None, "to_account_name": None,
            "note": merchant, "tags": [], "confidence": "medium",
        }],
    }

# Merchant/product keyword hints for OCR expenses. Each rule names candidate category
# names tried against the user's EXISTING categories, in order; nothing is created.
# Rules pointing to different categories are ambiguous and yield nothing.
# (keywords, candidate category names). Multi-character keywords only: single
# characters such as 面/药 match too much unrelated text.
# Each rule lists generic names first (flat category lists keep their earlier
# choice), then the leaves of BeeCount's two-level default tree, whose parents
# (餐饮、交通、娱乐、教育…) have children and so are never usable themselves.
_DINING = ('餐饮美食', '餐饮')
_TRANSPORT = ('交通出行', '交通')
_FUN = ('休闲娱乐', '娱乐')
_EDUCATION = ('教育培训', '教育')
KEYWORD_RULES = (
    (('餐厅', '饭店', '食堂', '小吃', '肯德基', '麦当劳', '必胜客', '汉堡王', '烧烤', '火锅',
      '面馆', '粉店', '包子', '早餐'), (*_DINING, '美食')),
    (('美团外卖',), (*_DINING, '美团外卖')),
    (('饿了么',), (*_DINING, '饿了么外卖')),
    (('京东外卖',), (*_DINING, '京东外卖')),
    (('外卖',), (*_DINING, '美食')),
    (('星巴克', '瑞幸', '咖啡'), (*_DINING, '咖啡')),
    (('奶茶', '蜜雪冰城', '喜茶', '茶百道', '古茗', '沪上阿姨'), (*_DINING, '奶茶')),
    (('地铁',), (*_TRANSPORT, '地铁')),
    (('公交',), (*_TRANSPORT, '公交')),
    (('出租车',), (*_TRANSPORT, '出租车')),
    (('滴滴', '打车'), (*_TRANSPORT, '网约车')),
    (('加油', '中石化', '中石油'), (*_TRANSPORT, '加油')),
    (('停车',), (*_TRANSPORT, '停车费')),
    (('铁路', '12306', '高铁', '航空', '机票', '哈啰', '青桔', '共享单车'), _TRANSPORT),
    (('超市', '便利店', '全家', '罗森', '7-Eleven', '美宜佳', '盒马', '永辉', '沃尔玛', '大润发', '物美',
      '淘宝', '天猫', '京东', '拼多多', '唯品会', '百货'), ('日用百货', '日用', '购物')),
    (('药店', '药房', '大药房', '医院', '诊所', '卫生院', '医药'), ('医疗健康', '医疗')),
    (('话费', '中国移动', '中国联通', '中国电信', '宽带', '流量'), ('通讯物流', '通讯')),
    (('电影', '影城', '影院'), (*_FUN, '电影')),
    (('KTV',), (*_FUN, 'KTV')),
    (('网吧', '游戏'), _FUN),
    (('书店', '教材'), (*_EDUCATION, '书籍')),
    (('培训', '课程'), (*_EDUCATION, '培训费')),
    (('理发', '美发', '美容'), ('美容美发', '美容')),
    (('快递', '顺丰', '邮政', '中通', '圆通', '韵达'), ('通讯物流', '快递')),
)


def _category_norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or '')).lower()


def keyword_category(texts, is_usable):
    """Return the first usable candidate of the single matching rule, else ''.

    `texts` are merchant/product strings; `is_usable(name)` says whether the
    user has exactly one leaf category of that name for this direction. A rule
    hit only through a keyword contained in another rule's longer hit (外卖 in
    美团外卖, 京东 in 京东外卖) is that longer rule's evidence, not a second opinion.
    """
    haystack = ''.join(_category_norm(text) for text in texts if text)
    if not haystack:
        return ''
    hits = [({_category_norm(k) for k in keywords if _category_norm(k) in haystack}, names)
            for keywords, names in KEYWORD_RULES]
    hits = [(found, names) for found, names in hits if found]
    longer = {k for found, _ in hits for k in found}
    matched = [names for found, names in hits
               if any(not any(k != other and k in other for other in longer) for k in found)]
    usable = {next((name for name in names if is_usable(name)), '') for names in matched}
    usable.discard('')
    return usable.pop() if len(usable) == 1 else ''

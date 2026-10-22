"""Bounded adapters for the supplied Alipay receipt families, not general bill guessing."""
import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal

_MONEY = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?'
_FIELDS = ('订单金额', '碰一下立减', '支付时间', '付款时间', '创建时间', '付款方式', '商品说明',
           '收单机构', '清算机构', '收款方全称', '转账备注', '对方账户', '支付奖励', '订单号',
           '商家订单号', '理由', '交易方式', '管理自动扣款', '服务详情', '更多')


def _lines(text):
    text = unicodedata.normalize('NFKC', text).replace('\r', '\n')
    return [line.strip() for line in text.splitlines() if line.strip()]


def alipay_internal_reason(text):
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
    if '支付宝小荷包' in compact and ('自动攒' in compact or '账户存取' in compact):
        return '支付宝小荷包自动攒属于资金划转，先不计消费；请稍后核对用途'
    return ''


def _detail(lines):
    compact = '\n'.join(lines)
    return (sum('账单详情' in line for line in lines) == 1 and '全部账单' in compact
            and any(line.startswith('账单管理') for line in lines) and '计入收支' in lines)


def _checkout(lines):
    return ('支付成功' in lines and '完成' in lines
            and any('支付宝积分' in line for line in lines)
            and any(re.match(r'^交易方式(?:\s|:|$)', line) for line in lines)
            and '余额宝' in '\n'.join(lines))


def alipay_channel_evidence(text):
    lines = _lines(text)
    return _detail(lines) or _checkout(lines)


def _header(lines):
    states = [(i, re.sub(r'^当前状态\s*:\s*', '', line)) for i, line in enumerate(lines)
              if re.fullmatch(r'(?:当前状态\s*:\s*)?(?:交易成功|支付成功|自动扣款成功|等待确认收货)', line)]
    if len(states) != 1:
        return None
    end, state = states[0]
    headers = [(i, re.fullmatch(r'([+−-])[¥￥]?\s*(' + _MONEY + ')', line))
               for i, line in enumerate(lines[:end])]
    headers = [(i, match) for i, match in headers if match]
    if len(headers) != 1:
        return None
    pos, match = headers[0]
    kind = 'income' if match[1] == '+' else 'expense'
    amount = Decimal(match[2].replace(',', ''))
    return pos, end, state, kind, amount


def alipay_visible_amount(text):
    """A discount below the signed transaction header is not a second payment."""
    lines = _lines(text)
    header = _header(lines) if _detail(lines) else None
    return (header[3], header[4]) if header else None


# Consumption labels Alipay displays → names tried against the user's existing
# native categories, in order. Transfer, saving, investment, credit and refund
# labels are deliberately absent: their purpose stays with the default/review path.
# Trailing names are leaves of BeeCount's two-level default tree (its parents are not usable).
CATEGORY_CANDIDATES = {
    '餐饮美食': ('餐饮美食', '餐饮', '美食'), '日用百货': ('日用百货', '日用', '购物'),
    '医疗健康': ('医疗健康', '医疗'), '交通出行': ('交通出行', '交通'),
    '服饰装扮': ('服饰装扮', '服饰', '服装'), '美容美发': ('美容美发', '美容'),
    '休闲娱乐': ('休闲娱乐', '娱乐', '其他娱乐'), '文化休闲': ('文化休闲', '娱乐', '其他娱乐'),
    '教育培训': ('教育培训', '教育'), '住房物业': ('住房物业', '住房'),
    '数码电器': ('数码电器', '数码'), '运动户外': ('运动户外', '运动'),
    '酒店旅游': ('酒店旅游', '旅行'), '母婴亲子': ('母婴亲子', '母婴'),
    '爱车养车': ('爱车养车', '汽车'), '家居家装': ('家居家装', '居家'),
    '宠物': ('宠物',), '通讯物流': ('通讯物流', '通讯'),
}


def _visible_category(lines, end):
    """Alipay's own displayed bill category below 账单管理; never inferred from the merchant."""
    values = []
    for i, line in enumerate(lines[end:], start=end):
        # Upstream normalization joins spaced Chinese, so the value may abut the label.
        match = re.fullmatch(r'账单分类[ \t:]*(.*)', line)
        if not match:
            continue
        value = match[1].strip()
        if not value and i+1 < len(lines):
            value = lines[i+1]  # Column-split OCR: the label precedes its value.
        values.append(re.sub(r'\s*[>〉›]$', '', value))
    if len(values) != 1 or not re.fullmatch(r'[一-鿿]{2,12}', values[0]) or values[0] == '计入收支':
        return ''
    return values[0]


def _method_after_benefits(lines):
    """The 交易方式 value listed after 支付宝积分+N / 体验金+N lines and the payee-row amount."""
    for line in lines[:6]:
        if re.fullmatch(r'[一-鿿A-Za-z]{1,10}[+＋]\d+(?:\.\d+)?', line) or re.fullmatch(r'[¥￥·*]\s*' + _MONEY, line):
            continue
        return line if re.match(r'^(?:余额宝|花呗|账户余额|余额|.{1,12}(?:银行|信用卡|储蓄卡))', line) else ''
    return ''


def parse_alipay_text(text, *, accounts, funding_aliases, default_category, channel_account, error_type,
                      saving_as_excluded_expense=False):
    lines = _lines(text)
    if not (_detail(lines) or _checkout(lines)):
        return None
    if any(marker in text for marker in ('微信支付', '微信转账', '财付通')):
        raise error_type('同一张支付宝账单出现其他支付渠道，请核对原图')
    reason = alipay_internal_reason(text)
    saving = bool(reason and saving_as_excluded_expense)
    if reason and not saving:
        raise error_type(reason)
    if any(re.fullmatch(r'(?:当前状态\s*:\s*)?(?:退款成功|退款中|已退款|已退回|支付失败|付款失败|交易失败)', line)
           for line in lines):
        raise error_type('支付宝存在明确失败或退款状态，请核对原记录')
    if lines.count('支付成功') > 1:
        raise error_type('支付宝出现多笔付款状态，请一次采集一笔')
    detail = _detail(lines)
    end = next(i for i, line in enumerate(lines) if line.startswith('账单管理')) if detail else next(i for i, line in enumerate(lines) if '支付宝积分' in line)
    body = lines[:end]
    compact = ''.join(body)
    if re.search(r'支付失败|交易失败|退款成功|退款中|退款金额|退款时间|已退款|已退回|待付款|等待付款|未支付|交易关闭|提现|信用卡还款|充值|USD|EUR|HKD|JPY|美元|欧元|港币|日元|\$|€', compact, re.I):
        raise error_type('支付宝付款状态、资金用途或币种需核对；不会作为成功消费入账')

    def field(label):
        matches = []
        for i, line in enumerate(body):
            match = re.fullmatch(re.escape(label) + r'(?:\s*:\s*(.*)|[ \t]+(.+)|)', line)
            if not match:
                continue
            value = (match[1] or match[2] or '').strip()
            if not value and i+1 < len(body):
                candidate = body[i+1]
                if not any(re.match('^' + re.escape(other) + r'(?:\s|:|$)', candidate) for other in _FIELDS):
                    value = candidate
            if not value:
                raise error_type('支付宝字段对应关系不明确，请从截图补读')
            matches.append(value)
        if len(matches) > 1:
            raise error_type('支付宝出现重复字段，请一次采集一笔')
        return matches[0] if matches else ''

    warnings = []
    if detail:
        header = _header(body)
        if not header:
            raise error_type('支付宝单笔金额、正负号或完成状态不明确')
        pos, status_pos, state, kind, amount = header
        names = [line for line in body[:pos] if line not in {'账单详情', '全部账单', '账单详情全部账单', '闲鱼', '收'}]
        if len(names) != 1 or not 1 <= len(names[0]) <= 120:
            raise error_type('支付宝收付款对象不明确，请从截图补读')
        note = re.sub(r'\s*[>〉›]$', '', names[0])
        if status_pos != pos + 1:
            raise error_type('支付宝金额与状态对应关系不明确')
        stamp_raw = field('支付时间') or field('付款时间')
        if kind == 'income':
            if state != '交易成功' or not field('转账备注') or not field('对方账户'):
                raise error_type('支付宝收款状态或对方信息不完整')
            if not stamp_raw:
                stamp_raw = field('创建时间')
                warnings.append('账目时间采用页面创建时间；不声称这是实际到账时间')
        elif state == '等待确认收货':
            if not all((stamp_raw, field('付款方式'), field('商品说明'), field('订单号'), field('商家订单号'))):
                raise error_type('尚待收货的订单缺少明确付款凭据，不自动记支出')
        elif state == '自动扣款成功':
            stamp_raw = stamp_raw or field('创建时间')
        elif state not in {'交易成功', '支付成功'}:
            raise error_type('支付宝尚未明确付款成功')
        order, reduction = field('订单金额'), field('碰一下立减')
        if order:
            if not re.fullmatch(_MONEY, order) or reduction and not re.fullmatch('-' + _MONEY, reduction):
                raise error_type('支付宝订单金额或优惠格式不明确')
            if Decimal(order.replace(',', '')) + Decimal((reduction or '0').replace(',', '')) != amount:
                raise error_type('支付宝实付与订单金额、优惠存在冲突，请核对')
    else:
        statuses = [i for i, line in enumerate(body) if line == '支付成功']
        # The success page never shows a sign (it is always a payment), so Apple OCR reading
        # the ¥ as '·' or '*' (2026-10-22) cannot change direction; amounts must still agree.
        amounts = [(i, re.fullmatch(r'[¥￥·*]\s*(' + _MONEY + ')', line)) for i, line in enumerate(body)]
        amounts = [(i, match) for i, match in amounts if match]
        if len(statuses) != 1 or not amounts or not statuses[0] < amounts[0][0]:
            raise error_type('支付宝付款成功页金额不明确')
        amount = Decimal(amounts[0][1][1].replace(',', ''))
        if len(amounts) > 2 or any(Decimal(match[1].replace(',', '')) != amount for _, match in amounts):
            raise error_type('支付宝成功页出现多笔不同金额，请核对')
        pos = amounts[0][0]
        end_name = next((i for i, line in enumerate(body) if re.match(r'^交易方式(?:\s|:|$)', line)), len(body))
        names = [line for line in body[pos+1:end_name] if not re.fullmatch(r'[¥￥·*]\s*' + _MONEY, line)]
        # OCR may list the 交易方式 label before the points/benefit lines and its value after them.
        method = (_method_after_benefits(lines[end:]) if body and re.fullmatch(r'交易方式[ \t:]*', body[-1])
                  else field('交易方式'))
        if len(names) != 1 or not 1 <= len(names[0]) <= 120 or not method:
            raise error_type('支付宝成功页收款对象或交易方式不明确')
        note, kind, stamp_raw = names[0], 'expense', ''
        same_row = re.fullmatch(r'(.{1,120}?)[ \t]+[¥￥·*]\s*(' + _MONEY + ')', note)
        if same_row:
            if Decimal(same_row[2].replace(',', '')) != amount:
                raise error_type('支付宝成功页收款行金额与实付不一致')
            note = same_row[1]
    if not 0 < amount <= 1_000_000_000:
        raise error_type('支付宝金额超出支持范围')
    stamp = ''
    if stamp_raw:
        raw = stamp_raw.replace('年', '-').replace('月', '-').replace('日', ' ').replace('/', '-')
        try:
            if not re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}[ T]+\d{1,2}:\d{2}:\d{2}', raw.strip()):
                raise ValueError
            value = datetime.strptime(re.sub(r'\s+', ' ', raw.strip()).replace('T', ' '), '%Y-%m-%d %H:%M:%S')
            stamp = value.replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
        except ValueError:
            raise error_type('支付宝账目日期无法读取，需要从截图补读；未采用当前时间') from None
    funding = re.sub(r'\s*[>〉›]$', '', field('付款方式') if detail else method)
    wallet = (funding_aliases or {}).get(funding, funding)
    matches = [name for name, currency in accounts if name == wallet and (currency or 'CNY') == 'CNY']
    order = field('订单号') if detail else ''
    if order and not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', order):
        raise error_type('支付宝订单号格式不明确')
    return {'engine': 'rules', 'requires_confirmation': True, 'warnings': warnings,
            'receipt_kind': 'alipay_saving' if saving else 'payment_result' if not detail else 'personal_incoming' if kind == 'income' else 'alipay_detail',
            'source_id': 'ocr-' + hashlib.sha256(('alipay:' + order).encode()).hexdigest() if order else None,
            'visible_category': _visible_category(lines, end) if detail else '',
            'evidence': {'amount_symbol_repaired': False, 'time_label_recovered': False, 'field_order_restored': False},
            'tx_drafts': [{'type': kind, 'amount': float(amount), 'currency': 'CNY', 'happened_at': stamp,
                           'category_name': default_category if kind == 'expense' else '',
                           'account_name': channel_account or (matches[0] if len(matches) == 1 else ''),
                           **({'exclude_from_stats': True, 'exclude_from_budget': True} if saving else {}),
                           'from_account_name': None, 'to_account_name': None,
                           'note': note, 'tags': [], 'confidence': 'medium'}]}

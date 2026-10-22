"""Vision transcriptions may put raw newlines inside the JSON "text" string (2026-10-22 Alipay captures)."""
import pytest

from src.services.ai.provider_client import _try_parse_json

RAW = '{"transaction_count":1,"text":"账单详情\n-12.00\n交易成功"}'


@pytest.mark.parametrize('content', [
    RAW,                                           # raw newline inside the string
    '```json\n' + RAW + '\n```',                   # fenced
    '以下是转录结果：\n' + RAW + '\n以上。',          # prose around it
    RAW.replace('\n', '\t'),                       # raw tab
])
def test_raw_control_characters_inside_strings_still_parse(content):
    parsed = _try_parse_json(content)
    assert parsed is not None and parsed['transaction_count'] == 1
    assert parsed['text'].startswith('账单详情') and parsed['text'].endswith('交易成功')
    assert '-12.00' in parsed['text']


@pytest.mark.parametrize('content', ['', '没有找到交易', '{"transaction_count":1,"text":"未闭合'])
def test_genuinely_unparseable_output_is_still_rejected(content):
    assert _try_parse_json(content) is None

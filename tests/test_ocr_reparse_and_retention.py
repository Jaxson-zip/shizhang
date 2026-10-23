"""User decision 2026-10-22: keep auto-booked screenshots 48h; free rules-only re-read of pending captures."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from test_ai_parse_tx import _make_client
from test_ocr_image_retention import IMAGE
from test_ocr_trigger import setup_trigger
from test_ocr_wechat_transfer_received import INLINE

from src.database import get_db
from src.main import app


def _channel(client, headers, ledger, account, expense):
    """The user's real setting: channel bookkeeping, where automatic captures are recorded."""
    income = client.post('/api/v1/write/ledgers/' + ledger + '/categories', headers=headers,
        json={'base_change_id': 0, 'name': '其他收入', 'kind': 'income'}).json()['entity_id']
    config = {'ocr_rules': {'ledgers': {ledger: {'accounting_mode': 'channel', 'wechat_account_id': account,
        'default_expense_category_id': expense, 'default_income_category_id': income}}}}
    assert client.patch('/api/v1/profile/me', headers=headers, json={'ai_config': config}).status_code == 200


def _hours_left(expires_at):
    return (datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).total_seconds() / 3600


def test_auto_booked_capture_keeps_its_screenshot_48_hours_and_lists_it_as_recent(tmp_path, monkeypatch):
    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path / 'previews.sqlite')
    client = _make_client()
    try:
        headers, ledger, account, expense, body = setup_trigger(client, 'auto-picture@example.invalid')
        _channel(client, headers, ledger, account, expense)
        body.update(review_policy='deferred', vision_fallback=True, image_base64=IMAGE)
        booked = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert booked.status_code == 200, booked.text
        page = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger, 'state': 'recent'}).json()
        assert page['recent_total'] == 1 and page['pending_total'] == 0
        item = page['items'][0]
        assert item['status'] == 'confirmed' and item['entity_id'] == booked.json()['entity_id']
        assert item['image']['available'] is True and 47.9 < _hours_left(item['image']['expires_at']) <= 48
        assert client.get('/api/v1/ai/ocr-inbox/' + item['id'] + '/image', headers=headers).status_code == 200
        # The hourly sweep keeps it until its own expiry; it is not a pending-only picture any more.
        ocr_images.cleanup(next(app.dependency_overrides[get_db]()))
        assert ocr_images.usage()['count'] == 1
        # A pending capture still keeps its picture for the 7-day review window.
        body.update(text='合成无法识别文字', request_id=str(uuid.uuid4()))
        from unittest.mock import AsyncMock, patch
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', AsyncMock(side_effect=ValueError('synthetic'))):
            pending = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert pending.status_code == 202
        detail = client.get('/api/v1/ai/ocr-inbox/' + pending.json()['capture_id'], headers=headers).json()
        assert _hours_left(detail['image']['expires_at']) > 7 * 24 - 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_quota_eviction_drops_the_soonest_expiring_picture_first(tmp_path, monkeypatch):
    import base64

    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path / 'previews.sqlite')
    monkeypatch.setattr(ocr_images, 'USER_BYTES', 2 * len(base64.b64decode(IMAGE)))
    assert ocr_images.retain('pending-review', 'a', IMAGE)                       # 7 days
    assert ocr_images.retain('auto-booked', 'a', IMAGE, ttl=ocr_images.AUTO_TTL_SECONDS)
    assert ocr_images.retain('newest', 'a', IMAGE)
    assert ocr_images.read('pending-review', 'a') is not None
    assert ocr_images.read('auto-booked', 'a') is None


def _capture_unrecognized_received_page(client, headers, ledger, monkeypatch):
    """Simulate a capture taken before the accepted-transfer rule existed."""
    from src.services import payment_rules
    now = datetime.now(timezone(timedelta(hours=8)))
    text = re.sub(r'2026年10月17日 12:03:04', now.strftime('%Y年%m月%d日 %H:%M:%S'), INLINE)
    with monkeypatch.context() as patched:
        patched.setattr(payment_rules, '_ACCEPTED_TRANSFER', re.compile(r'(?!)'))
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
            'ledger_id': ledger, 'text': text, 'request_id': str(uuid.uuid4()), 'review_policy': 'deferred'})
    assert response.status_code == 202, response.text
    return '/api/v1/ai/ocr-inbox/' + response.json()['capture_id']


def test_rules_reparse_books_a_decisive_reading_once_without_a_model(monkeypatch):
    # User request 2026-10-22: a decisive rules reading is booked, not left for another confirmation.
    from unittest.mock import AsyncMock, patch
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rules-reparse@example.invalid')
        _channel(client, headers, ledger, account, expense)
        path = _capture_unrecognized_received_page(client, headers, ledger, monkeypatch)
        before = client.get(path, headers=headers).json()
        assert before['draft'] is None
        action = {'expected_revision': before['revision'], 'action_id': str(uuid.uuid4())}
        model = AsyncMock()
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', model):
            result = client.post(path + '/reparse', headers=headers, json=action)
            assert result.status_code == 200, result.text
            assert client.post(path + '/reparse', headers=headers, json=action).status_code == 200  # same action replays
            assert client.post(path + '/reparse', headers=headers,
                               json={**action, 'action_id': str(uuid.uuid4())}).status_code == 409  # stale revision
        assert model.await_count == 0
        assert '已自动入账' in result.json()['message']
        rows = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == 'income' and rows[0]['amount'] == 48
        assert rows[0]['exclude_from_stats'] is False
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_rules_reparse_that_still_fails_changes_nothing_and_booked_captures_are_refused():
    client = _make_client()
    try:
        headers, ledger, account, expense, body = setup_trigger(client, 'rules-reparse-fail@example.invalid')
        _channel(client, headers, ledger, account, expense)
        failed = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
            'ledger_id': ledger, 'text': '合成无法识别文字', 'request_id': str(uuid.uuid4()), 'review_policy': 'deferred'})
        path = '/api/v1/ai/ocr-inbox/' + failed.json()['capture_id']
        before = client.get(path, headers=headers).json()
        result = client.post(path + '/reparse', headers=headers,
                             json={'expected_revision': before['revision'], 'action_id': str(uuid.uuid4())})
        assert result.status_code == 200 and '仍无法识别' in result.json()['message']
        assert result.json()['draft'] is None and result.json()['reason'] == before['reason']
        body.update(review_policy='deferred')
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).status_code == 200
        booked = client.get('/api/v1/ai/ocr-inbox', headers=headers,
                            params={'ledger_id': ledger, 'state': 'recent'}).json()['items'][0]
        assert client.post('/api/v1/ai/ocr-inbox/' + booked['id'] + '/reparse', headers=headers, json={
            'expected_revision': booked['revision'], 'action_id': str(uuid.uuid4())}).status_code == 409
    finally:
        client.close()
        app.dependency_overrides.clear()

"""User request 2026-10-22: pending captures are re-read with the current rules automatically and
booked like a fresh decisive capture, instead of waiting for a manual confirmation."""
import asyncio
from unittest.mock import AsyncMock, patch

from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_image_retention import IMAGE
from test_ocr_reparse_and_retention import _capture_unrecognized_received_page, _channel
from test_ocr_trigger import setup_trigger

from src.database import get_db
from src.main import app
from src.routers.ai.parse_tx_text import rebook_pending
from src.services.ocr_capture import OcrCapture


def _run(db):
    return asyncio.run(rebook_pending(db))


def _rows(client, headers, ledger):
    return client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()


def test_unbooked_capture_that_current_rules_read_is_booked_once(monkeypatch):
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rebook-unbooked@example.invalid')
        _channel(client, headers, ledger, account, expense)
        path = _capture_unrecognized_received_page(client, headers, ledger, monkeypatch)
        assert _rows(client, headers, ledger) == []
        db = next(app.dependency_overrides[get_db]())
        outcome = _run(db)
        assert outcome.get('booked') == 1, outcome
        rows = _rows(client, headers, ledger)
        assert len(rows) == 1 and rows[0]['tx_type'] == 'income' and rows[0]['exclude_from_stats'] is False
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
        assert _run(db).get('booked', 0) == 0                       # a later sweep never books it again
        assert len(_rows(client, headers, ledger)) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def _vision_provisional(client, email, store_text=None):
    headers, ledger, account, expense, body = setup_trigger(client, email)
    _channel(client, headers, ledger, account, expense)
    uid = client.get('/api/v1/profile/me', headers=headers).json()['user_id']
    _seed_ai_config(uid, vision_model='glm-4.6v-flash')
    import json

    from src.models import UserProfile
    db = next(app.dependency_overrides[get_db]())
    profile = db.query(UserProfile).filter(UserProfile.user_id == uid).one()
    config = json.loads(profile.ai_config_json)
    config['ocr_rules'] = {'ledgers': {ledger: {'accounting_mode': 'channel', 'wechat_account_id': account,
                                                'default_expense_category_id': expense}}}
    profile.ai_config_json = json.dumps(config)
    db.commit()
    original = body['text']
    body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                vision_fallback=True, image_base64=IMAGE)
    with patch('src.services.ai.payment_vision.call_chat_json',
               AsyncMock(return_value={'text': original, 'transaction_count': 1})):
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
    assert response.status_code == 202, response.text
    rows = _rows(client, headers, ledger)
    assert len(rows) == 1 and rows[0]['exclude_from_stats'] is True    # provisional, waiting for review
    capture = db.get(OcrCapture, response.json()['capture_id'])
    # Emulate a rule improvement: the stored OCR text is now readable by the current rules.
    capture.text = store_text(original) if store_text else original
    db.commit()
    return headers, ledger, db, '/api/v1/ai/ocr-inbox/' + capture.id


def test_provisional_entry_confirmed_by_the_current_rules_becomes_counted():
    client = _make_client()
    try:
        headers, ledger, db, path = _vision_provisional(client, 'rebook-provisional@example.invalid')
        outcome = _run(db)
        assert outcome.get('confirmed') == 1, outcome
        rows = _rows(client, headers, ledger)
        assert len(rows) == 1 and rows[0]['exclude_from_stats'] is False and rows[0]['amount'] == .01
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_provisional_entry_is_untouched_when_the_rules_read_a_different_amount():
    client = _make_client()
    try:
        headers, ledger, db, path = _vision_provisional(
            client, 'rebook-mismatch@example.invalid', lambda text: text.replace('· 0.01', '· 0.02'))
        outcome = _run(db)
        assert outcome.get('confirmed', 0) == 0 and outcome['mismatch'] == 1
        rows = _rows(client, headers, ledger)
        assert len(rows) == 1 and rows[0]['exclude_from_stats'] is True
        assert client.get(path, headers=headers).json()['status'] == 'pending'
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_unreadable_or_non_channel_captures_are_left_for_review():
    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rebook-unreadable@example.invalid')
        _channel(client, headers, ledger, account, expense)
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json={
            'ledger_id': ledger, 'text': '合成无法识别文字', 'request_id': 'x' * 32, 'review_policy': 'deferred'}).status_code == 202
        other, other_ledger, *_ = setup_trigger(client, 'rebook-funding@example.invalid')   # not channel mode
        assert client.post('/api/v1/ai/record-ocr-text', headers=other, json={
            'ledger_id': other_ledger, 'text': '合成无法识别文字', 'request_id': 'y' * 32, 'review_policy': 'deferred'}).status_code == 202
        db = next(app.dependency_overrides[get_db]())
        outcome = _run(db)
        assert outcome.get('booked', 0) == outcome.get('confirmed', 0) == 0
        assert _rows(client, headers, ledger) == [] and _rows(client, other, other_ledger) == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_scheduler_registers_the_automatic_sweep(monkeypatch):
    from src.config import get_settings
    from src.services.backup.scheduler import BackupScheduler
    monkeypatch.setattr(get_settings(), 'backup_scheduler_enabled', False)
    monkeypatch.setattr(BackupScheduler, '_rebook_ocr_captures', staticmethod(lambda: None))
    monkeypatch.setattr(BackupScheduler, '_cleanup_ocr_images', staticmethod(lambda: None))
    scheduler = BackupScheduler()
    try:
        scheduler.start_from_db()
        assert scheduler._scheduler.get_job('ocr-rules-rebook') is not None
    finally:
        scheduler.shutdown()

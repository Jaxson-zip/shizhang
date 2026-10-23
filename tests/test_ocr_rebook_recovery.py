"""Automatic rebooking must converge across native write failures and repeated scans."""
from unittest.mock import patch

import pytest
from test_ocr_auto_rebook import _make_client, _rows, _run, _vision_provisional

from src.main import app


def test_native_promotion_committed_before_failure_also_confirms_capture():
    from src.routers.write.transactions import update_tx

    client = _make_client()
    try:
        headers, ledger, db, path = _vision_provisional(client, 'rebook-postcommit@example.invalid')

        async def interrupted_after_commit(**kwargs):
            await update_tx(**kwargs)
            raise RuntimeError('Synthetic interruption after native commit')

        with patch('src.routers.write.transactions.update_tx', interrupted_after_commit):
            assert _run(db) == {'error': 1}
        rows = _rows(client, headers, ledger)
        assert len(rows) == 1 and rows[0]['exclude_from_stats'] is False
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
        assert _run(db) == {}
        assert len(_rows(client, headers, ledger)) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('failure', ['before_commit', 'version_conflict'])
def test_failed_native_promotion_rolls_back_capture_and_can_retry(failure):
    from src.routers.write.transactions import update_tx

    client = _make_client()
    try:
        headers, ledger, db, path = _vision_provisional(client, 'rebook-precommit@example.invalid')

        async def interrupted_before_commit(**kwargs):
            if failure == 'before_commit':
                raise RuntimeError('Synthetic interruption before native commit')
            kwargs['req'] = kwargs['req'].model_copy(update={
                'expected_change_id': kwargs['req'].expected_change_id + 1})
            return await update_tx(**kwargs)

        with patch('src.routers.write.transactions.update_tx', interrupted_before_commit):
            assert _run(db) == {'error': 1}
        rows = _rows(client, headers, ledger)
        assert len(rows) == 1 and rows[0]['exclude_from_stats'] is True
        assert client.get(path, headers=headers).json()['status'] == 'pending'
        assert _run(db) == {'confirmed': 1}
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
        assert len(_rows(client, headers, ledger)) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_old_unreadable_page_does_not_starve_a_newer_decisive_capture(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from test_ocr_auto_rebook import _capture_unrecognized_received_page, _channel
    from test_ocr_trigger import setup_trigger

    from src.database import get_db
    from src.services.ocr_capture import OcrCapture

    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rebook-pages@example.invalid')
        _channel(client, headers, ledger, account, expense)
        path = _capture_unrecognized_received_page(client, headers, ledger, monkeypatch)
        db = next(app.dependency_overrides[get_db]())
        decisive = db.get(OcrCapture, path.rsplit('/', 1)[1])
        stamp = datetime.now(timezone.utc) - timedelta(hours=1)
        # The identical timestamps also exercise the cursor's ID tie-breaker.
        db.add_all([OcrCapture(id=str(uuid4()), user_id=decisive.user_id, ledger_id=decisive.ledger_id,
            request_id=str(uuid4()), request_hash='0' * 64, text='合成不可读文字', draft=None,
            reason='合成旧失败', status='pending', created_at=stamp) for _ in range(300)])
        db.commit()
        outcome = _run(db)
        assert outcome.get('rules_rejected') == 300
        assert outcome.get('booked') == 1
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
        assert len(_rows(client, headers, ledger)) == 1
        assert _run(db) == {'rules_rejected': 300}
        assert len(_rows(client, headers, ledger)) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('manual_action', ['edit', 'resolve'])
def test_user_change_before_promotion_is_preserved(monkeypatch, manual_action):
    from sqlalchemy import select

    from src.models import ReadTxProjection

    client = _make_client()
    try:
        headers, ledger, db, path = _vision_provisional(client, 'rebook-concurrent@example.invalid')
        tx = db.scalar(select(ReadTxProjection))
        tx_id, version = tx.sync_id, tx.source_change_id
        injected = False

        def user_changes_first(_db, _ledger_id):
            nonlocal injected
            if injected:
                return
            injected = True
            if manual_action == 'edit':
                response = client.patch('/api/v1/write/ledgers/' + ledger + '/transactions/' + tx_id,
                    headers={**headers, 'Idempotency-Key': 'synthetic-concurrent-edit'}, json={
                        'base_change_id': 0, 'expected_change_id': version, 'note': '合成手动修改'})
            else:
                response = client.post(path + '/resolve', headers=headers, json={
                    'entity_id': tx_id, 'expected_change_id': version})
            assert response.status_code == 200, response.text

        monkeypatch.setattr('src.concurrency.lock_ledger_for_materialize', user_changes_first)
        outcome = _run(db)
        rows = _rows(client, headers, ledger)
        assert injected and len(rows) == 1 and rows[0]['exclude_from_stats'] is True
        if manual_action == 'edit':
            assert outcome == {'error': 1}  # Native expected_change_id rejects the stale promotion.
            assert rows[0]['note'] == '合成手动修改'
            assert client.get(path, headers=headers).json()['status'] == 'pending'
        else:
            assert outcome == {'changed': 1}
            assert client.get(path, headers=headers).json()['status'] == 'confirmed'
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_failure_after_native_creation_does_not_book_a_second_entry(monkeypatch):
    from test_ocr_auto_rebook import _capture_unrecognized_received_page, _channel
    from test_ocr_trigger import setup_trigger

    from src.database import get_db
    from src.routers.ai.parse_tx_text import create_tx

    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rebook-create-retry@example.invalid')
        _channel(client, headers, ledger, account, expense)
        path = _capture_unrecognized_received_page(client, headers, ledger, monkeypatch)
        db = next(app.dependency_overrides[get_db]())

        async def interrupted_after_create(**kwargs):
            await create_tx(**kwargs)
            raise RuntimeError('Synthetic interruption after native create')

        with patch('src.routers.ai.parse_tx_text.create_tx', interrupted_after_create):
            assert _run(db) == {'error': 1}
        assert client.get(path, headers=headers).json()['status'] == 'confirmed'
        assert len(_rows(client, headers, ledger)) == 1
        assert _run(db) == {}
        assert len(_rows(client, headers, ledger)) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_user_ignore_before_native_creation_prevents_booking(monkeypatch):
    from uuid import uuid4

    from test_ocr_auto_rebook import _capture_unrecognized_received_page, _channel
    from test_ocr_trigger import setup_trigger

    from src.database import get_db
    from src.routers.ai.parse_tx_text import create_tx

    client = _make_client()
    try:
        headers, ledger, account, expense, _ = setup_trigger(client, 'rebook-ignore@example.invalid')
        _channel(client, headers, ledger, account, expense)
        path = _capture_unrecognized_received_page(client, headers, ledger, monkeypatch)
        db = next(app.dependency_overrides[get_db]())

        async def user_ignores_first(**kwargs):
            item = client.get(path, headers=headers).json()
            response = client.post(path + '/state', headers=headers, json={
                'status': 'ignored', 'expected_revision': item['revision'], 'action_id': str(uuid4())})
            assert response.status_code == 200, response.text
            return await create_tx(**kwargs)

        with patch('src.routers.ai.parse_tx_text.create_tx', user_ignores_first):
            assert _run(db) == {'error': 1}
        assert client.get(path, headers=headers).json()['status'] == 'ignored'
        assert _rows(client, headers, ledger) == []
        assert _run(db) == {}
    finally:
        client.close()
        app.dependency_overrides.clear()

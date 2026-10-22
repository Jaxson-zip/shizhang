"""Persist uncertain captures without forcing an immediate browser review."""
from datetime import datetime, timedelta, timezone

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_personal_receipts import GROUP, INCOMING
from test_ocr_trigger import setup_trigger

from src.main import app


def test_unreadable_capture_is_stored_once_without_fabricating_a_transaction():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'deferred-unknown@example.invalid')
        body.update(text='合成无法判断金额与方向的文字', review_policy='deferred')
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint, headers=headers, json=body)
        assert first.status_code == 202, first.text
        data = first.json()
        assert data['capture_id'] and data['capture_status'] == 'pending'
        assert not data.get('entity_id') and 'review_payload' not in data and 'review_path' not in data
        repeated = client.post(endpoint, headers=headers, json=body)
        assert repeated.status_code == 202 and repeated.json()['capture_id'] == data['capture_id']
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['total'] == 1 and inbox['items'][0]['draft'] is None
        assert 'text' not in inbox['items'][0]
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_later_manual_completion_reuses_the_native_entry_and_clears_only_its_capture(monkeypatch):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'deferred-complete@example.invalid')
        body.update(text='合成待补全原文', review_policy='deferred')
        captured = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()
        inbox_path = '/api/v1/ai/ocr-inbox'
        item = client.get(inbox_path, headers=headers, params={'ledger_id': ledger}).json()['items'][0]
        detail = client.get(inbox_path+'/'+item['id'], headers=headers)
        assert detail.status_code == 200 and detail.json()['text'] == body['text']
        save = {'base_change_id': 0, 'tx_type': 'expense', 'amount': 7.8,
                'happened_at': datetime.now(timezone.utc).isoformat(), 'account_id': account,
                'account_name': '微信零钱', 'category_id': category, 'category_name': '其他', 'category_kind': 'expense'}
        save_headers = {**headers, 'Idempotency-Key': item['request_key']}
        endpoint = '/api/v1/write/ledgers/'+ledger+'/transactions'
        saved = client.post(endpoint, headers=save_headers, json=save)
        assert saved.status_code == 200
        entity = saved.json()['entity_id']
        linked = client.get(inbox_path, headers=headers, params={'ledger_id': ledger}).json()['items'][0]
        assert linked['entity_id'] == entity  # linked atomically, before the HTTP response
        assert client.post(endpoint, headers=save_headers, json=save).json()['entity_id'] == entity
        confirmed = client.post(inbox_path+'/'+captured['capture_id']+'/resolve', headers=headers, json={
            'entity_id': entity, 'expected_change_id': saved.json()['new_change_id']})
        assert confirmed.status_code == 200 and confirmed.json()['status'] == 'confirmed'
        assert client.get(inbox_path, headers=headers, params={'ledger_id': ledger}).json()['total'] == 0
        assert len(client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()) == 1
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['capture_status'] == 'confirmed'
        # Native retry entries expire, but the capture's permanent association
        # must still prevent this single intention becoming another entry.
        from src.routers.write import _shared
        future = datetime.now(timezone.utc)+timedelta(days=2)
        monkeypatch.setattr(_shared, '_utcnow', lambda: future)
        late = client.post(endpoint, headers=save_headers, json=save)
        assert late.status_code == 200 and late.json()['idempotency_replayed'] is True
        assert late.json()['entity_id'] == entity
        changed = client.post(endpoint, headers=save_headers, json={**save, 'amount': 9.9})
        assert changed.status_code == 409
        assert len(client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_capture_privacy_and_changed_same_operation_do_not_overwrite_or_add_records():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'deferred-owner@example.invalid')
        body.update(text='合成尚待核对', review_policy='deferred')
        first = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()
        changed = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={**body, 'text': '另一份合成文字'})
        assert changed.status_code == 409
        other, other_ledger, _, _, _ = setup_trigger(client, 'deferred-outsider@example.invalid')
        detail = client.get('/api/v1/ai/ocr-inbox/'+first['capture_id'], headers=other)
        assert detail.status_code == 404 and body['text'] not in detail.text
        foreign = client.get('/api/v1/ai/ocr-inbox', headers=other, params={'ledger_id': ledger})
        assert foreign.status_code in (403, 404)
        assert client.get('/api/v1/ai/ocr-inbox', headers=other, params={'ledger_id': other_ledger}).json()['total'] == 0
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['total'] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_provisional_native_save_and_capture_link_rollback_together(monkeypatch):
    from src.routers.write import transactions
    client = _make_client()
    try:
        headers, ledger, account, _, body = setup_trigger(client, 'deferred-atomic@example.invalid')
        body.update(text=GROUP, account_id=account, review_policy='deferred')
        real_guard = transactions.capture_write_guard

        def failing_guard(*args):
            replay, bind = real_guard(*args)

            def fail(receipt):
                bind(receipt)
                raise RuntimeError('synthetic failure before commit')
            return replay, fail

        monkeypatch.setattr(transactions, 'capture_write_guard', failing_guard)
        with pytest.raises(RuntimeError, match='synthetic failure'):
            client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['total'] == 1 and inbox['items'][0]['entity_id'] is None
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_lost_response_after_native_commit_recovers_the_link_without_another_entry(monkeypatch):
    from src import websocket_manager
    client = _make_client()
    try:
        headers, ledger, account, _, body = setup_trigger(client, 'deferred-response@example.invalid')
        body.update(text=GROUP, account_id=account, review_policy='deferred')

        async def fail(**kwargs):
            raise RuntimeError('synthetic loss after commit')

        monkeypatch.setattr(websocket_manager, 'broadcast_to_ledger', fail)
        with pytest.raises(RuntimeError, match='synthetic loss'):
            client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        resumed = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert resumed.status_code == 202 and resumed.json()['entity_id']
        assert len(client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('text,direction', [(INCOMING, 'income'), (GROUP, 'expense')])
def test_known_direction_is_recorded_once_without_opening_review_and_new_intent_is_separate(text, direction):
    client = _make_client()
    try:
        headers, ledger, account, _, body = setup_trigger(client, 'deferred-'+direction+'@example.invalid')
        body.update(text=text, review_policy='deferred', account_id=account)
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint, headers=headers, json=body)
        assert first.status_code == 202 and first.json()['entity_id'], first.text
        data = first.json()
        assert data['recorded'] is True and 'review_payload' not in data and 'shortcut_choices' not in data
        repeated = client.post(endpoint, headers=headers, json=body)
        assert repeated.json()['entity_id'] == data['entity_id']
        rows_path = '/api/v1/read/ledgers/'+ledger+'/transactions'
        rows = client.get(rows_path, headers=headers).json()
        assert len(rows) == 1 and rows[0]['tx_type'] == direction and rows[0]['amount'] > 0
        assert rows[0]['exclude_from_stats'] is True
        new_run = client.post(endpoint, headers=headers, json={**body, 'request_id': 'another-intent-1234567890'})
        assert new_run.status_code == 202 and new_run.json()['entity_id'] != data['entity_id']
        assert len(client.get(rows_path, headers=headers).json()) == 2
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()
        assert inbox['total'] == 2 and all(item['entity_id'] for item in inbox['items'])
    finally:
        client.close()
        app.dependency_overrides.clear()

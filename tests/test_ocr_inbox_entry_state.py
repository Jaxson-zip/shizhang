"""The inbox tells a provisional (not counted) entry from a counted or missing one."""
from unittest.mock import AsyncMock, patch

from test_ai_parse_tx import _make_client, _seed_ai_config
from test_ocr_trigger import setup_trigger
from test_ocr_vision_fallback import IMAGE

from src.main import app


def test_inbox_reports_whether_the_linked_entry_is_still_provisional():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'inbox-entry-state@example.invalid')
        uid = client.get('/api/v1/profile/me', headers=headers).json()['user_id']
        _seed_ai_config(uid, vision_model='glm-4.6v-flash')
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        with patch('src.services.ai.payment_vision.call_chat_json',
                   AsyncMock(return_value={'text': original, 'transaction_count': 1})):
            saved = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['entity_id']

        def inbox_item():
            items = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['items']
            assert len(items) == 1
            detail = client.get('/api/v1/ai/ocr-inbox/' + items[0]['id'], headers=headers).json()
            assert detail['entry'] == items[0]['entry']
            return items[0]

        assert inbox_item()['entry'] == {'exists': True, 'exclude_from_stats': True}
        row = client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json()[0]
        counted = client.patch('/api/v1/write/ledgers/' + ledger + '/transactions/' + saved, headers=headers,
            json={'base_change_id': 0, 'expected_change_id': row['entry_change_id'], 'exclude_from_stats': False})
        assert counted.status_code == 200, counted.text
        assert inbox_item()['entry'] == {'exists': True, 'exclude_from_stats': False}
        deleted = client.request('DELETE', '/api/v1/write/ledgers/' + ledger + '/transactions/' + saved,
            headers=headers, json={'base_change_id': 0})
        assert deleted.status_code == 200, deleted.text
        assert inbox_item()['entry'] == {'exists': False, 'exclude_from_stats': False}
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_unbooked_capture_has_no_entry_state():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'inbox-entry-none@example.invalid')
        body.update(text='合成无法识别的页面', review_policy='deferred')
        assert client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).status_code == 202
        item = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['items'][0]
        assert item['entity_id'] is None and item['entry'] is None
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_a_capture_whose_entry_was_deleted_can_be_ignored_but_a_live_one_cannot():
    from uuid import uuid4
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'inbox-entry-deleted@example.invalid')
        uid = client.get('/api/v1/profile/me', headers=headers).json()['user_id']
        _seed_ai_config(uid, vision_model='glm-4.6v-flash')
        original = body['text']
        body.update(text=original.replace('· 0.01', '· 0.O1'), review_policy='deferred',
                    vision_fallback=True, image_base64=IMAGE)
        with patch('src.services.ai.payment_vision.call_chat_json',
                   AsyncMock(return_value={'text': original, 'transaction_count': 1})):
            saved = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['entity_id']

        def item():
            return client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger}).json()['items']

        def ignore(capture):
            return client.post('/api/v1/ai/ocr-inbox/' + capture['id'] + '/state', headers=headers, json={
                'status': 'ignored', 'expected_revision': capture['revision'], 'action_id': str(uuid4())})
        live = item()[0]
        assert ignore(live).status_code == 409   # a live provisional entry is reviewed, not ignored
        deleted = client.request('DELETE', '/api/v1/write/ledgers/' + ledger + '/transactions/' + saved,
            headers=headers, json={'base_change_id': 0})
        assert deleted.status_code == 200, deleted.text
        gone = item()[0]
        result = ignore(gone)
        assert result.status_code == 200, result.text
        assert item() == []
        assert client.get('/api/v1/read/ledgers/' + ledger + '/transactions', headers=headers).json() == []
        ignored = client.get('/api/v1/ai/ocr-inbox', headers=headers,
                             params={'ledger_id': ledger, 'state': 'ignored'}).json()
        assert ignored['ignored_total'] == 1 and ignored['items'][0]['entry'] == {'exists': False, 'exclude_from_stats': False}
    finally:
        client.close()
        app.dependency_overrides.clear()

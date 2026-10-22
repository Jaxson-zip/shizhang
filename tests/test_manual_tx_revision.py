"""Optional per-entry revision guard; legacy non-strict callers stay compatible."""
from test_write_no_strict_base import _login_web, _make_client, _register_app, _seed_snapshot

from src.main import app


def test_manual_edit_stale_revision_does_not_overwrite_and_replay_still_works():
    client = _make_client()
    try:
        owner = _register_app(client, 'manual-revision@example.invalid')
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'MANUAL_REV')
        token = _login_web(client, 'manual-revision@example.invalid')['access_token']
        headers = {'Authorization': 'Bearer ' + token, 'X-Device-ID': 'manual-test'}
        path = '/api/v1/write/ledgers/MANUAL_REV/transactions'
        first = client.post(path, headers=headers, json={'base_change_id': 0, 'tx_type': 'expense', 'amount': 12.8, 'happened_at': '2026-10-16T12:00:00Z'})
        assert first.status_code == 200, first.text
        tx_id = first.json()['entity_id']
        version = first.json()['new_change_id']
        body = {'base_change_id': 0, 'expected_change_id': version, 'note': 'newer synthetic note'}
        guarded_headers = {**headers, 'Idempotency-Key': 'manual-edit-replay'}
        updated = client.patch(path + '/' + tx_id, headers=guarded_headers, json=body)
        assert updated.status_code == 200, updated.text
        stale = client.patch(path + '/' + tx_id, headers=headers, json={**body, 'note': 'stale draft'})
        assert stale.status_code == 409, stale.text
        replay = client.patch(path + '/' + tx_id, headers=guarded_headers, json=body)
        assert replay.status_code == 200 and replay.json()['idempotency_replayed'] is True
        rows = client.get('/api/v1/read/ledgers/MANUAL_REV/transactions', headers=headers).json()
        assert len(rows) == 1 and rows[0]['note'] == 'newer synthetic note'
        # An unrelated ledger write must not prevent editing the unchanged entry.
        another = client.post(path, headers=headers, json={'base_change_id': 0, 'tx_type': 'income', 'amount': 5, 'happened_at': '2026-10-16T13:00:00Z'})
        assert another.status_code == 200
        own_version = updated.json()['new_change_id']
        view = client.get('/api/v1/read/workspace/transactions?ledger_id=MANUAL_REV&tx_sync_id=' + tx_id, headers=headers).json()
        assert view['items'][0]['entry_change_id'] == own_version
        result = client.patch(path + '/' + tx_id, headers=headers, json={'base_change_id': 0, 'expected_change_id': own_version, 'note': 'valid after unrelated write'})
        assert result.status_code == 200, result.text
    finally:
        app.dependency_overrides.clear()

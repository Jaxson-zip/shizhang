"""Ledger lifetime counts must use the same client day boundary as analytics."""
from datetime import datetime, timezone

import pytest
from test_write_no_strict_base import _login_web, _make_client, _register_app, _seed_snapshot

from src.main import app
from src.routers.read import workspace


def _seed_entries(client, times):
    owner = _register_app(client, 'local-days@example.invalid')
    _seed_snapshot(client, owner['access_token'], owner['device_id'], 'LOCAL_DAYS')
    token = _login_web(client, 'local-days@example.invalid')['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    for instant in times:
        result = client.post('/api/v1/write/ledgers/LOCAL_DAYS/transactions', headers=headers,
                             json={'base_change_id': 0, 'tx_type': 'expense', 'amount': 0.01,
                                   'happened_at': instant})
        assert result.status_code == 200, result.text
    return headers


@pytest.mark.parametrize(('times', 'expected_days', 'utc_days'), [
    (['2026-10-01T00:30:00Z', '2026-10-01T16:30:00Z'], 2, 1),
    (['2026-10-01T23:30:00Z', '2026-10-02T00:30:00Z'], 1, 2),
])
def test_lifetime_days_match_local_analytics_without_changing_utc_default(times, expected_days, utc_days):
    client = _make_client()
    try:
        headers = _seed_entries(client, times)
        params = {'ledger_id': 'LOCAL_DAYS', 'tz_offset_minutes': 480}
        counts = client.get('/api/v1/read/workspace/ledger-counts', headers=headers, params=params)
        analytics = client.get('/api/v1/read/workspace/analytics', headers=headers,
                               params={**params, 'scope': 'all'})
        assert counts.status_code == analytics.status_code == 200
        assert counts.json()['distinct_days'] == analytics.json()['summary']['distinct_days'] == expected_days
        assert counts.json()['tx_count'] == 2
        default = client.get('/api/v1/read/workspace/ledger-counts', headers=headers,
                             params={'ledger_id': 'LOCAL_DAYS'})
        assert default.json()['distinct_days'] == utc_days
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_elapsed_days_use_local_today_and_local_first_day(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(workspace, 'datetime', FixedDateTime)
    client = _make_client()
    try:
        headers = _seed_entries(client, ['2026-10-16T16:30:00Z'])
        result = client.get('/api/v1/read/workspace/ledger-counts', headers=headers,
                            params={'ledger_id': 'LOCAL_DAYS', 'tz_offset_minutes': 480})
        assert result.status_code == 200, result.text
        assert result.json()['days_since_first_tx'] == 1
        assert result.json()['first_tx_at'].startswith('2026-10-16T16:30:00')
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('offset', [-721, 841])
def test_invalid_client_offset_is_rejected(offset):
    client = _make_client()
    try:
        headers = _seed_entries(client, [])
        result = client.get('/api/v1/read/workspace/ledger-counts', headers=headers,
                            params={'ledger_id': 'LOCAL_DAYS', 'tz_offset_minutes': offset})
        assert result.status_code == 422
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Synthetic native writes agree across accounts, analytics, calendar buckets and CSV."""
import csv
import io
from decimal import Decimal

import pytest
from test_write_no_strict_base import _login_web, _make_client, _register_app, _seed_snapshot

from src.main import app


def test_manual_lifecycle_keeps_read_views_and_export_consistent():
    client = _make_client()
    try:
        owner = _register_app(client, 'accounting-matrix@example.invalid')
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'ACCOUNTING')
        token = _login_web(client, 'accounting-matrix@example.invalid')['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        write = '/api/v1/write/ledgers/ACCOUNTING/'

        def create(kind, payload):
            response = client.post(write + kind, headers=headers, json={'base_change_id': 0, **payload})
            assert response.status_code == 200, response.text
            return response.json()

        def get(path, **params):
            response = client.get('/api/v1/read/workspace/' + path, headers=headers,
                                  params={'ledger_id': 'ACCOUNTING', **params})
            assert response.status_code == 200, response.text
            return response

        accounts = {}
        for name, balance in [('合成钱包A', 100), ('合成钱包B', 0)]:
            accounts[name] = create('accounts', {'name': name, 'account_type': 'cash', 'currency': 'CNY',
                                                'initial_balance': balance})['entity_id']
        entries = [
            ('before-midnight', 'expense', 10, '2026-09-30T15:59:00Z', '合成钱包A', False),
            ('income', 'income', 20, '2026-09-30T16:00:00Z', '合成钱包A', False),
            ('transfer', 'transfer', 30, '2026-09-30T16:10:00Z', None, False),
            ('excluded', 'expense', 5, '2026-09-30T16:20:00Z', '合成钱包B', True),
            ('spend', 'expense', 2.5, '2026-09-30T16:30:00Z', '合成钱包B', False),
            # Existing native signed-expense representation; no claim of a Web refund editor.
            ('refund', 'expense', -1.25, '2026-09-30T16:40:00Z', '合成钱包B', False),
        ]
        created = {}
        for note, kind, amount, instant, account, excluded in entries:
            payload = {'tx_type': kind, 'amount': amount, 'happened_at': instant, 'note': note,
                       'currency_code': 'CNY', 'exclude_from_stats': excluded}
            if account:
                payload.update(account_name=account, account_id=accounts[account])
            else:
                payload.update(from_account_name='合成钱包A', from_account_id=accounts['合成钱包A'],
                               to_account_name='合成钱包B', to_account_id=accounts['合成钱包B'])
            created[note] = create('transactions', payload)

        local = {'scope': 'month', 'period': '2026-10', 'tz_offset_minutes': 480, 'natural_month': True}
        analytics = get('analytics', **local).json()
        assert analytics['summary']['income_total'] == 20
        assert analytics['summary']['expense_total'] == 1.25  # transfer/excluded do not inflate spending
        assert analytics['summary']['balance'] == 18.75
        assert analytics['series'] == [{'bucket': '2026-10-01', 'income': 20.0, 'expense': 1.25, 'balance': 18.75}]
        balances = {a['name']: a['balance'] for a in get('accounts').json()}
        assert balances == {'合成钱包A': 80.0, '合成钱包B': 23.75}  # excluded still moves actual money
        counts = get('ledger-counts', tz_offset_minutes=480).json()
        assert counts['tx_count'] == 6 and counts['distinct_days'] == 2

        export = get('transactions.csv', lang='zh-CN', tz_offset_minutes=480,
                     date_from='2026-09-30T16:00:00Z', date_to='2026-10-31T16:00:00Z')
        assert export.content.startswith(b'\xef\xbb\xbf')
        rows = list(csv.DictReader(io.StringIO(export.text.lstrip('\ufeff'))))
        assert len(rows) == 5 and all(row['时间'].strip().startswith('2026-10-01') for row in rows)
        by_note = {row['备注']: row for row in rows}
        assert Decimal(by_note['refund']['金额']) == Decimal('-1.25')
        assert by_note['transfer']['类型'] == '转账' and by_note['transfer']['转入账户'] == '合成钱包B'
        # CSV is a full transaction export, not an analytics-only report.
        assert by_note['excluded']['金额'] == '5.00'

        spend = created['spend']
        updated = client.patch(write + 'transactions/' + spend['entity_id'], headers=headers,
                               json={'base_change_id': 0, 'expected_change_id': spend['new_change_id'], 'amount': 3.5})
        assert updated.status_code == 200, updated.text
        assert get('analytics', **local).json()['summary']['expense_total'] == 2.25
        excluded_id = created['excluded']['entity_id']
        deleted = client.request('DELETE', write + 'transactions/' + excluded_id, headers=headers,
                                 json={'base_change_id': 0})
        assert deleted.status_code == 200, deleted.text
        assert get('ledger-counts', tz_offset_minutes=480).json()['tx_count'] == 5
        balances = {a['name']: a['balance'] for a in get('accounts').json()}
        assert balances['合成钱包B'] == pytest.approx(27.75)
        assert get('analytics', **local).json()['summary']['expense_total'] == 2.25
    finally:
        client.close()
        app.dependency_overrides.clear()

"""Native financial and bounded-read acceptance on an isolated synthetic database."""
import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from test_write_no_strict_base import _login_web, _make_client, _register_app, _seed_snapshot

from src.database import get_db
from src.main import app
from src.models import Ledger, ReadTxProjection, User


def test_refund_income_reversal_edit_and_amount_search():
    client = _make_client()
    try:
        email = 'refund-closeout@example.invalid'
        owner = _register_app(client, email)
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'REFUNDS')
        headers = {'Authorization': 'Bearer ' + _login_web(client, email)['access_token']}
        write = '/api/v1/write/ledgers/REFUNDS/'
        account = client.post(write + 'accounts', headers=headers, json={
            'base_change_id': 0, 'name': 'Synthetic Wallet', 'account_type': 'cash',
            'currency': 'CNY', 'initial_balance': 100})
        assert account.status_code == 200, account.text
        created = []
        for kind, amount in [('expense', 20), ('expense', -5), ('income', 30), ('income', -10)]:
            r = client.post(write + 'transactions', headers=headers, json={
                'base_change_id': 0, 'tx_type': kind, 'amount': amount,
                'happened_at': '2026-10-18T04:00:00Z', 'account_name': 'Synthetic Wallet',
                'account_id': account.json()['entity_id'], 'currency_code': 'CNY'})
            assert r.status_code == 200, r.text
            created.append(r.json())
        def read(name, **params):
            r = client.get('/api/v1/read/workspace/' + name, headers=headers,
                           params={'ledger_id': 'REFUNDS', **params})
            assert r.status_code == 200, r.text
            return r.json()
        assert read('accounts')[0]['balance'] == 105
        stats = read('analytics', scope='month', period='2026-10', tz_offset_minutes=480, natural_month=True)
        assert stats['summary']['expense_total'] == 15
        assert stats['summary']['income_total'] == 20
        # Refunds remain discoverable under the UI's absolute-value amount filter.
        matches = read('transactions', amount_min=4, amount_max=6)
        assert len(matches['items']) == 1
        assert matches['items'][0]['amount'] == -5
        refund = created[1]
        r = client.patch(write + 'transactions/' + refund['entity_id'], headers=headers, json={
            'base_change_id': 0, 'expected_change_id': refund['new_change_id'], 'amount': -7})
        assert r.status_code == 200, r.text
        assert read('accounts')[0]['balance'] == 107
        assert read('ledger-counts')['tx_count'] == 4
        assert read('analytics', scope='month', period='2026-10', tz_offset_minutes=480,
                    natural_month=True)['summary']['expense_total'] == 13
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_ten_thousand_projection_rows_have_bounded_complete_pages_and_search():
    client = _make_client()
    try:
        email = 'large-read-closeout@example.invalid'
        owner = _register_app(client, email)
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'LARGE')
        headers = {'Authorization': 'Bearer ' + _login_web(client, email)['access_token']}
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            user = db.scalar(select(User).where(User.email == email))
            ledger = db.scalar(select(Ledger).where(Ledger.external_id == 'LARGE', Ledger.user_id == user.id))
            db.bulk_insert_mappings(ReadTxProjection, [dict(ledger_id=ledger.id, user_id=user.id,
                sync_id=f'bulk-{i:05}', tx_type='expense', amount=1,
                happened_at=datetime(2026, 10, 18, 4, 0, tzinfo=timezone.utc), tx_index=i,
                note='needle' if i % 97 == 0 else 'synthetic', source_change_id=0) for i in range(10000)])
            db.commit()
        finally:
            gen.close()
        url = '/api/v1/read/workspace/transactions'
        started = time.perf_counter()
        ids = set()
        timings = []
        for offset in range(0, 10000, 200):
            before = time.perf_counter()
            r = client.get(url, headers=headers, params={'ledger_id':'LARGE','limit':200,'offset':offset})
            timings.append((time.perf_counter() - before)*1000)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data['total'] == 10000 and len(data['items']) == 200
            ids.update(row['id'] for row in data['items'])
        assert len(ids) == 10000
        before = time.perf_counter()
        r = client.get(url, headers=headers, params={'ledger_id':'LARGE','q':'needle','limit':200})
        search_ms = (time.perf_counter() - before)*1000
        assert r.status_code == 200 and r.json()['total'] == 104
        assert len(r.json()['items']) == 104
        assert client.get(url,headers=headers,params={'limit':2001}).status_code == 422
        print('CLOSEOUT_READ_METRICS '+json.dumps({'projection_rows':10000,'pages':50,'page_size':200,
            'max_page_ms':round(max(timings),2),'search_ms':round(search_ms,2),
            'all_pages_seconds':round(time.perf_counter()-started,2),'unique_rows':len(ids)}))
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_ordinary_users_cannot_write_export_or_download_each_others_data(tmp_path, monkeypatch):
    from src.routers import attachments
    monkeypatch.setattr(attachments, '_attachment_root', lambda: tmp_path)
    client = _make_client()
    try:
        a = _register_app(client, 'isolation-a-closeout@example.invalid')
        _seed_snapshot(client, a['access_token'], a['device_id'], 'PRIVATE-A')
        _register_app(client, 'isolation-b-closeout@example.invalid')
        a_web = _login_web(client, 'isolation-a-closeout@example.invalid')
        b_web = _login_web(client, 'isolation-b-closeout@example.invalid')
        ah = {'Authorization':'Bearer '+a_web['access_token']}
        bh = {'Authorization':'Bearer '+b_web['access_token']}
        uploaded = client.post('/api/v1/attachments/upload',headers=ah,
            data={'ledger_id':'PRIVATE-A'},files={'file':('synthetic.txt',b'private synthetic receipt','text/plain')})
        assert uploaded.status_code == 200, uploaded.text
        fid = uploaded.json()['file_id']
        assert client.get('/api/v1/attachments/'+fid,headers=ah).content == b'private synthetic receipt'
        blocked = client.get('/api/v1/attachments/'+fid,headers=bh)
        assert blocked.status_code in (403,404) and b'private synthetic receipt' not in blocked.content
        blocked = client.post('/api/v1/write/ledgers/PRIVATE-A/transactions',headers=bh,json={
            'base_change_id':0,'tx_type':'expense','amount':99,'happened_at':'2026-10-18T04:00:00Z'})
        assert blocked.status_code in (403,404)
        rows = client.get('/api/v1/read/workspace/transactions',headers=bh,params={'ledger_id':'PRIVATE-A'})
        assert rows.status_code == 200 and rows.json()['items'] == []
        exported = client.get('/api/v1/read/workspace/transactions.csv',headers=bh,params={'ledger_id':'PRIVATE-A'})
        assert exported.status_code == 200 and 'private synthetic receipt' not in exported.text
        assert client.get('/api/v1/admin/backup/remotes',headers=bh).status_code == 403
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_logout_revokes_refresh_and_expired_access_cannot_read():
    from datetime import timedelta

    from src.security import _create_token
    client = _make_client()
    try:
        email = 'session-closeout@example.invalid'
        _register_app(client,email)
        session = _login_web(client,email)
        headers = {'Authorization':'Bearer '+session['access_token']}
        assert client.post('/api/v1/auth/logout',headers=headers,
            json={'refresh_token':session['refresh_token']}).status_code == 200
        assert client.post('/api/v1/auth/refresh',json={'refresh_token':session['refresh_token']}).status_code == 401
        expired = _create_token(session['user']['id'],'access',timedelta(seconds=-60),
            scopes=['read'],client_type='web')
        assert client.get('/api/v1/read/workspace/transactions',
            headers={'Authorization':'Bearer '+expired}).status_code == 401
    finally:
        client.close()
        app.dependency_overrides.clear()


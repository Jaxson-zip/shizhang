"""Reversible ignore applies only to unbooked captures, without changing native money."""
import uuid

from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger

from src.main import app


def test_unbooked_capture_can_be_ignored_and_restored_without_creating_a_transaction():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'inbox-ignore-first@example.invalid')
        body.update(text='合成无法判断金额与方向', review_policy='deferred')
        endpoint = '/api/v1/ai/ocr-inbox'
        captured = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()
        detail = client.get(endpoint+'/'+captured['capture_id'], headers=headers).json()
        action = {'status':'ignored','expected_revision':detail.get('revision','missing'), 'action_id':str(uuid.uuid4())}
        ignored = client.post(endpoint+'/'+detail['id']+'/state',headers=headers,json=action)
        assert ignored.status_code == 200, ignored.text
        assert ignored.json()['status'] == 'ignored'
        assert client.get(endpoint,headers=headers,params={'ledger_id':ledger}).json()['total'] == 0
        archived = client.get(endpoint,headers=headers,params={'ledger_id':ledger,'state':'ignored'}).json()
        assert archived['total'] == 1 and archived['items'][0]['draft'] is None
        assert archived['items'][0]['revision'] != detail['revision']
        assert client.post(endpoint+'/'+detail['id']+'/state',headers=headers,json=action).json() == ignored.json()
        restored = client.post(endpoint+'/'+detail['id']+'/state',headers=headers,json={
            'status':'pending','expected_revision':ignored.json()['revision'],'action_id':str(uuid.uuid4())})
        assert restored.status_code == 200, restored.text
        assert restored.json()['status'] == 'pending'
        assert client.get(endpoint,headers=headers,params={'ledger_id':ledger}).json()['total'] == 1
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
        assert client.get(endpoint+'/'+detail['id'],headers=headers).json()['text'] == body['text']
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_old_ignore_cannot_reapply_after_restore_and_new_capture_intent_is_separate():
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'inbox-stale-state@example.invalid')
        body.update(text='合成不明采集',review_policy='deferred')
        record = '/api/v1/ai/record-ocr-text'
        cid = client.post(record,headers=headers,json=body).json()['capture_id']
        path = '/api/v1/ai/ocr-inbox/'+cid
        first = client.get(path,headers=headers).json()
        ignore = {'status':'ignored','expected_revision':first['revision'],'action_id':str(uuid.uuid4())}
        archived = client.post(path+'/state',headers=headers,json=ignore).json()
        replay = client.post(record,headers=headers,json=body)
        assert replay.status_code == 202 and replay.json()['capture_status'] == 'ignored'
        restore = client.post(path+'/state',headers=headers,json={
            'status':'pending','expected_revision':archived['revision'],'action_id':str(uuid.uuid4())})
        assert restore.status_code == 200
        assert client.post(path+'/state',headers=headers,json=ignore).status_code == 409
        outsider, _, _, _, _ = setup_trigger(client,'inbox-stale-outsider@example.invalid')
        assert client.post(path+'/state',headers=outsider,json={
            'status':'ignored','expected_revision':restore.json()['revision'],'action_id':str(uuid.uuid4())}).status_code == 404
        assert client.get(path,headers=outsider).status_code == 404
        new = client.post(record,headers=headers,json={**body,'request_id':str(uuid.uuid4())})
        assert new.status_code == 202 and new.json()['capture_id'] != cid
        page = client.get('/api/v1/ai/ocr-inbox',headers=headers,params={'ledger_id':ledger}).json()
        assert page['pending_total'] == 2 and page['ignored_total'] == 0
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_ignored_capture_rejects_stale_editor_then_restore_can_complete_once():
    from datetime import datetime, timezone
    client = _make_client()
    try:
        headers,ledger,account,category,body=setup_trigger(client,'inbox-stale-editor@example.invalid')
        body.update(text='合成误截内容',review_policy='deferred')
        captured=client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body).json()
        path='/api/v1/ai/ocr-inbox/'+captured['capture_id']
        detail=client.get(path,headers=headers).json()
        archive=client.post(path+'/state',headers=headers,json={
            'status':'ignored','expected_revision':detail['revision'],'action_id':str(uuid.uuid4())})
        assert archive.status_code==200
        payload={'base_change_id':0,'tx_type':'expense','amount':7.8,'happened_at':datetime.now(timezone.utc).isoformat(),
            'account_id':account,'account_name':'微信零钱','category_id':category,'category_name':'其他','category_kind':'expense'}
        save_headers={**headers,'Idempotency-Key':detail['request_key']}
        endpoint='/api/v1/write/ledgers/'+ledger+'/transactions'
        assert client.post(endpoint,headers=save_headers,json=payload).status_code==409
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()==[]
        assert client.post(path+'/state',headers=headers,json={
            'status':'pending','expected_revision':archive.json()['revision'],'action_id':str(uuid.uuid4())}).status_code==200
        saved=client.post(endpoint,headers=save_headers,json=payload)
        assert saved.status_code==200,saved.text
        now=client.get(path,headers=headers).json()
        before=client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        blocked=client.post(path+'/state',headers=headers,json={
            'status':'ignored','expected_revision':now['revision'],'action_id':str(uuid.uuid4())})
        assert blocked.status_code==409
        assert client.post(path+'/resolve',headers=headers,json={
            'entity_id':saved.json()['entity_id'],'expected_change_id':saved.json()['new_change_id']}).status_code==200
        late=client.post(endpoint,headers=save_headers,json=payload)
        assert late.status_code==200 and late.json()['entity_id']==saved.json()['entity_id']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()==before
        confirmed=client.get(path,headers=headers).json()
        assert client.post(path+'/state',headers=headers,json={
            'status':'ignored','expected_revision':confirmed['revision'],'action_id':str(uuid.uuid4())}).status_code==409
        assert client.get('/api/v1/ai/ocr-inbox',headers=headers,params={'ledger_id':ledger}).json()['total']==0
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_two_concurrent_state_changes_accept_only_one_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database import Base, get_db
    engine=create_engine('sqlite:///'+str(tmp_path/'concurrent.sqlite'),connect_args={'check_same_thread':False,'timeout':10})
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    def override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db]=override
    client=TestClient(app)
    try:
        headers,ledger,_,_,body=setup_trigger(client,'inbox-concurrent@example.invalid')
        body.update(text='合成并发忽略',review_policy='deferred')
        cid=client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body).json()['capture_id']
        path='/api/v1/ai/ocr-inbox/'+cid
        revision=client.get(path,headers=headers).json()['revision']
        barrier=Barrier(2)
        def submit(_):
            barrier.wait(timeout=5)
            return client.post(path+'/state',headers=headers,json={
                'status':'ignored','expected_revision':revision,'action_id':str(uuid.uuid4())}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,range(2)))
        assert sorted(results)==[200,409]
        page=client.get('/api/v1/ai/ocr-inbox',headers=headers,params={'ledger_id':ledger,'state':'ignored'}).json()
        assert page['total']==1
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()==[]
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()

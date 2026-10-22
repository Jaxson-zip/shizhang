"""New durable captures survive the existing native encrypted backup pipeline."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_ocr_trigger import setup_trigger

from src.database import Base, get_db
from src.main import app
from src.services.backup.db_snapshot import vacuum_into
from src.services.backup.tar_builder import build_encrypted_zip, extract_zip


@pytest.mark.parametrize('ignored', [False, True])
def test_pending_capture_and_raw_text_survive_encrypted_restore_without_old_database(tmp_path, ignored):
    original = tmp_path/'original.sqlite3'
    engine = create_engine('sqlite:///'+str(original), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'capture-restore@example.invalid')
        body.update(text='合成待补全原文，仅用于恢复测试', review_policy='deferred')
        response = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert response.status_code == 202
        capture = response.json()['capture_id']
        path='/api/v1/ai/ocr-inbox/'+capture
        before=client.get(path,headers=headers).json()
        if ignored:
            changed=client.post(path+'/state',headers=headers,json={
                'status':'ignored','expected_revision':before['revision'],'action_id':str(uuid.uuid4())})
            assert changed.status_code==200
            before=client.get(path,headers=headers).json()
        stage = tmp_path/'stage'
        stage.mkdir()
        with sessions() as db:
            vacuum_into(db, stage/'db.sqlite3')
        archive = tmp_path/'encrypted.zip'
        key = 'synthetic-ocr-restore-passphrase'
        build_encrypted_zip(stage, archive, key)
        client.close()
        engine.dispose()
        assert original.resolve().is_relative_to(tmp_path.resolve())
        original.rename(tmp_path/'unavailable-original.sqlite3')
        restored = tmp_path/'restored'
        extract_zip(archive, restored, key)
        engine = create_engine('sqlite:///'+str(restored/'db.sqlite3'), connect_args={'check_same_thread': False})
        sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        client = TestClient(app)
        login = client.post('/api/v1/auth/login', json={'email': 'capture-restore@example.invalid',
            'password': 'Pa$$word1!', 'client_type': 'web', 'device_id': 'restored-capture'}).json()
        headers = {'Authorization': 'Bearer '+login['access_token']}
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id': ledger, 'state':'ignored' if ignored else 'pending'}).json()
        assert inbox['total'] == 1 and inbox['items'][0]['id'] == capture
        assert inbox['items'][0]['entity_id'] is None
        detail = client.get('/api/v1/ai/ocr-inbox/'+capture, headers=headers).json()
        assert detail['text'] == body['text'] and detail['status'] == ('ignored' if ignored else 'pending')
        assert detail['revision']==before['revision']
        assert detail['draft'] is None
        if ignored:
            restored_state=client.post('/api/v1/ai/ocr-inbox/'+capture+'/state',headers=headers,json={
                'status':'pending','expected_revision':detail['revision'],'action_id':str(uuid.uuid4())})
            assert restored_state.status_code==200
            assert client.get('/api/v1/ai/ocr-inbox',headers=headers,params={'ledger_id':ledger}).json()['total']==1
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        engine.dispose()
        app.dependency_overrides.clear()

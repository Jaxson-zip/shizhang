"""Clearing content keeps a minimal intent tombstone, never revives old requests."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_ai_parse_tx import _make_client
from test_ocr_trigger import setup_trigger

from src.main import app
from src.services.ocr_capture import OcrCapture


@pytest.mark.parametrize('booked', [False, True])
def test_cleared_capture_rejects_old_shortcut_and_editor_but_new_intent_can_start(booked):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client, 'cleared-'+str(booked).lower()+'@example.invalid')
        body.update(review_policy='deferred', category_name='不存在的合成分类')
        if not booked:
            body['text'] = '合成不明确内容'
        recorded = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert recorded.status_code == 202, recorded.text
        capture_id = recorded.json()['capture_id']
        assert bool(recorded.json().get('entity_id')) == booked
        if booked:
            head = client.get('/api/v1/read/ledgers/'+ledger, headers=headers).json()['source_change_id']
            deleted = client.request('DELETE', '/api/v1/write/ledgers/'+ledger+'/transactions/'+recorded.json()['entity_id'],
                headers=headers, json={'base_change_id': head})
            assert deleted.status_code == 200
        from src.database import get_db
        db = next(app.dependency_overrides[get_db]())
        try:
            row = db.scalar(select(OcrCapture).where(OcrCapture.id == capture_id))
            row.status, row.text, row.draft, row.reason = 'cleared', '', None, '用户已清空账本数据'
            row.entity_id = row.receipt = row.save_hash = None
            db.commit()
        finally:
            db.close()
        replay = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert replay.status_code == 410, replay.text
        endpoint = '/api/v1/ai/ocr-inbox/'+capture_id
        assert client.get(endpoint, headers=headers).status_code == 410
        assert client.get(endpoint+'/image', headers=headers).status_code == 410
        save_headers = {**headers, 'Idempotency-Key':'ocr-review-'+capture_id}
        stale = client.post('/api/v1/write/ledgers/'+ledger+'/transactions', headers=save_headers, json={
            'base_change_id':0, 'tx_type':'expense', 'amount':.01, 'happened_at':datetime.now(timezone.utc).isoformat(),
            'account_id':account, 'category_id':category, 'category_kind':'expense'})
        assert stale.status_code == 409
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        inbox = client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id':ledger}).json()
        assert inbox['pending_total'] == inbox['ignored_total'] == 0
        fresh = client.post('/api/v1/ai/record-ocr-text', headers=headers, json={**body,'request_id':str(uuid4())})
        assert fresh.status_code == 202 and fresh.json()['capture_id'] != capture_id
    finally:
        client.close()
        app.dependency_overrides.clear()

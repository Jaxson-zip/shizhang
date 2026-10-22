"""Temporary receipt pictures have bounded storage, never a permanent attachment."""
import base64

IMAGE = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='


def test_image_expires_without_access_and_a_retry_does_not_extend_its_life(tmp_path, monkeypatch):
    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    monkeypatch.setattr(ocr_images.time, 'time', lambda: 1000)
    assert ocr_images.retain('capture-a', 'user-a', IMAGE)
    picture = ocr_images.read('capture-a', 'user-a')
    assert picture['data'] == base64.b64decode(IMAGE)
    assert picture['mime'] == 'image/png'
    assert picture['expires_at'] == 1000 + 7*86400
    assert ocr_images.read('capture-a', 'user-b') is None
    monkeypatch.setattr(ocr_images.time, 'time', lambda: 2000)
    assert ocr_images.retain('capture-a', 'user-a', IMAGE)
    assert ocr_images.read('capture-a', 'user-a')['expires_at'] == picture['expires_at']
    monkeypatch.setattr(ocr_images.time, 'time', lambda: 1001+7*86400)
    ocr_images.cleanup()
    assert ocr_images.read('capture-a', 'user-a') is None
    assert ocr_images.usage()['bytes'] == 0


def test_user_and_server_quotas_evict_pictures_not_allow_unbounded_growth(tmp_path, monkeypatch):
    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    size = len(base64.b64decode(IMAGE))
    monkeypatch.setattr(ocr_images, 'USER_BYTES', size)
    monkeypatch.setattr(ocr_images, 'TOTAL_BYTES', 2*size)
    assert ocr_images.retain('one', 'a', IMAGE)
    assert ocr_images.retain('two', 'a', IMAGE)
    assert ocr_images.read('one', 'a') is None
    assert ocr_images.retain('three', 'b', IMAGE)
    assert ocr_images.retain('four', 'c', IMAGE)
    assert ocr_images.read('two', 'a') is None
    assert ocr_images.usage() == {'bytes': 2*size, 'count': 2}
    monkeypatch.setattr(ocr_images, 'MAX_IMAGE_BYTES', size-1)
    assert not ocr_images.retain('oversize', 'c', IMAGE)
    assert ocr_images.read('four', 'c') is not None


def test_capture_retains_private_image_then_ignore_erases_only_the_picture(tmp_path, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, patch

    from test_ai_parse_tx import _make_client
    from test_ocr_trigger import setup_trigger

    from src.main import app
    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'picture-owner@example.invalid')
        body.update(text='合成无法识别文字', review_policy='deferred', vision_fallback=True, image_base64=IMAGE)
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', AsyncMock(side_effect=ValueError('synthetic unavailable'))):
            result = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body)
        assert result.status_code == 202
        path = '/api/v1/ai/ocr-inbox/'+result.json()['capture_id']
        detail = client.get(path, headers=headers).json()
        assert detail['image']['available'] is True
        response = client.get(path+'/image', headers=headers)
        assert response.status_code == 200
        assert response.content == base64.b64decode(IMAGE)
        assert 'no-store' in response.headers['cache-control']
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert client.get(path+'/image').status_code == 401
        other, _, _, _, _ = setup_trigger(client, 'picture-outsider@example.invalid')
        assert client.get(path+'/image', headers=other).status_code == 404
        ignored = client.post(path+'/state', headers=headers, json={
            'status':'ignored','expected_revision':detail['revision'],'action_id':str(uuid.uuid4())})
        assert ignored.status_code == 200
        assert client.get(path+'/image', headers=headers).status_code == 410
        assert client.get(path, headers=headers).json()['text'] == body['text']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_saved_picture_can_be_reread_without_creating_any_transaction(tmp_path, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, patch

    from test_ai_parse_tx import _make_client
    from test_ocr_trigger import setup_trigger

    from src.main import app
    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'picture-reread@example.invalid')
        original = body['text']
        body.update(text='合成未识别金额', review_policy='deferred', vision_fallback=True, image_base64=IMAGE)
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', AsyncMock(side_effect=ValueError('synthetic unavailable'))):
            cid = client.post('/api/v1/ai/record-ocr-text', headers=headers, json=body).json()['capture_id']
        path = '/api/v1/ai/ocr-inbox/'+cid
        before = client.get(path, headers=headers).json()
        action = {'expected_revision':before['revision'], 'action_id':str(uuid.uuid4())}
        model = AsyncMock(return_value=original)
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', model):
            result = client.post(path+'/reread', headers=headers, json=action)
            assert result.status_code == 200, result.text
            assert result.json()['draft']['amount'] == .01
            assert result.json()['id'] == cid
            assert '已补读截图' in result.json()['reason']
            assert client.post(path+'/reread', headers=headers, json=action).status_code == 200
            assert model.await_count == 1
            assert client.post(path+'/reread', headers=headers, json={**action,'action_id':str(uuid.uuid4())}).status_code == 409
        assert client.get(path, headers=headers).json()['text'] == body['text']
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions', headers=headers).json() == []
        assert client.get('/api/v1/ai/ocr-inbox', headers=headers, params={'ledger_id':ledger}).json()['total'] == 1
        # The user's existing native save/resolve path removes the temporary picture.
        form = result.json()['draft']
        saved = client.post('/api/v1/write/ledgers/'+ledger+'/transactions',
            headers={**headers,'Idempotency-Key':before['request_key']}, json={
                'base_change_id':0,'tx_type':form['type'],'amount':form['amount'],
                'happened_at':form['happened_at'],'account_name':'微信零钱'})
        assert saved.status_code == 200, saved.text
        assert client.post(path+'/resolve', headers=headers, json={
            'entity_id':saved.json()['entity_id'],'expected_change_id':saved.json()['new_change_id']}).status_code == 200
        assert client.get(path+'/image',headers=headers).status_code == 410
        assert ocr_images.usage()['bytes'] == 0
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_concurrent_cache_writers_cannot_exceed_the_global_quota(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from src.services import ocr_images
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    monkeypatch.setattr(ocr_images, 'TOTAL_BYTES', 2*len(base64.b64decode(IMAGE)))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda i: ocr_images.retain(str(i), str(i), IMAGE), range(12)))
    assert ocr_images.usage()['count'] == 2


def test_expiry_scheduler_runs_when_backup_jobs_are_disabled(tmp_path, monkeypatch):
    from src.config import get_settings
    from src.services import ocr_images
    from src.services.backup.scheduler import BackupScheduler
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    monkeypatch.setattr(get_settings(), 'backup_scheduler_enabled', False)
    assert ocr_images.retain('orphan', 'missing-user', IMAGE)
    scheduler = BackupScheduler()
    try:
        scheduler.start_from_db()
        assert scheduler._scheduler.get_job('ocr-image-expiry') is not None
        assert not any(job.id.startswith('backup-schedule-') for job in scheduler._scheduler.get_jobs())
        # The startup sweep also removes pictures whose capture/user no longer exists.
        assert ocr_images.usage()['count'] == 0
    finally:
        scheduler.shutdown()


def test_native_backup_attachment_export_does_not_include_disposable_images(tmp_path, monkeypatch):
    import zipfile

    from src.config import get_settings
    from src.services import ocr_images
    from src.services.backup.tar_builder import build_encrypted_zip, hardlink_tree
    attachments = tmp_path/'data'/'attachments'
    attachments.mkdir(parents=True)
    (attachments/'kept.txt').write_text('native attachment', encoding='utf-8')
    monkeypatch.setattr(get_settings(), 'attachment_storage_dir', str(attachments))
    assert ocr_images.retain('temporary', 'user', IMAGE)
    assert not ocr_images.cache_path().is_relative_to(attachments)
    stage = tmp_path/'stage'
    hardlink_tree(attachments, stage/'attachments')
    archive = tmp_path/'backup.zip'
    build_encrypted_zip(stage, archive, 'synthetic-image-backup-exclusion')
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ['attachments/kept.txt']


def test_late_model_reply_cannot_undo_an_ignore(tmp_path, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import update
    from test_ai_parse_tx import _make_client
    from test_ocr_trigger import setup_trigger

    from src.database import get_db
    from src.main import app
    from src.services import ocr_images
    from src.services.ocr_capture import OcrCapture
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'reread-race@example.invalid')
        original = body['text']
        body.update(text='合成待补全',review_policy='deferred',vision_fallback=True,image_base64=IMAGE)
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', AsyncMock(side_effect=ValueError('synthetic unavailable'))):
            cid = client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body).json()['capture_id']
        path = '/api/v1/ai/ocr-inbox/'+cid
        before = client.get(path,headers=headers).json()
        async def delayed(*_):
            with next(app.dependency_overrides[get_db]()) as db:
                db.execute(update(OcrCapture).where(OcrCapture.id==cid).values(status='ignored'))
                db.commit()
            return original
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', delayed):
            result = client.post(path+'/reread',headers=headers,json={
                'expected_revision':before['revision'],'action_id':str(uuid.uuid4())})
        assert result.status_code == 409
        assert client.get(path,headers=headers).json()['status'] == 'ignored'
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
        # Even if the cache file has not yet been swept, ignored records do not expose it.
        assert client.get(path+'/image',headers=headers).status_code == 410
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_unavailable_model_retry_is_idempotent_and_missing_picture_never_calls_it(tmp_path, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock, patch

    from test_ai_parse_tx import _make_client
    from test_ocr_trigger import setup_trigger

    from src.main import app
    from src.services import ocr_images
    from src.services.ai.provider_client import ChatProviderError
    monkeypatch.setattr(ocr_images, 'cache_path', lambda: tmp_path/'previews.sqlite')
    client = _make_client()
    try:
        headers, ledger, _, _, body = setup_trigger(client, 'reread-unavailable@example.invalid')
        body.update(text='合成待补全',review_policy='deferred',vision_fallback=True,image_base64=IMAGE)
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', AsyncMock(side_effect=ChatProviderError('synthetic 429'))):
            cid = client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body).json()['capture_id']
        path = '/api/v1/ai/ocr-inbox/'+cid
        before = client.get(path,headers=headers).json()
        action = {'expected_revision':before['revision'],'action_id':str(uuid.uuid4())}
        model = AsyncMock(side_effect=ChatProviderError('synthetic 429'))
        with patch('src.routers.ai.parse_tx_text.transcribe_payment', model):
            result = client.post(path+'/reread',headers=headers,json=action)
            assert result.status_code == 200 and result.json()['draft'] is None
            assert '暂不可用' in result.json()['message']
            assert client.post(path+'/reread',headers=headers,json=action).json() == result.json()
            assert model.await_count == 1
            ocr_images.forget(cid, client.get('/api/v1/profile/me',headers=headers).json()['user_id'])
            missing = client.post(path+'/reread',headers=headers,json={
                'expected_revision':result.json()['revision'],'action_id':str(uuid.uuid4())})
            assert missing.status_code == 410 and model.await_count == 1
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()

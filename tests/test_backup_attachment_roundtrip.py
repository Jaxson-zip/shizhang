"""Native encrypted restore recovers real attachment bytes and their ledger references."""
from __future__ import annotations

import base64
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_write_no_strict_base import _login_web, _register_app, _seed_snapshot

from src.config import get_settings
from src.database import Base, get_db
from src.main import app
from src.services.backup.db_snapshot import vacuum_into
from src.services.backup.tar_builder import build_encrypted_zip, extract_zip, hardlink_tree


def test_encrypted_restore_recovers_nonempty_attachments_with_original_store_unavailable(tmp_path, monkeypatch):
    live = tmp_path / 'original'
    live.mkdir()
    attachments = live / 'attachments'
    monkeypatch.setattr(get_settings(), 'attachment_storage_dir', str(attachments))
    engine = create_engine('sqlite:///' + str(live / 'db.sqlite3'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    try:
        owner = _register_app(client, 'restore-attachments@example.invalid')
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'RESTORE_FILES')
        _register_app(client, 'restore-outsider@example.invalid')
        token = _login_web(client, 'restore-attachments@example.invalid')['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII=')
        expected = [('合成收据.png', png, 'image/png'), ('合成说明.txt', '仅用于恢复验证'.encode(), 'text/plain')]
        uploads = []
        for name, data, mime in expected:
            response = client.post('/api/v1/attachments/upload', headers=headers,
                                   data={'ledger_id': 'RESTORE_FILES'}, files={'file': (name, data, mime)})
            assert response.status_code == 200, response.text
            uploads.append(response.json())
        repeated = client.post('/api/v1/attachments/upload', headers=headers,
                               data={'ledger_id': 'RESTORE_FILES'}, files={'file': expected[0]})
        assert repeated.json()['file_id'] == uploads[0]['file_id']
        refs = [{'cloudFileId': row['file_id'], 'cloudSha256': row['sha256'], 'fileName': row['file_name'],
                 'fileSize': row['size'], 'mimeType': row['mime_type'], 'sortOrder': index}
                for index, row in enumerate(uploads)]
        response = client.post('/api/v1/write/ledgers/RESTORE_FILES/transactions', headers=headers,
                               json={'base_change_id': 0, 'tx_type': 'expense', 'amount': 12.5,
                                     'happened_at': '2026-10-17T00:30:00Z', 'attachments': refs})
        assert response.status_code == 200, response.text
        read_path = '/api/v1/read/ledgers/RESTORE_FILES/transactions'
        before_records = client.get(read_path, headers=headers).json()
        assert len(before_records) == 1 and len(before_records[0]['attachments']) == 2

        stage = tmp_path / 'stage'
        stage.mkdir()
        with sessions() as db:
            vacuum_into(db, stage / 'db.sqlite3')
        assert hardlink_tree(attachments, stage / 'attachments') == 2
        archive = tmp_path / 'encrypted.zip'
        passphrase = 'synthetic-isolated-restore-passphrase'
        build_encrypted_zip(stage, archive, passphrase)
        with pytest.raises(RuntimeError):
            extract_zip(archive, tmp_path / 'wrong-key', 'incorrect-synthetic-key')

        def tree(root):
            return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in root.rglob('*') if p.is_file()}

        expected_files = tree(stage)
        client.close()
        engine.dispose()
        # A restore to the configured original path, with its entire old store
        # unavailable: successful downloads cannot silently use old files.
        assert live.resolve().is_relative_to(tmp_path.resolve())
        live.rename(tmp_path / 'unavailable-original')
        assert not live.exists()
        extract_zip(archive, live, passphrase)
        assert tree(live) == expected_files
        with sqlite3.connect(live / 'db.sqlite3') as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT COUNT(*) FROM attachment_files').fetchone()[0] == 2
            assert db.execute('SELECT COUNT(*) FROM refresh_tokens').fetchone()[0] == 0
        engine = create_engine('sqlite:///' + str(live / 'db.sqlite3'), connect_args={'check_same_thread': False})
        sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        client = TestClient(app)
        restored_token = _login_web(client, 'restore-attachments@example.invalid')['access_token']
        outsider_token = _login_web(client, 'restore-outsider@example.invalid')['access_token']
        restored_headers = {'Authorization': 'Bearer ' + restored_token}
        assert client.get(read_path, headers=restored_headers).json() == before_records
        for row, (_, data, _) in zip(uploads, expected, strict=True):
            path = '/api/v1/attachments/' + row['file_id']
            download = client.get(path, headers=restored_headers)
            assert download.status_code == 200 and download.content == data
            assert hashlib.sha256(download.content).hexdigest() == row['sha256']
            denied = client.get(path, headers={'Authorization': 'Bearer ' + outsider_token})
            assert denied.status_code == 403
        dedup = client.post('/api/v1/attachments/upload', headers=restored_headers,
                            data={'ledger_id': 'RESTORE_FILES'}, files={'file': expected[0]})
        assert dedup.status_code == 200 and dedup.json()['file_id'] == uploads[0]['file_id']
    finally:
        client.close()
        engine.dispose()
        app.dependency_overrides.clear()

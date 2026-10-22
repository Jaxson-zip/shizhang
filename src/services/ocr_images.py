"""Bounded, disposable screenshot cache, separate from native ledger backups.

Use SQLite's existing inter-process write lock; no daemon, public file URL or
permanent attachment. JPEG compression already happens in the v9 Shortcut.
"""
import base64
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from .ai.payment_vision import image_data_url

TTL_SECONDS = 7 * 86400  # unresolved captures: the review window
AUTO_TTL_SECONDS = 48 * 3600  # user decision 2026-10-22: auto-booked captures, for checking against the entry
MAX_IMAGE_BYTES = 1024 * 1024
USER_BYTES = 20 * 1024 * 1024
TOTAL_BYTES = 128 * 1024 * 1024
USER_COUNT = 128
TOTAL_COUNT = 1024


def cache_path() -> Path:
    # A sibling of attachments, never a child: native backup attachment export
    # cannot silently turn short-lived screenshots into 30-day archives.
    return Path(get_settings().attachment_storage_dir).expanduser().parent / 'ocr-previews' / 'cache.sqlite'


@contextmanager
def _connection():
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(str(path), timeout=5)
    try:
        os.chmod(path, 0o600)
        db.execute('PRAGMA auto_vacuum=FULL')
        db.execute('PRAGMA secure_delete=ON')
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA max_page_count=' + str((TOTAL_BYTES + 8*1024*1024)//4096))
        db.execute('CREATE TABLE IF NOT EXISTS pictures (id TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                   'created REAL NOT NULL, expires REAL NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM pictures WHERE expires<=?', (time.time(),))
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def retain(capture_id: str, user_id: str, encoded: str, ttl: int = TTL_SECONDS) -> bool:
    url = image_data_url(encoded)
    mime, payload = url.split(';base64,', 1)
    data = base64.b64decode(payload, validate=True)
    if len(data) > MAX_IMAGE_BYTES:
        return False
    with _connection() as db:
        existing = db.execute('SELECT owner FROM pictures WHERE id=?', (capture_id,)).fetchone()
        if existing:
            return existing[0] == user_id  # never extend TTL on transport retry
        # Evict only temporary pictures, soonest-expiring first, never finance rows/text.
        for owner, byte_limit, count_limit in ((user_id, USER_BYTES, USER_COUNT), (None, TOTAL_BYTES, TOTAL_COUNT)):
            where, args = (' WHERE owner=?', (owner,)) if owner is not None else ('', ())
            while True:
                used, count = db.execute('SELECT COALESCE(SUM(length(data)),0),COUNT(*) FROM pictures'+where, args).fetchone()
                if used+len(data) <= byte_limit and count < count_limit:
                    break
                oldest = db.execute('SELECT id FROM pictures'+where+' ORDER BY expires,created,id LIMIT 1', args).fetchone()
                if oldest is None:
                    return False
                db.execute('DELETE FROM pictures WHERE id=?', oldest)
        now = time.time()
        db.execute('INSERT INTO pictures VALUES (?,?,?,?,?,?)',
                   (capture_id, user_id, now, now+ttl, mime.removeprefix('data:'), data))
    return True


def read(capture_id: str, user_id: str):
    with _connection() as db:
        row = db.execute('SELECT mime,data,expires FROM pictures WHERE id=? AND owner=?', (capture_id, user_id)).fetchone()
        return {'mime': row[0], 'data': row[1], 'expires_at': row[2]} if row else None


def availability(capture_id: str, user_id: str) -> dict:
    try:
        with _connection() as db:
            row = db.execute('SELECT expires FROM pictures WHERE id=? AND owner=?', (capture_id, user_id)).fetchone()
        return {'available': bool(row), 'expires_at': datetime.fromtimestamp(row[0], timezone.utc).isoformat() if row else None}
    except (OSError, sqlite3.Error):
        return {'available': False, 'expires_at': None}


def forget(capture_id: str, user_id: str):
    with _connection() as db:
        db.execute('DELETE FROM pictures WHERE id=? AND owner=?', (capture_id, user_id))


def keeps_picture(row) -> bool:
    """Pending captures keep theirs for review; auto-booked ones until their own 48h expiry."""
    return row.status == 'pending' or row.status == 'confirmed' and bool((row.draft or {}).get('_auto_request'))


def cleanup(db=None):
    """Hourly scheduler and every cache access enforce the same non-sliding TTL."""
    with _connection() as cache:
        if db is not None:
            from .ocr_capture import OcrCapture
            for capture_id, owner in cache.execute('SELECT id,owner FROM pictures').fetchall():
                row = db.get(OcrCapture, capture_id)
                if row is None or row.user_id != owner or not keeps_picture(row):
                    cache.execute('DELETE FROM pictures WHERE id=?', (capture_id,))


def usage():
    with _connection() as db:
        size, count = db.execute('SELECT COALESCE(SUM(length(data)),0),COUNT(*) FROM pictures').fetchone()
    return {'bytes': size, 'count': count}

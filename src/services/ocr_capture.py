"""Durable, per-user uncertain OCR captures; native transactions remain authoritative."""
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..database import Base


class OcrCapture(Base):
    __tablename__ = 'shizhang_ocr_captures'
    __table_args__ = (UniqueConstraint('user_id', 'ledger_id', 'request_id', name='uq_ocr_capture_intent'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    ledger_id: Mapped[str] = mapped_column(ForeignKey('ledgers.id', ondelete='CASCADE'), index=True)
    request_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    save_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def request_hash(req) -> str:
    payload = req.model_dump(mode='json')
    # New opt-in fields must not change the identity of a pending v8 capture.
    if not payload.get('vision_fallback') and payload.get('image_base64') is None:
        payload.pop('vision_fallback', None)
        payload.pop('image_base64', None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def existing_capture(db: Session, user_id: str, ledger_id: str, req) -> OcrCapture | None:
    row = db.scalar(select(OcrCapture).where(OcrCapture.user_id == user_id,
        OcrCapture.ledger_id == ledger_id, OcrCapture.request_id == req.request_id))
    if row is not None and row.status == 'cleared':
        raise HTTPException(status_code=410, detail='这次采集已随账本数据清空，请重新主动采集；旧请求不会恢复账目')
    if row is not None and row.request_hash != request_hash(req):
        raise HTTPException(status_code=409, detail='同一次采集的内容发生变化，请先核对原记录')
    return row


def retain_capture(db: Session, user_id: str, ledger_id: str, req, draft: dict | None, reason: str) -> tuple[OcrCapture, bool]:
    row = existing_capture(db, user_id, ledger_id, req)
    if row is not None:
        return row, False
    count = db.scalar(select(func.count()).select_from(OcrCapture).where(
        OcrCapture.user_id == user_id, OcrCapture.status == 'pending'))
    if count >= 1000:
        raise HTTPException(status_code=429, detail='待核对内容已达1000条，请先处理；本次尚未收下')
    row = OcrCapture(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'capture:{user_id}:{ledger_id}:{req.request_id}')),
        user_id=user_id, ledger_id=ledger_id, request_id=req.request_id, request_hash=request_hash(req),
        text=req.text, draft=draft, reason=reason[:255])
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = existing_capture(db, user_id, ledger_id, req)
        if row is None:
            raise
        return row, False
    db.refresh(row)
    # Only unresolved captures need a disposable picture. Successful automatic
    # writes keep neither a permanent attachment nor an unnecessary image copy.
    if req.image_base64 and req.vision_fallback and not (draft or {}).get('_auto_request'):
        from . import ocr_images
        try:
            ocr_images.retain(row.id, user_id, req.image_base64)
        except (ValueError, OSError, sqlite3.Error) as exc:
            logging.getLogger(__name__).warning('ocr.image_not_retained kind=%s', type(exc).__name__)
    return row, True


def capture_ack(row: OcrCapture) -> dict:
    return {'capture_id': row.id, 'capture_status': row.status, 'recorded': bool(row.entity_id),
            'entity_id': row.entity_id, 'message': '本次采集已忽略，尚未入账；可在已忽略列表恢复' if row.status == 'ignored'
            else '本次采集已核对' if row.status == 'confirmed'
            else '已入账，稍后核对' if row.entity_id else '已收下，稍后补全；尚未计入收支'}


def inbox_revision(row: OcrCapture) -> str:
    """Opaque optimistic revision; private action metadata stays out of list responses."""
    return hashlib.sha256(json.dumps([row.status, row.entity_id, row.draft, row.receipt],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def capture_write_guard(db: Session, user_id: str, ledger_id: str, key: str | None, payload_hash: str):
    """Bind the native entry and receipt in its transaction, beyond the 24h retry cache."""
    if not key or not key.startswith('ocr-review-'):
        return None, None
    row = db.scalar(select(OcrCapture).where(OcrCapture.id == key[len('ocr-review-'):],
        OcrCapture.user_id == user_id, OcrCapture.ledger_id == ledger_id))
    if row is None:
        return None, None  # older temporary review links keep their native behavior
    if row.receipt is not None:
        if row.save_hash != payload_hash:
            raise HTTPException(status_code=409, detail='这次采集已保存，不能换内容重复新建，请编辑原账目')
        return {**row.receipt, 'idempotency_replayed': True}, None
    if row.status != 'pending':
        raise HTTPException(status_code=409, detail='这次采集已处理，请刷新待核对内容')

    def bind(receipt):
        updated = db.execute(update(OcrCapture).where(OcrCapture.id == row.id,
            OcrCapture.receipt.is_(None), OcrCapture.status == 'pending').values(
                entity_id=receipt.entity_id, receipt=receipt.model_dump(mode='json'), save_hash=payload_hash,
                status='confirmed' if (row.draft or {}).get('_auto_request') else 'pending'))
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail='这次采集已保存，请刷新核对')
    return None, bind

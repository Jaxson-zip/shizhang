"""Persist per-user OCR captures for later review; no change to native transactions.

Revision ID: 0021_ocr_captures
Revises: 0020_category_parent_links
"""
import sqlalchemy as sa
from alembic import op

revision = '0021_ocr_captures'
down_revision = '0020_category_parent_links'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('shizhang_ocr_captures'):
        expected = {'id', 'user_id', 'ledger_id', 'request_id', 'request_hash', 'text', 'draft',
                    'reason', 'entity_id', 'receipt', 'save_hash', 'status', 'created_at'}
        if {column['name'] for column in inspector.get_columns('shizhang_ocr_captures')} != expected:
            raise RuntimeError('Existing OCR capture schema differs; do not overwrite')
        return  # managed additive rollout may have created this same table already
    op.create_table('shizhang_ocr_captures',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ledger_id', sa.String(), sa.ForeignKey('ledgers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', sa.String(100), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('draft', sa.JSON(), nullable=True),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('entity_id', sa.String(255), nullable=True),
        sa.Column('receipt', sa.JSON(), nullable=True),
        sa.Column('save_hash', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'ledger_id', 'request_id', name='uq_ocr_capture_intent'))
    for column in ('user_id', 'ledger_id', 'status'):
        op.create_index('ix_shizhang_ocr_captures_'+column, 'shizhang_ocr_captures', [column])


def downgrade():
    op.drop_table('shizhang_ocr_captures')

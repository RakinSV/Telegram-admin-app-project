"""F26: дополнительные Telethon-сессии для распределения источников

Основная сессия (TG_SESSION_STRING) остаётся в secrets/.env как есть — эта
таблица только для ДОПОЛНИТЕЛЬНЫХ аккаунтов, добавляемых по мере роста числа
источников за пределы разумного для одной сессии.

Revision ID: 0008_telethon_sessions
Revises: 0007_negative_alert_sent
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_telethon_sessions"
down_revision: str | None = "0007_negative_alert_sent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telethon_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("encrypted_session_string", sa.Text(), nullable=False),
        sa.Column("masked_hint", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("telethon_sessions")

"""Конкурсы и розыгрыши (F44) с прозрачным розыгрышем.

draw_seed генерируется и публикуется ЗАРАНЕЕ (до того как известен состав
участников), после розыгрыша сохраняется протокол — имея seed, список и
алгоритм, результат воспроизводит любой желающий. Без этого аудитория не
верит в честность, и конкурс не вовлекает, а раздражает.

Revision ID: 0027_contests
Revises: 0026_referrals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_contests"
down_revision = "0026_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prize", sa.Text(), nullable=False),
        sa.Column("winners_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("require_subscribed_chat_ids", sa.Text(), nullable=True),
        sa.Column("require_min_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("require_min_referrals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draw_seed", sa.String(length=64), nullable=False),
        sa.Column("draw_protocol", sa.Text(), nullable=True),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contests_chat_id", "contests", ["chat_id"])

    op.create_table(
        "contest_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contest_id", sa.Integer(), sa.ForeignKey("contests.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_contest_entry"),
    )
    op.create_index("ix_contest_entries_contest_id", "contest_entries", ["contest_id"])


def downgrade() -> None:
    op.drop_index("ix_contest_entries_contest_id", table_name="contest_entries")
    op.drop_table("contest_entries")
    op.drop_index("ix_contests_chat_id", table_name="contests")
    op.drop_table("contests")

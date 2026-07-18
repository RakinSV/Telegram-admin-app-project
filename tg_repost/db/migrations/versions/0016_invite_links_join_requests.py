"""F32: инвайт-ссылки целевых групп + заявки на вступление

Две новые таблицы: invite_links (созданные ботом инвайт-ссылки, Bot API не
даёт способа перечислить их иначе) и join_requests (апдейт chat_join_request,
решение принимает владелец через бота/веб-админку). См. db/models.py.

Revision ID: 0016_invite_links_join_requests
Revises: 0015_post_targets
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_invite_links_join_requests"
down_revision: str | None = "0015_post_targets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invite_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("invite_link", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("member_limit", sa.Integer(), nullable=True),
        sa.Column("creates_join_request", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invite_links_chat_id", "invite_links", ["chat_id"])

    op.create_table(
        "join_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("chat_id", "user_id", "status", name="uq_join_request_pending"),
    )
    op.create_index("ix_join_requests_chat_id", "join_requests", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_join_requests_chat_id", table_name="join_requests")
    op.drop_table("join_requests")
    op.drop_index("ix_invite_links_chat_id", table_name="invite_links")
    op.drop_table("invite_links")

"""initial schema: sources, target_groups, posts

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POST_STATUS = sa.Enum(
    "new", "filtered_out", "duplicate", "rewriting", "rewritten",
    "pending_approval", "approved", "rejected", "posted", "failed",
    name="poststatus", native_enum=False, length=32,
)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_username", sa.String(length=255), nullable=False),
        sa.Column("channel_title", sa.String(length=255), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("style_profile", sa.String(length=64), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sources_channel_username", "sources", ["channel_username"], unique=True)
    op.create_index("ix_sources_channel_id", "sources", ["channel_id"])

    op.create_table(
        "target_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_target_groups_chat_id", "target_groups", ["chat_id"], unique=True)

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("source_link", sa.String(length=512), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("rewritten_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("media_path", sa.String(length=512), nullable=True),
        sa.Column("status", _POST_STATUS, nullable=False),
        sa.Column("status_reason", sa.String(length=512), nullable=True),
        sa.Column("rewrite_tokens", sa.Integer(), nullable=True),
        sa.Column("rewrite_cost", sa.Float(), nullable=True),
        sa.Column("moderation_message_id", sa.BigInteger(), nullable=True),
        sa.Column("posted_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id", "source_message_id", name="uq_source_message"),
    )
    op.create_index("ix_posts_source_id", "posts", ["source_id"])
    op.create_index("ix_posts_content_hash", "posts", ["content_hash"])
    op.create_index("ix_posts_status", "posts", ["status"])


def downgrade() -> None:
    op.drop_table("posts")
    op.drop_index("ix_target_groups_chat_id", table_name="target_groups")
    op.drop_table("target_groups")
    op.drop_index("ix_sources_channel_id", table_name="sources")
    op.drop_index("ix_sources_channel_username", table_name="sources")
    op.drop_table("sources")

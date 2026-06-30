"""phase 4: post kind (ad/digest), ad_briefs, channel_growth_snapshots

Revision ID: 0004_phase4
Revises: 0003_phase3
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase4"
down_revision: str | None = "0003_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POST_KIND = sa.Enum(
    "source", "ad", "digest", name="postkind", native_enum=False, length=16,
)


def upgrade() -> None:
    # F21 — брифы нативной рекламы.
    op.create_table(
        "ad_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("times_used", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    # F22 — снимки числа подписчиков целевых каналов.
    op.create_table(
        "channel_growth_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("subscriber_count", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_channel_growth_snapshots_chat_id", "channel_growth_snapshots", ["chat_id"]
    )

    # posts: kind + ad_brief_id, и ослабление NOT NULL для AD/DIGEST постов,
    # у которых нет реального источника (F18-F21).
    with op.batch_alter_table("posts") as batch:
        batch.add_column(
            sa.Column("kind", _POST_KIND, nullable=False, server_default="source")
        )
        batch.add_column(sa.Column("ad_brief_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_posts_ad_brief_id", "ad_briefs", ["ad_brief_id"], ["id"]
        )
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column(
            "source_message_id", existing_type=sa.BigInteger(), nullable=True
        )
        batch.alter_column(
            "content_hash", existing_type=sa.String(length=64), nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table("posts") as batch:
        batch.alter_column(
            "content_hash", existing_type=sa.String(length=64), nullable=False
        )
        batch.alter_column(
            "source_message_id", existing_type=sa.BigInteger(), nullable=False
        )
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("fk_posts_ad_brief_id", type_="foreignkey")
        batch.drop_column("ad_brief_id")
        batch.drop_column("kind")

    op.drop_index(
        "ix_channel_growth_snapshots_chat_id", table_name="channel_growth_snapshots"
    )
    op.drop_table("channel_growth_snapshots")
    op.drop_table("ad_briefs")

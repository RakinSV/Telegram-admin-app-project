"""F06/F18-доп.: настраиваемое число вариантов рерайта/обложки на пост

Две новые таблицы (post_rewrite_variants, post_cover_variants) + индекс
активного варианта на posts — см. db/models.py и post_variants_repo.py.

Revision ID: 0010_post_variants
Revises: 0009_discovered_chats
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_post_variants"
down_revision: str | None = "0009_discovered_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("active_rewrite_variant_index", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("active_cover_variant_index", sa.Integer(), nullable=True))

    op.create_table(
        "post_rewrite_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_post_rewrite_variants_post_id", "post_rewrite_variants", ["post_id"],
    )

    op.create_table(
        "post_cover_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("media_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_post_cover_variants_post_id", "post_cover_variants", ["post_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_cover_variants_post_id", table_name="post_cover_variants")
    op.drop_table("post_cover_variants")
    op.drop_index("ix_post_rewrite_variants_post_id", table_name="post_rewrite_variants")
    op.drop_table("post_rewrite_variants")

    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_column("active_cover_variant_index")
        batch_op.drop_column("active_rewrite_variant_index")

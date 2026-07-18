"""F35: ручной учёт рекламного дохода

Новая таблица ad_revenue — журнал (не интеграция с биржей), см. AdRevenue
docstring в db/models.py.

Revision ID: 0018_ad_revenue
Revises: 0017_polls
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_ad_revenue"
down_revision: str | None = "0017_polls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ad_revenue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ad_brief_id", sa.Integer(), sa.ForeignKey("ad_briefs.id"), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ad_revenue")

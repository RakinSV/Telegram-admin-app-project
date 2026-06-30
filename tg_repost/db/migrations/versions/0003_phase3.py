"""phase 3: per-source enrichment flag

Revision ID: 0003_phase3
Revises: 0002_phase2
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase3"
down_revision: str | None = "0002_phase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # F16 — per-source «галочка добора знаний» (NULL = следовать глобальной).
    op.add_column("sources", sa.Column("enrich_sources", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("enrich_sources")

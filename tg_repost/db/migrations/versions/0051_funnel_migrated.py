"""Связь «воронка → сценарий конструктора» (F75, шаг 6).

Revision ID: 0051_funnel_migrated
Revises: 0050_bot_constructor
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_funnel_migrated"
down_revision = "0050_bot_constructor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable без значения по умолчанию: у существующих воронок переноса не
    # было, и выдумывать его нельзя.
    op.add_column(
        "funnels",
        sa.Column("migrated_to_flow_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("funnels", "migrated_to_flow_id")

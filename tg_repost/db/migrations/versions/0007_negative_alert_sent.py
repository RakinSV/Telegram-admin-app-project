"""F25: авто-реакция на негатив — posts.negative_alert_sent

Флаг «уведомление владельцу уже отправлено» — не слать повторно на каждый
цикл сбора статистики, пока порог негативных реакций превышен.

Revision ID: 0007_negative_alert_sent
Revises: 0006_post_created_at_index
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_negative_alert_sent"
down_revision: str | None = "0006_post_created_at_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "negative_alert_sent", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_column("negative_alert_sent")

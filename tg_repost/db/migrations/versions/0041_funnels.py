"""Воронки: цепочки сообщений с задержками (F71).

ЛИНЕЙНЫЕ, БЕЗ ВЕТВЛЕНИЙ — осознанный предел. Полноценный движок сценариев
разрастается бесконечно: за ветвлением просят циклы, за циклами переменные,
и получается плохой язык программирования внутри админки. Реальные задачи
владельца — онбординг новичка и цепочка напоминаний — линейны.

Revision ID: 0041_funnels
Revises: 0040_support
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_funnels"
down_revision = "0040_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funnels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="start"),
        # JSON-список шагов: колонки под них означали бы отдельную таблицу и
        # join ради данных, которые всегда читаются целиком.
        sa.Column("steps_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "funnel_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "funnel_id",
            sa.Integer(),
            sa.ForeignKey("funnels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        # Индекс СЛЕДУЮЩЕГО шага: хранить пройденный значило бы каждый раз
        # прибавлять единицу и однажды забыть это сделать.
        sa.Column("next_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        # Без причины «остановлена» выглядит как сбой.
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # Защита от повторного прохождения: человек, дважды нажавший
        # «Запустить», иначе получил бы всю цепочку дважды.
        sa.UniqueConstraint("funnel_id", "user_id", name="uq_funnel_run"),
    )
    op.create_index("ix_funnel_runs_funnel_id", "funnel_runs", ["funnel_id"])
    op.create_index("ix_funnel_runs_user_id", "funnel_runs", ["user_id"])
    op.create_index("ix_funnel_runs_status", "funnel_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_funnel_runs_status", table_name="funnel_runs")
    op.drop_index("ix_funnel_runs_user_id", table_name="funnel_runs")
    op.drop_index("ix_funnel_runs_funnel_id", table_name="funnel_runs")
    op.drop_table("funnel_runs")
    op.drop_table("funnels")

"""Очередь задач с курсором (фаза 11, решение 3).

Долгие операции — рассылка по сегменту (F64), шаги воронок (F71), повторы
постов (F55) — должны переживать рестарт процесса и продолжаться С МЕСТА
ОБРЫВА. Планировщик такого не умеет, а Celery с Redis означал бы второй
сервис в развёртывании ради свойства, которое даёт обычная строка в БД.

Revision ID: 0032_queued_tasks
Revises: 0031_channel_stats
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_queued_tasks"
down_revision = "0031_channel_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queued_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(32), nullable=False),
        # Параметры задачи, JSON строкой: набор полей у каждого вида свой, и
        # заводить под них колонки значило бы менять схему на каждую фичу.
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        # Прогресс. Именно курсор делает задачу возобновляемой: после обрыва
        # она продолжается, а не начинается заново.
        sa.Column("cursor", sa.String(255), nullable=True),
        sa.Column("done_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        # Отложенные шаги воронок (F71) — это оно.
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Обновляется обработчиком по ходу работы и служит арендой: задача в
        # статусе `running` с протухшим updated_at считается брошенной упавшим
        # процессом и подбирается заново.
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queued_tasks_kind", "queued_tasks", ["kind"])
    op.create_index("ix_queued_tasks_status", "queued_tasks", ["status"])
    # Выборка «что взять следующим» идёт ровно по этой тройке.
    op.create_index("ix_queued_tasks_pick", "queued_tasks", ["status", "run_after", "id"])


def downgrade() -> None:
    op.drop_index("ix_queued_tasks_pick", table_name="queued_tasks")
    op.drop_index("ix_queued_tasks_status", table_name="queued_tasks")
    op.drop_index("ix_queued_tasks_kind", table_name="queued_tasks")
    op.drop_table("queued_tasks")

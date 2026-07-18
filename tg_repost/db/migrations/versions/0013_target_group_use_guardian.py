"""F28: Guardian настраивается по целевым группам, не глобально

Добавляет TargetGroup.use_guardian. Плюс одноразовая миграция данных:
если задан GUARDIAN_GROUP_ID (текущая единственная защищаемая группа до
этой фичи), помечаем соответствующий target_groups.use_guardian=True, чтобы
защита не прервалась молча в момент деплоя (решено с пользователем
2026-07-17). Если такой цели ещё нет (Guardian мог защищать чат, в который
репост-бот ничего не публикует) — создаём строку с is_active=False (чтобы
не начать туда публиковать контент как побочный эффект), use_guardian=True.

Revision ID: 0013_target_group_use_guardian
Revises: 0012_target_group_can_post
Create Date: 2026-07-17
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from dotenv import load_dotenv

revision: str = "0013_target_group_use_guardian"
down_revision: str | None = "0012_target_group_can_post"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "target_groups",
        sa.Column("use_guardian", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # load_dotenv() — тот же приём, что и в db/session.py::_get_database_url,
    # миграция может запускаться в контексте, где .env ещё не подгружен.
    load_dotenv()
    raw = os.environ.get("GUARDIAN_GROUP_ID", "").strip()
    if not raw:
        return
    try:
        guardian_group_id = int(raw)
    except ValueError:
        return
    if not guardian_group_id:
        return

    conn = op.get_bind()
    result = conn.execute(
        sa.text("UPDATE target_groups SET use_guardian = 1 WHERE chat_id = :chat_id"),
        {"chat_id": guardian_group_id},
    )
    if result.rowcount == 0:
        conn.execute(
            sa.text(
                "INSERT INTO target_groups (chat_id, title, is_active, use_guardian) "
                "VALUES (:chat_id, NULL, 0, 1)"
            ),
            {"chat_id": guardian_group_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("target_groups") as batch_op:
        batch_op.drop_column("use_guardian")

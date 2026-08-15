"""Статистика канала из MTProto Stats API (F56).

Данные, которых физически нет у ботов-конкурентов: Bot API методов
`stats.*` не имеет вообще, нужна юзер-сессия — а она у нас уже работает в
listener (F02).

Числа подписчиков здесь нет намеренно: его собирает F22 в
`channel_growth_snapshots`, и вторая колонка с тем же смыслом означала бы
два источника правды.

Revision ID: 0031_channel_stats
Revises: 0030_recycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_channel_stats"
down_revision = "0030_recycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_stats_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Ключ арендатора в новой таблице сразу — решение 1 в FEATURES.md:
        # одна колонка сейчас против миграции по всей базе и ревизии каждого
        # запроса потом. Значение 1 = единственный владелец.
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("views_per_post", sa.Integer(), nullable=True),
        sa.Column("shares_per_post", sa.Integer(), nullable=True),
        sa.Column("reactions_per_post", sa.Integer(), nullable=True),
        # Доля подписчиков с ВКЛЮЧЁННЫМИ уведомлениями, 0–100. Главное поле
        # таблицы: её падение — отток до отписки.
        sa.Column("notifications_enabled_pct", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_channel_stats_snapshots_chat_id", "channel_stats_snapshots", ["chat_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_stats_snapshots_chat_id", table_name="channel_stats_snapshots")
    op.drop_table("channel_stats_snapshots")

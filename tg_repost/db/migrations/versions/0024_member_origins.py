"""Атрибуция подписчиков: откуда пришёл участник (F41).

Telegram сообщает использованную инвайт-ссылку в `chat_member`/
`chat_join_request` — эти данные приходили и выбрасывались. Теперь:
таблица `member_origins` (кто по какой ссылке пришёл и ушёл ли),
`join_requests.invite_link`, и стоимость размещения у ссылки для расчёта CPA.

Revision ID: 0024_member_origins
Revises: 0023_editorial_notes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_member_origins"
down_revision = "0023_editorial_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_origins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("invite_link", sa.String(length=255), nullable=True),
        sa.Column("invite_name", sa.String(length=64), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Уникальный: одна актуальная запись на пару (чат, участник) — повторное
    # вступление перезаписывает источник, а не плодит строки.
    op.create_index(
        "ix_member_origins_chat_user", "member_origins", ["chat_id", "user_id"], unique=True,
    )
    op.create_index("ix_member_origins_link", "member_origins", ["invite_link"])

    op.add_column("join_requests", sa.Column("invite_link", sa.String(length=255), nullable=True))
    op.add_column("invite_links", sa.Column("cost", sa.Float(), nullable=True))
    op.add_column(
        "invite_links",
        sa.Column("cost_currency", sa.String(length=8), nullable=False, server_default="RUB"),
    )


def downgrade() -> None:
    op.drop_column("invite_links", "cost_currency")
    op.drop_column("invite_links", "cost")
    op.drop_column("join_requests", "invite_link")
    op.drop_index("ix_member_origins_link", table_name="member_origins")
    op.drop_index("ix_member_origins_chat_user", table_name="member_origins")
    op.drop_table("member_origins")

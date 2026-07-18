"""F33: опросы (polls) в ленте

Новый PostKind.POLL (значение хранится строкой, native_enum=False — новый
член не требует ALTER TYPE, как было бы с настоящим SQL enum) + три новых
поля на posts для параметров опроса. Вопрос опроса — в уже существующем
`rewritten_text`, отдельного поля не заводим.

Revision ID: 0017_polls
Revises: 0016_invite_links_join_requests
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_polls"
down_revision: str | None = "0016_invite_links_join_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("poll_options", sa.Text(), nullable=True))
    op.add_column(
        "posts",
        sa.Column("poll_is_anonymous", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "posts",
        sa.Column(
            "poll_allows_multiple_answers", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_column("poll_allows_multiple_answers")
        batch_op.drop_column("poll_is_anonymous")
        batch_op.drop_column("poll_options")

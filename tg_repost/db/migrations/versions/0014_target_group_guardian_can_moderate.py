"""F28.10: флаг "может ли Guardian реально модерировать" на целевой группе

Аналог TargetGroup.can_post (миграция 0012), но для прав Guardian-бота, а
не репост-бота — синхронизируется из ОТДЕЛЬНОГО процесса Guardian через
`my_chat_member`-апдейт своего бота (см. `guardian/handlers/chat_member.py`).
NULL — Guardian ещё ни разу не видел статус в этом чате, отличать от
"точно знаем, что прав нет" (False).

Revision ID: 0014_target_group_guardian_can_moderate
Revises: 0013_target_group_use_guardian
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_target_group_guardian_can_moderate"
down_revision: str | None = "0013_target_group_use_guardian"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "target_groups", sa.Column("guardian_can_moderate", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("target_groups") as batch_op:
        batch_op.drop_column("guardian_can_moderate")

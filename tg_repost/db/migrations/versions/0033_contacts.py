"""CRM участника: ручные теги и заметки (F63).

ТАБЛИЦЫ «КОНТАКТ» ЗДЕСЬ НЕТ НАМЕРЕННО. Личность участника уже хранится:
имя и username — в `guardian.members`, откуда пришёл — в `member_origins`
(F41), кто привёл — в `referrals` (F42), активность — в `user_activity`
(F43). Своя копия карточки означала бы второй источник правды, который
неминуемо разойдётся с первым — ровно та ошибка, из-за которой пришлось
отменить журнал событий в фазе 11.

Карточка собирается ЧТЕНИЕМ. Хранится только то, чего больше нигде нет.

Revision ID: 0033_contacts
Revises: 0032_queued_tasks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_contacts"
down_revision = "0032_queued_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        # Без chat_id: тег вешается на ЧЕЛОВЕКА, а не на его участие в
        # конкретном чате. «Постоянный покупатель» остаётся таковым везде.
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("added_by", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "tag", name="uq_contact_tag"),
    )
    op.create_index("ix_contact_tags_user_id", "contact_tags", ["user_id"])
    # Выборка «все с этим тегом» — основа будущих сегментов (F64).
    op.create_index("ix_contact_tags_tag", "contact_tags", ["tenant_id", "tag"])

    op.create_table(
        "contact_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_contact_note"),
    )
    op.create_index("ix_contact_notes_user_id", "contact_notes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_contact_notes_user_id", table_name="contact_notes")
    op.drop_table("contact_notes")
    op.drop_index("ix_contact_tags_tag", table_name="contact_tags")
    op.drop_index("ix_contact_tags_user_id", table_name="contact_tags")
    op.drop_table("contact_tags")

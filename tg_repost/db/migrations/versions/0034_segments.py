"""Сегменты участников — сохранённые запросы (F63, основа F64).

Сегмент — это ЗАПРОС, а не список. Материализованный список устаревает
молча: человек ушёл из чата или перестал подходить под условие, а рассылка
всё равно уходит ему. Хранится только определение фильтра.

Revision ID: 0034_segments
Revises: 0033_contacts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_segments"
down_revision = "0033_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        # JSON с условиями: набор ключей меняется вместе с фичами, и колонки
        # под каждое условие означали бы миграцию на каждую возможность отбора.
        sa.Column("filter_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_contact_segment_name"),
    )


def downgrade() -> None:
    op.drop_table("contact_segments")

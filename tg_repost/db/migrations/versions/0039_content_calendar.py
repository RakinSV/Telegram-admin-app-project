"""Контент-календарь и согласование постов (F72).

Три поля на `posts`:

* `scheduled_for` — «не раньше этой даты». NULL сохраняет прежнее поведение:
  пост уходит в ближайший слот. Это НЕ точное время публикации — час
  по-прежнему выбирают слоты (F11) и умное расписание (F19);
* `approved_by` — кто одобрил. Без имени невозможно отличить «одобрил
  редактор» от «одобрил владелец», а на этом стоит второй уровень
  согласования;
* `needs_owner_approval` — флаг, а не новый статус. Статус-машина F05
  работает годами, и вносить в неё состояние ради НЕОБЯЗАТЕЛЬНОЙ проверки
  значило бы рисковать публикацией ради церемонии. Публикатор просто не
  берёт посты с этим флагом.

Revision ID: 0039_content_calendar
Revises: 0038_admin_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_content_calendar"
down_revision = "0038_admin_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("scheduled_for", sa.Date(), nullable=True))
    op.add_column("posts", sa.Column("approved_by", sa.String(64), nullable=True))
    op.add_column(
        "posts",
        sa.Column(
            "needs_owner_approval", sa.Boolean(), nullable=False, server_default="0",
        ),
    )
    op.create_index("ix_posts_scheduled_for", "posts", ["scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_posts_scheduled_for", table_name="posts")
    op.drop_column("posts", "needs_owner_approval")
    op.drop_column("posts", "approved_by")
    op.drop_column("posts", "scheduled_for")

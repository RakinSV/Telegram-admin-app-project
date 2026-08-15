"""Роли администраторов веб-панели (F37).

⚠️ МЕНЯЕТСЯ СПОСОБ ВХОДА. Раньше вход был по одному паролю без имени; теперь
нужны имя и пароль. Существующая учётка получает имя **owner** и роль
**owner** — пароль прежний, изменилось только то, что рядом надо ввести
«owner».

Почему нельзя было оставить как было: при одном пароле пригласить редактора
означало отдать ему токены ботов и session string, то есть полный доступ к
Telegram-аккаунту, а не к контенту.

UNIQUE добавляется отдельным индексом ПОСЛЕ заполнения: SQLite не умеет
`ALTER ... ADD CONSTRAINT`, а колонку с уникальностью в непустую таблицу
иначе не добавить.

Revision ID: 0038_admin_roles
Revises: 0037_ad_requests
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_admin_roles"
down_revision = "0037_ad_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("username", sa.String(64), nullable=True))
    op.add_column(
        "admin_users",
        sa.Column("role", sa.String(16), nullable=False, server_default="owner"),
    )

    # Существующая учётка становится владельцем с предсказуемым именем.
    # Молчаливое NULL здесь означало бы «войти невозможно»: форма входа
    # спрашивает имя, а сопоставить его будет не с чем.
    op.execute(
        "UPDATE admin_users SET username = 'owner', role = 'owner' "
        "WHERE username IS NULL"
    )
    op.create_index(
        "ux_admin_users_username", "admin_users", ["username"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_admin_users_username", table_name="admin_users")
    op.drop_column("admin_users", "role")
    op.drop_column("admin_users", "username")

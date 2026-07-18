"""F28: стоп-слова и whitelist доменов раздельно по каждой защищаемой группе

- stop_words: добавляем chat_id, уникальность теперь по (word, chat_id) —
  раньше слово было уникально ГЛОБАЛЬНО (одно и то же слово нельзя было
  завести в двух группах отдельно, хотя по факту список был один общий).
  Таблица маленькая (список стоп-слов вручную ведёт один оператор) —
  пересоздаём полностью через raw SQL, а не полагаемся на Alembic batch
  mode для SQLite менять constraint на лету (надёжнее для маленькой
  таблицы, чем гадать точное имя старого implicit unique-индекса).
- allowed_domains: новая таблица (раньше — один общий JSON-список внутри
  bot_config['allowed_domains'], см. guardian/domains_repo.py).

Существующие данные переносятся на GUARDIAN_GROUP_ID (текущая единственная
защищаемая группа до этой фичи), тот же принцип, что и в миграции
tg_repost 0013_target_group_use_guardian — ничего не молчаливо теряется,
даже если GUARDIAN_GROUP_ID не задан на момент миграции (тогда chat_id=0 —
не настоящий Telegram chat_id, но данные сохранены, а не отброшены).

Revision ID: 0002_per_chat_lists
Revises: 0001_guardian_init
Create Date: 2026-07-17
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from dotenv import load_dotenv

revision: str = "0002_per_chat_lists"
down_revision: str | None = "0001_guardian_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _current_guardian_group_id() -> int:
    load_dotenv()  # тот же приём, что и в db/session.py
    raw = os.environ.get("GUARDIAN_GROUP_ID", "").strip()
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def upgrade() -> None:
    conn = op.get_bind()
    guardian_group_id = _current_guardian_group_id()

    # --- stop_words: пересоздать с chat_id, перенести существующие слова ---
    existing_words = [
        row[0] for row in conn.execute(sa.text("SELECT word FROM stop_words")).fetchall()
    ]
    op.drop_table("stop_words")
    op.create_table(
        "stop_words",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("added_by", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_stop_words_word_chat", "stop_words", ["word", "chat_id"], unique=True,
    )
    for word in existing_words:
        conn.execute(
            sa.text(
                "INSERT INTO stop_words (word, chat_id, added_by) "
                "VALUES (:word, :chat_id, 'migrated')"
            ),
            {"word": word, "chat_id": guardian_group_id},
        )

    # --- allowed_domains: новая таблица, перенос из bot_config ---
    op.create_table(
        "allowed_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("added_by", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_allowed_domains_domain_chat", "allowed_domains", ["domain", "chat_id"], unique=True,
    )
    row = conn.execute(
        sa.text("SELECT value FROM bot_config WHERE key = 'allowed_domains'")
    ).fetchone()
    if row is not None:
        try:
            domains = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            domains = []
        for domain in domains:
            conn.execute(
                sa.text(
                    "INSERT INTO allowed_domains (domain, chat_id, added_by) "
                    "VALUES (:domain, :chat_id, 'migrated')"
                ),
                {"domain": domain, "chat_id": guardian_group_id},
            )


def downgrade() -> None:
    op.drop_index("uq_allowed_domains_domain_chat", table_name="allowed_domains")
    op.drop_table("allowed_domains")

    conn = op.get_bind()
    words = [
        row[0]
        for row in conn.execute(sa.text("SELECT DISTINCT word FROM stop_words")).fetchall()
    ]
    op.drop_table("stop_words")
    op.create_table(
        "stop_words",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(length=255), unique=True),
        sa.Column("added_by", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
    )
    for word in words:
        conn.execute(
            sa.text("INSERT INTO stop_words (word, added_by) VALUES (:word, 'migrated')"),
            {"word": word},
        )

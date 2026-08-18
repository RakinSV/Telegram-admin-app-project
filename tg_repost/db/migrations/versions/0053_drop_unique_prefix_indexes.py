"""Снять индексы, покрытые уникальными ограничениями (аудит 2026-08-19).

Revision ID: 0053_drop_unique_prefix_indexes
Revises: 0052_index_hygiene

ВТОРАЯ ВОЛНА ДУБЛЕЙ, И НАШЛАСЬ ОНА ТОЛЬКО НА СТЕНДЕ. Миграция 0052 убрала
девять индексов, дублировавших ОБЫЧНЫЕ составные. Проверка на живой базе
показала ещё девять — на этот раз дублирующих НЕЯВНЫЕ индексы уникальных
ограничений (`sqlite_autoindex_*`). Локальный сторож их не видел: SQLAlchemy
в списке индексов неявные не перечисляет, и «чисто» он говорил честно, но
неполно. Теперь сторож смотрит через PRAGMA, то есть ровно то же, что видит
СУБД.

Уникальное ограничение — это тоже индекс, и поиск по его началу работает так
же: `UNIQUE(source_id, source_message_id)` полностью покрывает поиск по
`source_id`. Отдельный индекс рядом не даёт ничего и стоит перезаписи ещё
одного B-дерева на каждой вставке. Дороже всего это на `posts` — самой
пишущей таблице системы.

То же верно и на Postgres: уникальное ограничение там тоже реализовано
индексом, и префиксный поиск идёт по нему.

`downgrade` возвращает индексы как были.
"""

from __future__ import annotations

from alembic import op

revision = "0053_drop_unique_prefix_indexes"
down_revision = "0052_index_hygiene"
branch_labels = None
depends_on = None

# (имя индекса, таблица, колонки, каким уникальным ограничением покрыт)
COVERED_BY_UNIQUE = [
    ("ix_posts_source_id", "posts", ["source_id"],
     "UNIQUE(source_id, source_message_id)"),
    ("ix_join_requests_chat_id", "join_requests", ["chat_id"],
     "UNIQUE(chat_id, user_id, status)"),
    ("ix_quiz_answers_quiz_id", "quiz_answers", ["quiz_id"],
     "UNIQUE(quiz_id, user_id)"),
    ("ix_contest_entries_contest_id", "contest_entries", ["contest_id"],
     "UNIQUE(contest_id, user_id)"),
    ("ix_payment_events_kind", "payment_events", ["kind"],
     "UNIQUE(kind, charge_id, period_end)"),
    ("ix_channel_subscriptions_chat_id", "channel_subscriptions", ["chat_id"],
     "UNIQUE(chat_id, user_id)"),
    ("ix_flow_nodes_version", "flow_nodes", ["flow_id", "version"],
     "UNIQUE(flow_id, version, node_key)"),
    ("ix_flow_runs_flow_id", "flow_runs", ["flow_id"],
     "UNIQUE(flow_id, user_id)"),
    # Таблица выведенного движка воронок: сама она оставлена пустой, но
    # лишний индекс на ней не нужен ровно так же.
    ("ix_funnel_runs_funnel_id", "funnel_runs", ["funnel_id"],
     "UNIQUE(funnel_id, user_id)"),
]


def upgrade() -> None:
    for name, table, _columns, _covered_by in COVERED_BY_UNIQUE:
        # `if_exists` намеренно: базы, собранные `create_all` (тесты), и базы
        # разных возрастов могут не иметь части этих индексов, а падение на
        # «нет такого индекса» остановило бы всю цепочку.
        op.drop_index(name, table_name=table, if_exists=True)


def downgrade() -> None:
    for name, table, columns, _covered_by in COVERED_BY_UNIQUE:
        op.create_index(name, table, columns, if_not_exists=True)

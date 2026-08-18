"""Порядок в индексах: снять дубли и выровнять имена (аудит 2026-08-18).

Revision ID: 0052_index_hygiene
Revises: 0051_funnel_migrated

НАЙДЕНО ЗАМЕРОМ СХЕМЫ, А НЕ ГЛАЗАМИ. Девять индексов оказались полными
дублями: их колонки — начало другого, составного индекса. SQLite (как и
Postgres) умеет искать по префиксу составного индекса, поэтому одноколоночный
рядом с ним не даёт НИЧЕГО, а стоит на каждой вставке и каждом обновлении
строки: каждый лишний индекс — это дополнительное B-дерево, которое надо
переписать.

Второй, менее очевидный вред: два равно подходящих индекса делают выбор
планировщика неустойчивым. Обнаружилось это ровно так — сторож планов
запросов мигал, потому что SQLite брал то `ix_queued_tasks_status`, то
`ix_queued_tasks_pick` на одном и том же запросе.

Дубли появились естественно: сначала колонка получала `index=True` как
внешний ключ или фильтр, потом под запрос добавлялся составной индекс с той
же колонкой первой, а старый никто не снимал.

ВТОРАЯ ЧАСТЬ — ИМЯ ИНДЕКСА. У `story_clusters.primary_post_id` индекс есть и
в моделях, и в миграциях, но под РАЗНЫМИ именами: миграция 0028 назвала его
`ix_story_clusters_primary`, а модели — `ix_story_clusters_primary_post_id`
(так его называет SQLAlchemy для `index=True`). Работал он всё это время, но
любая будущая миграция, сославшаяся на имя из моделей, упала бы на живой базе
и прошла бы в тестах. Нашёл это новый сторож расхождения миграций и моделей.

`downgrade` возвращает их как были — на случай, если какой-то запрос
неожиданно окажется зависимым от отдельного индекса на СУБД с другим
планировщиком.
"""

from __future__ import annotations

from alembic import op

revision = "0052_index_hygiene"
down_revision = "0051_funnel_migrated"
branch_labels = None
depends_on = None

# (имя индекса, таблица, колонки) — колонки нужны для downgrade.
REDUNDANT = [
    ("ix_ad_requests_chat_id", "ad_requests", ["chat_id"]),
    ("ix_affiliate_rewards_partner_user_id", "affiliate_rewards", ["partner_user_id"]),
    ("ix_flow_edges_flow_id", "flow_edges", ["flow_id"]),
    # Двухколоночный тоже дубль: он начало ix_flow_edges_from.
    ("ix_flow_edges_version", "flow_edges", ["flow_id", "version"]),
    ("ix_flow_nodes_flow_id", "flow_nodes", ["flow_id"]),
    ("ix_flow_runs_status", "flow_runs", ["status"]),
    ("ix_payment_events_user_id", "payment_events", ["user_id"]),
    ("ix_post_rewrite_variants_post_id", "post_rewrite_variants", ["post_id"]),
    ("ix_queued_tasks_status", "queued_tasks", ["status"]),
]


# Индекс, названный в миграциях иначе, чем его называют модели.
RENAMES = [
    ("ix_story_clusters_primary", "ix_story_clusters_primary_post_id",
     "story_clusters", ["primary_post_id"]),
]


def upgrade() -> None:
    for name, table, _columns in REDUNDANT:
        # `if_exists` намеренно: базы, созданные `create_all` (тесты) и базы
        # после разных этапов миграций могут не иметь части этих индексов, и
        # падение на «нет такого индекса» остановило бы всю цепочку.
        op.drop_index(name, table_name=table, if_exists=True)

    for old_name, new_name, table, columns in RENAMES:
        # Пересоздание, а не ALTER: SQLite не умеет переименовывать индексы, а
        # и в Postgres пересоздать индекс из четырёх строк дешевле, чем держать
        # две ветки кода под разные СУБД.
        op.drop_index(old_name, table_name=table, if_exists=True)
        op.create_index(new_name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for old_name, new_name, table, columns in RENAMES:
        op.drop_index(new_name, table_name=table, if_exists=True)
        op.create_index(old_name, table, columns, if_not_exists=True)

    for name, table, columns in REDUNDANT:
        op.create_index(name, table, columns, if_not_exists=True)

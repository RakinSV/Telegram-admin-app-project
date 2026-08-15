"""Фильтры на уровне источника (F54).

До этого фильтр слов был только глобальным, хотя README в обеих языковых
версиях уже обещал «стоп-/обязательные слова глобально ИЛИ НА КАНАЛ». Теперь
обещание становится правдой: шумной ленте — строгие правила, спокойной —
мягкие.

Колонки на `sources`, а не отдельная таблица: рядом уже лежат `target_chat_ids`
(CSV) и `style_profile` — переопределения источника хранятся именно так, и
заводить ради двух списков третий способ значило бы держать в системе два
разных механизма для одного и того же.

Revision ID: 0029_source_filters
Revises: 0028_story_clusters
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_source_filters"
down_revision = "0028_story_clusters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = «следовать глобальной настройке» — та же тристейт-семантика, что
    # у `enrich_sources` (F16). Пустая строка означала бы «явно пустой список»
    # и это РАЗНЫЕ вещи: у обязательных слов пустой список снимает требование.
    op.add_column("sources", sa.Column("filter_stop_words", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("filter_required_words", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "filter_required_words")
    op.drop_column("sources", "filter_stop_words")

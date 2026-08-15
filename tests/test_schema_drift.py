"""Расхождение моделей и миграций — закреплено, а не исправлено (аудит 2026-08-16).

ЗАЧЕМ ЭТОТ ТЕСТ. Тесты создают схему через `create_all` из моделей, а
боевая база — через alembic. Это два разных источника правды, и они уже
расходились: в F37 уникальный индекс на `admin_users.username` жил только в
миграции, поэтому тесты пропускали дубли, которых прод не допустил бы.
Молча такое расхождение обнаруживается в проде.

ПОЧЕМУ РАСХОЖДЕНИЯ НЕ УСТРАНЕНЫ, А ЗАФИКСИРОВАНЫ. Их 26, и ни одно не
меняет поведения:

* **20 × nullable** — модель говорит NOT NULL, база разрешает NULL. Все эти
  колонки заполняются значением по умолчанию на стороне Python, а строгая
  сторона здесь — ТЕСТЫ. То есть пропущенное значение упадёт в тестах и
  проскочит в проде, а не наоборот. Чинить это значит перелопатить 20 таблиц
  batch-миграциями SQLite ради поведения, которого не бывает;
* **4 × внешний ключ** — объявлен в модели, отсутствует в базе. Влияния нет
  вообще: `PRAGMA foreign_keys` в SQLite по умолчанию 0, ключи не
  проверяются даже там, где они есть (см. `funnels_repo.delete`);
* **1 × имя индекса** — `ix_story_clusters_primary` против
  `ix_story_clusters_primary_post_id`. Индекс тот же и на той же колонке,
  различается только имя.

Тест сторожит ЧИСЛО и СОСТАВ расхождений: новое расхождение уронит сборку,
а известные не будут каждый раз переоткрываться заново.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from tg_repost.db.models import Base

# Таблицы, у которых модель строже базы по nullable. Список именно такой
# длины и состава — если он изменился, значит появилась новая миграция,
# которая разошлась с моделью.
KNOWN_NULLABLE_DRIFT = {
    ("ad_briefs", "created_at"),
    ("ad_revenue", "created_at"),
    ("admin_users", "created_at"),
    ("admin_users", "updated_at"),
    ("app_settings", "updated_at"),
    ("audit_log", "created_at"),
    ("channel_growth_snapshots", "captured_at"),
    ("discovered_chats", "discovered_at"),
    ("invite_links", "created_at"),
    ("join_requests", "requested_at"),
    ("post_cover_variants", "created_at"),
    ("post_rewrite_variants", "created_at"),
    ("post_stats", "captured_at"),
    ("posts", "original_text"),
    ("posts", "created_at"),
    ("posts", "updated_at"),
    ("secrets", "updated_at"),
    ("sources", "added_at"),
    ("target_groups", "added_at"),
    ("telethon_sessions", "added_at"),
}

KNOWN_MISSING_FK_TABLES = {"ad_requests", "posts"}
KNOWN_INDEX_DRIFT = {"ix_story_clusters_primary", "ix_story_clusters_primary_post_id"}


@pytest.fixture(scope="module")
def _diff() -> list:
    """Разница между моделями и базой, СОБРАННОЙ МИГРАЦИЯМИ.

    Отдельная временная база: сравнивать с рабочей нельзя — она могла
    пережить ручные правки, и тест начал бы зависеть от чужой истории.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "drift.db"
        url = f"sqlite:///{db_path.as_posix()}"

        # Config БЕЗ ini-файла, и это принципиально: при чтении `alembic.ini`
        # env.py вызывает `fileConfig()`, а тот переинициализирует логирование
        # всего процесса и отцепляет обработчик pytest. Поймано на общем
        # прогоне: соседний тест, проверяющий предупреждение через `caplog`,
        # падал с пустым логом, хотя по отдельности проходил.
        config = Config()
        config.set_main_option("script_location", "tg_repost/db/migrations")
        config.set_main_option("sqlalchemy.url", url)
        # env.py берёт URL из настроек приложения — перебиваем его на время
        # прогона, иначе миграции уедут в рабочую базу.
        config.attributes["sqlalchemy.url"] = url
        import tg_repost.config as app_config

        original = app_config.get_settings

        class _Patched:
            def __getattr__(self, name):
                if name == "database_url":
                    return url
                return getattr(original(), name)

        app_config.get_settings = lambda: _Patched()  # type: ignore[assignment]
        try:
            command.upgrade(config, "head")
        finally:
            app_config.get_settings = original  # type: ignore[assignment]

        engine = sa.create_engine(url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diff = compare_metadata(ctx, Base.metadata)
        engine.dispose()
        return list(diff)


def _flatten(diff: list) -> list:
    """Alembic отдаёт часть различий списком внутри списка — разворачиваем."""
    out = []
    for item in diff:
        if isinstance(item, list):
            out.extend(item)
        else:
            out.append(item)
    return out


def test_no_missing_tables_or_columns(_diff):
    """САМОЕ ВАЖНОЕ: миграции создают ВСЕ таблицы и колонки моделей.

    Забытая колонка — это `OperationalError: no such column` в проде при
    зелёных тестах.
    """
    kinds = {item[0] for item in _flatten(_diff)}

    assert "add_table" not in kinds
    assert "add_column" not in kinds
    assert "remove_column" not in kinds


def test_nullable_drift_did_not_grow(_diff):
    found = {
        (item[2], item[3]) for item in _flatten(_diff) if item[0] == "modify_nullable"
    }

    assert found == KNOWN_NULLABLE_DRIFT, (
        "изменился набор колонок, где модель строже базы: "
        f"новые {found - KNOWN_NULLABLE_DRIFT}, ушедшие {KNOWN_NULLABLE_DRIFT - found}"
    )


def test_only_known_foreign_keys_are_missing(_diff):
    tables = {
        item[1].table.name for item in _flatten(_diff) if item[0] == "add_fk"
    }

    assert tables <= KNOWN_MISSING_FK_TABLES, f"новый несозданный внешний ключ: {tables}"


def test_only_known_index_drift(_diff):
    names = {
        item[1].name
        for item in _flatten(_diff)
        if item[0] in ("add_index", "remove_index")
    }

    assert names <= KNOWN_INDEX_DRIFT, f"новое расхождение по индексам: {names}"


def test_drift_total_did_not_grow(_diff):
    """Общий счётчик — сторож против расхождений, не попавших в категории выше."""
    assert len(_flatten(_diff)) == 26, (
        f"число расхождений моделей и миграций изменилось: {len(_flatten(_diff))} вместо 26"
    )

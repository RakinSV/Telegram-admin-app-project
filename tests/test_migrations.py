"""Цепочка миграций применяется и совпадает с моделями.

ЧЕГО ЗДЕСЬ НЕ БЫЛО ДО 2026-08-18. Пятьдесят две миграции — и ни одной проверки,
что цепочка вообще применяется на чистой базе. Локально это не всплывало,
потому что тесты строят схему из моделей (`Base.metadata.create_all`) и
миграции не трогают вовсе.

ЦЕНА ЭТОГО УЖЕ ПЛАТИЛАСЬ. Guardian на стенде уходил в цикл перезапусков,
потому что образ пересобирали только для `tg_repost`, и контейнер не знал
миграции `0003_spam_reviews`. Диагноз тогда искали в токенах — то есть не там,
где была причина.

РАСХОЖДЕНИЕ МОДЕЛЕЙ И МИГРАЦИЙ проверяет соседний файл — `test_schema_drift.py`,
и делает это подробнее (типы, nullable, внешние ключи). Здесь его не
дублируем: два сторожа на одно и то же со временем разъезжаются, и чинить
начинают тот, который громче ругается. Здесь остаётся то, чего он не смотрит:
применяется ли цепочка вообще, нет ли в получившейся схеме индексов-дублей и
что происходит с ОТДЕЛЬНОЙ базой Guardian.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from guardian.config import invalidate_settings_cache as invalidate_guardian_cache
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import Base

# Таблицы, которых в моделях нет намеренно.
_ALEMBIC_OWN = {"alembic_version"}
# Таблицы старого движка воронок: удалён 2026-08-18, а таблицы оставлены в базе
# пустыми намеренно — данные никто не терял, миграции не переписывались.
_RETIRED = {"funnels", "funnel_steps", "funnel_runs"}


def _invalidate_caches() -> None:
    """Сбросить ОБА кэша настроек.

    У Guardian свой `lru_cache` — сбрасывать только кэш `tg_repost` мало.
    Поймано этим же тестом: второй прогон цепочки Guardian в том же процессе
    молча обновлял ПЕРВУЮ базу (в кэше остался её адрес), новый файл оставался
    пустым, и тест сообщал «таблиц нет в миграциях вовсе». Ровно та ошибка,
    ради поиска которой этот файл и написан, только в самом тесте.
    """
    invalidate_settings_cache()
    invalidate_guardian_cache()


def _upgraded_db(tmp_dir: Path, script_location: str, ini: str, env_var: str) -> Path:
    """Применить всю цепочку миграций на пустой файл базы.

    АДРЕС БАЗЫ ЗАДАЁТСЯ ПЕРЕМЕННОЙ СРЕДЫ, А НЕ `sqlalchemy.url`: `env.py`
    намеренно перетирает url значением из настроек, чтобы адрес базы не
    дублировался в двух местах. Первая версия теста этого не учла — цепочка
    успешно применялась к тестовой базе В ПАМЯТИ, файл на диске не появлялся,
    и тест падал на пустом месте, хотя миграции были в порядке.
    """
    db_path = tmp_dir / "migrated.db"
    config = Config(ini)
    config.set_main_option("script_location", script_location)

    previous = os.environ.get(env_var)
    os.environ[env_var] = f"sqlite:///{db_path.as_posix()}"
    _invalidate_caches()
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = previous
        _invalidate_caches()
    return db_path


@pytest.fixture(scope="session")
def migrated_db(tmp_path_factory) -> Path:
    """Файл базы после всей цепочки миграций — ОДИН на весь прогон.

    Область session, а не function: применение 52 миграций на Windows идёт
    десятками секунд, и повторять его ради каждой проверки значит платить
    минуты на каждом запуске тестов. Первая версия кэшировала путь через
    `request.config.cache` и ловила `NoSuchTableError` — pytest вычищает
    `tmp_path` предыдущего теста, и кэш указывал на удалённый файл.
    """
    return _upgraded_db(
        tmp_path_factory.mktemp("migrated"), "tg_repost/db/migrations",
        "alembic.ini", "DATABASE_URL",
    )


@pytest.fixture(scope="session")
def migrated_schema(migrated_db):
    return inspect(create_engine(f"sqlite:///{migrated_db.as_posix()}"))


def test_migration_chain_applies_to_an_empty_database(migrated_db):
    """Главное: цепочка проходит целиком, без падения на середине."""
    assert migrated_db.exists()
    conn = sqlite3.connect(migrated_db)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert "posts" in tables
    assert "alembic_version" in tables


def test_guardian_migration_chain_applies(guardian_migrated_db):
    """Своя база и своя цепочка — единственная реальная граница безопасности
    в системе, и проверять её надо отдельно."""
    conn = sqlite3.connect(guardian_migrated_db)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert "members" in tables, sorted(tables)








def test_redundant_indexes_are_gone_after_migration(migrated_schema):
    """Миграция 0052 действительно снимает дубли, а не только модели их не
    объявляют. Проверять надо именно миграцию: на стенде схема получена ею, а
    не `create_all`, и «в моделях чисто» там ничего не значит."""
    problems = []
    for table in sorted(Base.metadata.tables):
        indexes = [
            (index["name"], tuple(index["column_names"]))
            for index in migrated_schema.get_indexes(table)
        ]
        for name, columns in indexes:
            for other, other_columns in indexes:
                if name == other or len(other_columns) <= len(columns):
                    continue
                if other_columns[: len(columns)] == columns:
                    problems.append(f"{table}: {name} ⊂ {other}")

    assert not problems, "в миграциях остались индексы-дубли: " + "; ".join(problems)


@pytest.fixture(scope="session")
def guardian_migrated_db(tmp_path_factory) -> Path:
    """База Guardian после его собственной цепочки — тоже одна на прогон."""
    return _upgraded_db(
        tmp_path_factory.mktemp("guardian_migrated"), "guardian/db/migrations",
        "alembic_guardian.ini", "GUARDIAN_DATABASE_URL",
    )


@pytest.fixture(scope="session")
def guardian_migrated_schema(guardian_migrated_db):
    return inspect(create_engine(f"sqlite:///{guardian_migrated_db.as_posix()}"))


def test_guardian_columns_match_the_models(guardian_migrated_schema):
    """Guardian живёт в отдельной базе со своей цепочкой — значит и разойтись
    с моделями может независимо. Именно на его цепочке система уже один раз
    уходила в цикл перезапусков."""
    from guardian.db.models import Base as GuardianBase

    problems = []
    for table in sorted(GuardianBase.metadata.tables):
        try:
            in_db = {
                column["name"]
                for column in guardian_migrated_schema.get_columns(table)
            }
        except Exception:
            problems.append(f"{table}: таблицы нет в миграциях вовсе")
            continue
        in_models = set(GuardianBase.metadata.tables[table].columns.keys())
        missing = in_models - in_db
        if missing:
            problems.append(f"{table}: нет колонок {sorted(missing)}")

    assert not problems, "миграции Guardian разошлись с моделями: " + "; ".join(problems)


def test_guardian_indexes_match_the_models(guardian_migrated_schema):
    from guardian.db.models import Base as GuardianBase

    problems = []
    for table in sorted(GuardianBase.metadata.tables):
        try:
            in_db = {
                index["name"]
                for index in guardian_migrated_schema.get_indexes(table)
            }
        except Exception:
            continue
        in_models = {index.name for index in GuardianBase.metadata.tables[table].indexes}
        missing = in_models - in_db
        if missing:
            problems.append(f"{table}: нет индексов {sorted(missing)}")

    assert not problems, (
        "индексы моделей Guardian отсутствуют в миграциях: " + "; ".join(problems)
    )

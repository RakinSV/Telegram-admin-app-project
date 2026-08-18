"""Схема не должна обрастать индексами-дублями (аудит 2026-08-18).

НАЙДЕНО ЗАМЕРОМ СХЕМЫ: девять индексов оказались полными дублями — их колонки
были началом другого, составного индекса. И SQLite, и Postgres умеют искать по
префиксу составного индекса, поэтому одноколоночный рядом с ним не даёт
НИЧЕГО, а платить за него приходится каждой вставкой: лишнее B-дерево надо
переписывать на каждой строке.

Второй вред тоньше: два равно подходящих индекса делают выбор планировщика
неустойчивым. Именно так это и вскрылось — сторож планов запросов мигал, потому
что SQLite брал то `ix_queued_tasks_status`, то `ix_queued_tasks_pick` на одном
и том же запросе.

Дубли появляются естественно и незаметно: колонка получает `index=True` как
внешний ключ, потом под запрос добавляется составной индекс с той же колонкой
первой, а старый никто не снимает. Поэтому проверка постоянная, а не разовая.
"""

from __future__ import annotations

from sqlalchemy import inspect

from guardian.db.session import engine as guardian_engine
from tg_repost.db.session import engine


def _redundant(target_engine) -> list[str]:
    insp = inspect(target_engine)
    problems: list[str] = []
    for table in sorted(insp.get_table_names()):
        indexes = [
            (i["name"], tuple(i["column_names"])) for i in insp.get_indexes(table)
        ]
        for name, columns in indexes:
            for other, other_columns in indexes:
                if name == other or len(other_columns) <= len(columns):
                    continue
                if other_columns[: len(columns)] == columns:
                    problems.append(
                        f"{table}: {name}{columns} — это префикс "
                        f"{other}{other_columns}, платим за него каждой вставкой"
                    )
    return problems


def test_no_redundant_indexes_in_tg_repost():
    problems = _redundant(engine)
    assert not problems, "индексы-дубли:\n" + "\n".join(problems)


def test_no_redundant_indexes_in_guardian():
    """Guardian со своей базой и своей цепочкой миграций — правило то же."""
    problems = _redundant(guardian_engine)
    assert not problems, "индексы-дубли:\n" + "\n".join(problems)

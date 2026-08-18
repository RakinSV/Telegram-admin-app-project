"""Схема не должна обрастать индексами-дублями (аудит 2026-08-18/19).

НАЙДЕНО ЗАМЕРОМ СХЕМЫ, ДВУМЯ ЗАХОДАМИ.

Первый: девять индексов оказались полными дублями обычных составных — их
колонки были началом другого индекса. И SQLite, и Postgres умеют искать по
префиксу составного индекса, поэтому одноколоночный рядом с ним не даёт
НИЧЕГО, а платить за него приходится каждой вставкой: лишнее B-дерево надо
переписывать на каждой строке.

Второй заход нашёл ЕЩЁ ДЕВЯТЬ — и только на живой базе стенда. Они
дублировали неявные индексы уникальных ограничений (`sqlite_autoindex_*`),
которых SQLAlchemy в списке индексов не показывает. Первая версия этого
сторожа спрашивала именно у SQLAlchemy и отвечала «чисто» — честно, но
неполно. Поэтому теперь вопрос задаётся через PRAGMA: это ровно то, что видит
сама СУБД, включая индексы, которых никто не объявлял руками.

Второй вред дублей тоньше первого: два равно подходящих индекса делают выбор
планировщика неустойчивым. Именно так это и вскрылось — сторож планов запросов
мигал, потому что SQLite брал то `ix_queued_tasks_status`, то
`ix_queued_tasks_pick` на одном и том же запросе.

Дубли появляются естественно и незаметно: колонка получает `index=True` как
внешний ключ, потом на неё же кладётся уникальное ограничение или составной
индекс, а старый никто не снимает. Поэтому проверка постоянная, а не разовая.
"""

from __future__ import annotations

from sqlalchemy import text

from guardian.db.session import engine as guardian_engine
from tg_repost.db.session import engine


def _indexes(conn, table: str) -> list[tuple[str, tuple[str, ...]]]:
    """Все индексы таблицы ГЛАЗАМИ СУБД, включая неявные."""
    rows = conn.execute(text(f"PRAGMA index_list('{table}')")).fetchall()
    result = []
    for row in rows:
        name = row[1]
        columns = tuple(
            info[2]
            for info in conn.execute(text(f"PRAGMA index_info('{name}')")).fetchall()
        )
        result.append((name, columns))
    return result


def _redundant(target_engine) -> list[str]:
    problems: list[str] = []
    with target_engine.connect() as conn:
        tables = [
            row[0] for row in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )).fetchall()
        ]
        for table in sorted(tables):
            indexes = _indexes(conn, table)
            for name, columns in indexes:
                # Неявный индекс уникального ограничения снять нельзя — он и
                # есть ограничение. Ругаться имеет смысл только на явные.
                if name.startswith("sqlite_autoindex"):
                    continue
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

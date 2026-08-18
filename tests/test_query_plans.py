"""Горячие запросы не должны сползать в полный скан таблицы.

ЗАЧЕМ СТОРОЖ, А НЕ РАЗОВЫЙ ЗАМЕР. Планы проверены на живых данных стенда
2026-08-18: все горячие запросы шли по индексам. Но план — свойство схемы, а
не намерения: достаточно кому-то добавить фильтр по новому полю или снять
`index=True`, и запрос молча станет читать таблицу целиком. Заметно это будет
не сразу, а на объёме — то есть в самый неудобный момент.

ПРОВЕРЯЕТСЯ «ИДЁТ ПО ИНДЕКСУ», А НЕ «ПО ЭТОМУ ИНДЕКСУ». Первая версия
требовала конкретное имя и мигала: на `queued_tasks` подходили сразу два
индекса, и SQLite брал то один, то другой. Требовать имя — значит проверять
решение планировщика, а не свойство схемы; дубли индексов ловит отдельный
сторож `test_schema_indexes.py`.

ЧТО ЗДЕСЬ СОЗНАТЕЛЬНО НЕ ПРОВЕРЯЕТСЯ. Страница `/audit` сортирует по `id` —
это алиас rowid, SQLite идёт по нему в обратную сторону и останавливается на
`LIMIT`, поэтому «SCAN audit_log» там не дефект, а оптимальный план. Именно
из-за этого ранее задуманный индекс на `audit_log.created_at` не появился:
измерение показало, что страница по этому полю не сортирует вовсе.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tg_repost.db.session import engine

# (описание, запрос, по какой таблице обязан быть поиск по индексу)
HOT_QUERIES = [
    (
        "очередь: взять следующую задачу",
        "SELECT * FROM queued_tasks WHERE run_after <= '2026-08-18' "
        "AND status = 'pending' ORDER BY run_after LIMIT 1",
        "queued_tasks",
    ),
    (
        "очередь: упавшие задачи на дашборд",
        "SELECT * FROM queued_tasks WHERE status = 'failed' "
        "ORDER BY updated_at DESC LIMIT 10",
        "queued_tasks",
    ),
    (
        "очередь: уборка завершённых по сроку",
        "SELECT * FROM queued_tasks WHERE status IN ('done','failed','canceled') "
        "AND updated_at < '2026-01-01'",
        "queued_tasks",
    ),
    (
        "посты: очередь модерации",
        "SELECT * FROM posts WHERE status = 'pending_approval' "
        "ORDER BY created_at DESC LIMIT 50",
        "posts",
    ),
    (
        "посты: отбор для уборки медиа",
        "SELECT * FROM posts WHERE media_path IS NOT NULL "
        "AND status IN ('rejected','posted') AND created_at < '2026-08-01'",
        "posts",
    ),
    (
        "посты: поиск дубля по хэшу",
        "SELECT * FROM posts WHERE content_hash = 'abc'",
        "posts",
    ),
    (
        "статистика: снимки поста",
        "SELECT * FROM post_stats WHERE post_id IN (1,2,3) ORDER BY captured_at",
        "post_stats",
    ),
    (
        "варианты рерайта поста на нужном языке",
        "SELECT * FROM post_rewrite_variants WHERE post_id = 5 AND language = 'ru'",
        "post_rewrite_variants",
    ),
    (
        "обложки поста",
        "SELECT * FROM post_cover_variants WHERE post_id = 5",
        "post_cover_variants",
    ),
]


def _plan(sql: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + sql)).fetchall()
    return [str(row[-1]) for row in rows]


@pytest.mark.parametrize("label,sql,table", HOT_QUERIES,
                         ids=[q[0] for q in HOT_QUERIES])
def test_hot_query_uses_an_index(label, sql, table):
    lines = _plan(sql)
    joined = " | ".join(lines)

    assert any(
        line.startswith(f"SEARCH {table} USING") and "INDEX" in line
        for line in lines
    ), f"{label}: поиск по {table} идёт не через индекс. План: {joined}"
    assert not any(
        line.startswith("SCAN") and "USING" not in line for line in lines
    ), f"{label}: полный скан таблицы. План: {joined}"

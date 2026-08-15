"""Последний снимок метрик поста — одна точка на всю систему.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Запрос «взять последний снимок из `post_stats`» был
написан заново в ЧЕТЫРЁХ местах: `scheduler/stats.py` (F14), `scheduler/
digest.py` (F20), `engagement_repo.py` (F53) и `scheduler/recycle.py` (F55).
Все четыре писались независимо, и все четыре повторили одну и ту же ошибку —
сортировку только по `captured_at`, без тай-брейка.

Ошибка не теоретическая: гранулярность системных часов на Windows ~15 мс,
поэтому два замера подряд регулярно получают ОДИНАКОВУЮ метку времени, а при
равенстве порядок строк не определён. Поймано на F53 прогоном одного теста
десять раз подряд: 4 прохода, 6 падений. В `scheduler/stats.py` эта ошибка
жила с момента написания F14, то есть цифры в `/stats` могли браться из
устаревшего замера.

Это ровно тот сценарий, который в проекте уже разбирали: F51 появилась
потому, что правила приёма скопировали в две ветки и копии разошлись.
Лечение то же — общая точка вместо копий.

ПОБОЧНАЯ ВЫГОДА. Три из четырёх мест ходили в базу в цикле по постам
(N+1 запросов). Здесь это один запрос на весь список.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tg_repost.db.models import PostStat


def latest_stats_for(session: Session, post_ids: list[int]) -> dict[int, PostStat]:
    """Последний снимок по каждому посту: `{post_id: PostStat}`.

    Посты без единого снимка в результат не попадают — вызывающий сам решает,
    считать их нулём или пропускать. Это разные ответы: для порога в F55 «нет
    метрик» означает «не знаем, выстрелил ли» и повторять не надо, а для
    средних в F53 такой пост просто не участвует в расчёте.

    Сортировка ПО ВОЗРАСТАНИЮ, победитель определяется тем, что затирает
    предыдущего в словаре. Тай-брейк по `id` обязателен — см. docstring модуля.
    """
    if not post_ids:
        return {}

    rows = (
        session.query(PostStat)
        .filter(PostStat.post_id.in_(post_ids))
        .order_by(PostStat.captured_at.asc(), PostStat.id.asc())
        .all()
    )
    return {row.post_id: row for row in rows}


def latest_stat(session: Session, post_id: int) -> PostStat | None:
    """Последний снимок одного поста. `None` — метрик ещё не снимали."""
    return latest_stats_for(session, [post_id]).get(post_id)


def latest_views_for(session: Session, post_ids: list[int]) -> dict[int, int]:
    """Просмотры по последнему снимку: `{post_id: views}`.

    Пост БЕЗ снимка или со снимком, где `view_count` пуст, получает 0 —
    здесь это осознанно, потому что все вызывающие ранжируют по просмотрам,
    а «неизвестно» в ранжировании ведёт себя как ноль.
    """
    return {
        post_id: (stat.view_count or 0)
        for post_id, stat in latest_stats_for(session, post_ids).items()
    }

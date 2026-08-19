"""Сколько запросов к базе стоит показать страницу (замер 2026-08-19).

ПОЧЕМУ ЭТО ВООБЩЕ ТЕСТ. N+1 не роняет ничего: страница отвечает 200 и на двух
запросах, и на ста пятидесяти. Обычный тест такого не видит по устройству —
он проверяет ответ, а не цену ответа. Поэтому цена закреплена здесь числом.

Замер до правок:

* `/settings` — 155 запросов, из них 154 одинаковых «есть ли оверлей у поля»,
  по одному на каждое из 154 полей;
* `/guardian/settings` — 41 обращение к таблице секретов, по одному на поле:
  значение каждого поля бралось через `get_guardian_settings()`, а тот каждый
  раз идёт в базу за оверлеем и расшифровкой токена;
* экспорт постов — запрос целей на КАЖДЫЙ пост, то есть цена росла ровно
  вместе с объёмом выгрузки.

Все три жили в одном цикле событий вместе с четырьмя ботами: сто пятьдесят
обращений к базе на показ страницы — это сто пятьдесят остановок этого цикла.

Пороги стоят с запасом и ловят не «стало на один больше», а возврат самой
ошибки — цикла вместо одной выборки.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import event

from tg_repost.db.session import engine


@contextlib.contextmanager
def counting_queries():
    """Считает SQL-запросы, выполненные внутри блока."""
    counter = {"n": 0, "statements": []}

    def _before(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1
        counter["statements"].append(" ".join(statement.split())[:90])

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _repeated(counter) -> tuple[str, int]:
    """Самый частый запрос и сколько раз он повторился — цикл виден именно
    так: один и тот же текст запроса десятки раз подряд."""
    from collections import Counter

    if not counter["statements"]:
        return "", 0
    return Counter(counter["statements"]).most_common(1)[0]


# --- страницы ---


def test_settings_page_does_not_query_per_field():
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)
    client.get("/settings")  # прогрев: первый заход компилирует шаблон

    with counting_queries() as counter:
        response = client.get("/settings")

    assert response.status_code == 200
    statement, times = _repeated(counter)
    assert counter["n"] <= 10, (
        f"страница настроек снова ходит в базу по кругу: {counter['n']} запросов, "
        f"чаще всего x{times}: {statement}"
    )


def test_guardian_settings_page_reads_settings_once():
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)
    client.get("/guardian/settings")

    with counting_queries() as counter:
        response = client.get("/guardian/settings")

    assert response.status_code == 200
    statement, times = _repeated(counter)
    assert counter["n"] <= 8, (
        f"настройки Guardian снова читаются на каждое поле: {counter['n']} запросов, "
        f"чаще всего x{times}: {statement}"
    )


# --- экспорт ---


@pytest.mark.parametrize("n_posts", [5, 40])
def test_export_cost_does_not_grow_with_post_count(n_posts):
    """ГЛАВНАЯ ПРОВЕРКА: цена выгрузки не должна зависеть от её объёма.

    Два размера подряд именно затем, чтобы поймать рост. Один размер сказал бы
    только «запросов немного», а вопрос в другом — становится ли их больше,
    когда постов больше.
    """
    from datetime import datetime, timedelta, timezone

    from tg_repost.db.models import Post, PostKind, PostStatus, PostTarget
    from tg_repost.db.session import session_scope
    from tg_repost.export import export_posts

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()
        for i in range(n_posts):
            post = Post(
                kind=PostKind.SOURCE, original_text=f"текст {i}",
                status=PostStatus.POSTED, created_at=now - timedelta(hours=i),
                posted_at=now - timedelta(hours=i),
            )
            session.add(post)
            session.flush()
            session.add(PostTarget(post_id=post.id, chat_id=-100 - i, ok=True))

    with counting_queries() as counter:
        rows = export_posts()

    assert len(rows) == n_posts
    statement, times = _repeated(counter)
    assert counter["n"] <= 6, (
        f"выгрузка {n_posts} постов стоит {counter['n']} запросов — цена снова "
        f"растёт вместе с объёмом; чаще всего x{times}: {statement}"
    )

    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()


def test_export_still_returns_targets_after_batching():
    """Обратная проверка: собрав цели одним запросом, их легко потерять или
    приписать не тому посту. Выгрузка без целей выглядит целой, а данные в
    ней неверные — и заметят это уже на стороне того, кому её отдали."""
    from datetime import datetime, timezone

    from tg_repost.db.models import Post, PostKind, PostStatus, PostTarget
    from tg_repost.db.session import session_scope
    from tg_repost.export import export_posts

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()
        first = Post(kind=PostKind.SOURCE, original_text="первый",
                     status=PostStatus.POSTED, created_at=now, posted_at=now)
        second = Post(kind=PostKind.SOURCE, original_text="второй",
                      status=PostStatus.POSTED, created_at=now, posted_at=now)
        session.add_all([first, second])
        session.flush()
        session.add_all([
            PostTarget(post_id=first.id, chat_id=-1001, ok=True),
            PostTarget(post_id=first.id, chat_id=-1002, ok=False),
            PostTarget(post_id=second.id, chat_id=-2001, ok=True),
        ])

    rows = {row["original_text"]: row for row in export_posts()}

    assert len(rows["первый"]["targets"]) == 2, "цели первого поста потерялись"
    assert len(rows["второй"]["targets"]) == 1, "чужие цели приписаны посту"

    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()

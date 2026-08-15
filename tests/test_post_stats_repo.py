"""Общая точка «последний снимок метрик поста» (`post_stats_repo`).

Модуль появился потому, что этот запрос был написан заново в четырёх местах
(F14, F20, F53, F55) и все четыре повторили одну ошибку — сортировку без
тай-брейка. Поэтому тесты здесь в первую очередь про детерминированность, а
не про арифметику.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import post_stats_repo
from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostStat).delete()
            session.query(Post).delete()

    _wipe()
    yield
    _wipe()


def _post() -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, original_text="т", status=PostStatus.POSTED)
        session.add(post)
        session.flush()
        return post.id


def _stat(post_id: int, views: int, *, at: datetime, reactions: int = 0, forwards: int = 0) -> None:
    with session_scope() as session:
        session.add(
            PostStat(
                post_id=post_id, view_count=views, reaction_count=reactions,
                forward_count=forwards, captured_at=at,
            )
        )


def test_empty_input_returns_empty():
    with session_scope() as session:
        assert post_stats_repo.latest_stats_for(session, []) == {}


def test_post_without_snapshots_is_absent_not_zero():
    """Отсутствие в словаре — это «метрик не снимали», и это не ноль.

    Разница принципиальна: для порога в F55 «не знаем, выстрелил ли» значит
    не повторять, а для средних в F53 такой пост просто не участвует.
    Схлопни это в ноль — и оба поведения станут неверными.
    """
    post_id = _post()
    with session_scope() as session:
        assert post_stats_repo.latest_stats_for(session, [post_id]) == {}
        assert post_stats_repo.latest_stat(session, post_id) is None


def test_latest_snapshot_wins():
    post_id = _post()
    _stat(post_id, 100, at=_utcnow() - timedelta(hours=3))
    _stat(post_id, 900, at=_utcnow() - timedelta(hours=1))

    with session_scope() as session:
        assert post_stats_repo.latest_stat(session, post_id).view_count == 900


def test_latest_wins_regardless_of_insertion_order():
    """Свежий снимок вставлен ПЕРВЫМ — порядок вставки не должен решать."""
    post_id = _post()
    _stat(post_id, 900, at=_utcnow() - timedelta(hours=1))
    _stat(post_id, 100, at=_utcnow() - timedelta(hours=3))

    with session_scope() as session:
        assert post_stats_repo.latest_stat(session, post_id).view_count == 900


def test_equal_timestamps_resolve_deterministically():
    """Совпадающие метки времени — выигрывает вставленный позже.

    Ровно тот случай, ради которого модуль и появился: часы на Windows
    тикают ~15 мс, и два замера подряд регулярно получают одну метку.
    """
    post_id = _post()
    moment = _utcnow() - timedelta(hours=1)
    for views in (111, 222, 333):
        _stat(post_id, views, at=moment)

    for _ in range(5):
        with session_scope() as session:
            assert post_stats_repo.latest_stat(session, post_id).view_count == 333


def test_each_post_resolved_independently():
    first = _post()
    second = _post()
    _stat(first, 10, at=_utcnow() - timedelta(hours=2))
    _stat(first, 20, at=_utcnow() - timedelta(hours=1))
    _stat(second, 500, at=_utcnow() - timedelta(hours=5))

    with session_scope() as session:
        latest = post_stats_repo.latest_stats_for(session, [first, second])

    assert latest[first].view_count == 20
    assert latest[second].view_count == 500


def test_unrequested_posts_are_not_returned():
    wanted = _post()
    other = _post()
    _stat(wanted, 10, at=_utcnow())
    _stat(other, 20, at=_utcnow())

    with session_scope() as session:
        latest = post_stats_repo.latest_stats_for(session, [wanted])

    assert set(latest) == {wanted}


def test_latest_views_treats_null_as_zero():
    post_id = _post()
    _stat(post_id, 0, at=_utcnow())
    with session_scope() as session:
        row = session.query(PostStat).filter(PostStat.post_id == post_id).one()
        row.view_count = None

    with session_scope() as session:
        assert post_stats_repo.latest_views_for(session, [post_id]) == {post_id: 0}


def test_latest_views_skips_posts_without_snapshots():
    measured = _post()
    unmeasured = _post()
    _stat(measured, 42, at=_utcnow())

    with session_scope() as session:
        views = post_stats_repo.latest_views_for(session, [measured, unmeasured])

    assert views == {measured: 42}


def test_single_query_for_many_posts():
    """Раньше три из четырёх мест ходили в базу в цикле (N+1).

    Считаем реально выполненные SELECT-ы по `post_stats`: их должно быть
    ровно один независимо от числа постов.
    """
    from sqlalchemy import event

    ids = [_post() for _ in range(5)]
    for i, post_id in enumerate(ids):
        _stat(post_id, (i + 1) * 10, at=_utcnow())

    seen: list[str] = []

    with session_scope() as session:
        def _capture(_conn, _cursor, statement, *_args):
            if "post_stats" in statement.lower() and statement.lstrip().upper().startswith("SELECT"):
                seen.append(statement)

        event.listen(session.get_bind(), "before_cursor_execute", _capture)
        try:
            latest = post_stats_repo.latest_stats_for(session, ids)
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", _capture)

    assert len(latest) == 5
    assert len(seen) == 1, f"ожидался один запрос, было {len(seen)}"

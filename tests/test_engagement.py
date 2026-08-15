"""Метрики вовлечённости канала: ERR и ER (F53).

Главное, что защищаем: снимки метрик не складываются. `post_stats` хранит
историю замеров, и наивная сумма превратила бы один пост с 900 просмотрами
в три поста с 1400 — то есть завысила бы охват, который потом покажут
рекламодателю.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import engagement_repo
from tg_repost.db.models import (
    ChannelGrowthSnapshot,
    Post,
    PostStat,
    PostStatus,
    TargetGroup,
)
from tg_repost.db.session import session_scope

CHAT = -100777


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostStat).delete()
            session.query(ChannelGrowthSnapshot).delete()
            session.query(Post).delete()
            # Цели чистим тоже: блок ERR в /stats перебирает активные каналы,
            # и цель, оставшаяся от соседнего теста, подмешала бы в сводку
            # чужие числа.
            session.query(TargetGroup).filter(TargetGroup.chat_id == CHAT).delete()

    _wipe()
    yield
    _wipe()


def _make_post(days_ago: int = 1, chat_id: int = CHAT) -> int:
    with session_scope() as session:
        post = Post(
            source_id=None,
            original_text="текст",
            status=PostStatus.POSTED,
            posted_chat_id=chat_id,
            posted_at=_utcnow() - timedelta(days=days_ago),
        )
        session.add(post)
        session.flush()
        return post.id


def _add_stat(post_id: int, views: int, reactions: int, forwards: int, minutes_ago: int) -> None:
    with session_scope() as session:
        session.add(
            PostStat(
                post_id=post_id,
                view_count=views,
                reaction_count=reactions,
                forward_count=forwards,
                captured_at=_utcnow() - timedelta(minutes=minutes_ago),
            )
        )


def _set_subscribers(count: int, chat_id: int = CHAT) -> None:
    with session_scope() as session:
        session.add(ChannelGrowthSnapshot(chat_id=chat_id, subscriber_count=count))


# --- чистые функции ---


def test_reach_rate_basic():
    assert engagement_repo.compute_reach_rate(views=300, subscribers=1000) == 30.0


def test_engagement_rate_basic():
    assert engagement_repo.compute_engagement_rate(reactions=20, forwards=10, views=300) == 10.0


def test_zero_subscribers_gives_none_not_zero():
    """«Не знаем» нельзя показывать как «0%» — это разные утверждения."""
    assert engagement_repo.compute_reach_rate(views=100, subscribers=0) is None


def test_zero_views_gives_none_not_zero():
    assert engagement_repo.compute_engagement_rate(reactions=0, forwards=0, views=0) is None


# --- главная ловушка: снимки не складываются ---


def test_only_latest_snapshot_counts():
    """Три замера одного поста — это один пост, а не три.

    Без этого сумма (100+400+900) завысила бы охват в полтора раза, и ERR
    ушёл бы к рекламодателю завышенным.

    СНИМКИ ВСТАВЛЕНЫ В ОБРАТНОМ ПОРЯДКЕ — сначала самый свежий. Так и должно
    быть: при вставке по возрастанию тест проходил даже со сломанным отбором,
    потому что словарь схлопывал дубли и «последняя физическая строка»
    случайно совпадала с верным ответом. Обратный порядок эту случайность
    убирает — теперь выигрывает только тот, кто действительно смотрит на
    `captured_at`.
    """
    post_id = _make_post()
    _add_stat(post_id, views=900, reactions=12, forwards=4, minutes_ago=60)
    _add_stat(post_id, views=400, reactions=5, forwards=2, minutes_ago=120)
    _add_stat(post_id, views=100, reactions=1, forwards=0, minutes_ago=180)
    _set_subscribers(3000)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.posts_with_stats == 1
    assert report.avg_views == 900          # последний снимок, не 1400 и не 466
    assert report.avg_reactions == 12
    assert report.reach_rate == 30.0        # 900 / 3000


def test_equal_timestamps_resolve_deterministically():
    """Снимки с ОДИНАКОВОЙ меткой времени — выигрывает вставленный позже.

    Не теоретический случай: гранулярность системных часов на Windows ~15 мс,
    и два замера подряд регулярно получают идентичный `captured_at`. Пока
    тай-брейка по `id` не было, выбор был случайным — один и тот же тест
    давал 4 прохода и 6 падений на десяти запусках, а в проде это означало
    бы устаревшее число подписчиков в ERR.
    """
    post_id = _make_post()
    same_moment = _utcnow() - timedelta(minutes=30)
    with session_scope() as session:
        for views in (111, 222, 333):
            session.add(
                PostStat(
                    post_id=post_id, view_count=views, reaction_count=0,
                    forward_count=0, captured_at=same_moment,
                )
            )
    _set_subscribers(1000)

    for _ in range(5):
        report = engagement_repo.build_engagement_report(CHAT)
        assert report.avg_views == 333


def test_equal_subscriber_timestamps_resolve_deterministically():
    post_id = _make_post()
    _add_stat(post_id, views=200, reactions=0, forwards=0, minutes_ago=10)
    same_moment = _utcnow()
    with session_scope() as session:
        for count in (500, 1500):
            session.add(
                ChannelGrowthSnapshot(
                    chat_id=CHAT, subscriber_count=count, captured_at=same_moment,
                )
            )

    for _ in range(5):
        assert engagement_repo.build_engagement_report(CHAT).subscribers == 1500


def test_latest_snapshot_picked_per_post_independently():
    """У каждого поста свой последний замер, а не общий по каналу."""
    old_post = _make_post(days_ago=5)
    new_post = _make_post(days_ago=1)
    _add_stat(old_post, views=1000, reactions=10, forwards=0, minutes_ago=500)
    _add_stat(old_post, views=2000, reactions=20, forwards=0, minutes_ago=400)
    _add_stat(new_post, views=100, reactions=1, forwards=0, minutes_ago=10)
    _set_subscribers(4000)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.posts_with_stats == 2
    assert report.avg_views == (2000 + 100) // 2


# --- окно, каналы, покрытие данными ---


def test_posts_outside_window_ignored():
    old = _make_post(days_ago=90)
    _add_stat(old, views=5000, reactions=100, forwards=50, minutes_ago=10)
    _set_subscribers(1000)

    report = engagement_repo.build_engagement_report(CHAT, window_days=30)

    assert report.enough_data is False
    assert report.posts_total == 0


def test_other_channel_posts_ignored():
    mine = _make_post()
    other = _make_post(chat_id=-100888)
    _add_stat(mine, views=200, reactions=2, forwards=0, minutes_ago=10)
    _add_stat(other, views=9999, reactions=999, forwards=999, minutes_ago=10)
    _set_subscribers(1000)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.posts_with_stats == 1
    assert report.avg_views == 200


def test_reports_partial_coverage():
    """Метрики есть не у всех постов — это должно быть видно в отчёте.

    Средние считаются по измеренной части, и знать об этом нужно ДО того,
    как цифру покажут рекламодателю.
    """
    measured = _make_post()
    _make_post()  # без единого снимка
    _add_stat(measured, views=500, reactions=5, forwards=1, minutes_ago=10)
    _set_subscribers(2500)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.posts_total == 2
    assert report.posts_with_stats == 1
    assert report.reach_rate == 20.0


def test_no_stats_at_all_is_not_enough_data():
    _make_post()
    _set_subscribers(1000)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.enough_data is False
    assert report.reach_rate is None


def test_missing_subscribers_still_gives_engagement_rate():
    """Без снимка подписчиков ERR посчитать нельзя, а ER — можно.

    Одна недостающая величина не должна обнулять весь отчёт.
    """
    post_id = _make_post()
    _add_stat(post_id, views=400, reactions=30, forwards=10, minutes_ago=10)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.reach_rate is None
    assert report.engagement_rate == 10.0  # (30 + 10) / 400


def test_latest_subscriber_snapshot_wins():
    post_id = _make_post()
    _add_stat(post_id, views=300, reactions=0, forwards=0, minutes_ago=10)
    _set_subscribers(500)
    _set_subscribers(1500)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.subscribers == 1500
    assert report.reach_rate == 20.0


# --- вывод в /stats ---


def test_stats_block_shows_err_for_active_target():
    from tg_repost import targets_repo
    from tg_repost.scheduler.stats import engagement_lines

    targets_repo.add_target(CHAT, title="Мой канал")
    post_id = _make_post()
    _add_stat(post_id, views=250, reactions=20, forwards=5, minutes_ago=10)
    _set_subscribers(1000)

    text = "\n".join(engagement_lines(window_days=30))

    assert "Мой канал" in text
    assert "25.0%" in text   # ERR: 250 / 1000
    assert "10.0%" in text   # ER: (20 + 5) / 250


def test_stats_block_warns_about_partial_coverage():
    """Предупреждение о неполном покрытии обязано быть видно в сводке.

    Иначе владелец назовёт рекламодателю средние по одному посту из десяти,
    не зная об этом.
    """
    from tg_repost import targets_repo
    from tg_repost.scheduler.stats import engagement_lines

    targets_repo.add_target(CHAT, title="Мой канал")
    measured = _make_post()
    _make_post()
    _add_stat(measured, views=100, reactions=0, forwards=0, minutes_ago=10)
    _set_subscribers(1000)

    text = "\n".join(engagement_lines(window_days=30))

    assert "1 из 2" in text


def test_stats_block_empty_when_no_data():
    from tg_repost import targets_repo
    from tg_repost.scheduler.stats import engagement_lines

    targets_repo.add_target(CHAT, title="Мой канал")
    _make_post()  # без метрик

    assert engagement_lines(window_days=30) == []


def test_null_metric_columns_treated_as_zero():
    """`view_count` и прочие nullable — старые строки могут быть пустыми."""
    post_id = _make_post()
    _add_stat(post_id, views=0, reactions=0, forwards=0, minutes_ago=10)
    with session_scope() as session:
        row = session.query(PostStat).filter(PostStat.post_id == post_id).one()
        row.view_count = None
        row.reaction_count = None
        row.forward_count = None
    _set_subscribers(1000)

    report = engagement_repo.build_engagement_report(CHAT)

    assert report.avg_views == 0
    assert report.engagement_rate is None  # делить на ноль просмотров нельзя

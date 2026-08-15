"""Медиакит для рекламодателя (F65).

Медиакит — документ для переговоров, в котором заинтересованная сторона мы.
Поэтому тесты в основном про ЧЕСТНОСТЬ цифр, а не про их наличие:

* средний охват по одному замеренному посту из сорока — это не средний
  охват, и оговорка про покрытие обязана быть;
* отсутствующие данные показываются как отсутствующие, а не как ноль;
* пост без замеров не может попасть в «лучшие» — мы про него просто ничего
  не знаем.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import mediakit_repo
from tg_repost.db.models import (
    ChannelGrowthSnapshot,
    ChannelStatsSnapshot,
    Post,
    PostKind,
    PostStat,
    PostStatus,
    TargetGroup,
)
from tg_repost.db.session import session_scope

CHAT = -100321321


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostStat).delete()
            session.query(Post).delete()
            session.query(ChannelGrowthSnapshot).delete()
            session.query(ChannelStatsSnapshot).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _channel(title: str = "Мой канал") -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT, title=title, is_active=True))


def _post(views: int | None, *, days_ago: int = 1, text: str = "текст поста") -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE,
            original_text=text,
            rewritten_text=text,
            status=PostStatus.POSTED,
            posted_chat_id=CHAT,
            posted_at=_utcnow() - timedelta(days=days_ago),
        )
        session.add(post)
        session.flush()
        post_id = post.id
        if views is not None:
            session.add(
                PostStat(
                    post_id=post_id, view_count=views, reaction_count=1,
                    forward_count=0, captured_at=_utcnow() - timedelta(days=days_ago),
                )
            )
        return post_id


def _subscribers(*counts: int) -> None:
    with session_scope() as session:
        for i, count in enumerate(counts):
            session.add(
                ChannelGrowthSnapshot(
                    chat_id=CHAT, subscriber_count=count,
                    captured_at=_utcnow() - timedelta(days=len(counts) - i),
                )
            )


# --- базовое ---


def test_missing_channel_returns_none():
    assert mediakit_repo.build(CHAT) is None


def test_channel_without_data_is_marked_not_enough():
    """Медиакит без охватов — лист бумаги с названием канала.

    Честнее сказать «данных мало», чем отдать пустоту и получить вопрос,
    на который нечего ответить.
    """
    _channel()

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.has_enough_data is False


def test_collects_numbers_from_existing_sources():
    _channel()
    _post(300)
    _subscribers(1000, 1200)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.has_enough_data is True
    assert kit.subscribers == 1200
    assert kit.subscribers_delta == 200
    assert kit.avg_views == 300
    assert kit.reach_rate == 25.0  # 300 / 1200


# --- честность цифр ---


def test_coverage_note_when_metrics_are_partial():
    """Средние по одному посту из трёх — это оговорка, а не тонкость."""
    _channel()
    _post(500)
    _post(None)
    _post(None)
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.posts_published == 3
    assert kit.posts_with_metrics == 1
    assert kit.coverage_note_needed is True


def test_no_coverage_note_when_everything_measured():
    _channel()
    _post(100)
    _post(200)
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.coverage_note_needed is False


def test_single_snapshot_gives_no_growth_number():
    """Разница значения с самим собой — это не «нулевой рост», а «не знаем».

    Показать «+0» рекламодателю значило бы соврать: канал мог расти, просто
    мы замерили один раз.
    """
    _channel()
    _post(100)
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.subscribers == 1000
    assert kit.subscribers_delta is None


def test_missing_subscribers_do_not_become_zero():
    _channel()
    _post(100)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.subscribers is None
    assert kit.reach_rate is None  # без подписчиков ERR не посчитать


def test_unmeasured_post_never_enters_top():
    """Пост без замеров не может быть «лучшим» — мы про него ничего не знаем."""
    _channel()
    _post(50, text="слабый но замеренный")
    _post(None, text="незамеренный")
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert [p.snippet for p in kit.top_posts] == ["слабый но замеренный"]


# --- топ постов ---


def test_top_posts_sorted_by_views_and_limited():
    _channel()
    for views in (10, 900, 500, 300, 700):
        _post(views, text=f"пост {views}")
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert [p.views for p in kit.top_posts] == [900, 700, 500]
    assert len(kit.top_posts) == mediakit_repo.TOP_POSTS


def test_snippet_is_trimmed():
    _channel()
    _post(100, text="а" * 500)
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert len(kit.top_posts[0].snippet) <= 160


def test_posts_outside_window_are_ignored():
    _channel()
    _post(900, days_ago=200, text="старый")
    _post(100, days_ago=1, text="свежий")
    _subscribers(1000)

    kit = mediakit_repo.build(CHAT, window_days=30)

    assert kit is not None
    assert [p.snippet for p in kit.top_posts] == ["свежий"]


def test_notifications_share_is_picked_up_when_collected():
    _channel()
    _post(100)
    _subscribers(1000)
    with session_scope() as session:
        session.add(
            ChannelStatsSnapshot(
                chat_id=CHAT, notifications_enabled_pct=64.5, captured_at=_utcnow(),
            )
        )

    kit = mediakit_repo.build(CHAT)

    assert kit is not None
    assert kit.notifications_enabled_pct == 64.5


# --- страница ---


def test_page_opens_and_shows_numbers():
    client = _client()
    _bootstrap(client)
    _channel()
    _post(300)
    _subscribers(1000, 1200)

    response = client.get(f"/mediakit?chat_id={CHAT}&days=30")

    assert response.status_code == 200
    assert "Мой канал" in response.text
    assert "1200" in response.text


def test_page_warns_when_data_is_thin():
    client = _client()
    _bootstrap(client)
    _channel()

    response = client.get(f"/mediakit?chat_id={CHAT}")

    assert "Данных пока мало" in response.text


def test_page_has_no_public_route():
    """Публичной ссылки нет намеренно: она изменила бы модель угроз.

    В `webui/auth.py` записано, что CSRF-токенов нет, потому что сторонних
    origin не бывает. Один публичный маршрут ломает эту предпосылку.
    """
    client = _client()

    assert client.get("/mediakit", follow_redirects=False).status_code in (302, 303, 307)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    _channel()
    _post(300)
    _post(None)
    _subscribers(1000, 1200)

    client.get(f"/lang/{lang}?next=/mediakit", follow_redirects=False)
    response = client.get(f"/mediakit?chat_id={CHAT}")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)

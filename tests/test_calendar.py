"""Контент-календарь и согласование (F72).

Два главных свойства:

1. **Календарь не врёт о будущем.** Посты без даты не раскладываются по
   дням: система их так не публикует, и нарисованное расписание, которое
   она не исполняет, хуже отсутствия расписания.
2. **Ограничения реально работают.** Дата «не раньше» и ожидание владельца
   должны останавливать ПУБЛИКАТОР, а не только показываться в интерфейсе.
   Поле, которое никто не проверяет, — это обещание, а не ограничение.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from tg_repost import ad_requests_repo, calendar_repo
from tg_repost.db.models import AdBrief, AdRequest, Post, PostKind, PostStatus
from tg_repost.db.session import session_scope

CHAT = -100515151


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _utcnow().date()


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Post).delete()
            session.query(AdRequest).delete()
            session.query(AdBrief).delete()

    _wipe()
    yield
    _wipe()


def _post(
    *,
    status: PostStatus = PostStatus.APPROVED,
    scheduled_for: date | None = None,
    posted_days_ago: int | None = None,
    needs_owner: bool = False,
    text: str = "текст поста",
) -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE,
            original_text=text,
            rewritten_text=text,
            status=status,
            scheduled_for=scheduled_for,
            needs_owner_approval=needs_owner,
        )
        if posted_days_ago is not None:
            post.posted_at = _utcnow() - timedelta(days=posted_days_ago)
            post.posted_chat_id = CHAT
        session.add(post)
        session.flush()
        return post.id


# --- честность горизонта ---


def test_undated_posts_are_counted_not_spread_over_days():
    """ГЛАВНОЕ СВОЙСТВО.

    Система публикует их «когда дойдёт очередь». Разложить их по дням
    значило бы показать расписание, которого система не исполняет.
    """
    for _ in range(3):
        _post(scheduled_for=None)

    view = calendar_repo.build(CHAT)

    assert view.undated_queue == 3
    assert all(not day.posts for day in view.days)


def test_scheduled_post_appears_on_its_day():
    day = _today() + timedelta(days=5)
    _post(scheduled_for=day, text="анонс")

    view = calendar_repo.build(CHAT)

    cell = next(d for d in view.days if d.day == day)
    assert [p.snippet for p in cell.posts] == ["анонс"]


def test_published_posts_appear_as_facts():
    _post(status=PostStatus.POSTED, posted_days_ago=2, text="вышло позавчера")

    view = calendar_repo.build(CHAT)

    cell = next(d for d in view.days if d.day == _today() - timedelta(days=2))
    assert cell.posts[0].is_published is True
    assert cell.is_past is True


def test_posts_outside_horizon_are_not_shown():
    _post(scheduled_for=_today() + timedelta(days=365))
    _post(status=PostStatus.POSTED, posted_days_ago=90)

    view = calendar_repo.build(CHAT)

    assert all(not day.posts for day in view.days)


def test_today_is_marked():
    view = calendar_repo.build(CHAT)

    today_cells = [d for d in view.days if d.is_today]
    assert len(today_cells) == 1
    assert today_cells[0].day == _today()


def test_ads_share_the_same_grid():
    """Владелец планирует ОДНУ ленту, а не две.

    Разнеси рекламу и посты — и рекламный пост встанет в день, где уже
    стоит анонс, потому что при планировании его не было видно.
    """
    day = _today() + timedelta(days=3)
    request_id = ad_requests_repo.create(
        chat_id=CHAT, advertiser="@shop", brief_text="бриф", slot_date=day,
    )
    ad_requests_repo.accept(request_id)
    _post(scheduled_for=day, text="свой пост")

    view = calendar_repo.build(CHAT)

    cell = next(d for d in view.days if d.day == day)
    assert cell.ad_advertiser == "@shop"
    assert cell.posts  # и свой пост виден рядом — конфликт заметен сразу


# --- публикатор уважает ограничения ---


async def test_publisher_skips_future_dated_post(monkeypatch):
    """Поле, которое никто не проверяет, — обещание, а не ограничение.

    Без этой проверки анонс вышел бы до события, ради которого написан.
    """
    from tg_repost.scheduler import posting

    _post(scheduled_for=_today() + timedelta(days=3))
    published: list[int] = []

    async def _fake_publish(_bot, post_id):
        published.append(post_id)

    monkeypatch.setattr(posting, "publish_post", _fake_publish)

    class _App:
        bot = object()

    await posting.publish_slot(_App())

    assert published == []


async def test_publisher_takes_post_whose_day_has_come(monkeypatch):
    from tg_repost.scheduler import posting

    post_id = _post(scheduled_for=_today())
    published: list[int] = []

    async def _fake_publish(_bot, pid):
        published.append(pid)

    monkeypatch.setattr(posting, "publish_post", _fake_publish)

    class _App:
        bot = object()

    await posting.publish_slot(_App())

    assert published == [post_id]


async def test_publisher_takes_undated_post_as_before(monkeypatch):
    """NULL сохраняет прежнее поведение — обновление ничего не ломает."""
    from tg_repost.scheduler import posting

    post_id = _post(scheduled_for=None)
    published: list[int] = []

    async def _fake_publish(_bot, pid):
        published.append(pid)

    monkeypatch.setattr(posting, "publish_post", _fake_publish)

    class _App:
        bot = object()

    await posting.publish_slot(_App())

    assert published == [post_id]


async def test_publisher_skips_post_awaiting_owner(monkeypatch):
    from tg_repost.scheduler import posting

    _post(needs_owner=True)
    published: list[int] = []

    async def _fake_publish(_bot, pid):
        published.append(pid)

    monkeypatch.setattr(posting, "publish_post", _fake_publish)

    class _App:
        bot = object()

    await posting.publish_slot(_App())

    assert published == []


# --- согласование ---


def test_owner_approval_not_required_by_default(monkeypatch):
    """Навязывать согласование там, где владелец один, — церемония."""
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "require_owner_approval", False, raising=False)
    post_id = _post()

    calendar_repo.mark_approved(post_id, by_username="editor1", by_role="editor")

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.approved_by == "editor1"
        assert post.needs_owner_approval is False


def test_editor_approval_waits_for_owner_when_enabled(monkeypatch):
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "require_owner_approval", True, raising=False)
    post_id = _post()

    calendar_repo.mark_approved(post_id, by_username="editor1", by_role="editor")

    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is True


def test_owner_approval_never_waits_for_itself(monkeypatch):
    """Владелец не должен подтверждать сам себя — это тупик."""
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "require_owner_approval", True, raising=False)
    post_id = _post()

    calendar_repo.mark_approved(post_id, by_username="owner", by_role="owner")

    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False


def test_owner_can_release_the_post():
    post_id = _post(needs_owner=True)

    assert calendar_repo.approve_by_owner(post_id) is True
    assert calendar_repo.approve_by_owner(post_id) is False  # уже снято

    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False


def test_awaiting_count_and_list():
    _post(needs_owner=True, text="ждёт")
    _post(needs_owner=False)

    view = calendar_repo.build(CHAT)

    assert view.awaiting_owner == 1
    assert [p.snippet for p in calendar_repo.posts_awaiting_owner()] == ["ждёт"]


# --- перенос даты ---


def test_schedule_and_unschedule():
    post_id = _post(scheduled_for=None)
    day = _today() + timedelta(days=4)

    assert calendar_repo.schedule_post(post_id, day) is True
    assert calendar_repo.schedule_post(post_id, None) is True

    with session_scope() as session:
        assert session.get(Post, post_id).scheduled_for is None


def test_published_post_cannot_be_rescheduled():
    """Опубликованное уже вышло — двигать в календаре нечего.

    Молча делать вид, что получилось, значило бы показать владельцу дату,
    которая ни на что не влияет.
    """
    post_id = _post(status=PostStatus.POSTED, posted_days_ago=1)

    assert calendar_repo.schedule_post(post_id, _today()) is False


def test_rejected_post_cannot_be_rescheduled():
    post_id = _post(status=PostStatus.REJECTED)

    assert calendar_repo.schedule_post(post_id, _today()) is False

"""Тесты общей бизнес-логики модерации (F07, Фаза 5.3) — переиспользуется и
Telegram-ботом, и веб-админкой."""

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import (
    AppSetting,
    InvalidStatusTransition,
    Post,
    PostKind,
    PostStatus,
    TargetGroup,
)
from tg_repost.db.session import session_scope
from tg_repost.moderation import approve_post, edit_post_text, get_post, list_pending_posts, reject_post
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _isolated_state():
    """Изоляция: общий sqlite-engine-синглтон на весь pytest-процесс."""
    with session_scope() as session:
        session.query(Post).delete()
        session.query(TargetGroup).delete()
        session.query(AppSetting).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(AppSetting).delete()
    invalidate_settings_cache()


def _make_post(status: PostStatus = PostStatus.REWRITTEN, text: str = "original") -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=status, original_text=text, rewritten_text=text)
        session.add(post)
        session.flush()
        return post.id


def test_list_pending_posts_includes_rewritten_and_pending_approval():
    _make_post(PostStatus.REWRITTEN)
    _make_post(PostStatus.PENDING_APPROVAL)
    _make_post(PostStatus.POSTED)

    pending = list_pending_posts()
    assert len(pending) == 2
    assert {p.status for p in pending} == {PostStatus.REWRITTEN, PostStatus.PENDING_APPROVAL}


def test_get_post_returns_none_for_missing():
    assert get_post(999999) is None


def test_get_post_returns_existing():
    post_id = _make_post()
    post = get_post(post_id)
    assert post is not None
    assert post.id == post_id


def test_reject_post_sets_status_and_reason():
    post_id = _make_post(PostStatus.PENDING_APPROVAL)
    assert reject_post(post_id, reason="не подходит") is True
    post = get_post(post_id)
    assert post.status == PostStatus.REJECTED
    assert post.status_reason == "не подходит"


def test_reject_post_invalid_transition_raises():
    """Регрессия: веб-очередь модерации (`/moderation`) показывает посты со
    статусом REWRITTEN наравне с PENDING_APPROVAL (см. list_pending_posts),
    но статус-машина запрещает REWRITTEN -> REJECTED напрямую. Раньше это
    приводило к необработанному InvalidStatusTransition (500) на роуте
    POST /moderation/{id}/reject — теперь роут ловит исключение явно."""
    post_id = _make_post(PostStatus.REWRITTEN)
    with pytest.raises(InvalidStatusTransition):
        reject_post(post_id)


def test_reject_post_missing_returns_false():
    assert reject_post(999999) is False


def test_edit_post_text_updates_rewritten_text():
    post_id = _make_post(text="old text")
    assert edit_post_text(post_id, "new text") is True
    assert get_post(post_id).rewritten_text == "new text"


def test_edit_post_text_missing_returns_false():
    assert edit_post_text(999999, "x") is False


async def test_approve_post_missing_returns_message():
    outcome = await approve_post(bot=None, post_id=999999)
    assert outcome == "пост не найден"


async def test_approve_post_invalid_transition_raises():
    post_id = _make_post(PostStatus.REJECTED)  # терминальный статус — нет перехода в approved
    with pytest.raises(InvalidStatusTransition):
        await approve_post(bot=None, post_id=post_id)


async def test_approve_post_immediate_publish_fails_without_targets():
    """Без активных целевых групп publish_post помечает пост failed, не
    обращаясь к Bot API — поэтому здесь безопасно передать bot=None."""
    assert get_settings().scheduled_posting_enabled is False
    post_id = _make_post(PostStatus.REWRITTEN)

    outcome = await approve_post(bot=None, post_id=post_id)

    assert outcome == "failed"
    assert get_post(post_id).status == PostStatus.FAILED


async def test_approve_post_queues_when_scheduled_posting_enabled():
    settings_store.save_setting("scheduled_posting_enabled", True, "bool")
    settings_store.save_setting("posting_slots", ["10:00", "18:00"], "csv_list")
    invalidate_settings_cache()
    post_id = _make_post(PostStatus.REWRITTEN)

    outcome = await approve_post(bot=None, post_id=post_id)

    assert "в очереди публикации" in outcome
    assert "10:00" in outcome
    assert get_post(post_id).status == PostStatus.APPROVED

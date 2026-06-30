"""Тесты статус-машины постов (F05)."""

import pytest

from tg_repost.db.models import (
    InvalidStatusTransition,
    Post,
    PostStatus,
)


def _make_post(status: PostStatus) -> Post:
    return Post(
        source_id=1,
        source_message_id=1,
        original_text="x",
        content_hash="h",
        status=status,
    )


def test_valid_happy_path():
    post = _make_post(PostStatus.NEW)
    post.set_status(PostStatus.REWRITING)
    post.set_status(PostStatus.REWRITTEN)
    post.set_status(PostStatus.PENDING_APPROVAL)
    post.set_status(PostStatus.APPROVED)
    post.set_status(PostStatus.POSTED)
    assert post.status is PostStatus.POSTED


def test_new_can_be_filtered_out():
    post = _make_post(PostStatus.NEW)
    post.set_status(PostStatus.FILTERED_OUT, reason="стоп-слово")
    assert post.status is PostStatus.FILTERED_OUT
    assert post.status_reason == "стоп-слово"


def test_new_can_be_duplicate():
    post = _make_post(PostStatus.NEW)
    post.set_status(PostStatus.DUPLICATE)
    assert post.status is PostStatus.DUPLICATE


def test_reject_from_pending():
    post = _make_post(PostStatus.PENDING_APPROVAL)
    post.set_status(PostStatus.REJECTED)
    assert post.status is PostStatus.REJECTED


def test_invalid_transition_raises():
    post = _make_post(PostStatus.NEW)
    with pytest.raises(InvalidStatusTransition):
        post.set_status(PostStatus.POSTED)


def test_terminal_status_cannot_transition():
    post = _make_post(PostStatus.POSTED)
    with pytest.raises(InvalidStatusTransition):
        post.set_status(PostStatus.APPROVED)


def test_same_status_is_noop():
    post = _make_post(PostStatus.NEW)
    post.set_status(PostStatus.NEW)
    assert post.status is PostStatus.NEW


def test_failed_can_retry():
    post = _make_post(PostStatus.FAILED)
    post.set_status(PostStatus.REWRITING)
    assert post.status is PostStatus.REWRITING


def test_rewritten_can_skip_pending_approval_for_auto_post():
    # Используется _auto_publish_rewritten (AUTO_POST_ENABLED=true) — без
    # ручной модерации REWRITTEN сразу становится APPROVED.
    post = _make_post(PostStatus.REWRITTEN)
    post.set_status(PostStatus.APPROVED)
    assert post.status is PostStatus.APPROVED


def test_rewritten_cannot_go_directly_to_rejected():
    post = _make_post(PostStatus.REWRITTEN)
    with pytest.raises(InvalidStatusTransition):
        post.set_status(PostStatus.REJECTED)


def test_terminal_flag():
    assert PostStatus.POSTED.is_terminal
    assert PostStatus.REJECTED.is_terminal
    assert not PostStatus.NEW.is_terminal
    assert not PostStatus.REWRITING.is_terminal

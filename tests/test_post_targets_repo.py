"""Тесты `post_targets_repo.py` (F29) — CRUD результатов публикации по цели."""

from tg_repost import post_targets_repo
from tg_repost.db.models import Post, PostKind, PostStatus, PostTarget
from tg_repost.db.session import session_scope


def _clean() -> None:
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()


def _make_post() -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, original_text="x")
        session.add(post)
        session.flush()
        return post.id


def test_record_targets_writes_success_and_failure_rows():
    _clean()
    post_id = _make_post()
    post_targets_repo.record_targets(
        post_id, [(-100111, 42, None), (-100222, None, "TimedOut")]
    )
    rows = {r.chat_id: r for r in post_targets_repo.list_targets_for_post(post_id)}
    assert rows[-100111].ok is True
    assert rows[-100111].message_id == 42
    assert rows[-100222].ok is False
    assert rows[-100222].error == "TimedOut"
    _clean()


def test_list_targets_for_post_ordered_and_scoped():
    _clean()
    post_id = _make_post()
    other_post_id = _make_post()
    post_targets_repo.record_targets(post_id, [(-100111, 1, None), (-100222, 2, None)])
    post_targets_repo.record_targets(other_post_id, [(-100333, 3, None)])
    rows = post_targets_repo.list_targets_for_post(post_id)
    assert [r.chat_id for r in rows] == [-100111, -100222]
    _clean()


def test_get_target_returns_none_for_missing():
    assert post_targets_repo.get_target(999999) is None


def test_set_message_id_updates_existing():
    _clean()
    post_id = _make_post()
    post_targets_repo.record_targets(post_id, [(-100111, 42, None)])
    target_id = post_targets_repo.list_targets_for_post(post_id)[0].id
    assert post_targets_repo.set_message_id(target_id, None) is True
    assert post_targets_repo.get_target(target_id).message_id is None
    _clean()


def test_set_message_id_missing_returns_false():
    assert post_targets_repo.set_message_id(999999, None) is False


def test_set_pinned_updates_existing():
    _clean()
    post_id = _make_post()
    post_targets_repo.record_targets(post_id, [(-100111, 42, None)])
    target_id = post_targets_repo.list_targets_for_post(post_id)[0].id
    assert post_targets_repo.set_pinned(target_id, True) is True
    assert post_targets_repo.get_target(target_id).pinned is True
    _clean()


def test_set_pinned_missing_returns_false():
    assert post_targets_repo.set_pinned(999999, True) is False

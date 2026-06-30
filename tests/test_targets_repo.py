"""Тесты CRUD-логики целевых групп (F08, F12, Фаза 5.3)."""

from tg_repost import targets_repo
from tg_repost.db.models import TargetGroup
from tg_repost.db.session import session_scope


def _clear_targets() -> None:
    with session_scope() as session:
        session.query(TargetGroup).delete()


def test_add_target_creates_new():
    _clear_targets()
    target, created = targets_repo.add_target(-100111, "My Channel")
    assert created is True
    assert target.chat_id == -100111
    assert target.title == "My Channel"
    assert target.is_active is True


def test_add_target_reactivates_existing_and_updates_title():
    _clear_targets()
    target, _ = targets_repo.add_target(-100222, "Old Title")
    targets_repo.toggle_target(target.id)  # деактивировать

    again, created = targets_repo.add_target(-100222, "New Title")
    assert created is False
    assert again.id == target.id
    assert again.is_active is True
    assert again.title == "New Title"


def test_list_targets_ordered_by_id():
    _clear_targets()
    targets_repo.add_target(-100333)
    targets_repo.add_target(-100444)
    targets = targets_repo.list_targets()
    assert [t.chat_id for t in targets] == [-100333, -100444]


def test_get_target_returns_none_for_missing():
    _clear_targets()
    assert targets_repo.get_target(999999) is None


def test_toggle_target_flips_state():
    _clear_targets()
    target, _ = targets_repo.add_target(-100555)
    assert targets_repo.toggle_target(target.id) is False
    assert targets_repo.toggle_target(target.id) is True


def test_toggle_target_missing_returns_none():
    _clear_targets()
    assert targets_repo.toggle_target(999999) is None

"""Тесты `guardian/handlers/chat_member.py` (F28.10) — обнаружение, реально
ли Guardian может модерировать чат, и синхронизация в БД tg_repost."""

from types import SimpleNamespace

from guardian.handlers.chat_member import _can_moderate, on_my_chat_member
from tg_repost import targets_repo
from tg_repost.db.models import TargetGroup
from tg_repost.db.session import session_scope


def _clear_targets() -> None:
    with session_scope() as session:
        session.query(TargetGroup).delete()


def _member(status: str, can_restrict_members: bool | None = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, can_restrict_members=can_restrict_members)


def _event(chat_id: int, member: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), new_chat_member=member)


# --- _can_moderate ---


def test_can_moderate_true_for_creator():
    assert _can_moderate(_member("creator")) is True


def test_can_moderate_true_for_admin_with_restrict_right():
    assert _can_moderate(_member("administrator", can_restrict_members=True)) is True


def test_can_moderate_false_for_admin_without_restrict_right():
    """Частый реальный случай: владелец сделал бота админом, но снял
    конкретно право "ограничивать участников" — Guardian бесполезен без
    него (не может мутить/банить), хоть формально и "администратор"."""
    assert _can_moderate(_member("administrator", can_restrict_members=False)) is False


def test_can_moderate_false_for_plain_member():
    assert _can_moderate(_member("member")) is False


def test_can_moderate_false_for_left():
    assert _can_moderate(_member("left")) is False


def test_can_moderate_false_for_kicked():
    assert _can_moderate(_member("kicked")) is False


# --- on_my_chat_member ---


async def test_on_my_chat_member_syncs_true_when_promoted_with_rights():
    _clear_targets()
    targets_repo.add_target(-100111, "Test Group")
    event = _event(-100111, _member("administrator", can_restrict_members=True))
    await on_my_chat_member(event)
    with session_scope() as session:
        target = session.query(TargetGroup).filter(TargetGroup.chat_id == -100111).one()
        assert target.guardian_can_moderate is True


async def test_on_my_chat_member_syncs_false_when_admin_missing_restrict_right():
    _clear_targets()
    targets_repo.add_target(-100111, "Test Group")
    event = _event(-100111, _member("administrator", can_restrict_members=False))
    await on_my_chat_member(event)
    with session_scope() as session:
        target = session.query(TargetGroup).filter(TargetGroup.chat_id == -100111).one()
        assert target.guardian_can_moderate is False


async def test_on_my_chat_member_syncs_false_when_kicked():
    _clear_targets()
    target, _ = targets_repo.add_target(-100111, "Test Group")
    targets_repo.sync_guardian_can_moderate(-100111, True)
    event = _event(-100111, _member("kicked"))
    await on_my_chat_member(event)
    with session_scope() as session:
        updated = session.query(TargetGroup).filter(TargetGroup.chat_id == -100111).one()
        assert updated.guardian_can_moderate is False


async def test_on_my_chat_member_noop_when_chat_not_a_target():
    _clear_targets()
    event = _event(-100999, _member("administrator", can_restrict_members=True))
    await on_my_chat_member(event)  # не должно упасть — просто нечего обновлять
    with session_scope() as session:
        assert session.query(TargetGroup).count() == 0

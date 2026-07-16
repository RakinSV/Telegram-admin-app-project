"""Тесты авто-обнаружения чатов для целевых групп (F08-доп.): CRUD-логика
`discovered_chats_repo.py` и хендлер `my_chat_member` в `moderation_bot.py`."""

from types import SimpleNamespace

from tg_repost import discovered_chats_repo, targets_repo
from tg_repost.db.models import DiscoveredChat, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.telegram.moderation_bot import _discovered_can_post, _on_my_chat_member


def _clear() -> None:
    with session_scope() as session:
        session.query(DiscoveredChat).delete()
        session.query(TargetGroup).delete()


def _membership(
    chat_id: int, chat_type: str, title: str | None, status: str,
    can_post_messages: bool | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type, title=title),
        new_chat_member=SimpleNamespace(status=status, can_post_messages=can_post_messages),
    )


def _update(membership: SimpleNamespace | None) -> SimpleNamespace:
    return SimpleNamespace(my_chat_member=membership)


# --- discovered_chats_repo ---

def test_record_discovered_chat_creates_new():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100111, "My Group", "supergroup")
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert len(rows) == 1
    assert rows[0].chat_id == -100111
    assert rows[0].title == "My Group"
    assert rows[0].chat_type == "supergroup"


def test_record_discovered_chat_upserts_existing():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100111, "Old Title", "group")
    discovered_chats_repo.record_discovered_chat(-100111, "New Title", "supergroup")
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert len(rows) == 1
    assert rows[0].title == "New Title"
    assert rows[0].chat_type == "supergroup"


def test_remove_discovered_chat():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100111, "Group", "group")
    discovered_chats_repo.remove_discovered_chat(-100111)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


def test_remove_discovered_chat_missing_is_noop():
    _clear()
    discovered_chats_repo.remove_discovered_chat(-100999)


def test_record_discovered_chat_sanitizes_title():
    """Регресс-тест (security-ревью): title приходит напрямую от Telegram
    из чужого чата (my_chat_member) — не должен доносить zero-width/
    bidi-override символы до /targets."""
    _clear()
    rlo = chr(0x202E)
    discovered_chats_repo.record_discovered_chat(-100111, f"Evil{rlo}Title", "group")
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert rows[0].title == "EvilTitle"


def test_list_pending_excludes_already_added_targets():
    # Ключевая гарантия: как только чат добавлен как цель публикации, он
    # больше не занимает место в списке "обнаруженных" на /targets.
    _clear()
    discovered_chats_repo.record_discovered_chat(-100111, "Group A", "group")
    discovered_chats_repo.record_discovered_chat(-100222, "Group B", "group")
    targets_repo.add_target(-100111, "Group A")

    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert [r.chat_id for r in rows] == [-100222]


# --- moderation_bot._on_my_chat_member ---

async def test_on_my_chat_member_records_chat_when_bot_added():
    _clear()
    update = _update(_membership(-100333, "supergroup", "New Group", "member"))
    await _on_my_chat_member(update, None)
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert [r.chat_id for r in rows] == [-100333]
    assert rows[0].can_post is None  # группа — не проверяем, участник и так может писать


async def test_on_my_chat_member_records_chat_when_bot_promoted_to_admin():
    _clear()
    update = _update(_membership(
        -100333, "channel", "News", "administrator", can_post_messages=True,
    ))
    await _on_my_chat_member(update, None)
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert [r.chat_id for r in rows] == [-100333]
    assert rows[0].can_post is True


async def test_on_my_chat_member_removes_chat_when_bot_kicked():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100333, "Group", "group")
    update = _update(_membership(-100333, "group", "Group", "kicked"))
    await _on_my_chat_member(update, None)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


async def test_on_my_chat_member_removes_chat_when_bot_left():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100333, "Group", "group")
    update = _update(_membership(-100333, "group", "Group", "left"))
    await _on_my_chat_member(update, None)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


async def test_on_my_chat_member_syncs_can_post_on_already_added_target():
    """Регресс-тест (аудит ведения групп, раунд 3): права бота отозвали
    (админ -> обычный участник) в чате, который УЖЕ добавлен как цель
    публикации — раньше это нигде не отражалось, кроме тихого провала
    следующей публикации."""
    _clear()
    target, _ = targets_repo.add_target(-100444, "Already A Target")
    update = _update(_membership(-100444, "channel", "Already A Target", "member"))
    await _on_my_chat_member(update, None)
    with session_scope() as session:
        updated = session.get(TargetGroup, target.id)
        assert updated.can_post is False


async def test_on_my_chat_member_sets_can_post_false_on_already_added_target_when_kicked():
    _clear()
    target, _ = targets_repo.add_target(-100555, "Kicked From Target")
    update = _update(_membership(-100555, "channel", "Kicked From Target", "kicked"))
    await _on_my_chat_member(update, None)
    with session_scope() as session:
        updated = session.get(TargetGroup, target.id)
        assert updated.can_post is False


async def test_on_my_chat_member_ignores_private_chats():
    # my_chat_member тоже стреляет для личных чатов (/start, блокировка бота)
    # — это не целевая группа, не должно попадать в discovered_chats.
    _clear()
    update = _update(_membership(555, "private", None, "member"))
    await _on_my_chat_member(update, None)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


async def test_on_my_chat_member_noop_when_no_membership_update():
    _clear()
    update = _update(None)
    await _on_my_chat_member(update, None)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


# --- moderation_bot._discovered_can_post ---
# Значимо только для каналов (см. docstring) — обычный участник канала
# никогда не может постить от своего имени, в отличие от групп.

def test_discovered_can_post_none_for_non_channel():
    member = SimpleNamespace(status="member", can_post_messages=None)
    assert _discovered_can_post("group", member) is None
    assert _discovered_can_post("supergroup", member) is None


def test_discovered_can_post_false_for_plain_member_in_channel():
    member = SimpleNamespace(status="member", can_post_messages=None)
    assert _discovered_can_post("channel", member) is False


def test_discovered_can_post_true_for_creator_in_channel():
    member = SimpleNamespace(status="creator", can_post_messages=None)
    assert _discovered_can_post("channel", member) is True


def test_discovered_can_post_true_for_admin_with_post_rights():
    member = SimpleNamespace(status="administrator", can_post_messages=True)
    assert _discovered_can_post("channel", member) is True


def test_discovered_can_post_false_for_admin_without_post_rights():
    member = SimpleNamespace(status="administrator", can_post_messages=False)
    assert _discovered_can_post("channel", member) is False

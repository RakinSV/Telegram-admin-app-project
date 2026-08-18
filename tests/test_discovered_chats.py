"""Тесты авто-обнаружения чатов для целевых групп (F08-доп.): CRUD-логика
`discovered_chats_repo.py` и хендлер `my_chat_member` в `moderation_bot.py`."""


from tg_repost import discovered_chats_repo, targets_repo
from tg_repost.db.models import DiscoveredChat, TargetGroup
from tg_repost.db.session import session_scope
from tests.aiogram_fakes import fake_membership
from tg_repost.telegram.moderation_bot import _discovered_can_post, _on_my_chat_member


def _clear() -> None:
    with session_scope() as session:
        session.query(DiscoveredChat).delete()
        session.query(TargetGroup).delete()




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
    update = fake_membership(chat_id=-100333, chat_type="supergroup", title="New Group", new_status="member")
    await _on_my_chat_member(update)
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert [r.chat_id for r in rows] == [-100333]
    assert rows[0].can_post is None  # группа — не проверяем, участник и так может писать


async def test_on_my_chat_member_records_chat_when_bot_promoted_to_admin():
    _clear()
    update = fake_membership(chat_id=-100333, chat_type="channel", title="News", new_status="administrator", can_post=True)
    await _on_my_chat_member(update)
    rows = discovered_chats_repo.list_pending_discovered_chats()
    assert [r.chat_id for r in rows] == [-100333]
    assert rows[0].can_post is True


async def test_on_my_chat_member_removes_chat_when_bot_kicked():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100333, "Group", "group")
    update = fake_membership(chat_id=-100333, chat_type="group", title="Group", new_status="kicked")
    await _on_my_chat_member(update)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


async def test_on_my_chat_member_removes_chat_when_bot_left():
    _clear()
    discovered_chats_repo.record_discovered_chat(-100333, "Group", "group")
    update = fake_membership(chat_id=-100333, chat_type="group", title="Group", new_status="left")
    await _on_my_chat_member(update)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


async def test_on_my_chat_member_syncs_can_post_on_already_added_target():
    """Регресс-тест (аудит ведения групп, раунд 3): права бота отозвали
    (админ -> обычный участник) в чате, который УЖЕ добавлен как цель
    публикации — раньше это нигде не отражалось, кроме тихого провала
    следующей публикации."""
    _clear()
    target, _ = targets_repo.add_target(-100444, "Already A Target")
    update = fake_membership(chat_id=-100444, chat_type="channel", title="Already A Target", new_status="member")
    await _on_my_chat_member(update)
    with session_scope() as session:
        updated = session.get(TargetGroup, target.id)
        assert updated.can_post is False


async def test_on_my_chat_member_sets_can_post_false_on_already_added_target_when_kicked():
    _clear()
    target, _ = targets_repo.add_target(-100555, "Kicked From Target")
    update = fake_membership(chat_id=-100555, chat_type="channel", title="Kicked From Target", new_status="kicked")
    await _on_my_chat_member(update)
    with session_scope() as session:
        updated = session.get(TargetGroup, target.id)
        assert updated.can_post is False


async def test_on_my_chat_member_ignores_private_chats():
    # my_chat_member тоже стреляет для личных чатов (/start, блокировка бота)
    # — это не целевая группа, не должно попадать в discovered_chats.
    _clear()
    update = fake_membership(chat_id=555, chat_type="private", title="", new_status="member")
    await _on_my_chat_member(update)
    assert discovered_chats_repo.list_pending_discovered_chats() == []


# Прежний тест «апдейт без членства» удалён вместе с переходом на aiogram:
# обработчик получает `ChatMemberUpdated` напрямую, и события без членства не
# существует — проверять было бы нечего.


# --- moderation_bot._discovered_can_post ---
# Значимо только для каналов (см. docstring) — обычный участник канала
# никогда не может постить от своего имени, в отличие от групп.

def _member(status: str, can_post: bool | None = None):
    """Участник нужного статуса — настоящим типом aiogram."""
    return fake_membership(
        chat_id=-1, new_status=status, can_post=can_post,
    ).new_chat_member


def test_discovered_can_post_none_for_non_channel():
    member = _member("member")
    assert _discovered_can_post("group", member) is None
    assert _discovered_can_post("supergroup", member) is None


def test_discovered_can_post_false_for_plain_member_in_channel():
    assert _discovered_can_post("channel", _member("member")) is False


def test_discovered_can_post_true_for_creator_in_channel():
    assert _discovered_can_post("channel", _member("creator")) is True


def test_discovered_can_post_true_for_admin_with_post_rights():
    assert _discovered_can_post("channel", _member("administrator", True)) is True


def test_discovered_can_post_false_for_admin_without_post_rights():
    assert _discovered_can_post("channel", _member("administrator", False)) is False

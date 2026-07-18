"""Тесты F32 — инвайт-ссылки и заявки на вступление: `invites_repo.py`
(CRUD) и `telegram/invites.py` (тонкая Bot API обвязка)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from tg_repost import invites_repo
from tg_repost.db.models import InviteLink, JoinRequestRecord
from tg_repost.db.session import session_scope
from tg_repost.telegram.invites import (
    approve_join_request,
    create_invite_link,
    decline_join_request,
    revoke_invite_link,
)


def _clean() -> None:
    with session_scope() as session:
        session.query(InviteLink).delete()
        session.query(JoinRequestRecord).delete()


# --- invites_repo: инвайт-ссылки ---


def test_record_and_list_invite_links():
    _clean()
    invites_repo.record_invite_link(-100111, "https://t.me/+abc", "test", None, False)
    links = invites_repo.list_invite_links(-100111)
    assert len(links) == 1
    assert links[0].invite_link == "https://t.me/+abc"
    assert links[0].is_revoked is False


def test_list_invite_links_scoped_to_chat():
    _clean()
    invites_repo.record_invite_link(-100111, "https://t.me/+a", None, None, False)
    invites_repo.record_invite_link(-100222, "https://t.me/+b", None, None, False)
    assert len(invites_repo.list_invite_links(-100111)) == 1
    assert len(invites_repo.list_invite_links()) == 2


def test_mark_revoked_updates_flag():
    _clean()
    link = invites_repo.record_invite_link(-100111, "https://t.me/+a", None, None, False)
    assert invites_repo.mark_revoked(link.id) is True
    assert invites_repo.get_invite_link(link.id).is_revoked is True


def test_mark_revoked_missing_returns_false():
    assert invites_repo.mark_revoked(999999) is False


# --- invites_repo: заявки на вступление ---


def test_record_join_request_creates_new():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", "hi")
    pending = invites_repo.list_pending_join_requests(-100111)
    assert len(pending) == 1
    assert pending[0].username == "someone"


def test_record_join_request_upserts_existing_pending():
    """Telegram может прислать `chat_join_request` снова для того же
    пользователя, если заявка ещё не решена — не должно создавать дубль
    (см. UniqueConstraint в db/models.py)."""
    _clean()
    invites_repo.record_join_request(-100111, 555, "old_name", "old bio")
    invites_repo.record_join_request(-100111, 555, "new_name", "new bio")
    pending = invites_repo.list_pending_join_requests(-100111)
    assert len(pending) == 1
    assert pending[0].username == "new_name"
    assert pending[0].bio == "new bio"


def test_decide_join_request_approves():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    decided = invites_repo.decide_join_request(request_id, approved=True)
    assert decided.status == "approved"
    assert decided.decided_at is not None
    assert invites_repo.list_pending_join_requests() == []


def test_decide_join_request_declines():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    decided = invites_repo.decide_join_request(request_id, approved=False)
    assert decided.status == "declined"


def test_decide_join_request_missing_returns_none():
    assert invites_repo.decide_join_request(999999, approved=True) is None


def test_decide_join_request_already_decided_returns_none():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    invites_repo.decide_join_request(request_id, approved=True)
    assert invites_repo.decide_join_request(request_id, approved=False) is None


def test_record_join_request_after_decision_creates_new_pending_row():
    """После решения (approved/declined) новая заявка от того же
    пользователя — это НОВАЯ pending-запись (уникальность — только среди
    pending), а не апдейт старой уже решённой."""
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    invites_repo.decide_join_request(request_id, approved=False)

    invites_repo.record_join_request(-100111, 555, "someone", None)
    pending = invites_repo.list_pending_join_requests(-100111)
    assert len(pending) == 1
    assert pending[0].id != request_id


# --- telegram/invites.py ---


async def test_create_invite_link_calls_bot_and_records():
    _clean()
    bot = AsyncMock()
    bot.create_chat_invite_link.return_value = AsyncMock(invite_link="https://t.me/+xyz")

    link = await create_invite_link(bot, -100111, "test", 10, creates_join_request=True)

    bot.create_chat_invite_link.assert_awaited_once_with(
        chat_id=-100111, name="test", member_limit=10, creates_join_request=True,
    )
    assert link.invite_link == "https://t.me/+xyz"
    assert link.member_limit == 10


async def test_revoke_invite_link_calls_bot_and_marks_revoked():
    _clean()
    link = invites_repo.record_invite_link(-100111, "https://t.me/+a", None, None, False)
    bot = AsyncMock()

    ok = await revoke_invite_link(bot, link.id)

    assert ok is True
    bot.revoke_chat_invite_link.assert_awaited_once_with(
        chat_id=-100111, invite_link="https://t.me/+a",
    )
    assert invites_repo.get_invite_link(link.id).is_revoked is True


async def test_revoke_invite_link_missing_returns_false():
    bot = AsyncMock()
    assert await revoke_invite_link(bot, 999999) is False
    bot.revoke_chat_invite_link.assert_not_awaited()


async def test_approve_join_request_calls_bot_and_decides():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = AsyncMock()

    ok = await approve_join_request(bot, request_id)

    assert ok is True
    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    assert invites_repo.get_join_request(request_id).status == "approved"


async def test_decline_join_request_calls_bot_and_decides():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = AsyncMock()

    ok = await decline_join_request(bot, request_id)

    assert ok is True
    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    assert invites_repo.get_join_request(request_id).status == "declined"


async def test_approve_join_request_missing_returns_false():
    bot = AsyncMock()
    assert await approve_join_request(bot, 999999) is False
    bot.approve_chat_join_request.assert_not_awaited()

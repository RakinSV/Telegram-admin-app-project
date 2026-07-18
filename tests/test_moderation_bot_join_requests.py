"""Тесты F32-хендлеров бота модерации: `_on_chat_join_request` (запись +
уведомление владельца) и `_decide_join_request` (кнопки Одобрить/Отклонить)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tg_repost import invites_repo
from tg_repost.db.models import JoinRequestRecord
from tg_repost.db.session import session_scope
from tg_repost.telegram.moderation_bot import _decide_join_request, _on_chat_join_request


def _clean() -> None:
    with session_scope() as session:
        session.query(JoinRequestRecord).delete()


def _fake_join_request(chat_id: int, user_id: int, username: str | None, bio: str | None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, title="Test Group"),
        from_user=SimpleNamespace(id=user_id, username=username, full_name="Test User"),
        bio=bio,
    )


async def test_on_chat_join_request_records_and_notifies_owner():
    _clean()
    update = SimpleNamespace(
        chat_join_request=_fake_join_request(-100111, 555, "someone", "hi there"),
    )
    context = SimpleNamespace(bot=AsyncMock())

    await _on_chat_join_request(update, context)

    pending = invites_repo.list_pending_join_requests(-100111)
    assert len(pending) == 1
    assert pending[0].user_id == 555
    context.bot.send_message.assert_awaited_once()
    kwargs = context.bot.send_message.call_args.kwargs
    assert "someone" in kwargs["text"] or "@someone" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"jrq_ok:{pending[0].id}"


async def test_on_chat_join_request_noop_when_no_request():
    context = SimpleNamespace(bot=AsyncMock())
    await _on_chat_join_request(SimpleNamespace(chat_join_request=None), context)
    context.bot.send_message.assert_not_awaited()


async def test_on_chat_join_request_survives_notify_failure():
    """Регресс-профилактика: сбой отправки уведомления не должен ронять
    хендлер — заявка уже записана и её можно решить из веб-админки."""
    _clean()
    update = SimpleNamespace(chat_join_request=_fake_join_request(-100111, 555, None, None))
    context = SimpleNamespace(bot=AsyncMock())
    context.bot.send_message.side_effect = RuntimeError("Telegram недоступен")

    await _on_chat_join_request(update, context)

    assert len(invites_repo.list_pending_join_requests(-100111)) == 1


async def test_decide_join_request_approves_and_edits_message():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = AsyncMock()
    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)
    context = SimpleNamespace(application=SimpleNamespace(bot=bot))

    await _decide_join_request(query, context, request_id, approved=True)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    query.edit_message_text.assert_awaited_once()
    assert "Одобрена" in query.edit_message_text.call_args.args[0]


async def test_decide_join_request_declines():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = AsyncMock()
    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)
    context = SimpleNamespace(application=SimpleNamespace(bot=bot))

    await _decide_join_request(query, context, request_id, approved=False)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    assert "Отклонена" in query.edit_message_text.call_args.args[0]


async def test_decide_join_request_missing_shows_error():
    bot = AsyncMock()
    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)
    context = SimpleNamespace(application=SimpleNamespace(bot=bot))

    await _decide_join_request(query, context, 999999, approved=True)

    bot.approve_chat_join_request.assert_not_awaited()
    assert "не найдена" in query.edit_message_text.call_args.args[0]

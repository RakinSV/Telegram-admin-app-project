"""F32-обработчики бота модерации: заявка на вступление и кнопки решения.

Переписаны под aiogram 2026-08-18: обработчик принимает саму заявку и бота, а
не апдейт с контекстом. Объекты берутся настоящие (`tests/aiogram_fakes.py`) —
самодельные заглушки прошли бы там, где живой код различает `Message` и
`InaccessibleMessage`.
"""

from __future__ import annotations

from tests.aiogram_fakes import fake_bot, fake_callback, fake_join_request, sent_methods
from tg_repost import invites_repo
from tg_repost.db.models import JoinRequestRecord
from tg_repost.db.session import session_scope
from tg_repost.telegram.moderation_bot import _decide_join_request, _on_chat_join_request


def _clean() -> None:
    with session_scope() as session:
        session.query(JoinRequestRecord).delete()


def _edited_text(bot) -> str:
    """Текст, которым бот заменил сообщение с кнопками."""
    for method in sent_methods(bot):
        text = getattr(method, "text", None) or getattr(method, "caption", None)
        if text:
            return text
    return ""


async def test_on_chat_join_request_records_and_notifies_owner():
    _clean()
    bot = fake_bot()
    request = fake_join_request(bot, -100111, 555, "someone", "hi there")

    await _on_chat_join_request(request, bot)

    pending = invites_repo.list_pending_join_requests(-100111)
    assert len(pending) == 1
    assert pending[0].user_id == 555
    bot.send_message.assert_awaited_once()
    assert "Заявка на вступление" in bot.send_message.await_args.kwargs["text"]


async def test_notification_failure_does_not_lose_the_request():
    """Сбой отправки уведомления не должен ронять обработчик: заявка уже
    записана, и решить её можно из веб-админки."""
    _clean()
    bot = fake_bot()
    bot.send_message.side_effect = RuntimeError("Telegram недоступен")
    request = fake_join_request(bot, -100111, 555)

    await _on_chat_join_request(request, bot)

    assert len(invites_repo.list_pending_join_requests(-100111)) == 1


async def test_join_request_saves_invite_link_for_attribution():
    """F41: по какой ссылке подана заявка — источник не должен потеряться к
    моменту одобрения."""
    _clean()
    bot = fake_bot()
    request = fake_join_request(
        bot, -100111, 555, invite_link="https://t.me/+abcdef",
    )

    await _on_chat_join_request(request, bot)

    record = invites_repo.list_pending_join_requests(-100111)[0]
    assert record.invite_link == "https://t.me/+abcdef"


async def test_join_request_without_link_stores_none():
    _clean()
    bot = fake_bot()

    await _on_chat_join_request(fake_join_request(bot, -100111, 556), bot)

    assert invites_repo.list_pending_join_requests(-100111)[0].invite_link is None


async def test_decide_join_request_approves_and_edits_message():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = fake_bot()
    query = fake_callback(bot, f"jrq_ok:{request_id}")

    await _decide_join_request(query, bot, request_id, approved=True)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    assert "Одобрена" in _edited_text(bot)


async def test_decide_join_request_declines():
    _clean()
    invites_repo.record_join_request(-100111, 555, "someone", None)
    request_id = invites_repo.list_pending_join_requests()[0].id
    bot = fake_bot()
    query = fake_callback(bot, f"jrq_no:{request_id}")

    await _decide_join_request(query, bot, request_id, approved=False)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-100111, user_id=555)
    assert "Отклонена" in _edited_text(bot)


async def test_decide_join_request_missing_shows_error():
    """Заявку могли решить из админки, пока владелец смотрел на кнопки."""
    _clean()
    bot = fake_bot()
    query = fake_callback(bot, "jrq_ok:9999")

    await _decide_join_request(query, bot, 9999, approved=True)

    bot.approve_chat_join_request.assert_not_awaited()
    assert "уже решена" in _edited_text(bot)

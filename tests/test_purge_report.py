"""Зачистка после рейда и репорты от участников (F58).

Тесты в основном про ограничения, которые задал Telegram, и про то, что мы
их не пытаемся обойти враньём:

* Bot API не перечисляет сообщения — работаем по диапазону id, и часть его
  заведомо не существует. Ошибки по отдельным сообщениям это норма, а не
  сбой, и падать на них нельзя;
* бот не удаляет сообщения старше 48 часов — значит «зачистить всё за
  неделю» невозможно, и обещать это в подсказке нельзя;
* диапазон ограничен сверху, иначе ответ на старое сообщение превращается
  в тысячи бесполезных запросов.

Отдельно: жалоба от участника не должна становиться способом забить
лог-канал.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from guardian.db.models import ModerationLog
from guardian.db.session import session_scope
from guardian.handlers import purge_report

CHAT = -100606060
ADMIN = 111
MEMBER = 222


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    with session_scope() as session:
        session.query(ModerationLog).delete()
    purge_report._last_report.clear()

    settings = purge_report.get_guardian_settings()
    monkeypatch.setattr(settings, "protected_chat_ids", [CHAT], raising=False)
    # Лог-канал не настроен — отправка молча пропускается, как в проде.
    monkeypatch.setattr(settings, "guardian_log_channel_id", 0, raising=False)
    yield
    with session_scope() as session:
        session.query(ModerationLog).delete()


def _bot(deleted: list[int] | None = None, fail_ids: set[int] | None = None) -> AsyncMock:
    bot = AsyncMock()
    bucket = deleted if deleted is not None else []
    bad = fail_ids or set()

    async def _delete(chat_id, message_id):
        if message_id in bad:
            raise TelegramBadRequest(method=None, message="message to delete not found")
        bucket.append(message_id)

    bot.delete_message = AsyncMock(side_effect=_delete)
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(user=SimpleNamespace(id=ADMIN))]
    )
    return bot


def _message(
    *, from_id: int, message_id: int, reply_to_id: int | None = None,
    chat_id: int = CHAT, reply_author: int | None = None, text: str = "спам",
) -> SimpleNamespace:
    reply = None
    if reply_to_id is not None:
        reply = SimpleNamespace(
            message_id=reply_to_id,
            from_user=SimpleNamespace(
                id=reply_author if reply_author is not None else MEMBER,
                username="spammer", is_bot=False,
            ),
            text=text,
            caption=None,
        )
    return SimpleNamespace(
        message_id=message_id,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=from_id, username="user", is_bot=False),
        reply_to_message=reply,
        reply=AsyncMock(),
    )


# --- purge ---


async def test_purge_deletes_the_whole_range():
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(from_id=ADMIN, message_id=110, reply_to_id=100)

    await purge_report.cmd_purge(message, bot)

    assert deleted == list(range(100, 111))  # включая саму команду


async def test_purge_survives_missing_messages():
    """Часть id в диапазоне не существует — это норма работы по диапазону.

    Bot API не умеет перечислять сообщения, поэтому «дырки» неизбежны, и
    падать на них значило бы не уметь чистить чат вообще.
    """
    deleted: list[int] = []
    bot = _bot(deleted, fail_ids={102, 103, 107})
    message = _message(from_id=ADMIN, message_id=110, reply_to_id=100)

    await purge_report.cmd_purge(message, bot)

    assert 102 not in deleted
    assert len(deleted) == 8  # 11 в диапазоне минус 3 отсутствующих


async def test_purge_requires_admin():
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(from_id=MEMBER, message_id=110, reply_to_id=100)

    await purge_report.cmd_purge(message, bot)

    assert deleted == []
    message.reply.assert_awaited()


async def test_purge_without_reply_explains_the_48h_limit():
    """Подсказка обязана называть ограничение Telegram.

    Иначе владелец решит, что «зачистить вчерашний рейд» не сработало
    из-за поломки, хотя бот физически не может удалять старое.
    """
    bot = _bot()
    message = _message(from_id=ADMIN, message_id=110)

    await purge_report.cmd_purge(message, bot)

    text = message.reply.await_args.args[0]
    assert "48" in text
    bot.delete_message.assert_not_awaited()


async def test_purge_refuses_too_large_range():
    """Ответ на старое сообщение — тысячи бесполезных запросов к API."""
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(
        from_id=ADMIN, message_id=10_000, reply_to_id=1,
    )

    await purge_report.cmd_purge(message, bot)

    assert deleted == []
    assert str(purge_report.MAX_PURGE) in message.reply.await_args.args[0]


async def test_purge_ignored_in_unprotected_chat():
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(from_id=ADMIN, message_id=110, reply_to_id=100, chat_id=-1)

    await purge_report.cmd_purge(message, bot)

    assert deleted == []


async def test_purge_is_logged():
    bot = _bot([])
    message = _message(from_id=ADMIN, message_id=105, reply_to_id=100)

    await purge_report.cmd_purge(message, bot)

    with session_scope() as session:
        row = session.query(ModerationLog).filter(ModerationLog.action == "purge").one()
        assert "удалено 6" in (row.reason or "")


# --- report ---


async def test_report_command_is_deleted_from_chat():
    """Команда не должна висеть в чате и привлекать внимание к спаму."""
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(from_id=MEMBER, message_id=200, reply_to_id=199)

    await purge_report.cmd_report(message, bot)

    assert 200 in deleted


async def test_report_without_reply_does_nothing_more():
    deleted: list[int] = []
    bot = _bot(deleted)
    message = _message(from_id=MEMBER, message_id=200)

    await purge_report.cmd_report(message, bot)

    assert deleted == [200]  # удалили только саму команду


async def test_repeated_reports_are_throttled():
    """Недовольный участник иначе забьёт лог-канал жалобами на оппонента,
    и модератор перестанет читать канал целиком."""
    bot = _bot([])
    for message_id in (200, 201, 202):
        await purge_report.cmd_report(
            _message(from_id=MEMBER, message_id=message_id, reply_to_id=199), bot,
        )

    assert len(purge_report._last_report) == 1


async def test_report_on_bot_message_is_ignored():
    """Жаловаться на сообщение бота бессмысленно."""
    bot = _bot([])
    message = _message(from_id=MEMBER, message_id=200, reply_to_id=199)
    message.reply_to_message.from_user.is_bot = True

    await purge_report.cmd_report(message, bot)

    assert purge_report._last_report  # проход был, но дальше ничего не случилось


# --- решение по жалобе ---


async def test_report_decision_requires_admin_of_source_chat():
    """Кнопки живут в лог-канале, но решение касается ГРУППЫ.

    Админом надо быть именно там: доступ к каналу логов сам по себе не
    делает человека модератором чата.
    """
    deleted: list[int] = []
    bot = _bot(deleted)
    callback = SimpleNamespace(
        data=f"rp:del:{CHAT}:199",
        from_user=SimpleNamespace(id=MEMBER),
        message=None,
        answer=AsyncMock(),
    )

    await purge_report.on_report_decision(callback, bot)

    assert deleted == []
    assert callback.answer.await_args.kwargs.get("show_alert") is True


async def test_admin_decision_deletes_the_message():
    deleted: list[int] = []
    bot = _bot(deleted)
    callback = SimpleNamespace(
        data=f"rp:del:{CHAT}:199",
        from_user=SimpleNamespace(id=ADMIN),
        message=None,
        answer=AsyncMock(),
    )

    await purge_report.on_report_decision(callback, bot)

    assert deleted == [199]
    with session_scope() as session:
        assert session.query(ModerationLog).count() == 1


async def test_skip_decision_deletes_nothing():
    deleted: list[int] = []
    bot = _bot(deleted)
    callback = SimpleNamespace(
        data="rp:skip",
        from_user=SimpleNamespace(id=ADMIN),
        message=None,
        answer=AsyncMock(),
    )

    await purge_report.on_report_decision(callback, bot)

    assert deleted == []

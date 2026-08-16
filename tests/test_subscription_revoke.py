"""Закрытие доступа по окончании подписки (F49).

Тесты про поведение на сбоях: именно там разница между «человек ушёл из
платного канала» и «человек навсегда потерял доступ, за который платил».
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from tg_repost import subscriptions_repo as subs
from tg_repost.db.models import ChannelSubscription, PaymentEvent
from tg_repost.db.session import session_scope
from tg_repost.scheduler.subscriptions import revoke_expired_subscriptions

CHAT = -1005000
ALICE = 9201
BOB = 9202


def _expired_at() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=subs.KICK_GRACE_HOURS + 2)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()

    _wipe()
    yield
    _wipe()


async def test_expired_member_is_removed():
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    bot = AsyncMock()

    closed = await revoke_expired_subscriptions(bot)

    assert closed == 1
    assert bot.ban_chat_member.await_count == 1


async def test_ban_is_followed_by_unban():
    """ГЛАВНАЯ ДЕТАЛЬ.

    Бан без снятия оставляет человека в чёрном списке: он оплатит снова и
    не сможет войти по новой ссылке. Обратная дорога — весь смысл подписки.
    """
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    bot = AsyncMock()

    await revoke_expired_subscriptions(bot)

    assert bot.unban_chat_member.await_count == 1
    assert bot.unban_chat_member.await_args.kwargs["only_if_banned"] is True


async def test_active_subscription_is_untouched():
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=datetime.now(timezone.utc) + timedelta(days=3),
    )
    bot = AsyncMock()

    assert await revoke_expired_subscriptions(bot) == 0
    assert bot.ban_chat_member.await_count == 0


async def test_failure_on_one_does_not_stop_the_rest():
    """Иначе одна строка копит неснятые доступы у всех остальных."""
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    subs.grant(chat_id=CHAT, user_id=BOB, paid_until=_expired_at())
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = [Exception("Bad Request: chat not found"), None]

    closed = await revoke_expired_subscriptions(bot)

    assert closed == 1
    assert bot.ban_chat_member.await_count == 2


async def test_subscription_stays_active_when_removal_failed():
    """Пометить закрытым, а потом упасть — значит оставить человека в канале
    навсегда: следующий проход его уже не увидит."""
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = Exception("Bad Request: not enough rights")

    await revoke_expired_subscriptions(bot)

    view = subs.get(CHAT, ALICE)
    assert view is not None
    assert view.status == subs.STATUS_ACTIVE
    assert subs.due_for_revoke() != []


async def test_person_who_already_left_is_closed_without_error():
    """Человек вышел сам — не наша ошибка, но и держать подписку вечно
    активной незачем."""
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = Exception(
        "Bad Request: user not found in the chat"
    )

    await revoke_expired_subscriptions(bot)

    view = subs.get(CHAT, ALICE)
    assert view is not None
    assert view.status == subs.STATUS_EXPIRED


async def test_nothing_to_do_makes_no_calls():
    bot = AsyncMock()

    assert await revoke_expired_subscriptions(bot) == 0
    assert bot.ban_chat_member.await_count == 0


async def test_closed_subscription_is_not_processed_twice():
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_expired_at())
    bot = AsyncMock()
    await revoke_expired_subscriptions(bot)

    assert await revoke_expired_subscriptions(bot) == 0

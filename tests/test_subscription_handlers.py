"""Обработчики платного доступа в Engage (F49).

Проверяется то, что нельзя проверить в репозитории: порядок шагов, заданный
Telegram, и поведение на сбоях. Живыми платежами не проверялось — нужен бот,
подписка и настоящие звёзды.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engage.handlers import subscription
from tg_repost import subscriptions_repo as subs
from tg_repost.db.models import ChannelSubscription, PaymentEvent
from tg_repost.db.session import session_scope

CHAT = -1005000
ALICE = 9101
PRICE = 250
CHARGE = "charge_xyz"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _plan_on(monkeypatch):
    monkeypatch.setattr(
        subscription, "_plan", lambda: (CHAT, PRICE, "Закрытый клуб"),
    )


@pytest.fixture
def _plan_off(monkeypatch):
    monkeypatch.setattr(subscription, "_plan", lambda: None)


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.create_invoice_link.return_value = "https://t.me/invoice/abc"
    bot.create_chat_invite_link.return_value = SimpleNamespace(
        invite_link="https://t.me/+personal",
    )
    return bot


def _message(payment=None) -> AsyncMock:
    message = AsyncMock()
    message.from_user = SimpleNamespace(id=ALICE, username="alice", first_name="Алиса")
    message.successful_payment = payment
    return message


def _payment(**over) -> SimpleNamespace:
    data = {
        "telegram_payment_charge_id": CHARGE,
        "invoice_payload": subscription.build_payload(CHAT),
        "total_amount": PRICE,
        "currency": "XTR",
        "subscription_expiration_date": int(
            (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
        ),
        "is_recurring": True,
        "is_first_recurring": True,
    }
    data.update(over)
    return SimpleNamespace(**data)


# --- payload ---


def test_payload_carries_the_channel():
    """Канал кладётся В САМ ПЛАТЁЖ: между счётом и оплатой могут пройти
    сутки и перезапуск бота."""
    assert subscription.parse_payload(subscription.build_payload(CHAT)) == CHAT


@pytest.mark.parametrize("raw", [None, "", "мусор", "sub:", "sub:abc", "other:1"])
def test_broken_payload_is_rejected(raw):
    assert subscription.parse_payload(raw) is None


# --- счёт ---


async def test_subscribe_creates_invoice_link(_plan_on):
    message, bot = _message(), _bot()

    await subscription.on_subscribe(message, bot)

    assert bot.create_invoice_link.await_count == 1
    kwargs = bot.create_invoice_link.await_args.kwargs
    assert kwargs["currency"] == "XTR"
    assert kwargs["subscription_period"] == subscription.SUBSCRIPTION_PERIOD


async def test_subscribe_says_so_when_not_configured(_plan_off):
    message, bot = _message(), _bot()

    await subscription.on_subscribe(message, bot)

    assert bot.create_invoice_link.await_count == 0
    assert "не настроен" in message.answer.await_args.args[0]


async def test_active_subscriber_gets_link_instead_of_second_invoice(_plan_on):
    """Второй счёт активному подписчику — прямой путь к двойному списанию."""
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=datetime.now(timezone.utc) + timedelta(days=10),
        invite_link="https://t.me/+existing",
    )
    message, bot = _message(), _bot()

    await subscription.on_subscribe(message, bot)

    assert bot.create_invoice_link.await_count == 0
    assert "https://t.me/+existing" in message.answer.await_args.args[0]


# --- подтверждение платежа ---


async def test_pre_checkout_is_answered(_plan_on):
    """Молчание дольше 10 секунд Telegram считает отказом."""
    query = AsyncMock()
    query.invoice_payload = subscription.build_payload(CHAT)
    query.from_user = SimpleNamespace(id=ALICE)

    await subscription.on_pre_checkout(query)

    assert query.answer.await_args.kwargs["ok"] is True


async def test_pre_checkout_rejects_foreign_channel(_plan_on):
    """Счёт от чужого канала оплачивать нельзя."""
    query = AsyncMock()
    query.invoice_payload = subscription.build_payload(-999)
    query.from_user = SimpleNamespace(id=ALICE)

    await subscription.on_pre_checkout(query)

    assert query.answer.await_args.kwargs["ok"] is False


async def test_pre_checkout_rejects_when_access_is_off(_plan_off):
    query = AsyncMock()
    query.invoice_payload = subscription.build_payload(CHAT)
    query.from_user = SimpleNamespace(id=ALICE)

    await subscription.on_pre_checkout(query)

    assert query.answer.await_args.kwargs["ok"] is False
    assert "не списаны" in query.answer.await_args.kwargs["error_message"]


# --- оплата ---


async def test_payment_grants_single_use_link(_plan_on):
    message, bot = _message(_payment()), _bot()

    await subscription.on_successful_payment(message, bot)

    assert bot.create_chat_invite_link.await_args.kwargs["member_limit"] == 1
    view = subs.get(CHAT, ALICE)
    assert view is not None and view.is_active


async def test_repeated_payment_update_is_ignored_entirely(_plan_on):
    """ГЛАВНАЯ ЗАЩИТА.

    Апдейт об оплате приходит дважды. Проверяем именно ОСТАНОВКУ обработки,
    а не «ссылка не создалась второй раз»: ссылку и без защиты не создали бы
    второй раз — она уже сохранена в подписке. Первая версия этого теста
    проходила при СНЯТОЙ защите, что и выяснила диверсия.

    Наблюдаемый признак — второе «оплата получена» человеку, который платил
    один раз.
    """
    bot = _bot()
    first, second = _message(_payment()), _message(_payment())

    await subscription.on_successful_payment(first, bot)
    await subscription.on_successful_payment(second, bot)

    assert first.answer.await_count == 1
    assert second.answer.await_count == 0, "повтор дошёл до конца обработки"
    assert bot.create_chat_invite_link.await_count == 1


async def test_duplicate_payment_does_not_grant_when_link_was_not_issued(_plan_on):
    """Тот же дубль, но по сбойному пути: ссылки ещё нет.

    Здесь «ссылка уже сохранена» не спасает, и без защиты повтор полез бы
    создавать инвайт заново.
    """
    bot = _bot()
    bot.create_chat_invite_link.side_effect = Exception("нет прав")
    await subscription.on_successful_payment(_message(_payment()), bot)
    bot.create_chat_invite_link.side_effect = None

    await subscription.on_successful_payment(_message(_payment()), bot)

    assert bot.create_chat_invite_link.await_count == 1


async def test_payment_uses_expiry_from_telegram(_plan_on):
    """Дату окончания считает Telegram; своя арифметика с ней разойдётся."""
    expires = datetime.now(timezone.utc) + timedelta(days=45)
    message = _message(_payment(subscription_expiration_date=int(expires.timestamp())))

    await subscription.on_successful_payment(message, _bot())

    view = subs.get(CHAT, ALICE)
    assert view is not None
    assert abs((view.paid_until - expires).total_seconds()) < 2


async def test_payment_with_broken_payload_is_not_lost_silently(_plan_on, caplog):
    """Доступ выдать не по чему, но и молчать нельзя — иначе оплата исчезнет."""
    message = _message(_payment(invoice_payload="мусор"))

    await subscription.on_successful_payment(message, _bot())

    assert subs.get(CHAT, ALICE) is None
    assert "F49" in caplog.text


async def test_payment_is_recorded_even_if_invite_fails(_plan_on):
    """САМЫЙ ВАЖНЫЙ СБОЙНЫЙ ПУТЬ.

    Деньги уже списаны. Потерять запись об оплате из-за недоступного
    Telegram — это «заплатите ещё раз» в ответ человеку.
    """
    bot = _bot()
    bot.create_chat_invite_link.side_effect = Exception("Bad Request: not enough rights")
    message = _message(_payment())

    await subscription.on_successful_payment(message, bot)

    view = subs.get(CHAT, ALICE)
    assert view is not None and view.is_active
    assert view.invite_link is None
    assert "владельцу" in message.answer.await_args.args[0]


async def test_renewal_keeps_the_same_link(_plan_on):
    """Продление не должно плодить ссылки: человек уже в канале."""
    bot = _bot()
    await subscription.on_successful_payment(_message(_payment()), bot)
    later = datetime.now(timezone.utc) + timedelta(days=60)
    await subscription.on_successful_payment(
        _message(_payment(
            telegram_payment_charge_id="charge_2",
            is_first_recurring=False,
            subscription_expiration_date=int(later.timestamp()),
        )),
        bot,
    )

    assert bot.create_chat_invite_link.await_count == 1
    view = subs.get(CHAT, ALICE)
    assert view is not None
    # Продление действительно засчитано, а не отброшено как дубль.
    assert abs((view.paid_until - later).total_seconds()) < 2

"""Деньги на стыках модулей (аудит 2026-08-16).

Аудит нашёл три бага подряд, и все три были ОДНОГО вида: каждый модуль
исправен и покрыт тестами, а между ними никто не ходит. Тесты по функциям
такого не видят по определению — они сами вызывают то, что в бою не
вызывается.

Поэтому здесь сценарии идут ЧЕРЕЗ РЕАЛЬНЫЕ ТОЧКИ ВХОДА и проверяют, что
деньги сходятся после каждого шага: оплата → комиссия партнёру → возврат →
снятие комиссии.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost import affiliate_repo, subscriptions_repo as subs
from tg_repost.db.models import (
    AffiliateReward,
    ChannelSubscription,
    PaymentEvent,
    Referral,
)
from tg_repost.db.session import session_scope

PARTNER = 9701
PAYER = 9702
CHAT = -1009700
CHARGE = "seam_charge"
PRICE = 100


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(AffiliateReward).delete()
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()
            session.query(Referral).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _percent_30(monkeypatch):
    monkeypatch.setattr(affiliate_repo, "_percent", lambda: 30)


@pytest.fixture
def _confirmed_referral():
    with session_scope() as session:
        session.add(Referral(
            inviter_user_id=PARTNER,
            invited_user_id=PAYER,
            chat_id=CHAT,
            joined_at=datetime.now(timezone.utc) - timedelta(days=10),
            first_message_at=datetime.now(timezone.utc) - timedelta(days=9),
            confirmed_at=datetime.now(timezone.utc),
        ))


async def _pay_through_the_handler(charge_id: str = CHARGE) -> None:
    """Оплата ИМЕННО через обработчик бота, а не через репозиторий.

    Смысл файла в этом: репозиторий и так покрыт, а ломались стыки.
    """
    from engage.handlers import subscription

    payment = SimpleNamespace(
        telegram_payment_charge_id=charge_id,
        invoice_payload=subscription.build_payload(CHAT),
        total_amount=PRICE,
        currency="XTR",
        subscription_expiration_date=int(
            (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
        ),
        is_recurring=True,
        is_first_recurring=True,
    )
    message = AsyncMock()
    message.from_user = SimpleNamespace(
        id=PAYER, username="payer", first_name="Плательщик",
    )
    message.successful_payment = payment

    bot = AsyncMock()
    bot.create_chat_invite_link.return_value = SimpleNamespace(
        invite_link="https://t.me/+seam",
    )
    await subscription.on_successful_payment(message, bot)


async def test_payment_through_the_handler_pays_the_partner(
    _percent_30, _confirmed_referral,
):
    """ГЛАВНЫЙ СТЫК.

    Комиссия должна начисляться сама, в момент оплаты, а не отдельной
    командой — иначе партнёрская программа существует только на бумаге.
    """
    await _pay_through_the_handler()

    assert affiliate_repo.balance_of(PARTNER).owed == 30


async def test_refund_takes_the_commission_back(_percent_30, _confirmed_referral):
    """САМАЯ ДОРОГАЯ ОШИБКА, ЕСЛИ ПРОПУСТИТЬ СТЫК.

    Человек платит 100, партнёр получает 30, человек возвращает деньги — и
    у владельца минус 30 из воздуха.
    """
    await _pay_through_the_handler()
    bot = AsyncMock()
    import engage.bot as engage_bot

    original = engage_bot.build_reply_bot
    engage_bot.build_reply_bot = lambda: bot
    try:
        done, _ = await subs.refund(CHAT, PAYER)
    finally:
        engage_bot.build_reply_bot = original

    assert done is True
    assert affiliate_repo.balance_of(PARTNER).owed == 0
    assert subs.revenue_stars() == 0


async def test_unconfirmed_referral_earns_nothing_through_the_handler(_percent_30):
    """Без подтверждения (F42) комиссия шла бы за аккаунт, который зашёл по
    ссылке и исчез. Проверяется на живом пути, а не на репозитории."""
    with session_scope() as session:
        session.add(Referral(
            inviter_user_id=PARTNER, invited_user_id=PAYER, chat_id=CHAT,
        ))

    await _pay_through_the_handler()

    assert affiliate_repo.balance_of(PARTNER).owed == 0


async def test_duplicate_delivery_pays_the_partner_once(
    _percent_30, _confirmed_referral,
):
    """Повтор апдейта не должен ни выдать доступ дважды, ни заплатить дважды."""
    await _pay_through_the_handler()
    await _pay_through_the_handler()

    assert affiliate_repo.balance_of(PARTNER).owed == 30
    with session_scope() as session:
        assert session.query(PaymentEvent).filter(
            PaymentEvent.kind == subs.KIND_PAYMENT,
        ).count() == 1


async def test_renewal_pays_the_partner_again(_percent_30, _confirmed_referral):
    """Продление — новая оплата, значит и новая комиссия: партнёр привёл
    человека, который платит второй месяц."""
    await _pay_through_the_handler(charge_id="first")
    await _pay_through_the_handler(charge_id="second")

    assert affiliate_repo.balance_of(PARTNER).owed == 60

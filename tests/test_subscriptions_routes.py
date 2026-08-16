"""Страница подписчиков и возврат денег (F49).

Возврат необратим и трогает настоящие деньги, поэтому тесты в основном про
границы: кто вообще может открыть страницу, что происходит при отказе
Telegram и не задваивается ли возврат.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import subscriptions_repo as subs
from tg_repost.db.models import AdminUser, ChannelSubscription, PaymentEvent
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password

CHAT = -1005000
ALICE = 9301
CHARGE = "charge_page"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()

    _wipe()
    yield
    _wipe()


def _paid(amount: int = 250) -> None:
    subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE,
        chat_id=CHAT, amount=amount,
        period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=datetime.now(timezone.utc) + timedelta(days=30),
        charge_id=CHARGE, invite_link="https://t.me/+abc",
    )


@pytest.fixture
def _engage_bot(monkeypatch) -> AsyncMock:
    bot = AsyncMock()
    monkeypatch.setattr("engage.bot.build_reply_bot", lambda: bot)
    return bot


# --- страница ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/subscriptions").status_code == 200


def test_page_shows_subscriber_and_revenue():
    client = _client()
    _bootstrap(client)
    _paid(amount=250)

    body = client.get("/subscriptions").text

    assert str(ALICE) in body
    assert "250" in body


def test_revenue_drops_after_refund_event():
    """Выручка считается по журналу: иначе возврат остался бы незамеченным."""
    client = _client()
    _bootstrap(client)
    _paid(amount=250)
    subs.record_event(
        kind=subs.KIND_REFUND, charge_id=CHARGE, user_id=ALICE, amount=250,
    )

    assert "0 ⭐" in client.get("/subscriptions").text


def test_page_is_owner_only():
    """Деньги — уровень секретов и пользователей, а не редактора контента."""
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_sub", role=access.ROLE_EDITOR,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login", data={"username": "editor_sub", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/subscriptions").status_code == 403


# --- возврат ---


def test_refund_returns_money_and_revokes_access(_engage_bot):
    client = _client()
    _bootstrap(client)
    _paid()

    response = client.post(
        f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False,
    )

    assert response.status_code == 303
    assert _engage_bot.refund_star_payment.await_count == 1
    view = subs.get(CHAT, ALICE)
    assert view is not None and view.status == subs.STATUS_REFUNDED


def test_refund_also_removes_from_the_channel(_engage_bot):
    """Джоба закрытия берёт только активные по сроку — возвращённого она
    не увидит, и он остался бы в канале навсегда с возвращёнными деньгами."""
    client = _client()
    _bootstrap(client)
    _paid()

    client.post(f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False)

    assert _engage_bot.ban_chat_member.await_count == 1
    assert _engage_bot.unban_chat_member.await_count == 1


def test_refund_subtracts_the_original_amount(_engage_bot):
    """Ноль вместо суммы оставил бы выручку завышенной ровно на неё."""
    client = _client()
    _bootstrap(client)
    _paid(amount=250)

    client.post(f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False)

    assert subs.revenue_stars() == 0


def test_failed_refund_keeps_access(_engage_bot):
    """САМАЯ ВАЖНАЯ ГРАНИЦА.

    Telegram отказал — значит денег человек не получил. Закрыть доступ
    здесь означало бы оставить его и без канала, и без денег.
    """
    client = _client()
    _bootstrap(client)
    _paid()
    _engage_bot.refund_star_payment.side_effect = Exception("Bad Request: charge not found")

    client.post(f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False)

    view = subs.get(CHAT, ALICE)
    assert view is not None and view.is_active


def test_refund_without_payment_is_refused(_engage_bot):
    client = _client()
    _bootstrap(client)

    response = client.post(
        f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False,
    )

    assert response.status_code == 303
    assert _engage_bot.refund_star_payment.await_count == 0


def test_money_returned_even_if_removal_fails(_engage_bot):
    """Деньги уже ушли обратно — откатывать это нельзя, но сказать надо."""
    client = _client()
    _bootstrap(client)
    _paid()
    _engage_bot.ban_chat_member.side_effect = Exception("not enough rights")

    client.post(f"/subscriptions/{CHAT}/{ALICE}/refund", follow_redirects=False)

    view = subs.get(CHAT, ALICE)
    assert view is not None and view.status == subs.STATUS_REFUNDED


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    _paid()

    client.get(f"/lang/{lang}?next=/subscriptions", follow_redirects=False)
    response = client.get("/subscriptions")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)

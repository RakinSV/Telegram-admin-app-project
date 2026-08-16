"""Платный доступ по подписке Stars (F49) — ядро.

Ошибка здесь стоит денег, а не неловкости: лишнее продление — месяц
бесплатного доступа, пропущенное — человек заплатил и остался за дверью.
Поэтому тесты в основном про идемпотентность и про границу закрытия
доступа, а не про то, что строки пишутся в базу.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import subscriptions_repo as subs
from tg_repost.db.models import ChannelSubscription, PaymentEvent
from tg_repost.db.session import session_scope

CHAT = -1005000
ALICE = 9001
BOB = 9002
CHARGE = "charge_abc"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()

    _wipe()
    yield
    _wipe()


# --- идемпотентность ---


def test_same_payment_twice_is_recorded_once():
    """ГЛАВНАЯ ЗАЩИТА ФИЧИ.

    Апдейт об оплате приходит дважды: переподключение, ретрай, перезапуск
    бота с недоставленной очередью. Второй раз ничего менять нельзя.
    """
    end = _now() + timedelta(days=30)

    first = subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE, period_end=end,
    )
    second = subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE, period_end=end,
    )

    assert first is True
    assert second is False
    with session_scope() as session:
        assert session.query(PaymentEvent).count() == 1


def test_renewal_with_new_period_is_a_new_fact():
    """Продление — новый факт, даже если Telegram повторил тот же charge_id.

    Достоверно неизвестно, меняется ли charge_id при продлении; ключ из
    трёх полей верен при обоих ответах.
    """
    first_end = _now() + timedelta(days=30)
    second_end = first_end + timedelta(days=30)

    subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE, period_end=first_end,
    )
    renewal = subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE, period_end=second_end,
    )

    assert renewal is True


def test_renewal_with_new_charge_id_is_a_new_fact():
    end = _now() + timedelta(days=30)
    subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE, period_end=end,
    )

    assert subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id="charge_2", user_id=ALICE, period_end=end,
    ) is True


def test_one_off_payments_are_deduplicated_too():
    """Разовый платёж БЕЗ срока — самая коварная дыра.

    Если бы `period_end` был NULL, уникальность бы не сработала: в SQL
    NULL != NULL, и дубли прошли бы насквозь.
    """
    first = subs.record_event(kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE)
    second = subs.record_event(kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE)

    assert (first, second) == (True, False)


def test_refund_of_the_same_charge_is_a_separate_fact():
    """Возврат и оплата — разные события с одним charge_id."""
    subs.record_event(kind=subs.KIND_PAYMENT, charge_id=CHARGE, user_id=ALICE)

    assert subs.record_event(
        kind=subs.KIND_REFUND, charge_id=CHARGE, user_id=ALICE,
    ) is True


def test_repeated_refund_is_rejected():
    subs.record_event(kind=subs.KIND_REFUND, charge_id=CHARGE, user_id=ALICE)

    assert subs.record_event(
        kind=subs.KIND_REFUND, charge_id=CHARGE, user_id=ALICE,
    ) is False


# --- выдача и продление доступа ---


def test_grant_creates_active_subscription():
    view = subs.grant(
        chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=30),
        invite_link="https://t.me/+abc",
    )

    assert view.is_active is True
    assert view.invite_link == "https://t.me/+abc"


def test_renewal_does_not_create_second_row():
    """Одна строка на пару (канал, человек): иначе история рассыплется."""
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=30))
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=60))

    assert len(subs.list_all(chat_id=CHAT)) == 1


def test_renewal_sets_the_date_from_telegram_not_sum():
    """Сроки НЕ суммируются: период считает Telegram, наша арифметика
    поверх него рано или поздно разойдётся с тем, что видит человек."""
    first = _now() + timedelta(days=30)
    second = _now() + timedelta(days=45)
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=first)

    view = subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=second)

    assert abs((view.paid_until - second).total_seconds()) < 2


def test_regranting_clears_revocation():
    """Человек вернулся и заплатил снова — доступ должен ожить."""
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() - timedelta(days=1))
    subs.mark_revoked(CHAT, ALICE)

    view = subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=30))

    assert view.status == subs.STATUS_ACTIVE


# --- закрытие доступа ---


def test_expired_subscription_is_due_for_revoke():
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=_now() - timedelta(hours=subs.KICK_GRACE_HOURS + 1),
    )

    assert [v.user_id for v in subs.due_for_revoke()] == [ALICE]


def test_grace_period_protects_a_late_renewal():
    """ВАЖНАЯ ГРАНИЦА.

    Продление приходит отдельным апдейтом и может опоздать на минуты.
    Выкинуть заплатившего и позвать обратно через пять минут — хуже, чем
    подождать.
    """
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=_now() - timedelta(hours=max(1, subs.KICK_GRACE_HOURS - 1)),
    )

    assert subs.due_for_revoke() == []


def test_active_subscription_is_not_due():
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=5))

    assert subs.due_for_revoke() == []


def test_revoked_subscription_is_not_returned_again():
    """Иначе человека выкидывало бы на каждом проходе джобы."""
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=_now() - timedelta(hours=subs.KICK_GRACE_HOURS + 1),
    )
    subs.mark_revoked(CHAT, ALICE)

    assert subs.due_for_revoke() == []


def test_revoking_twice_reports_nothing_to_do():
    subs.grant(chat_id=CHAT, user_id=ALICE, paid_until=_now() + timedelta(days=1))

    assert subs.mark_revoked(CHAT, ALICE) is True
    assert subs.mark_revoked(CHAT, ALICE) is False


def test_subscriptions_of_different_people_are_independent():
    subs.grant(
        chat_id=CHAT, user_id=ALICE,
        paid_until=_now() - timedelta(hours=subs.KICK_GRACE_HOURS + 1),
    )
    subs.grant(chat_id=CHAT, user_id=BOB, paid_until=_now() + timedelta(days=10))

    assert [v.user_id for v in subs.due_for_revoke()] == [ALICE]


# --- деньги ---


def test_revenue_counts_payments_and_subtracts_refunds():
    """Считается ПО ЖУРНАЛУ: подписка знает состояние, а деньги — это
    последовательность фактов."""
    subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id="a", user_id=ALICE, amount=100,
    )
    subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id="b", user_id=BOB, amount=250,
    )
    subs.record_event(
        kind=subs.KIND_REFUND, charge_id="a", user_id=ALICE, amount=100,
    )

    assert subs.revenue_stars() == 250


def test_history_is_newest_first():
    subs.record_event(kind=subs.KIND_PAYMENT, charge_id="a", user_id=ALICE, amount=10)
    subs.record_event(kind=subs.KIND_PAYMENT, charge_id="b", user_id=ALICE, amount=20)

    rows = subs.history(ALICE)

    assert [r.charge_id for r in rows] == ["b", "a"]

"""Партнёрские начисления поверх рефералов (F67).

Тесты стоят не на арифметике процента, а на трёх местах, где партнёрская
программа обычно течёт: возврат платежа, самоприглашение и повторная
обработка того же платежа. Каждое из них — прямой убыток владельца.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tg_repost import affiliate_repo, subscriptions_repo as subs
from tg_repost.db.models import AffiliateReward, PaymentEvent, Referral
from tg_repost.db.session import session_scope

PARTNER = 9401
PAYER = 9402
CHAT = -1005000


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(AffiliateReward).delete()
            session.query(PaymentEvent).delete()
            session.query(Referral).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _percent_30(monkeypatch):
    monkeypatch.setattr(affiliate_repo, "_percent", lambda: 30)


def _referral(inviter: int = PARTNER, invited: int = PAYER, *, confirmed: bool = True):
    with session_scope() as session:
        session.add(Referral(
            inviter_user_id=inviter,
            invited_user_id=invited,
            chat_id=CHAT,
            joined_at=datetime.now(timezone.utc) - timedelta(days=10),
            first_message_at=datetime.now(timezone.utc) - timedelta(days=9),
            confirmed_at=datetime.now(timezone.utc) if confirmed else None,
        ))


def _payment(user_id: int = PAYER, amount: int = 100, charge: str = "ch1") -> int:
    event_id = subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id=charge, user_id=user_id,
        chat_id=CHAT, amount=amount,
    )
    assert event_id is not None
    return event_id


# --- начисление ---


def test_confirmed_referral_earns_commission(_percent_30):
    _referral()

    assert affiliate_repo.accrue_for_payment(_payment(amount=100)) == 30
    assert affiliate_repo.balance_of(PARTNER).owed == 30


def test_unconfirmed_referral_earns_nothing(_percent_30):
    """Без подтверждения (F42) комиссия шла бы за аккаунт, который зашёл по
    ссылке и тут же исчез."""
    _referral(confirmed=False)

    assert affiliate_repo.accrue_for_payment(_payment()) == 0


def test_payment_without_referral_earns_nothing(_percent_30):
    assert affiliate_repo.accrue_for_payment(_payment()) == 0


def test_self_referral_earns_nothing(_percent_30):
    """ТЕЧЬ ВТОРАЯ.

    Второй аккаунт, приглашённый самим собой, превращает комиссию в скидку.
    """
    _referral(inviter=PAYER, invited=PAYER)

    assert affiliate_repo.accrue_for_payment(_payment()) == 0


def test_zero_percent_disables_the_programme(monkeypatch):
    """Комиссия по умолчанию означала бы раздачу доли выручки без решения
    владельца."""
    monkeypatch.setattr(affiliate_repo, "_percent", lambda: 0)
    _referral()

    assert affiliate_repo.accrue_for_payment(_payment()) == 0


def test_same_payment_accrues_once(_percent_30):
    """ТЕЧЬ ТРЕТЬЯ: повторная обработка того же платежа."""
    _referral()
    event_id = _payment()

    first = affiliate_repo.accrue_for_payment(event_id)
    second = affiliate_repo.accrue_for_payment(event_id)

    assert (first, second) == (30, 0)
    assert affiliate_repo.balance_of(PARTNER).owed == 30


def test_refund_event_is_not_a_payment(_percent_30):
    """Комиссия с возврата — начисление за то, что деньги ушли обратно."""
    _referral()
    event_id = subs.record_event(
        kind=subs.KIND_REFUND, charge_id="ch1", user_id=PAYER, amount=100,
    )

    assert affiliate_repo.accrue_for_payment(event_id) == 0


def test_percent_is_frozen_on_the_accrual(_percent_30, monkeypatch):
    """Настройку поменяют, а прошлые начисления должны остаться объяснимыми."""
    _referral()
    affiliate_repo.accrue_for_payment(_payment(amount=100))
    monkeypatch.setattr(affiliate_repo, "_percent", lambda: 5)

    rows = affiliate_repo.history(PARTNER)

    assert rows[0].percent == 30


def test_tiny_payment_rounds_to_zero_and_is_skipped(_percent_30):
    """Начисление в ноль звёзд — строка в журнале, которая ничего не значит."""
    _referral()

    assert affiliate_repo.accrue_for_payment(_payment(amount=3)) == 0


# --- возврат ---


def test_refund_reverses_the_accrual(_percent_30):
    """ТЕЧЬ ПЕРВАЯ, САМАЯ ДОРОГАЯ.

    Человек платит 100, партнёр получает 30, человек возвращает деньги — и
    у владельца минус 30 из воздуха.
    """
    _referral()
    event_id = _payment(amount=100)
    affiliate_repo.accrue_for_payment(event_id)

    assert affiliate_repo.reverse_for_payment(event_id) == 30
    assert affiliate_repo.balance_of(PARTNER).owed == 0


def test_reversal_is_recorded_not_deleted(_percent_30):
    """Партнёр должен видеть, что и почему у него забрали."""
    _referral()
    event_id = _payment()
    affiliate_repo.accrue_for_payment(event_id)
    affiliate_repo.reverse_for_payment(event_id)

    kinds = [r.kind for r in affiliate_repo.history(PARTNER)]

    assert affiliate_repo.KIND_ACCRUAL in kinds
    assert affiliate_repo.KIND_REVERSAL in kinds


def test_double_reversal_takes_money_once(_percent_30):
    _referral()
    event_id = _payment()
    affiliate_repo.accrue_for_payment(event_id)
    affiliate_repo.reverse_for_payment(event_id)

    assert affiliate_repo.reverse_for_payment(event_id) == 0
    assert affiliate_repo.balance_of(PARTNER).owed == 0


def test_reversal_without_accrual_does_nothing(_percent_30):
    assert affiliate_repo.reverse_for_payment(_payment()) == 0


# --- выплаты ---


def test_payout_reduces_the_debt(_percent_30):
    _referral()
    affiliate_repo.accrue_for_payment(_payment(amount=100))

    assert affiliate_repo.record_payout(PARTNER, 30) is True
    balance = affiliate_repo.balance_of(PARTNER)
    assert balance.earned == 30
    assert balance.owed == 0


def test_payout_larger_than_debt_is_refused(_percent_30):
    """Запись выплаты больше заработанного — неправда в истории, которую
    потом никто не распутает."""
    _referral()
    affiliate_repo.accrue_for_payment(_payment(amount=100))

    assert affiliate_repo.record_payout(PARTNER, 500) is False
    assert affiliate_repo.balance_of(PARTNER).owed == 30


def test_payout_after_refund_respects_the_reversal(_percent_30):
    """Возврат уменьшает долг: выплачивать снятое нельзя."""
    _referral()
    event_id = _payment(amount=100)
    affiliate_repo.accrue_for_payment(event_id)
    affiliate_repo.reverse_for_payment(event_id)

    assert affiliate_repo.record_payout(PARTNER, 30) is False


def test_zero_payout_is_refused():
    assert affiliate_repo.record_payout(PARTNER, 0) is False


def test_partners_are_sorted_by_earnings(_percent_30):
    _referral(inviter=PARTNER, invited=PAYER)
    _referral(inviter=9403, invited=9404)
    affiliate_repo.accrue_for_payment(_payment(user_id=PAYER, amount=100, charge="a"))
    affiliate_repo.accrue_for_payment(
        _payment(user_id=9404, amount=1000, charge="b")
    )

    assert [p.partner_user_id for p in affiliate_repo.partners()] == [9403, PARTNER]


def test_total_owed_ignores_negative_balances(_percent_30):
    """Переплаченный партнёр не должен уменьшать общий долг остальным."""
    _referral()
    affiliate_repo.accrue_for_payment(_payment(amount=100))

    assert affiliate_repo.total_owed() == 30


# --- связь с платежами ---


def test_payment_flow_accrues_through_the_handler(_percent_30):
    """Начисление должно происходить само, а не по отдельной команде."""
    from engage.handlers import subscription

    _referral()
    event_id = subs.record_event(
        kind=subs.KIND_PAYMENT, charge_id="flow", user_id=PAYER,
        chat_id=CHAT, amount=200,
    )
    assert event_id is not None
    affiliate_repo.accrue_for_payment(event_id)

    assert affiliate_repo.balance_of(PARTNER).owed == 60
    assert subscription.PAYLOAD_PREFIX == "sub"


def test_partner_of_returns_none_for_unknown(_percent_30):
    assert affiliate_repo.partner_of(SimpleNamespace(id=1).id) is None

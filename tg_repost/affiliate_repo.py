"""Партнёрские начисления поверх рефералов (F67).

F42 УЖЕ СДЕЛАЛ СЛОЖНУЮ ЧАСТЬ. Реферал засчитывается, только когда
приглашённый вступил, написал хотя бы раз и прожил N дней. Здесь остаётся
надстроить деньги — и главное тут не арифметика процента, а три места, где
партнёрская программа обычно течёт.

ТЕЧЬ ПЕРВАЯ: ВОЗВРАТ. Человек платит 100 звёзд, партнёр получает 30,
человек возвращает деньги — и у владельца минус 30 из воздуха. Поэтому
возврат ОБЯЗАН отменять начисление, и отмена делается тем же журналом
отрицательной строкой, а не удалением: удалённая история не объясняет
партнёру, куда делись его деньги.

ТЕЧЬ ВТОРАЯ: САМОПРИГЛАШЕНИЕ. Второй аккаунт, приглашённый самим собой,
превращает комиссию в скидку. Начисление на самого себя не делается никогда,
даже если реферал прошёл все проверки F42.

ТЕЧЬ ТРЕТЬЯ: ПОВТОР. Тот же платёжный апдейт может прийти дважды — как и в
F49, ключ идемпотентности стоит в базе, а не только в коде.

БАЛАНС — ЭТО СУММА СТРОК, А НЕ ПОЛЕ. Поле пришлось бы менять при каждой
оплате, возврате и выплате; потерянная правка разошлась бы с историей
навсегда, а сумму пересчитать можно всегда.

ВЫПЛАТЫ — ВРУЧНУЮ, И ЭТО НЕ НЕДОДЕЛКА. Telegram не даёт боту переводить
звёзды другому человеку: вывод идёт через Fragment на кошелёк владельца.
Значит система может честно посчитать, сколько партнёр заработал, и
записать факт выплаты — но не может её провести. Рисовать кнопку «выплатить»,
которая ничего не переводит, было бы враньём.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from tg_repost.db.models import AffiliateReward, PaymentEvent, Referral
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

KIND_ACCRUAL = "accrual"
KIND_REVERSAL = "reversal"
KIND_PAYOUT = "payout"


@dataclass(frozen=True)
class PartnerBalance:
    partner_user_id: int
    earned: int
    paid_out: int

    @property
    def owed(self) -> int:
        return self.earned - self.paid_out


def _percent() -> int:
    from tg_repost.config import get_settings

    return max(0, min(100, getattr(get_settings(), "affiliate_percent", 0)))


def partner_of(user_id: int) -> int | None:
    """Кто привёл этого человека. `None` — никто или реферал не подтверждён.

    Подтверждение (F42) обязательно: без него комиссия начислялась бы за
    аккаунт, который зашёл по ссылке и тут же исчез.
    """
    with session_scope() as session:
        row = (
            session.query(Referral)
            .filter(
                Referral.invited_user_id == user_id,
                Referral.confirmed_at.isnot(None),
            )
            .first()
        )
        return row.inviter_user_id if row is not None else None


def accrue_for_payment(payment_event_id: int) -> int:
    """Начислить комиссию за платёж. Возвращает начисленное (0 — не за что).

    Ноль возвращается во всех случаях, когда начислять НЕ НАДО, и это не
    ошибка: программа выключена, приведшего нет, реферал не подтверждён,
    человек привёл сам себя, комиссия округлилась в ноль.
    """
    percent = _percent()
    if percent <= 0:
        return 0

    with session_scope() as session:
        payment = session.get(PaymentEvent, payment_event_id)
        if payment is None or payment.kind != "payment" or payment.amount <= 0:
            return 0
        payer_id = payment.user_id
        amount = payment.amount

    partner_id = partner_of(payer_id)
    if partner_id is None:
        return 0
    if partner_id == payer_id:
        # Самоприглашение превращает комиссию в скидку.
        logger.warning("F67: %s привёл сам себя — комиссия не начислена", payer_id)
        return 0

    reward = amount * percent // 100
    if reward <= 0:
        return 0

    try:
        with session_scope() as session:
            session.add(AffiliateReward(
                kind=KIND_ACCRUAL,
                partner_user_id=partner_id,
                payer_user_id=payer_id,
                payment_event_id=payment_event_id,
                amount=reward,
                percent=percent,
            ))
    except IntegrityError:
        logger.info("F67: начисление за платёж #%d уже было", payment_event_id)
        return 0

    logger.info(
        "F67: партнёру %s начислено %d ⭐ (%d%% от %d) за %s",
        partner_id, reward, percent, amount, payer_id,
    )
    return reward


def reverse_for_payment(payment_event_id: int) -> int:
    """Отменить начисление при возврате. Возвращает снятое.

    Отмена — отрицательная строка, а не удаление: партнёр должен видеть, что
    именно и почему у него забрали, иначе первый же возврат превращается в
    спор без доказательств.
    """
    with session_scope() as session:
        accrual = (
            session.query(AffiliateReward)
            .filter(
                AffiliateReward.payment_event_id == payment_event_id,
                AffiliateReward.kind == KIND_ACCRUAL,
            )
            .first()
        )
        if accrual is None:
            return 0
        partner_id = accrual.partner_user_id
        payer_id = accrual.payer_user_id
        amount = accrual.amount
        percent = accrual.percent

    try:
        with session_scope() as session:
            session.add(AffiliateReward(
                kind=KIND_REVERSAL,
                partner_user_id=partner_id,
                payer_user_id=payer_id,
                payment_event_id=payment_event_id,
                amount=-amount,
                percent=percent,
                note="возврат платежа",
            ))
    except IntegrityError:
        return 0

    logger.info("F67: с партнёра %s снято %d ⭐ (возврат)", partner_id, amount)
    return amount


def record_payout(partner_user_id: int, amount: int, note: str | None = None) -> bool:
    """Отметить выплату партнёру. Деньги переводятся ВНЕ системы.

    Telegram не даёт боту переслать звёзды человеку, поэтому здесь только
    запись факта. Сумма проверяется по долгу: записать выплату больше
    заработанного значит внести в историю неправду, которую потом никто не
    распутает.
    """
    if amount <= 0:
        return False
    balance = balance_of(partner_user_id)
    if amount > balance.owed:
        logger.warning(
            "F67: выплата %d ⭐ больше долга %d ⭐ партнёру %s — отклонена",
            amount, balance.owed, partner_user_id,
        )
        return False

    with session_scope() as session:
        session.add(AffiliateReward(
            kind=KIND_PAYOUT,
            partner_user_id=partner_user_id,
            amount=-amount,
            note=note,
        ))
    logger.info("F67: выплата %d ⭐ партнёру %s записана", amount, partner_user_id)
    return True


def balance_of(partner_user_id: int) -> PartnerBalance:
    with session_scope() as session:
        rows = (
            session.query(AffiliateReward)
            .filter(AffiliateReward.partner_user_id == partner_user_id)
            .all()
        )
    earned = sum(r.amount for r in rows if r.kind in (KIND_ACCRUAL, KIND_REVERSAL))
    paid = sum(-r.amount for r in rows if r.kind == KIND_PAYOUT)
    return PartnerBalance(
        partner_user_id=partner_user_id, earned=earned, paid_out=paid,
    )


def partners() -> list[PartnerBalance]:
    """Все партнёры с ненулевой историей, самые заработавшие сверху."""
    with session_scope() as session:
        ids = {
            row.partner_user_id
            for row in session.query(AffiliateReward.partner_user_id).all()
        }
    balances = [balance_of(pid) for pid in ids]
    return sorted(balances, key=lambda b: b.earned, reverse=True)


def history(partner_user_id: int, limit: int = 100) -> list[AffiliateReward]:
    with session_scope() as session:
        rows = (
            session.query(AffiliateReward)
            .filter(AffiliateReward.partner_user_id == partner_user_id)
            .order_by(AffiliateReward.created_at.desc(), AffiliateReward.id.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def total_owed(since: datetime | None = None) -> int:
    """Сколько всего должны партнёрам — для сводки владельцу."""
    del since  # долг не зависит от периода: он либо выплачен, либо нет
    return sum(max(0, b.owed) for b in partners())

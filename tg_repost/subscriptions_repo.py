"""Платный доступ по подписке Telegram Stars (F49).

ЧТО ДЕЛАЕТ TELEGRAM, А ЧТО МЫ. Платёжный контур — целиком Telegram: он
принимает звёзды, сам списывает следующий период и сам решает, когда
подписка кончилась. Наша часть — обвязка: выдать доступ, снять доступ,
связать оплату с человеком в CRM. Именно этого у конкурентов нет, а приём
денег писать не нужно.

ЖУРНАЛ ФАКТОВ ВМЕСТО ПОЛЯ СОСТОЯНИЯ. Оплата приходит апдейтом, а апдейт
может продублироваться: переподключение, ретрай, перезапуск бота с
недоставленной очередью. «Выдать доступ, если статус не активен» на повторе
выдаст его дважды и продлит срок бесплатно. Поэтому каждый платёжный факт
сначала кладётся в append-only журнал, и только НОВЫЙ факт что-то меняет.

ОШИБКА ЗДЕСЬ СТОИТ ДЕНЕГ, А НЕ НЕЛОВКОСТИ. В рассылке лишнее сообщение —
досадно; в платежах лишнее продление — это месяц бесплатного доступа, а
пропущенное — человек заплатил и остался за дверью. Поэтому проверки
двойные: сначала в коде, потом ограничением в базе.

⚠️ НЕ ПРОВЕРЕНО НА ЖИВЫХ ПЛАТЕЖАХ. Ни один из сценариев ниже не прогонялся
против настоящего Telegram: для этого нужен бот, подписка и настоящие
звёзды. Поведение платёжного API взято из документации, а не подтверждено
опытом. Главная неизвестная — меняется ли `telegram_payment_charge_id` при
продлении; ключ идемпотентности собран так, чтобы работать при обоих
ответах (см. `PaymentEvent`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from tg_repost.db.models import ChannelSubscription, PaymentEvent
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

KIND_PAYMENT = "payment"
KIND_REFUND = "refund"
KIND_CANCELED = "canceled"

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_CANCELED = "canceled"
STATUS_REFUNDED = "refunded"

CURRENCY = "XTR"

# Заглушка для платежей без срока (разовых). Не NULL — потому что в SQL
# уникальность на NULL не срабатывает, и дубли проходили бы насквозь.
NO_PERIOD = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Запас перед закрытием доступа. Продление приходит отдельным апдейтом и
# может опоздать на минуты: выкинуть человека, который заплатил, и позвать
# обратно через пять минут — хуже, чем подождать.
KICK_GRACE_HOURS = 6


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite отдаёт наивные метки — сравнение с aware упало бы."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SubscriptionView:
    chat_id: int
    user_id: int
    status: str
    paid_until: datetime
    invite_link: str | None
    charge_id: str | None

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE and self.paid_until > _utcnow()


def _view(row: ChannelSubscription) -> SubscriptionView:
    return SubscriptionView(
        chat_id=row.chat_id,
        user_id=row.user_id,
        status=row.status,
        paid_until=_aware(row.paid_until),  # type: ignore[arg-type]
        invite_link=row.invite_link,
        charge_id=row.charge_id,
    )


def record_event(
    *,
    kind: str,
    charge_id: str,
    user_id: int,
    period_end: datetime | None = None,
    chat_id: int | None = None,
    amount: int = 0,
    invoice_payload: str | None = None,
    is_recurring: bool = False,
    is_first_recurring: bool = False,
) -> int | None:
    """Записать платёжный факт. `None` — такой факт уже был.

    Возвращаемое значение — ЕДИНСТВЕННОЕ основание что-то менять. Вызывающий
    обязан ничего не делать при `None`, иначе идемпотентность бессмысленна.

    Возвращается именно ID записи, а не «да/нет»: к платёжному факту
    привязываются партнёрские начисления (F67), и без его идентификатора
    повторная обработка начислила бы комиссию второй раз.
    """
    end = period_end or NO_PERIOD
    try:
        with session_scope() as session:
            row = PaymentEvent(
                kind=kind,
                charge_id=charge_id,
                user_id=user_id,
                chat_id=chat_id,
                amount=amount,
                currency=CURRENCY,
                invoice_payload=invoice_payload,
                is_recurring=is_recurring,
                is_first_recurring=is_first_recurring,
                period_end=end,
            )
            session.add(row)
            session.flush()
            return row.id
    except IntegrityError:
        # Ограничение в базе — вторая линия защиты. Первой (проверкой перед
        # вставкой) обойтись нельзя: между проверкой и вставкой помещается
        # вторая доставка того же апдейта.
        logger.info(
            "F49: повторный платёжный факт %s/%s — пропущен", kind, charge_id,
        )
        return None


def grant(
    *,
    chat_id: int,
    user_id: int,
    paid_until: datetime,
    charge_id: str | None = None,
    invite_link: str | None = None,
) -> SubscriptionView:
    """Выдать или продлить доступ.

    Продление НЕ СУММИРУЕТ сроки, а ставит дату, присланную Telegram: он
    считает период сам, и наша арифметика поверх неё рано или поздно
    разошлась бы с тем, что видит человек в интерфейсе Telegram.
    """
    with session_scope() as session:
        row = (
            session.query(ChannelSubscription)
            .filter(
                ChannelSubscription.chat_id == chat_id,
                ChannelSubscription.user_id == user_id,
            )
            .first()
        )
        if row is None:
            row = ChannelSubscription(chat_id=chat_id, user_id=user_id)
            session.add(row)
        row.status = STATUS_ACTIVE
        row.paid_until = paid_until
        row.revoked_at = None
        if charge_id:
            row.charge_id = charge_id
        if invite_link:
            row.invite_link = invite_link
        session.flush()
        return _view(row)


def get(chat_id: int, user_id: int) -> SubscriptionView | None:
    with session_scope() as session:
        row = (
            session.query(ChannelSubscription)
            .filter(
                ChannelSubscription.chat_id == chat_id,
                ChannelSubscription.user_id == user_id,
            )
            .first()
        )
        return _view(row) if row is not None else None


def list_all(chat_id: int | None = None, status: str | None = None) -> list[SubscriptionView]:
    with session_scope() as session:
        query = session.query(ChannelSubscription)
        if chat_id is not None:
            query = query.filter(ChannelSubscription.chat_id == chat_id)
        if status is not None:
            query = query.filter(ChannelSubscription.status == status)
        rows = query.order_by(ChannelSubscription.paid_until.desc()).all()
        return [_view(row) for row in rows]


def due_for_revoke(now: datetime | None = None) -> list[SubscriptionView]:
    """Кому пора закрыть доступ.

    Отсчёт от `paid_until` плюс запас: продление приходит отдельным апдейтом
    и может опоздать. Возвращаются только активные — уже закрытые не должны
    выкидываться повторно при каждом проходе.
    """
    moment = (now or _utcnow()) - timedelta(hours=KICK_GRACE_HOURS)
    with session_scope() as session:
        rows = (
            session.query(ChannelSubscription)
            .filter(
                ChannelSubscription.status == STATUS_ACTIVE,
                ChannelSubscription.paid_until < moment,
            )
            .order_by(ChannelSubscription.paid_until.asc())
            .all()
        )
        return [_view(row) for row in rows]


def mark_revoked(chat_id: int, user_id: int, *, status: str = STATUS_EXPIRED) -> bool:
    with session_scope() as session:
        row = (
            session.query(ChannelSubscription)
            .filter(
                ChannelSubscription.chat_id == chat_id,
                ChannelSubscription.user_id == user_id,
            )
            .first()
        )
        if row is None or row.status != STATUS_ACTIVE:
            return False
        row.status = status
        row.revoked_at = _utcnow()
        logger.info(
            "F49: доступ закрыт (%s) для %s в %s", status, user_id, chat_id,
        )
        return True


async def refund(chat_id: int, user_id: int) -> tuple[bool, str]:
    """Вернуть деньги за подписку и закрыть доступ. `(успех, объяснение)`.

    ВОЗВРАЩАЕТ ТОТ ЖЕ БОТ, КОТОРЫЙ ПОЛУЧИЛ ПЛАТЁЖ. `refundStarPayment`
    привязан к токену: платил человек боту Engage, значит и возврат идёт
    через него, а не через бота модерации. Веб-процесс поднимает его на один
    вызов — тот же приём, что у ответов поддержки (F68).

    ПОРЯДОК: сначала деньги, потом доступ. Закрыть доступ и не вернуть
    деньги — худший из исходов: человек остался и без канала, и без денег.
    Обратный порядок в худшем случае оставляет оплаченный доступ у того,
    кому уже вернули, — это чинится вторым нажатием.
    """
    view = get(chat_id, user_id)
    if view is None or not view.charge_id:
        return False, "Нечего возвращать: платёж не найден."

    from engage.bot import build_reply_bot

    bot = build_reply_bot()
    if bot is None:
        return False, "Не настроен токен Engage — возврат делает тот же бот, что принял оплату."

    removed = True
    try:
        await bot.refund_star_payment(
            user_id=user_id, telegram_payment_charge_id=view.charge_id,
        )
        # Доступ снимается ЗДЕСЬ, а не джобой: та забирает только активные
        # подписки по сроку, а у возвращённой статус другой и срок ещё не
        # вышел — человек остался бы в канале навсегда с возвращёнными
        # деньгами.
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.unban_chat_member(
                chat_id=chat_id, user_id=user_id, only_if_banned=True,
            )
        except Exception as exc:  # noqa: BLE001
            removed = False
            logger.warning(
                "F49: деньги возвращены, но выгнать %s из %s не вышло: %s",
                user_id, chat_id, exc,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("F49: возврат %s не прошёл: %s", view.charge_id, exc)
        return False, f"Telegram отказал в возврате: {exc}"
    finally:
        await bot.session.close()

    # Сумма берётся из ИСХОДНОГО платежа: иначе выручка после возврата
    # осталась бы завышенной ровно на эту сумму.
    refunded = _paid_amount(view.charge_id)
    # Факт возврата — такая же запись в журнале, как оплата. Повторное
    # нажатие её не задвоит: ключ идемпотентности тот же.
    record_event(
        kind=KIND_REFUND,
        charge_id=view.charge_id,
        user_id=user_id,
        chat_id=chat_id,
        amount=refunded,
        period_end=view.paid_until,
    )
    # F67: партнёрская комиссия с возвращённого платежа ОБЯЗАНА сняться.
    # Иначе человек платит 100, партнёр получает 30, человек возвращает
    # деньги — и у владельца минус 30 из воздуха.
    from tg_repost import affiliate_repo

    payment_id = _payment_event_id(view.charge_id)
    if payment_id is not None:
        affiliate_repo.reverse_for_payment(payment_id)
    mark_revoked(chat_id, user_id, status=STATUS_REFUNDED)
    logger.info("F49: возврат по %s (%d ⭐), доступ закрыт", view.charge_id, refunded)
    if not removed:
        return True, "Деньги возвращены, но из канала выйти не удалось — проверьте права бота."
    return True, "Деньги возвращены, доступ закрыт."


def _last_payment(charge_id: str) -> PaymentEvent | None:
    with session_scope() as session:
        row = (
            session.query(PaymentEvent)
            .filter(
                PaymentEvent.charge_id == charge_id,
                PaymentEvent.kind == KIND_PAYMENT,
            )
            .order_by(PaymentEvent.id.desc())
            .first()
        )
        if row is not None:
            session.expunge(row)
        return row


def _paid_amount(charge_id: str) -> int:
    """Сколько было получено по этому платежу — для суммы возврата."""
    row = _last_payment(charge_id)
    return row.amount if row is not None else 0


def _payment_event_id(charge_id: str) -> int | None:
    row = _last_payment(charge_id)
    return row.id if row is not None else None


def history(user_id: int, limit: int = 50) -> list[PaymentEvent]:
    """Платёжная история человека — для карточки в CRM (F63)."""
    with session_scope() as session:
        rows = (
            session.query(PaymentEvent)
            .filter(PaymentEvent.user_id == user_id)
            .order_by(PaymentEvent.created_at.desc(), PaymentEvent.id.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def revenue_stars(since: datetime | None = None) -> int:
    """Сколько звёзд получено. Возвраты вычитаются.

    Считается ПО ЖУРНАЛУ, а не по подпискам: подписка знает только текущее
    состояние, а деньги — это последовательность фактов.
    """
    with session_scope() as session:
        query = session.query(PaymentEvent)
        if since is not None:
            query = query.filter(PaymentEvent.created_at >= since)
        rows = query.all()
    total = 0
    for row in rows:
        if row.kind == KIND_PAYMENT:
            total += row.amount
        elif row.kind == KIND_REFUND:
            total -= row.amount
    return total

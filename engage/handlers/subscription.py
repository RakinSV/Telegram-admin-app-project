"""Платный доступ: счёт, оплата, выдача ссылки (F49).

ПОРЯДОК ШАГОВ ЗАДАЁТ TELEGRAM, И ОН ЖЁСТКИЙ:

1. `/subscribe` → создаём ссылку на счёт (`createInvoiceLink`) с
   `subscription_period` — дальше подписку ведёт Telegram сам;
2. `pre_checkout_query` → **ответить обязательно и в течение 10 секунд**,
   иначе Telegram отменит платёж. Поэтому здесь нет ни походов в сеть, ни
   тяжёлых запросов: только проверка, что канал ещё продаётся;
3. `successful_payment` → записать факт и выдать доступ.

ДОСТУП ВЫДАЁТСЯ ПЕРСОНАЛЬНОЙ ССЫЛКОЙ С ЛИМИТОМ В ОДНО ИСПОЛЬЗОВАНИЕ. Общая
ссылка означала бы, что один оплативший приводит весь чат, и платный доступ
перестаёт быть платным после первого же покупателя.

ПОРЯДОК «СНАЧАЛА ЗАПИСЬ, ПОТОМ ВЫДАЧА» ВАЖЕН. Если сначала выдать ссылку, а
потом упасть на записи, повторная доставка апдейта выдаст вторую ссылку.
Обратный порядок в худшем случае оставит оплату без ссылки — и это чинится
кнопкой «моя ссылка», а лишний доступ не чинится ничем.

⚠️ НЕ ПРОВЕРЕНО ЖИВЫМИ ПЛАТЕЖАМИ: нужен бот, подписка и настоящие звёзды.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from tg_repost import subscriptions_repo as subs
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="subscription")

# Период подписки в секундах. Telegram принимает только 30 суток — это не
# наш выбор и не настройка.
SUBSCRIPTION_PERIOD = 30 * 24 * 60 * 60

PAYLOAD_PREFIX = "sub"


def build_payload(chat_id: int) -> str:
    """`sub:<chat_id>` — по нему платёж сопоставляется с каналом.

    Идентификатор канала кладётся В САМ ПЛАТЁЖ, а не запоминается на стороне
    бота: между показом счёта и оплатой могут пройти сутки и перезапуск.
    """
    return f"{PAYLOAD_PREFIX}:{chat_id}"


def parse_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith(PAYLOAD_PREFIX + ":"):
        return None
    try:
        return int(payload.split(":", 1)[1])
    except ValueError:
        return None


def _plan() -> tuple[int, int, str] | None:
    """Действующий тариф: (chat_id, цена в звёздах, название канала).

    `None` — платный доступ не настроен; тогда команда честно об этом
    говорит, а не показывает счёт в никуда.
    """
    from tg_repost.config import get_settings

    settings = get_settings()
    if not getattr(settings, "paid_access_enabled", False):
        return None
    chat_id = getattr(settings, "paid_access_chat_id", 0)
    price = getattr(settings, "paid_access_price_stars", 0)
    if not chat_id or price <= 0:
        return None
    return chat_id, price, getattr(settings, "paid_access_title", "Закрытый канал")


@router.message(Command("subscribe"))
async def on_subscribe(message: Message, bot: Bot) -> None:
    plan = _plan()
    if plan is None:
        await message.answer("Платный доступ сейчас не настроен.")
        return
    chat_id, price, title = plan
    user = message.from_user
    if user is None:
        return

    current = subs.get(chat_id, user.id)
    if current is not None and current.is_active:
        # Второй счёт активному подписчику — прямой путь к двойному списанию.
        text = "Подписка активна до " + current.paid_until.strftime("%d.%m.%Y")
        if current.invite_link:
            text += f"\n\nВаша ссылка: {current.invite_link}"
        await message.answer(text)
        return

    link = await bot.create_invoice_link(
        title=title,
        description=f"Доступ к «{title}» на 30 дней",
        payload=build_payload(chat_id),
        currency=subs.CURRENCY,
        prices=[LabeledPrice(label=title, amount=price)],
        subscription_period=SUBSCRIPTION_PERIOD,
    )
    await message.answer(
        f"Доступ к «{title}» — {price} ⭐ в месяц.\n"
        "Подписка продлевается автоматически, отменить можно в Telegram.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"Оплатить {price} ⭐", url=link),
        ]]),
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Подтверждение платежа. ОТВЕТИТЬ ОБЯЗАТЕЛЬНО И БЫСТРО.

    Telegram даёт 10 секунд и отменяет платёж молчанием, поэтому здесь нет
    ни сетевых вызовов, ни тяжёлых запросов. Отказ — только когда платить
    заведомо не за что: платный доступ выключен или счёт от чужого канала.
    """
    chat_id = parse_payload(query.invoice_payload)
    plan = _plan()
    if chat_id is None or plan is None or chat_id != plan[0]:
        await query.answer(
            ok=False,
            error_message="Этот доступ больше не продаётся. Деньги не списаны.",
        )
        logger.warning(
            "F49: отклонён pre_checkout от %s, payload=%r",
            query.from_user.id, query.invoice_payload,
        )
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, bot: Bot) -> None:
    payment = message.successful_payment
    user = message.from_user
    if payment is None or user is None:
        return

    chat_id = parse_payload(payment.invoice_payload)
    if chat_id is None:
        logger.error(
            "F49: оплата %s без разбираемого payload %r — доступ не выдан",
            payment.telegram_payment_charge_id, payment.invoice_payload,
        )
        return

    expires = payment.subscription_expiration_date
    period_end = (
        datetime.fromtimestamp(expires, tz=timezone.utc) if expires
        else datetime.now(timezone.utc) + timedelta(seconds=SUBSCRIPTION_PERIOD)
    )

    # СНАЧАЛА ЗАПИСЬ. `None` означает, что этот же апдейт уже обработан, и
    # выдавать доступ второй раз нельзя — см. docstring модуля.
    event_id = subs.record_event(
        kind=subs.KIND_PAYMENT,
        charge_id=payment.telegram_payment_charge_id,
        user_id=user.id,
        chat_id=chat_id,
        amount=payment.total_amount,
        invoice_payload=payment.invoice_payload,
        is_recurring=bool(payment.is_recurring),
        is_first_recurring=bool(payment.is_first_recurring),
        period_end=period_end,
    )
    if event_id is None:
        logger.info("F49: повторный апдейт об оплате от %s — пропущен", user.id)
        return

    # F67: комиссия тому, кто привёл этого человека. Сбой начисления не
    # должен ломать выдачу доступа — человек заплатил за канал, а не за
    # партнёрскую программу.
    try:
        from tg_repost import affiliate_repo

        affiliate_repo.accrue_for_payment(event_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("F67: начисление за платёж #%s не прошло: %s", event_id, exc)

    existing = subs.get(chat_id, user.id)
    invite = existing.invite_link if existing is not None else None
    if invite is None:
        try:
            created = await bot.create_chat_invite_link(
                chat_id=chat_id,
                name=f"sub:{user.id}",
                member_limit=1,
            )
            invite = created.invite_link
        except Exception as exc:  # noqa: BLE001
            # Оплата уже записана — терять её нельзя. Доступ выдаст владелец
            # или повторный запрос ссылки; сообщать человеку «ошибка,
            # платите снова» было бы худшим из возможных ответов.
            logger.error(
                "F49: не удалось создать инвайт для %s в %s: %s",
                user.id, chat_id, exc,
            )

    subs.grant(
        chat_id=chat_id,
        user_id=user.id,
        paid_until=period_end,
        charge_id=payment.telegram_payment_charge_id,
        invite_link=invite,
    )

    if invite:
        await message.answer(
            "Оплата получена. Ваша персональная ссылка (действует один раз):\n"
            f"{invite}\n\n"
            f"Доступ оплачен до {period_end.strftime('%d.%m.%Y')}."
        )
    else:
        await message.answer(
            "Оплата получена, но ссылку выдать не удалось — я уже сообщил "
            "владельцу. Напишите сюда, если она не придёт в ближайшее время."
        )

"""Магазин в боте: витрина, счёт, оплата (F69 + F70).

ДВА ВИДА СЧЕТОВ В ОДНОМ БОТЕ — главная сложность этого файла. Подписка
(F49) идёт за Stars без провайдера, товары — за рубли через провайдера из
@BotFather. Обработчик оплаты у Telegram один на всё, поэтому счета
различаются по ПРЕФИКСУ payload: `sub:` и `ord:`. Перепутать их значило бы
выдать доступ в закрытый канал за оплату кружки.

ПРОВЕРКА ОСТАТКА — В `pre_checkout`. Это единственный момент, когда Telegram
спрашивает нас до списания денег: отказ там человек переживёт, отказ после
оплаты — нет.

АДРЕС ДОСТАВКИ ЗАПРАШИВАЕТ TELEGRAM (`need_shipping_address`), а не мы
отдельным диалогом: свой диалог означал бы четыре сообщения вместо одной
формы, и половина людей отвалилась бы на середине.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from tg_repost import shop_repo as shop
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="shop")


def _enabled() -> bool:
    from tg_repost.config import get_settings

    return bool(getattr(get_settings(), "shop_enabled", False))


def _provider_token() -> str:
    from engage.config import get_engage_settings

    return get_engage_settings().shop_provider_token


def format_shipping(payment) -> str | None:  # noqa: ANN001 — SuccessfulPayment
    """Адрес доставки одной строкой для карточки заказа.

    Хранится текстом, а не разобранным на поля: сортировать по индексу нам
    незачем, а форматы адресов у стран разные, и своя схема быстро начала бы
    терять части чужих адресов.
    """
    info = getattr(payment, "order_info", None)
    if info is None:
        return None
    parts = [getattr(info, "name", None), getattr(info, "phone_number", None)]
    address = getattr(info, "shipping_address", None)
    if address is not None:
        parts.extend([
            getattr(address, "country_code", None),
            getattr(address, "post_code", None),
            getattr(address, "city", None),
            getattr(address, "street_line1", None),
            getattr(address, "street_line2", None),
        ])
    joined = ", ".join(p for p in parts if p)
    return joined or None


@router.message(Command("shop"))
async def on_shop(message: Message) -> None:
    if not _enabled():
        await message.answer("Магазин сейчас закрыт.")
        return

    products = [p for p in shop.list_products(only_active=True) if p.in_stock]
    if not products:
        await message.answer("Пока нечего предложить — товары закончились.")
        return

    await message.answer(
        "Что есть в наличии:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{p.name} — {p.price_human}",
                callback_data=f"buy:{p.id}",
            )]
            for p in products
        ]),
    )


@router.callback_query(F.data.startswith("buy:"))
async def on_buy(callback, bot: Bot) -> None:  # noqa: ANN001 — CallbackQuery
    await callback.answer()
    if not _enabled():
        return
    try:
        product_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return

    product = shop.get_product(product_id)
    if product is None or not product.is_active or not product.in_stock:
        await callback.message.answer("Этого товара уже нет.")
        return

    token = _provider_token()
    if not token:
        # Честный ответ вместо счёта в никуда: без провайдера Telegram
        # счёт просто не примет, и человек увидит непонятную ошибку.
        await callback.message.answer(
            "Оплата пока не настроена — напишите владельцу.",
        )
        logger.warning("F70: SHOP_PROVIDER_TOKEN не задан, счёт не выставлен")
        return

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=product.name,
        description=product.description or product.name,
        payload=shop.build_payload(product.id),
        provider_token=token,
        currency=product.currency,
        prices=[LabeledPrice(label=product.name, amount=product.price)],
        need_name=True,
        need_phone_number=True,
        need_shipping_address=True,
        is_flexible=False,
    )


@router.pre_checkout_query(F.invoice_payload.startswith(shop.PAYLOAD_PREFIX + ":"))
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Последняя проверка перед списанием. Ответить нужно за 10 секунд."""
    product_id = shop.parse_payload(query.invoice_payload)
    if product_id is None or not _enabled():
        await query.answer(ok=False, error_message="Магазин закрыт. Деньги не списаны.")
        return

    ok, reason = shop.can_sell(product_id)
    if not ok:
        await query.answer(ok=False, error_message=f"{reason} Деньги не списаны.")
        logger.info("F69: отказ в оплате товара #%s: %s", product_id, reason)
        return
    await query.answer(ok=True)


@router.message(F.successful_payment.func(
    lambda p: (p.invoice_payload or "").startswith(shop.PAYLOAD_PREFIX + ":")
))
async def on_paid(message: Message) -> None:
    payment = message.successful_payment
    user = message.from_user
    if payment is None or user is None:
        return

    product_id = shop.parse_payload(payment.invoice_payload)
    if product_id is None:
        logger.error(
            "F69: оплата %s с неразбираемым payload %r",
            payment.telegram_payment_charge_id, payment.invoice_payload,
        )
        return

    order = shop.record_paid_order(
        user_id=user.id,
        product_id=product_id,
        amount=payment.total_amount,
        currency=payment.currency,
        charge_id=payment.telegram_payment_charge_id,
        shipping=format_shipping(payment),
    )
    if order is None:
        # Повтор апдейта: заказ уже создан, вторую посылку слать не надо.
        return

    text = f"Заказ №{order.id} оплачен: {order.product_name}, {order.amount_human}."
    if order.is_oversold:
        # Человеку про «продали больше, чем было» знать рано — сначала
        # владелец решит, довезти или вернуть. Но и обещать отправку сегодня
        # нельзя.
        text += "\n\nЯ уточню сроки отправки и напишу."
    await message.answer(text)

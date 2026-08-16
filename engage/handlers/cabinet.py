"""Кнопка открытия личного кабинета — Mini App (F74).

КНОПКИ НЕТ, ПОКА НЕ ЗАДАН АДРЕС, и это не заглушка. Мини-апп требует, чтобы
система была доступна из интернета по HTTPS; пока адреса нет, кнопка вела бы
в никуда, а человек считал бы поломкой бота то, что просто не настроено.

Telegram открывает мини-апп ТОЛЬКО по https и не принимает localhost —
проверить адрес заранее дешевле, чем ловить молчаливое «кнопка не
нажимается».
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="cabinet")


def miniapp_url() -> str:
    """Адрес кабинета или пустая строка, если открывать нечего."""
    from tg_repost.config import get_settings

    url = (getattr(get_settings(), "miniapp_url", "") or "").strip()
    if not url:
        return ""
    if not url.startswith("https://"):
        # Telegram молча не откроет такую кнопку; лучше сказать это в лог,
        # чем оставить владельца гадать.
        logger.warning("F74: MINIAPP_URL должен начинаться с https:// — кнопки не будет")
        return ""
    return url


def cabinet_keyboard(label: str = "Личный кабинет") -> InlineKeyboardMarkup | None:
    url = miniapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url)),
    ]])


@router.message(Command("cabinet"))
async def on_cabinet(message: Message) -> None:
    keyboard = cabinet_keyboard()
    if keyboard is None:
        await message.answer("Личный кабинет пока не настроен.")
        return
    await message.answer(
        "Здесь видно только ваше: подписка, приглашённые вами люди и каталог.",
        reply_markup=keyboard,
    )

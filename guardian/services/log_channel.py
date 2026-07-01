"""Отправка уведомлений о действиях модерации в приватный лог-канал (G08).

Не критичный путь — сбой отправки (канал недоступен/бот не админ там)
логируется и проглатывается, не должен ронять основной пайплайн модерации
(тот же fail-soft паттерн, что и остальной проект)."""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from guardian.config import get_guardian_settings
from guardian.logging_conf import get_logger

logger = get_logger(__name__)

_EMOJI: dict[str, str] = {
    "warn": "⚠️",
    "mute": "🔇",
    "unmute": "🔊",
    "kick": "👢",
    "ban": "🔴",
    "unban": "🟢",
    "delete_msg": "🗑️",
    "verify": "✅",
    "trust": "🤝",
    "untrust": "🚫",
}


async def log_action(
    bot: Bot,
    action: str,
    user_id: int,
    chat_id: int,
    reason: str | None = None,
    username: str | None = None,
    message_text: str | None = None,
    inline_kb: InlineKeyboardMarkup | None = None,
) -> None:
    settings = get_guardian_settings()
    if not settings.guardian_log_channel_id:
        return

    # Бот шлёт с parse_mode=HTML по умолчанию (см. bot.py) — username/reason/
    # message_text все либо напрямую пользовательский ввод, либо построены из
    # него (стоп-слово, домен), поэтому экранируем перед подстановкой, иначе
    # злоумышленник мог бы внедрить HTML-разметку/ссылку в сообщения
    # лог-канала (найдено при security-аудите).
    emoji = _EMOJI.get(action, "ℹ️")
    who = f"@{escape(username)}" if username else f"id{user_id}"
    lines = [f"{emoji} [{action.upper()}] {who} (chat {chat_id})"]
    if reason:
        lines.append(f"Причина: {escape(reason)}")
    if message_text:
        snippet = escape(message_text[:200])
        lines.append(f"Текст: «{snippet}»")

    try:
        await bot.send_message(
            settings.guardian_log_channel_id, "\n".join(lines), reply_markup=inline_kb
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Не удалось записать в лог-канал (action=%s, user=%s): %s",
            action,
            user_id,
            exc,
        )

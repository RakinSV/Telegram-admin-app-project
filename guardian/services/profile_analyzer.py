"""Анализ профиля нового участника (G15) — сигналы подозрительности БЕЗ LLM,
используются, чтобы сделать капчу строже для похожих на бота профилей. НЕ
приводит к бану/автоотказу сам по себе — только усиливает капчу (см.
GUARDIAN_FEATURES.md: "ВАЖНО: не банить только за профиль — это слишком
агрессивно")."""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from guardian.logging_conf import get_logger

logger = get_logger(__name__)

_BIO_SUSPICIOUS_WORDS = ("crypto", "крипто", "заработок", "earn", "invest", "инвест")
# user_id выше этого — аккаунт создан примерно после 2023 (Telegram выдаёт
# id по возрастающей) — НЕ индикатор сам по себе (см. спецификацию), только
# в сумме с другими сигналами.
_NEW_ACCOUNT_ID_THRESHOLD = 7_000_000_000


async def compute_profile_score(bot: Bot, user_id: int, username: str | None) -> int:
    """Сумма сигналов (0-5): нет username +1, новый по id +1, нет фото +1,
    подозрительная био +2. Любая ошибка Bot API по отдельному сигналу не
    прерывает остальные — просто этот сигнал не засчитывается."""
    score = 0
    if not username:
        score += 1
    if user_id > _NEW_ACCOUNT_ID_THRESHOLD:
        score += 1

    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count == 0:
            score += 1
    except TelegramBadRequest as exc:
        logger.debug("G15: не удалось получить фото профиля %s: %s", user_id, exc)

    try:
        chat = await bot.get_chat(user_id)
        bio = (getattr(chat, "bio", None) or "").lower()
        if any(word in bio for word in _BIO_SUSPICIOUS_WORDS):
            score += 2
    except TelegramBadRequest as exc:
        logger.debug("G15: не удалось получить био %s: %s", user_id, exc)

    return score

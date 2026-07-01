"""Точка входа Guardian (см. guardian/GUARDIAN.md) — ОТДЕЛЬНЫЙ процесс от
tg_repost/main.py, свой bot token, своя БД.

Запуск: python -m guardian.bot
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from guardian.config import get_guardian_settings
from guardian.db.models import StopWord, TrustedUser
from guardian.db.session import session_scope
from guardian.handlers import admin, join, messages
from guardian.logging_conf import get_logger, setup_logging
from guardian.services.warn_system import reset_expired_warns

logger = get_logger(__name__)

_STOPWORDS_SEED_PATH = "guardian/data/stopwords_default.txt"
# Стоп-слова/whitelist доменов могут меняться НЕ только Telegram-командами
# Guardian (те дёргают `.reload()` сами сразу после записи), но и веб-
# админкой tg_repost — а это ДРУГОЙ ОС-процесс, у него нет способа
# уведомить синглтоны `keyword_filter`/`link_filter` в процессе Guardian
# напрямую. Периодический опрос — самое простое решение, одинаково
# работающее независимо от источника изменения (см. guardian/config.py про
# тот же выбор для настроек).
_FILTER_RELOAD_INTERVAL_SECONDS = 60


def _reload_filters() -> None:
    with session_scope() as session:
        messages.keyword_filter.reload(session)
        messages.link_filter.reload(session)
    # flood_filter не хранит своё состояние в БД (только пороги — часть
    # GuardianSettings/bot_config), но у него, в отличие от keyword_filter/
    # link_filter, нет собственного reload(session) — пороги применяются
    # через update_limits(). Раньше эта джоба его не трогала вообще, и
    # /guardian/settings/flood молча ничего не применял без перезапуска
    # процесса (найдено при код-ревью).
    settings = get_guardian_settings()
    messages.flood_filter.update_limits(
        settings.flood_max_messages, settings.flood_window_seconds
    )


def _seed_stopwords_if_empty() -> None:
    """G03: начальный список стоп-слов загружается один раз, только если
    таблица пуста — дальше редактируется исключительно /addword /delword,
    не этим файлом (повторный запуск не затирает ручные правки)."""
    with session_scope() as session:
        if session.query(StopWord).count() > 0:
            return
        try:
            with open(_STOPWORDS_SEED_PATH, encoding="utf-8") as f:
                words = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
        except FileNotFoundError:
            logger.warning(
                "Файл стартовых стоп-слов не найден: %s", _STOPWORDS_SEED_PATH
            )
            return
        for word in words:
            session.add(StopWord(word=word.lower(), added_by="seed"))
    logger.info("Загружено %d стоп-слов по умолчанию", len(words))


async def _auto_trust_repost_bot(bot: Bot) -> None:
    """G12/интеграция с репост-ботом: без этого спам-фильтр удалял бы
    посты репост-бота (они содержат ссылки на источники — см. GUARDIAN.md).
    REPOST_BOT_ID обязан быть числовым user_id, не @username — Bot API не
    резолвит username в id без предварительного общения бота с ним.

    ВАЖНО: этот id получает ПОЛНЫЙ обход спам-/линк-/антифлуд-фильтров (см.
    `handlers/messages.py::_is_trusted`) — опечатка в `.env` тихо выдаёт эту
    привилегию произвольному аккаунту. Поэтому лог — на уровне WARNING (не
    INFO, который обычно не читают в стабильной работе) и с попыткой
    подтвердить личность через `bot.get_chat` — чтобы оператор увидел это в
    логах контейнера при старте и мог сверить, что id верный (найдено при
    security-аудите)."""
    settings = get_guardian_settings()
    if not settings.repost_bot_id:
        return
    identifier = settings.repost_bot_id.lstrip("@")
    if not identifier.lstrip("-").isdigit():
        logger.warning(
            "REPOST_BOT_ID='%s' не похож на числовой user_id — авто-trust пропущен",
            settings.repost_bot_id,
        )
        return
    user_id = int(identifier)
    with session_scope() as session:
        exists = (
            session.query(TrustedUser)
            .filter(
                TrustedUser.user_id == user_id,
                TrustedUser.chat_id == settings.guardian_group_id,
            )
            .one_or_none()
        )
        if exists is not None:
            return
        session.add(
            TrustedUser(
                user_id=user_id,
                chat_id=settings.guardian_group_id,
                added_by="auto",
                reason="репост-бот (REPOST_BOT_ID)",
            )
        )

    identity = f"id{user_id}"
    try:
        chat = await bot.get_chat(user_id)
        identity = (
            f"id{user_id} (@{chat.username}, {chat.first_name})"
            if chat.username
            else f"id{user_id} ({chat.first_name})"
        )
    except TelegramBadRequest:
        pass  # бот ещё не "видел" этот id — не критично, сама привилегия всё равно выдана
    logger.warning(
        "REPOST_BOT_ID: %s добавлен в trusted (полный обход спам-фильтров) — "
        "проверь, что это действительно репост-бот",
        identity,
    )


async def main() -> None:
    setup_logging("INFO")
    settings = get_guardian_settings()
    logger.info("Запуск Guardian...")

    if not settings.is_configured:
        logger.error(
            "GUARDIAN_BOT_TOKEN/GUARDIAN_GROUP_ID не заданы в .env — Guardian не "
            "может стартовать (см. .env.example, секция Guardian)."
        )
        return

    _seed_stopwords_if_empty()
    _reload_filters()

    bot = Bot(
        token=settings.guardian_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await _auto_trust_repost_bot(
        bot
    )  # после Bot(), т.к. подтверждает личность через bot.get_chat
    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: admin (команды) — раньше messages (общий обработчик
    # текста), иначе /warn и т.п. дошли бы и до спам-фильтра как обычный текст.
    dp.include_router(join.router)
    dp.include_router(admin.router)
    dp.include_router(messages.router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_expired_warns, CronTrigger(hour=3, minute=0), id="warn_ttl_reset"
    )
    scheduler.add_job(
        _reload_filters,
        IntervalTrigger(seconds=_FILTER_RELOAD_INTERVAL_SECONDS),
        id="filter_reload",
    )
    scheduler.start()

    try:
        await dp.start_polling(bot, scheduler=scheduler)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())

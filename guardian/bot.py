"""Точка входа Guardian (см. guardian/GUARDIAN.md) — ОТДЕЛЬНЫЙ процесс от
tg_repost/main.py, свой bot token, своя БД.

Запуск: python -m guardian.bot
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from guardian import settings_store, trusted_repo
from guardian.config import get_guardian_settings
from guardian.db.models import Member, StopWord, TrustedUser
from guardian.db.session import session_scope
from guardian.handlers import admin, join, messages, stats
from guardian.logging_conf import get_logger, setup_logging
from guardian.services import daily_stats_repo, raid_detector
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


def _apply_quiet_hours_schedule() -> None:
    """G16: если `quiet_hours_enabled`, пересчитывает `strict_mode` по
    текущему часу UTC и перезаписывает настройку. Расписание ПРИОРИТЕТНЕЕ
    ручного `/mode` между тиками — следующий тик (см. `_FILTER_RELOAD_INTERVAL_SECONDS`-
    подобный интервал ниже) снова применит расписание, откатывая ручное
    переключение, если оно противоречит текущему часу. Это осознанный выбор
    (не баг): включив расписание, оператор ожидает, что оно и есть источник
    истины, а не разовый ручной override, который стоило бы теперь помнить
    отключить обратно."""
    settings = get_guardian_settings()
    if not settings.quiet_hours_enabled:
        return
    hour = datetime.now(timezone.utc).hour
    start, end = settings.quiet_hours_start_hour, settings.quiet_hours_end_hour
    is_quiet_hours = start <= hour < end if start <= end else hour >= start or hour < end
    settings_store.save_setting("strict_mode", is_quiet_hours, "bool", updated_by="schedule")


def _auto_trust_eligible_members() -> None:
    """G12: автодоверие — участник без единого варна, состоящий в группе
    дольше `auto_trust_after_days` (по умолчанию 30), становится доверенным
    автоматически (закрывает поле `auto_trust_after_days`, которое раньше
    существовало только в настройках, но нигде не читалось — найдено при
    ретроспективе). `auto_trust_after_days <= 0` — оператор явно выключил
    автодоверие (тот же sentinel-паттерн, что `negative_reaction_threshold=0`
    в tg_repost — "0 = выкл.")."""
    settings = get_guardian_settings()
    if not settings.guardian_group_id or settings.auto_trust_after_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.auto_trust_after_days)
    with session_scope() as session:
        candidates = (
            session.query(Member)
            .filter(
                Member.chat_id == settings.guardian_group_id,
                Member.join_date < cutoff,
                Member.warn_count == 0,
                Member.is_trusted.is_(False),
                Member.is_banned.is_(False),
                Member.is_verified.is_(True),
            )
            .all()
        )
        candidate_ids = [m.user_id for m in candidates]

    reason = f"автодоверие: {settings.auto_trust_after_days}+ дней без нарушений"
    for user_id in candidate_ids:
        if trusted_repo.add_trusted(user_id, settings.guardian_group_id, added_by="auto", reason=reason):
            logger.info("G12: %s автоматически добавлен в доверенные (%s)", user_id, reason)


def _finalize_yesterday_stats() -> None:
    """G17: ежедневная джоба — фиксирует ВЧЕРАШНИЙ день в `daily_stats`,
    гарантируя непрерывную историю для `/growth` даже если `/stats`/`/growth`
    ни разу не вызывались за день (сегодняшняя запись и так пересчитывается
    "по требованию" при каждом вызове — см. `daily_stats_repo.sum_range`,
    но БЕЗ этой джобы день, за который никто не спросил статистику,
    останется без записи вообще)."""
    settings = get_guardian_settings()
    if not settings.guardian_group_id:
        return
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    daily_stats_repo.compute_and_store_daily_stats(settings.guardian_group_id, day=yesterday)


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

    # SOCKS5, не MTProto — Bot API ходит по HTTPS (см. config.py::bot_api_proxy_url).
    # AiohttpSession() парсит URL СРАЗУ в конструкторе (не лениво при первом
    # запросе) — битый GUARDIAN_BOT_API_PROXY_URL иначе ронял бы процесс
    # необработанным ValueError вместо понятного лога (найдено security-ревью).
    session = None
    if settings.bot_api_proxy_url:
        try:
            session = AiohttpSession(proxy=settings.bot_api_proxy_url)
        except ValueError as exc:
            logger.error(
                "GUARDIAN_BOT_API_PROXY_URL некорректен (%s) — Guardian не может "
                "стартовать. Формат: socks5://[user:pass@]host:port.", exc,
            )
            return
    bot = Bot(
        token=settings.guardian_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    await _auto_trust_repost_bot(
        bot
    )  # после Bot(), т.к. подтверждает личность через bot.get_chat
    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: admin/stats (команды) — раньше messages (общий
    # обработчик текста), иначе /warn, /stats и т.п. дошли бы и до
    # спам-фильтра как обычный текст.
    dp.include_router(join.router)
    dp.include_router(raid_detector.router)
    dp.include_router(admin.router)
    dp.include_router(stats.router)
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
    scheduler.add_job(
        _finalize_yesterday_stats, CronTrigger(hour=0, minute=5), id="finalize_daily_stats"
    )
    scheduler.add_job(
        _auto_trust_eligible_members, CronTrigger(hour=4, minute=0), id="auto_trust"
    )
    scheduler.add_job(
        raid_detector.check_raid,
        IntervalTrigger(minutes=1),
        args=[bot],
        id="raid_check",
    )
    scheduler.add_job(
        _apply_quiet_hours_schedule, IntervalTrigger(minutes=15), id="quiet_hours"
    )
    scheduler.start()

    try:
        await dp.start_polling(bot, scheduler=scheduler)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())

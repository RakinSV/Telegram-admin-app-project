"""Точка входа (Фаза 1, шаг 11).

Запускает в одном asyncio-цикле:
  - Telethon listener (чтение источников, F02-F04);
  - бот модерации python-telegram-bot (F07);
  - APScheduler-тик пайплайна (рерайт + модерация/постинг, F06/F08).

Запуск:  python -m tg_repost.main
"""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger, setup_logging
from tg_repost.rewriter.client import RewriterClient
from tg_repost.scheduler.jobs import pipeline_tick
from tg_repost.scheduler.posting import parse_slot, publish_slot
from tg_repost.scheduler.stats import collect_stats
from tg_repost.telegram.listener import build_client, start_listener
from tg_repost.telegram.moderation_bot import build_application

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Запуск Telegram Content Repost System v0.1")

    # --- Telethon listener ---
    tele_client = build_client()
    await start_listener(tele_client)

    # --- Бот модерации (PTB) ---
    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Бот модерации запущен")

    # --- Планировщик пайплайна ---
    rewriter = RewriterClient()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        pipeline_tick,
        trigger="interval",
        seconds=settings.pipeline_interval_seconds,
        args=[rewriter, application],
        max_instances=1,
        coalesce=True,
        id="pipeline_tick",
    )
    # F11 — слоты авто-постинга по расписанию.
    if settings.scheduled_posting_enabled:
        added = 0
        for slot in settings.posting_slots:
            parsed = parse_slot(slot)
            if parsed is None:
                logger.warning("Некорректный слот публикации '%s' — пропущен", slot)
                continue
            hour, minute = parsed
            scheduler.add_job(
                publish_slot,
                trigger=CronTrigger(hour=hour, minute=minute),
                args=[application],
                max_instances=1,
                coalesce=True,
                id=f"slot_{hour:02d}{minute:02d}",
            )
            added += 1
        if added == 0:
            logger.warning(
                "SCHEDULED_POSTING_ENABLED=true, но нет валидных слотов в "
                "POSTING_SLOTS — одобренные посты НЕ будут публиковаться!"
            )
        else:
            logger.info("Авто-постинг по расписанию включён, слотов: %d", added)

    # F14 — периодический сбор статистики просмотров.
    if settings.stats_enabled:
        scheduler.add_job(
            collect_stats,
            trigger="interval",
            minutes=settings.stats_interval_minutes,
            args=[tele_client],
            max_instances=1,
            coalesce=True,
            id="collect_stats",
        )
        logger.info("Сбор статистики включён, период %d мин", settings.stats_interval_minutes)

    scheduler.start()
    logger.info("Пайплайн-тик каждые %d с (auto_post=%s, scheduled_posting=%s)",
                settings.pipeline_interval_seconds, settings.auto_post_enabled,
                settings.scheduled_posting_enabled)

    # --- Ожидание сигнала остановки ---
    stop_event = asyncio.Event()

    def _request_stop() -> None:
        logger.info("Получен сигнал остановки")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows не поддерживает add_signal_handler для всех сигналов.
            pass

    try:
        if not stop_event.is_set():
            await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Останавливаюсь…")
        scheduler.shutdown(wait=False)
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await tele_client.disconnect()
        logger.info("Остановлено.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

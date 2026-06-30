"""Точка входа (Фаза 1, шаг 11; Фаза 5 — веб-админка).

Запускает в одном asyncio-цикле:
  - Веб-админку FastAPI (F23, Фаза 5) — ВСЕГДА, первой, на 127.0.0.1:8000.
    Не зависит от Telegram-секретов, нужен только database_url (есть дефолт).
  - Telethon listener (чтение источников, F02-F04) — только если
    `settings.is_minimally_configured`; иначе ждём, пока секреты зададут
    через веб-визард `/setup`.
  - Бот модерации python-telegram-bot (F07) — аналогично.
  - APScheduler-тик пайплайна (рерайт + модерация/постинг, F06/F08).

Запуск:  python -m tg_repost.main
"""

from __future__ import annotations

import asyncio

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application
from telethon import TelegramClient

from tg_repost.config import Settings, get_settings
from tg_repost.logging_conf import get_logger, setup_logging
from tg_repost.rewriter.client import RewriterClient
from tg_repost.scheduler.digest import run_digest_job
from tg_repost.scheduler.growth import collect_growth_snapshot
from tg_repost.scheduler.jobs import pipeline_tick
from tg_repost.scheduler.posting import parse_slot, publish_slot
from tg_repost.scheduler.stats import collect_stats
from tg_repost.telegram.listener import build_client, start_listener
from tg_repost.telegram.moderation_bot import build_application
from tg_repost.webui import runtime_state
from tg_repost.webui.app import create_app

logger = get_logger(__name__)

WEBUI_HOST = "127.0.0.1"
WEBUI_PORT = 8000


async def _start_telegram_components(
    settings: Settings,
) -> tuple[TelegramClient, Application, AsyncIOScheduler]:
    """Поднять Telethon listener + бот модерации + планировщик.

    Вынесено в отдельную функцию (не только из run()): Фаза 5.2 переиспользует
    этот же путь в `webui/supervisor.py` для рестарта компонентов из админки
    без перезапуска всего процесса.
    """
    tele_client = build_client()
    await start_listener(tele_client)
    runtime_state.set_component_status("listener", True)

    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    runtime_state.set_component_status("bot", True)
    logger.info("Бот модерации запущен")

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

    if settings.digest_enabled:
        scheduler.add_job(
            run_digest_job,
            trigger=CronTrigger(
                day_of_week=settings.digest_day_of_week,
                hour=settings.digest_hour,
                minute=settings.digest_minute,
            ),
            args=[rewriter, application],
            max_instances=1,
            coalesce=True,
            id="digest_job",
        )
        logger.info("Авто-дайджест включён: %s %02d:%02d",
                    settings.digest_day_of_week, settings.digest_hour, settings.digest_minute)

    if settings.growth_tracking_enabled:
        scheduler.add_job(
            collect_growth_snapshot,
            trigger="interval",
            minutes=settings.growth_snapshot_interval_minutes,
            args=[tele_client],
            max_instances=1,
            coalesce=True,
            id="collect_growth_snapshot",
        )
        logger.info("Growth-трекер включён, период %d мин",
                    settings.growth_snapshot_interval_minutes)

    scheduler.start()
    runtime_state.set_component_status("scheduler", True)
    logger.info("Пайплайн-тик каждые %d с (auto_post=%s, scheduled_posting=%s)",
                settings.pipeline_interval_seconds, settings.auto_post_enabled,
                settings.scheduled_posting_enabled)
    return tele_client, application, scheduler


async def _stop_telegram_components(
    tele_client: TelegramClient, application: Application, scheduler: AsyncIOScheduler
) -> None:
    """Аккуратно остановить Telethon/бота/планировщик (см. `run()`/Фаза 5.2)."""
    scheduler.shutdown(wait=False)
    runtime_state.set_component_status("scheduler", False)
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    runtime_state.set_component_status("bot", False)
    await tele_client.disconnect()
    runtime_state.set_component_status("listener", False)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Запуск Telegram Content Repost System v0.1")

    # --- Веб-админка (Фаза 5) — стартует всегда, первой ---
    web_app = create_app()
    uv_config = uvicorn.Config(web_app, host=WEBUI_HOST, port=WEBUI_PORT, log_level="warning")
    uv_server = uvicorn.Server(uv_config)
    # uvicorn.Server.serve() сам перехватывает SIGINT/SIGTERM через
    # signal.signal() (см. Server.capture_signals() в исходниках uvicorn) —
    # старых версий с методом install_signal_handlers() в текущей версии нет
    # (mypy справедливо находит это при сборке). Поэтому НЕ регистрируем
    # собственный loop.add_signal_handler() — это бы боролось с uvicorn за
    # один и тот же сигнал непредсказуемым образом. Вместо этого отдаём
    # сигналы целиком uvicorn (хорошо протестированная логика) и сами следим
    # за `uv_server.should_exit`, чтобы синхронно остановить и Telegram-часть.
    web_task = asyncio.create_task(uv_server.serve())
    logger.info("Веб-админка: http://%s:%d", WEBUI_HOST, WEBUI_PORT)

    # --- Telethon listener / бот / планировщик — только если хватает секретов ---
    tele_client: TelegramClient | None = None
    application: Application | None = None
    scheduler: AsyncIOScheduler | None = None
    if settings.is_minimally_configured:
        tele_client, application, scheduler = await _start_telegram_components(settings)
    else:
        logger.warning(
            "Минимальная конфигурация не завершена (TG_API_ID/HASH, "
            "TG_BOT_TOKEN, TG_OWNER_USER_ID, OPENAI_API_KEY) — Telethon/бот/"
            "планировщик не запущены. Открой http://%s:%d/setup",
            WEBUI_HOST, WEBUI_PORT,
        )

    # --- Ожидание остановки: web_task сам завершается, когда uvicorn
    # обработает SIGINT/SIGTERM (см. комментарий выше) и грациозно
    # остановится — никакого опроса не нужно. Если веб-сервер не смог
    # стартовать (например порт занят), web_task завершится с исключением
    # сразу — тоже корректно пройдём через finally и остановим Telegram-часть.
    try:
        await web_task
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Останавливаюсь…")
        if tele_client is not None and application is not None and scheduler is not None:
            await _stop_telegram_components(tele_client, application, scheduler)
        # web_task в норме уже завершён к этому моменту (мы его только что
        # дождались выше) — здесь страховка на случай, если run() был отменён
        # извне ДО того, как web_task сам успел доработать.
        if not web_task.done():
            uv_server.should_exit = True
            await web_task
        logger.info("Остановлено.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

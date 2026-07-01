"""Жизненный цикл Telethon listener / бота модерации / планировщика (F23, Фаза 5.2).

`main.py` вызывает `start_components()`/`stop_components()` при старте/
остановке процесса. Веб-роуты `/components` вызывают
`restart_telethon_listener()`/`restart_moderation_bot()`/
`resync_scheduler_jobs()` для живого изменения БЕЗ перезапуска процесса —
например, после смены `TG_SESSION_STRING`/`TG_BOT_TOKEN` через `/secrets`
или интервалов/расписаний через `/settings`.

Намеренно НЕ общий supervisor для произвольных компонентов — три явные
именованные функции (см. план Фазы 5, раздел "Архитектурное решение:
настройки и live-reload"): компонентов всего три, видов изменений тоже
немного, обобщённая абстракция добавила бы риск утечки asyncio-задач/
двойной регистрации джобов без реальной выгоды на таком масштабе.
"""

from __future__ import annotations

from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telethon import TelegramClient

from tg_repost.config import Settings, get_settings
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient
from tg_repost.scheduler.digest import run_digest_job
from tg_repost.scheduler.growth import collect_growth_snapshot
from tg_repost.scheduler.jobs import pipeline_tick
from tg_repost.scheduler.posting import parse_slot, publish_slot
from tg_repost.scheduler.smart_schedule import auto_apply_slots_job
from tg_repost.scheduler.stats import collect_stats
from tg_repost.telegram.listener import build_client, start_listener
from tg_repost.telegram.moderation_bot import build_application
from tg_repost.webui import runtime_state

logger = get_logger(__name__)


@dataclass
class RunningComponents:
    """Текущие живые экземпляры (если запущены) — единые на процесс, чтобы
    main.py и веб-роуты /components работали с одними и теми же объектами."""

    tele_client: TelegramClient | None = None
    application: Application | None = None
    scheduler: AsyncIOScheduler | None = None
    rewriter: RewriterClient | None = None

    @property
    def is_running(self) -> bool:
        return self.tele_client is not None


_components = RunningComponents()


def get_components() -> RunningComponents:
    """Текущие живые компоненты (для дашборда/диагностики)."""
    return _components


def _resync_optional_job(
    scheduler: AsyncIOScheduler, job_id: str, enabled: bool, func: object, args: list, trigger: object
) -> None:
    """Удалить-и-создать-заново джобу по флагу `enabled` (идемпотентно).

    Простой и надёжный способ синхронизации: джобов немного, пересоздание
    дешевле точечного diff триггера+аргументов, а заодно решает проблему
    "джоба держит ссылку на старый tele_client/application после рестарта"
    — после restart_telethon_listener()/restart_moderation_bot() этот же
    путь пересоздаёт зависимые джобы со свежими ссылками.
    """
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)
    if enabled:
        scheduler.add_job(func, trigger=trigger, args=args, max_instances=1,
                           coalesce=True, id=job_id)


def _sync_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """Привести состав и параметры джобов планировщика в соответствие с
    текущими настройками и текущими живыми компонентами. Используется и при
    первом старте (джобов ещё нет), и при resync/рестарте компонента
    (часть джобов уже существует) — единая точка истины вместо дублирования
    логики регистрации в нескольких местах.
    """
    rewriter = _components.rewriter
    application = _components.application
    tele_client = _components.tele_client

    if scheduler.get_job("pipeline_tick") is None:
        scheduler.add_job(
            pipeline_tick,
            trigger=IntervalTrigger(seconds=settings.pipeline_interval_seconds),
            args=[rewriter, application],
            max_instances=1, coalesce=True, id="pipeline_tick",
        )
    else:
        # F19/план Фазы 5: интервал мог измениться через /settings —
        # reschedule_job, а не remove+re-add (штатный APScheduler API).
        scheduler.reschedule_job(
            "pipeline_tick",
            trigger=IntervalTrigger(seconds=settings.pipeline_interval_seconds),
        )

    # Слоты публикации: количество и времена переменные — проще снести все
    # текущие slot_* и создать заново по актуальному списку.
    for job in list(scheduler.get_jobs()):
        if job.id.startswith("slot_"):
            scheduler.remove_job(job.id)
    if settings.scheduled_posting_enabled:
        added = 0
        for slot in settings.posting_slots:
            parsed = parse_slot(slot)
            if parsed is None:
                logger.warning("Некорректный слот публикации '%s' — пропущен", slot)
                continue
            hour, minute = parsed
            scheduler.add_job(
                publish_slot, trigger=CronTrigger(hour=hour, minute=minute),
                args=[application], max_instances=1, coalesce=True,
                id=f"slot_{hour:02d}{minute:02d}",
            )
            added += 1
        if added == 0:
            logger.warning(
                "SCHEDULED_POSTING_ENABLED=true, но нет валидных слотов в "
                "POSTING_SLOTS — одобренные посты НЕ будут публиковаться!"
            )

    _resync_optional_job(
        scheduler, "collect_stats", settings.stats_enabled,
        collect_stats, [tele_client],
        IntervalTrigger(minutes=settings.stats_interval_minutes),
    )
    _resync_optional_job(
        scheduler, "digest_job", settings.digest_enabled,
        run_digest_job, [rewriter, application],
        CronTrigger(day_of_week=settings.digest_day_of_week,
                    hour=settings.digest_hour, minute=settings.digest_minute),
    )
    _resync_optional_job(
        scheduler, "collect_growth_snapshot", settings.growth_tracking_enabled,
        collect_growth_snapshot, [tele_client],
        IntervalTrigger(minutes=settings.growth_snapshot_interval_minutes),
    )
    _resync_optional_job(
        scheduler, "smart_schedule_auto_apply", settings.smart_schedule_auto_apply,
        auto_apply_slots_job, [],
        IntervalTrigger(hours=24),
    )


async def start_components(settings: Settings | None = None) -> None:
    """Поднять Telethon listener + бот модерации + планировщик с нуля."""
    if _components.is_running:
        logger.warning("start_components: компоненты уже запущены, пропуск")
        return
    settings = settings or get_settings()

    _components.tele_client = build_client()
    await start_listener(_components.tele_client)
    runtime_state.set_component_status("listener", True)

    _components.application = build_application()
    await _components.application.initialize()
    await _components.application.start()
    await _components.application.updater.start_polling(drop_pending_updates=True)
    runtime_state.set_component_status("bot", True)
    logger.info("Бот модерации запущен")

    _components.rewriter = RewriterClient()
    _components.scheduler = AsyncIOScheduler()
    _sync_jobs(_components.scheduler, settings)
    _components.scheduler.start()
    runtime_state.set_component_status("scheduler", True)
    logger.info(
        "Пайплайн-тик каждые %d с (auto_post=%s, scheduled_posting=%s)",
        settings.pipeline_interval_seconds, settings.auto_post_enabled,
        settings.scheduled_posting_enabled,
    )


async def stop_components() -> None:
    """Остановить всё (no-op, если ничего не запущено)."""
    if not _components.is_running:
        return
    if _components.scheduler is not None:
        _components.scheduler.shutdown(wait=False)
        runtime_state.set_component_status("scheduler", False)
        _components.scheduler = None
    if _components.application is not None:
        await _components.application.updater.stop()
        await _components.application.stop()
        await _components.application.shutdown()
        runtime_state.set_component_status("bot", False)
        _components.application = None
    if _components.tele_client is not None:
        await _components.tele_client.disconnect()
        runtime_state.set_component_status("listener", False)
        _components.tele_client = None
    _components.rewriter = None
    logger.info("Telegram-компоненты остановлены")


async def restart_telethon_listener() -> None:
    """Пересобрать Telethon-клиент (например, после смены TG_SESSION_STRING
    через /secrets) — без остановки бота/планировщика. Зависимые джобы
    (collect_stats, collect_growth_snapshot) автоматически получают свежую
    ссылку через `_sync_jobs`."""
    if not _components.is_running:
        logger.warning("restart_telethon_listener: компоненты не запущены")
        return
    if _components.tele_client is not None:
        await _components.tele_client.disconnect()
    _components.tele_client = build_client()
    await start_listener(_components.tele_client)
    runtime_state.set_component_status("listener", True)
    if _components.scheduler is not None:
        _sync_jobs(_components.scheduler, get_settings())
    logger.info("Telethon listener перезапущен")


async def restart_moderation_bot() -> None:
    """Пересобрать бота модерации (например, после смены TG_BOT_TOKEN через
    /secrets) — без остановки listener/планировщика. Зависимые джобы
    (pipeline_tick, slot_*, digest_job) автоматически получают свежую
    ссылку через `_sync_jobs`."""
    if not _components.is_running:
        logger.warning("restart_moderation_bot: компоненты не запущены")
        return
    if _components.application is not None:
        await _components.application.updater.stop()
        await _components.application.stop()
        await _components.application.shutdown()
    _components.application = build_application()
    await _components.application.initialize()
    await _components.application.start()
    await _components.application.updater.start_polling(drop_pending_updates=True)
    runtime_state.set_component_status("bot", True)
    if _components.scheduler is not None:
        _sync_jobs(_components.scheduler, get_settings())
    logger.info("Бот модерации перезапущен")


async def resync_scheduler_jobs(settings: Settings | None = None) -> None:
    """Привести джобы планировщика в соответствие с текущими настройками —
    идемпотентно, безопасно вызывать многократно (например, после
    сохранения группы настроек на /settings)."""
    if _components.scheduler is None:
        logger.warning("resync_scheduler_jobs: планировщик не запущен")
        return
    _sync_jobs(_components.scheduler, settings or get_settings())
    logger.info("Состав джобов планировщика синхронизирован с настройками")

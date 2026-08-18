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

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.ext import Application
from telethon import TelegramClient

from tg_repost.config import Settings, get_settings
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import RewriterClient, invalidate_rewriter_cache
from tg_repost import (
    broadcasts_repo,
    flow_bots,
    flow_engine,
    task_queue,
    webhooks_repo,
)
from tg_repost.crypto_rails import polling as crypto_polling
from tg_repost.scheduler.channel_stats import collect_channel_stats
from tg_repost.scheduler.digest import run_digest_job
from tg_repost.scheduler.growth import collect_growth_snapshot
from tg_repost.scheduler.jobs import pipeline_tick
from tg_repost.scheduler.posting import parse_slot, publish_slot
from tg_repost.scheduler.recycle import run_recycle_job
from tg_repost.scheduler.smart_schedule import auto_apply_slots_job
from tg_repost.rss.poller import poll_rss_sources
from tg_repost.scheduler.stats import collect_stats
from tg_repost.telegram.listener import build_client, build_extra_clients, start_listeners
from tg_repost.telegram.moderation_bot import build_application
from tg_repost.webui import runtime_state

logger = get_logger(__name__)

# Обработчики очереди регистрируются при импорте супервизора: он поднимается
# раньше планировщика, и к моменту первого прохода воркера все виды задач
# уже известны. Иначе задача, поставленная до регистрации, ушла бы в failed
# с «нет обработчика» — см. `task_queue.run_once`.
broadcasts_repo.register_handler()
webhooks_repo.register_handler()
crypto_polling.register_handler()
flow_engine.register_handler()


async def _run_task_queue() -> None:
    """Один проход воркера очереди (F64 и далее F71)."""
    await task_queue.run_pending()


async def _run_backup_job(keep: int) -> None:
    """Резервная копия по расписанию.

    В отдельном потоке: `run_backup` читает файлы базы и жмёт их в архив, а
    это блокирующая работа на секунды — в общем цикле она задержала бы и
    веб-админку, и опрос ботов.
    """
    from tg_repost.tools.backup import run_backup

    try:
        archive = await asyncio.to_thread(run_backup, keep)
    except Exception:
        # Сбой копии не должен ронять планировщик: остальные джобы к резервным
        # копиям отношения не имеют.
        logger.exception("Резервная копия не создана")
        return
    logger.info("Резервная копия готова: %s", archive.name)


@dataclass
class RunningComponents:
    """Текущие живые экземпляры (если запущены) — единые на процесс, чтобы
    main.py и веб-роуты /components работали с одними и теми же объектами.

    `tele_client` — ОСНОВНОЙ Telethon-клиент, используется везде за пределами
    listener-а (сбор статистики F14, growth-снимки F22) как и раньше.
    `extra_tele_clients` — дополнительные клиенты F26, используются ТОЛЬКО
    listener-ом для распределения источников; остальным компонентам не нужны.
    """

    tele_client: TelegramClient | None = None
    extra_tele_clients: list[TelegramClient] = field(default_factory=list)
    application: Application | None = None
    scheduler: AsyncIOScheduler | None = None
    rewriter: RewriterClient | None = None
    # F75: диспетчер aiogram, ведущий ВСЕ боты реестра, и задача его опроса.
    # Живёт в этом же процессе намеренно: список ботов задаётся в админке, и
    # владелец, добавив бота, ждёт, что тот заработает, а не что кто-то зайдёт
    # по SSH перезапускать контейнер.
    flow_dispatcher: object | None = None
    flow_polling: object | None = None

    @property
    def is_running(self) -> bool:
        """Работает ли хоть что-нибудь.

        РАНЬШЕ ЗДЕСЬ БЫЛ ТОЛЬКО TELETHON, и это ломало остановку: при неудачном
        старте listener-а `stop_components` выходил сразу, оставляя работать
        планировщик и ботов сценариев. Теперь компоненты поднимаются независимо
        друг от друга, поэтому и признак «что-то живо» должен быть общим.
        """
        return any((
            self.tele_client is not None,
            self.application is not None,
            self.scheduler is not None,
            self.flow_polling is not None,
        ))


_components = RunningComponents()


def get_components() -> RunningComponents:
    """Текущие живые компоненты (для дашборда/диагностики)."""
    return _components


def _resync_optional_job(
    scheduler: AsyncIOScheduler, job_id: str, enabled: bool, func: object, args: list,
    trigger: object, *, run_now: bool = False,
) -> None:
    """Удалить-и-создать-заново джобу по флагу `enabled` (идемпотентно).

    Простой и надёжный способ синхронизации: джобов немного, пересоздание
    дешевле точечного diff триггера+аргументов, а заодно решает проблему
    "джоба держит ссылку на старый tele_client/application после рестарта"
    — после restart_telethon_listener()/restart_moderation_bot() этот же
    путь пересоздаёт зависимые джобы со свежими ссылками.

    `run_now` — не ждать целый интервал до первого запуска. По умолчанию
    выключено: для сбора статистики или дайджеста лишний прогон на каждом
    сохранении настроек — сюрприз, а не польза.
    """
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)
    if not enabled:
        return
    extra = {"next_run_time": datetime.now(timezone.utc)} if run_now else {}
    scheduler.add_job(func, trigger=trigger, args=args, max_instances=1,
                      coalesce=True, id=job_id, **extra)


def _sync_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """Привести состав и параметры джобов планировщика в соответствие с
    текущими настройками и текущими живыми компонентами. Используется и при
    первом старте (джобов ещё нет), и при resync/рестарте компонента
    (часть джобов уже существует) — единая точка истины вместо дублирования
    логики регистрации в нескольких местах.
    """
    # Пересобираем ВСЕГДА (не только при первом старте) — `RewriterClient()`
    # дёшев (AsyncOpenAI() в конструкторе не делает сетевых вызовов, только
    # читает settings), а без пересборки ротация OPENAI_API_KEY/смена
    # OPENAI_BASE_URL/MODEL через /secrets и /settings тихо не применялась
    # бы: старый `_components.rewriter` держал бы СТАРЫЙ ключ до полного
    # рестарта контейнера (найдено security-ревью — тот же класс бага, что
    # уже чинили для WEBUI_MASTER_KEY). `_sync_jobs()` вызывается и из
    # `resync_scheduler_jobs()` (после /settings и /secrets, см. app.py), и
    # из restart_telethon_listener()/restart_moderation_bot() — везде, где
    # нужен свежий rewriter.
    _components.rewriter = RewriterClient()
    # Отдельный кэш get_rewriter() (см. его докстринг) для эмбеддингов
    # дедупа в listener.py — не связан с `_components.rewriter`, без явного
    # сброса продолжал бы работать со старым base_url/моделью бесконечно
    # (найдено на реальном деплое: смена модели на роутер OpenRouter-типа
    # применилась к рерайту, но не к эмбеддингам при захвате сообщения).
    invalidate_rewriter_cache()
    rewriter = _components.rewriter
    application = _components.application
    tele_client = _components.tele_client

    # Пайплайн-тик отправляет посты на одобрение и публикует их — без бота
    # модерации делать ему нечего, а падать каждую минуту он будет исправно.
    if application is None:
        if scheduler.get_job("pipeline_tick") is not None:
            scheduler.remove_job("pipeline_tick")
        logger.warning(
            "Бот модерации не запущен — пайплайн-тик не ставлю: рерайт и "
            "публикация всё равно упрутся в отсутствующего бота",
        )
    elif scheduler.get_job("pipeline_tick") is None:
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
        # `reschedule_job` меняет ТОЛЬКО trigger/next_run_time, НЕ args
        # (проверено по исходнику APScheduler) — без этой строки джоба после
        # restart_moderation_bot()/restart_telethon_listener() продолжала бы
        # держать ссылку на СТАРЫЙ (уже .shutdown()) Application/tele_client,
        # тихо ломая рерайт после ротации TG_BOT_TOKEN через /secrets (найдено
        # security-ревью). `rewriter`/`application` в этой функции уже
        # свежепрочитаны из `_components` в начале `_sync_jobs`.
        scheduler.modify_job("pipeline_tick", args=[rewriter, application])

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

    # Джобы, которым НУЖЕН Telethon, при его отсутствии не заводятся вовсе.
    # Иначе каждая минута расписания давала бы трассировку в логе про `None`,
    # и настоящие сообщения в нём утонули бы — а работы всё равно никакой.
    _resync_optional_job(
        scheduler, "collect_stats", settings.stats_enabled and tele_client is not None,
        collect_stats, [tele_client, application],
        IntervalTrigger(minutes=settings.stats_interval_minutes),
    )
    _resync_optional_job(
        scheduler, "digest_job", settings.digest_enabled,
        run_digest_job, [rewriter, application],
        CronTrigger(day_of_week=settings.digest_day_of_week,
                    hour=settings.digest_hour, minute=settings.digest_minute),
    )
    # F64: воркер очереди. Всегда включён и стоит копейки на холостом ходу —
    # `run_pending` при пустой очереди делает один SELECT и выходит. Прятать
    # его за настройку значило бы дать возможность выключить доставку уже
    # созданных рассылок, не заметив этого.
    _resync_optional_job(
        scheduler, "task_queue_worker", True,
        _run_task_queue, [],
        IntervalTrigger(seconds=settings.task_queue_interval_seconds),
    )
    # F75: просроченные сроки ответа в сценариях. Всегда включена и почти
    # ничего не стоит на холостом ходу (один SELECT по индексу
    # `ix_flow_runs_waiting`). Прятать за настройку нельзя: выключенная, она
    # оставляет людей висеть посреди сценария навсегда, а владелец видит
    # вечное «идёт». Раз в 5 минут: сроки измеряются часами, точность до
    # минуты тут не нужна.
    _resync_optional_job(
        scheduler, "flow_sweep_timeouts", True,
        flow_engine.sweep_timeouts, [flow_bots.bot_for],
        IntervalTrigger(minutes=5),
    )
    _resync_optional_job(
        scheduler, "channel_stats_job",
        settings.channel_stats_enabled and tele_client is not None,
        collect_channel_stats, [tele_client],
        IntervalTrigger(hours=settings.channel_stats_interval_hours),
    )
    # Резервная копия по расписанию. РАНЬШЕ КОПИИ ДЕЛАЛИСЬ ТОЛЬКО КНОПКОЙ, и
    # «хранение 14 последних» из кода не работало в Docker ни дня: каталог не
    # был смонтирован наружу, и каждый деплой стирал копии вместе со слоем
    # контейнера (разбор архитектуры 2026-08-18). Джоба не зависит ни от
    # Telegram, ни от бота — она про сохранность данных, а не про доставку.
    _resync_optional_job(
        scheduler, "daily_backup", settings.backup_enabled,
        _run_backup_job, [settings.backup_keep],
        CronTrigger(hour=max(0, min(23, settings.backup_hour)), minute=0),
    )
    _resync_optional_job(
        scheduler, "recycle_job", settings.recycle_enabled,
        run_recycle_job, [],
        IntervalTrigger(hours=settings.recycle_interval_hours),
    )
    _resync_optional_job(
        scheduler, "collect_growth_snapshot",
        settings.growth_tracking_enabled and tele_client is not None,
        collect_growth_snapshot, [tele_client],
        IntervalTrigger(minutes=settings.growth_snapshot_interval_minutes),
    )
    _resync_optional_job(
        scheduler, "smart_schedule_auto_apply", settings.smart_schedule_auto_apply,
        auto_apply_slots_job, [],
        IntervalTrigger(hours=24),
    )
    # RSS-опрос не зависит ни от Telethon, ни от бота: ленты берутся обычным
    # HTTP. Поэтому джоба живёт наравне с остальными, но её работоспособность
    # не завязана на доступность Telegram — при отвалившемся Telethon ленты
    # продолжают наполнять очередь.
    # run_now: включив опрос, пользователь ждёт, что ленты проверятся, а не
    # что первые записи появятся через интервал (по умолчанию 15 минут) —
    # именно так выглядела жалоба «добавил RSS, ничего не прилетает». Лишний
    # прогон безвреден: записи дедуплицируются по guid.
    _resync_optional_job(
        scheduler, "poll_rss_sources", settings.rss_enabled,
        poll_rss_sources, [],
        IntervalTrigger(minutes=max(1, settings.rss_poll_interval_minutes)),
        run_now=True,
    )


async def start_components(settings: Settings | None = None) -> None:
    """Поднять Telethon listener + бот модерации + боты сценариев + планировщик.

    КАЖДЫЙ КОМПОНЕНТ ПОДНИМАЕТСЯ ОТДЕЛЬНО, И ПАДЕНИЕ ОДНОГО НЕ УНОСИТ
    ОСТАЛЬНЫХ. Найдено аудитом на стенде: Telegram оттуда недоступен, Telethon
    падал с `ConnectionError`, и вместе с ним НЕ запускались ни планировщик, ни
    воркер очереди, ни боты конструктора — хотя ни один из них от Telethon не
    зависит. Снаружи это выглядело как «админка работает, а система нет»:
    рассылки не уходят, шаги воронок не отправляются, сроки в сценариях не
    подметаются, и единственный признак — серый значок на `/components`.

    Порядок сохранён: сначала чтение (listener), потом отправка (боты), потом
    расписание. Планировщик идёт последним, потому что его джобы держат ссылки
    на всё перечисленное выше.
    """
    if _components.is_running:
        logger.warning("start_components: компоненты уже запущены, пропуск")
        return
    settings = settings or get_settings()

    try:
        _components.tele_client = build_client()
        _components.extra_tele_clients = build_extra_clients()
        await start_listeners(
            [_components.tele_client, *_components.extra_tele_clients]
        )
        runtime_state.set_component_status("listener", True)
    except Exception:
        # Типичные причины: не поднялся прокси, истекла сессия, провайдер
        # режет Telegram. Всё это чинится в админке, и админка обязана при
        # этом работать — вместе с очередью и расписанием.
        logger.exception(
            "Telethon listener не поднялся — остальные компоненты запускаю без него"
        )
        _components.tele_client = None
        _components.extra_tele_clients = []
        runtime_state.set_component_status("listener", False)

    try:
        _components.application = build_application()
        await _components.application.initialize()
        await _components.application.start()
        assert _components.application.updater is not None  # build_application() не отключает updater
        # allowed_updates=ALL_TYPES явно (не полагаемся на дефолт Bot API) —
        # my_chat_member нужен для обнаружения чатов (F08-доп., см.
        # moderation_bot.py::_on_my_chat_member), явное перечисление надёжнее
        # недокументированного здесь дефолтного поведения getUpdates.
        await _components.application.updater.start_polling(
            drop_pending_updates=True, allowed_updates=Update.ALL_TYPES,
        )
        runtime_state.set_component_status("bot", True)
        logger.info("Бот модерации запущен")
    except Exception:
        logger.exception(
            "Бот модерации не поднялся — остальные компоненты запускаю без него"
        )
        _components.application = None
        runtime_state.set_component_status("bot", False)

    # F75: боты-конструкторы. Поднимаются ПОСЛЕ бота модерации и до
    # планировщика: подметание просроченных сроков (джоба ниже) отправляет
    # сообщения этими же ботами, и к первому её проходу они должны быть живы.
    try:
        await start_flow_bots()
    except Exception:
        logger.exception("Боты-конструкторы не поднялись — продолжаю без них")

    _components.scheduler = AsyncIOScheduler()
    _sync_jobs(_components.scheduler, settings)  # тоже строит _components.rewriter
    _components.scheduler.start()
    runtime_state.set_component_status("scheduler", True)
    # Итог пишем ПО ФАКТУ, а не по настройкам: строка «пайплайн-тик каждые
    # 30 с» сразу после «пайплайн-тик не ставлю» — это ровно то враньё в логе,
    # из-за которого потом ищут несуществующую проблему.
    jobs = sorted(job.id for job in _components.scheduler.get_jobs())
    logger.info("Планировщик запущен, джоб %d: %s", len(jobs), ", ".join(jobs))
    if _components.application is not None:
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
    await stop_flow_bots()
    if _components.application is not None:
        assert _components.application.updater is not None  # build_application() не отключает updater
        await _components.application.updater.stop()
        await _components.application.stop()
        await _components.application.shutdown()
        runtime_state.set_component_status("bot", False)
        _components.application = None
    if _components.tele_client is not None:
        await _components.tele_client.disconnect()
        runtime_state.set_component_status("listener", False)
        _components.tele_client = None
    for extra in _components.extra_tele_clients:
        await extra.disconnect()
    _components.extra_tele_clients = []
    _components.rewriter = None
    logger.info("Telegram-компоненты остановлены")


async def restart_telethon_listener() -> None:
    """Пересобрать Telethon-клиент(ы) (например, после смены TG_SESSION_STRING
    через /secrets или добавления/отключения доп. сессий F26) — без остановки
    бота/планировщика. Зависимые джобы (collect_stats, collect_growth_snapshot,
    используют только ОСНОВНОЙ клиент) автоматически получают свежую ссылку
    через `_sync_jobs`."""
    if not _components.is_running:
        logger.warning("restart_telethon_listener: компоненты не запущены")
        return
    if _components.tele_client is not None:
        await _components.tele_client.disconnect()
    for extra in _components.extra_tele_clients:
        await extra.disconnect()

    _components.tele_client = build_client()
    _components.extra_tele_clients = build_extra_clients()
    await start_listeners([_components.tele_client, *_components.extra_tele_clients])
    runtime_state.set_component_status("listener", True)
    if _components.scheduler is not None:
        _sync_jobs(_components.scheduler, get_settings())
    logger.info(
        "Telethon listener перезапущен (%d доп. сессий)", len(_components.extra_tele_clients),
    )


async def restart_moderation_bot() -> None:
    """Пересобрать бота модерации (например, после смены TG_BOT_TOKEN через
    /secrets) — без остановки listener/планировщика. Зависимые джобы
    (pipeline_tick, slot_*, digest_job) автоматически получают свежую
    ссылку через `_sync_jobs`."""
    if not _components.is_running:
        logger.warning("restart_moderation_bot: компоненты не запущены")
        return
    if _components.application is not None:
        assert _components.application.updater is not None  # build_application() не отключает updater
        await _components.application.updater.stop()
        await _components.application.stop()
        await _components.application.shutdown()
    _components.application = build_application()
    await _components.application.initialize()
    await _components.application.start()
    assert _components.application.updater is not None  # build_application() не отключает updater
    # allowed_updates=ALL_TYPES явно (не полагаемся на дефолт Bot API) —
    # my_chat_member нужен для обнаружения чатов (F08-доп., см.
    # moderation_bot.py::_on_my_chat_member), явное перечисление надёжнее
    # недокументированного здесь дефолтного поведения getUpdates.
    await _components.application.updater.start_polling(
        drop_pending_updates=True, allowed_updates=Update.ALL_TYPES,
    )
    runtime_state.set_component_status("bot", True)
    if _components.scheduler is not None:
        _sync_jobs(_components.scheduler, get_settings())
    logger.info("Бот модерации перезапущен")


def _flow_dispatcher() -> object:
    """Диспетчер ботов-конструкторов — ОДИН на процесс, создаётся один раз.

    Router в aiogram — модульный синглтон: включить его во ВТОРОЙ диспетчер
    (например, собранный при перезапуске) нельзя, aiogram отказывает «router is
    already attached». Поэтому диспетчер переживает перезапуски опроса, а
    меняется только состав ботов.
    """
    if _components.flow_dispatcher is None:
        from aiogram import Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage

        from tg_repost import flow_handlers

        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(flow_handlers.router)
        _components.flow_dispatcher = dispatcher
    return _components.flow_dispatcher


async def start_flow_bots() -> None:
    """Начать опрос всех включённых ботов реестра (F75).

    ОДИН ДИСПЕТЧЕР НА ВСЕ БОТЫ: aiogram ведёт «one or more» ботов, и
    обработчик получает тот, которому пришёл апдейт.
    """
    if _components.flow_polling is not None:
        logger.warning("start_flow_bots: опрос уже идёт")
        return
    bots = flow_bots.active_bots()
    if not bots:
        # Ботов нет или все выключены — это норма, а не сбой: пока владелец не
        # добавил ни одного, опрашивать некого.
        logger.info("F75: включённых ботов-конструкторов нет — опрос не запущен")
        runtime_state.set_component_status("flow_bots", False)
        return

    dispatcher = _flow_dispatcher()
    _components.flow_polling = asyncio.create_task(
        # handle_signals=False обязательно: обработчики сигналов ставит
        # веб-сервер, и второй претендент на них ломает штатную остановку.
        dispatcher.start_polling(*bots.values(), handle_signals=False),  # type: ignore[attr-defined]
    )
    runtime_state.set_component_status("flow_bots", True)
    logger.info("F75: опрос ботов-конструкторов начат (%d шт.)", len(bots))


async def stop_flow_bots() -> None:
    """Остановить опрос ботов реестра и закрыть их соединения."""
    dispatcher = _components.flow_dispatcher
    task = _components.flow_polling
    _components.flow_polling = None
    if task is None:
        return
    if dispatcher is not None:
        with contextlib.suppress(Exception):
            await dispatcher.stop_polling()  # type: ignore[attr-defined]
    if isinstance(task, asyncio.Task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    await flow_bots.forget_all()
    runtime_state.set_component_status("flow_bots", False)
    logger.info("F75: опрос ботов-конструкторов остановлен")


async def restart_flow_bots() -> None:
    """Перечитать реестр и поднять опрос заново — после правок в админке.

    Вызывается со страницы ботов: добавили бота, сменили токен, выключили —
    всё это должно действовать сразу. Иначе «все настройки в админке»
    заканчивается там, где начинается SSH.
    """
    await stop_flow_bots()
    await start_flow_bots()


async def resync_scheduler_jobs(settings: Settings | None = None) -> None:
    """Привести джобы планировщика в соответствие с текущими настройками —
    идемпотентно, безопасно вызывать многократно (например, после
    сохранения группы настроек на /settings)."""
    if _components.scheduler is None:
        logger.warning("resync_scheduler_jobs: планировщик не запущен")
        return
    _sync_jobs(_components.scheduler, settings or get_settings())
    logger.info("Состав джобов планировщика синхронизирован с настройками")

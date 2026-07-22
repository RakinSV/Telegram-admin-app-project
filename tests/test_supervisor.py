"""Тесты жизненного цикла компонентов (F23, Фаза 5.2): чистая логика
синхронизации джобов APScheduler — без реальных Telegram-соединений
(сам APScheduler-планировщик не требует сети, job-функции не вызываются,
только регистрируются)."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tg_repost.config import Settings
from tg_repost.webui.supervisor import (
    RunningComponents,
    _resync_optional_job,
    _sync_jobs,
    get_components,
)
from tg_repost.webui import supervisor as supervisor_module


def _noop(*args, **kwargs):
    pass


def test_running_components_is_running_false_by_default():
    assert RunningComponents().is_running is False


def test_running_components_is_running_true_with_client():
    assert RunningComponents(tele_client=object()).is_running is True


def test_get_components_returns_singleton():
    assert get_components() is get_components()


def test_resync_optional_job_creates_when_enabled():
    scheduler = AsyncIOScheduler()
    _resync_optional_job(scheduler, "test_job", True, _noop, [], IntervalTrigger(seconds=60))
    assert scheduler.get_job("test_job") is not None


def test_resync_optional_job_removes_when_disabled():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_noop, trigger=IntervalTrigger(seconds=60), id="test_job")
    _resync_optional_job(scheduler, "test_job", False, _noop, [], IntervalTrigger(seconds=60))
    assert scheduler.get_job("test_job") is None


def test_resync_optional_job_noop_when_disabled_and_absent():
    scheduler = AsyncIOScheduler()
    _resync_optional_job(scheduler, "test_job", False, _noop, [], IntervalTrigger(seconds=60))
    assert scheduler.get_job("test_job") is None


def test_resync_optional_job_idempotent_recreation_updates_args():
    scheduler = AsyncIOScheduler()
    _resync_optional_job(scheduler, "test_job", True, _noop, [1], IntervalTrigger(seconds=60))
    _resync_optional_job(scheduler, "test_job", True, _noop, [2], IntervalTrigger(seconds=60))
    job = scheduler.get_job("test_job")
    assert job is not None
    assert list(job.args) == [2]
    # Не задвоилась — одна джоба с этим id.
    assert sum(1 for j in scheduler.get_jobs() if j.id == "test_job") == 1


def test_sync_jobs_creates_pipeline_tick():
    settings = Settings()
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("pipeline_tick") is not None


def test_sync_jobs_rebuilds_rewriter_every_call():
    # Регрессия (security-ревью): _components.rewriter раньше строился ОДИН
    # РАЗ в start_components() и никогда не пересобирался — ротация
    # OPENAI_API_KEY через /secrets тихо не применялась (RewriterClient
    # держит ключ, снятый в конструкторе, до полного рестарта контейнера).
    # _sync_jobs() теперь пересобирает его на каждый вызов (дёшево — не
    # делает сетевых вызовов, см. RewriterClient.__init__).
    settings = Settings()
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    first_rewriter = supervisor_module._components.rewriter
    assert first_rewriter is not None

    _sync_jobs(scheduler, settings)
    second_rewriter = supervisor_module._components.rewriter
    assert second_rewriter is not None
    assert second_rewriter is not first_rewriter


def test_sync_jobs_invalidates_listener_rewriter_cache_too():
    """Регрессия (найдено на реальном деплое): `get_rewriter()` в
    `listener.py` — ОТДЕЛЬНЫЙ `@lru_cache`-синглтон от `_components.rewriter`,
    используется для эмбеддингов дедупа (F13) при захвате сообщения. Смена
    OPENAI_MODEL/EMBEDDING_MODEL через /settings пересобирала
    `_components.rewriter` (см. тест выше), но НЕ сбрасывала этот кэш —
    listener.py продолжал бы получать эмбеддинги через старый клиент со
    старой моделью бесконечно, без явного `invalidate_rewriter_cache()`."""
    from tg_repost.rewriter.client import get_rewriter

    settings = Settings()
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    first = get_rewriter()

    _sync_jobs(scheduler, settings)
    second = get_rewriter()

    assert second is not first


def test_sync_jobs_reschedule_does_not_duplicate_pipeline_tick():
    settings = Settings()
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    settings.pipeline_interval_seconds = 999
    _sync_jobs(scheduler, settings)
    assert sum(1 for j in scheduler.get_jobs() if j.id == "pipeline_tick") == 1


def test_sync_jobs_reschedule_updates_pipeline_tick_args(monkeypatch):
    # Регрессия (security-ревью): reschedule_job() меняет ТОЛЬКО
    # trigger/next_run_time (проверено по исходнику APScheduler), НЕ args —
    # без явного modify_job(args=...) джоба после restart_moderation_bot()
    # продолжала бы держать ссылку на СТАРЫЙ (уже .shutdown()) Application,
    # тихо ломая рерайт после ротации TG_BOT_TOKEN через /secrets.
    settings = Settings()
    scheduler = AsyncIOScheduler()

    old_application = object()
    monkeypatch.setattr(supervisor_module._components, "application", old_application)
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("pipeline_tick").args[1] is old_application

    new_application = object()
    monkeypatch.setattr(supervisor_module._components, "application", new_application)
    _sync_jobs(scheduler, settings)

    job = scheduler.get_job("pipeline_tick")
    assert job.args[1] is new_application
    assert job.args[1] is not old_application


def test_sync_jobs_no_optional_jobs_by_default():
    settings = Settings()  # все *_enabled по умолчанию False
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "collect_stats" not in job_ids
    assert "digest_job" not in job_ids
    assert "collect_growth_snapshot" not in job_ids
    assert "smart_schedule_auto_apply" not in job_ids


def test_sync_jobs_creates_smart_schedule_auto_apply_when_enabled():
    """F19 доделка: автоприменение рекомендации к POSTING_SLOTS раз в сутки,
    только если явно включено (по умолчанию — только ручная кнопка)."""
    settings = Settings()
    settings.smart_schedule_auto_apply = True
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("smart_schedule_auto_apply") is not None


def test_sync_jobs_removes_smart_schedule_auto_apply_when_disabled_again():
    settings = Settings()
    settings.smart_schedule_auto_apply = True
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("smart_schedule_auto_apply") is not None
    settings.smart_schedule_auto_apply = False
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("smart_schedule_auto_apply") is None


def test_sync_jobs_creates_optional_job_when_enabled():
    settings = Settings()
    settings.stats_enabled = True
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("collect_stats") is not None


def test_sync_jobs_removes_optional_job_when_disabled_again():
    settings = Settings()
    settings.stats_enabled = True
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("collect_stats") is not None
    settings.stats_enabled = False
    _sync_jobs(scheduler, settings)
    assert scheduler.get_job("collect_stats") is None


def test_sync_jobs_creates_slot_jobs():
    settings = Settings()
    settings.scheduled_posting_enabled = True
    settings.posting_slots = ["10:00", "14:00"]
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "slot_1000" in job_ids
    assert "slot_1400" in job_ids


def test_sync_jobs_recreates_slot_jobs_on_change():
    settings = Settings()
    settings.scheduled_posting_enabled = True
    settings.posting_slots = ["10:00"]
    scheduler = AsyncIOScheduler()
    _sync_jobs(scheduler, settings)
    settings.posting_slots = ["18:00"]
    _sync_jobs(scheduler, settings)
    slot_ids = {j.id for j in scheduler.get_jobs() if j.id.startswith("slot_")}
    assert slot_ids == {"slot_1800"}


def test_rss_job_is_scheduled_to_run_immediately():
    """Включив опрос, пользователь ждёт проверки лент, а не первых записей
    через интервал (15 минут по умолчанию) — именно так выглядела жалоба
    «добавил RSS, ничего не прилетает»."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    from tg_repost.webui.supervisor import _resync_optional_job

    scheduler = AsyncIOScheduler()

    async def _noop() -> None:
        return None

    _resync_optional_job(
        scheduler, "poll_rss_sources", True, _noop, [],
        IntervalTrigger(minutes=15), run_now=True,
    )
    job = scheduler.get_job("poll_rss_sources")
    assert job is not None
    assert job.next_run_time is not None


def test_other_optional_jobs_keep_waiting_a_full_interval():
    """Прогонять сбор статистики/дайджест на каждом сохранении настроек —
    сюрприз, а не польза: run_now по умолчанию выключен."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    from tg_repost.webui.supervisor import _resync_optional_job

    scheduler = AsyncIOScheduler()

    async def _noop() -> None:
        return None

    _resync_optional_job(
        scheduler, "collect_stats", True, _noop, [], IntervalTrigger(minutes=60),
    )
    job = scheduler.get_job("collect_stats")
    assert job is not None

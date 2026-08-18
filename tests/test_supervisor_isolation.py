"""Падение одного компонента не уносит остальные (аудит стенда 2026-08-18).

НАЙДЕНО НА ЖИВОЙ СИСТЕМЕ, а не в коде. Со стенда Telegram недоступен, Telethon
падал с `ConnectionError` — и вместе с ним НЕ запускались планировщик, воркер
очереди и боты конструктора. Ни один из них от Telethon не зависит. Снаружи это
выглядит как «админка открывается, а система мертва»: рассылки не уходят, шаги
воронок не отправляются, сроки в сценариях не подметаются. Единственный признак
— серый значок на `/components`, который ещё надо догадаться открыть.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_repost.webui import runtime_state, supervisor


@pytest.fixture(autouse=True)
def _clean_components():
    """Свой набор компонентов на тест: модульный синглтон иначе протечёт."""
    original = supervisor._components
    supervisor._components = supervisor.RunningComponents()
    yield
    supervisor._components = original


@pytest.fixture
def _broken_telethon():
    """Telethon не поднимается — ровно то, что происходит на стенде."""
    with patch.object(
        supervisor, "build_client",
        side_effect=ConnectionError("Connection to Telegram failed 5 time(s)"),
    ), patch.object(supervisor, "build_extra_clients", return_value=[]), \
            patch.object(supervisor, "start_listeners", new=AsyncMock()):
        yield


@pytest.fixture
def _working_bot():
    bot = MagicMock()
    bot.initialize = AsyncMock()
    bot.start = AsyncMock()
    bot.stop = AsyncMock()
    bot.shutdown = AsyncMock()
    bot.updater.start_polling = AsyncMock()
    bot.updater.stop = AsyncMock()
    with patch.object(supervisor, "build_bot", return_value=bot):
        yield bot


async def test_scheduler_starts_even_when_telethon_is_down(
    _broken_telethon, _working_bot,
):
    """ГЛАВНОЕ. Планировщик — это очередь задач: рассылки, шаги воронок,
    сроки сценариев. Он не должен зависеть от чужой сети."""
    await supervisor.start_components()

    components = supervisor.get_components()
    assert components.scheduler is not None, "планировщик не запущен"
    assert components.tele_client is None
    assert runtime_state.get_component_status()["scheduler"] is True
    assert runtime_state.get_component_status()["listener"] is False

    await supervisor.stop_components()


async def test_queue_worker_is_scheduled_without_telethon(
    _broken_telethon, _working_bot,
):
    """Воркер очереди — единственное, что доставляет уже созданные рассылки.
    Без него они просто не уходят, и владелец узнаёт об этом от подписчиков."""
    await supervisor.start_components()

    jobs = {job.id for job in supervisor.get_components().scheduler.get_jobs()}
    assert "task_queue_worker" in jobs
    assert "flow_sweep_timeouts" in jobs, "сроки в сценариях никто не подметает"

    await supervisor.stop_components()


async def test_telethon_jobs_are_not_scheduled_without_a_client(
    _broken_telethon, _working_bot,
):
    """Джоба, которой нужен Telethon, при его отсутствии не заводится вовсе:
    иначе каждый её проход — трассировка в логе и ноль работы."""
    # Настройки берутся настоящие и правятся копией: подменять `get_settings`
    # заглушкой значит подсунуть планировщику заглушки вместо чисел.
    settings = supervisor.get_settings().model_copy(update={
        "stats_enabled": True,
        "channel_stats_enabled": True,
        "growth_tracking_enabled": True,
    })

    await supervisor.start_components(settings)

    jobs = {job.id for job in supervisor.get_components().scheduler.get_jobs()}
    assert "collect_stats" not in jobs
    assert "channel_stats_job" not in jobs
    assert "collect_growth_snapshot" not in jobs

    await supervisor.stop_components()


async def test_pipeline_tick_is_not_scheduled_without_the_bot(_broken_telethon):
    """Без бота модерации пайплайн-тику некуда отправлять посты."""
    with patch.object(
        supervisor, "build_bot", side_effect=RuntimeError("нет токена"),
    ):
        await supervisor.start_components()

    components = supervisor.get_components()
    jobs = {job.id for job in components.scheduler.get_jobs()}
    assert "pipeline_tick" not in jobs
    assert "task_queue_worker" in jobs, "очередь должна работать и без бота"
    assert runtime_state.get_component_status()["bot"] is False

    await supervisor.stop_components()


async def test_everything_stops_even_if_telethon_never_started(
    _broken_telethon, _working_bot,
):
    """Признак «что-то живо» раньше смотрел только на Telethon, и остановка
    молча пропускала планировщик — он продолжал работать в останавливаемом
    процессе."""
    await supervisor.start_components()
    assert supervisor.get_components().is_running is True

    await supervisor.stop_components()

    components = supervisor.get_components()
    assert components.scheduler is None
    assert components.moderation_bot is None
    assert runtime_state.get_component_status()["scheduler"] is False


# --- видимость сбоев опроса (найдено на стенде 2026-08-18) ---


async def test_polling_failure_marks_the_bot_down():
    """Задача опроса живёт сама по себе, и исключение внутри неё никто не
    читает: asyncio промолчит до сборки мусора, а `/health` продолжит
    показывать бота живым.

    Ровно это и случилось на стенде после перевода на aiogram: опрос
    остановился через двадцать секунд, а система об этом не узнала.
    """
    import asyncio

    runtime_state.set_component_status("bot", True)

    async def _fails():
        raise RuntimeError("Unauthorized")

    task = asyncio.create_task(_fails())
    supervisor._watch_polling(task, "bot", "Бот модерации")
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)  # даём сработать колбэку

    assert runtime_state.get_component_status()["bot"] is False


async def test_polling_stopped_without_error_is_also_noticed():
    """Опрос, завершившийся молча, — тоже неработающий бот."""
    import asyncio

    runtime_state.set_component_status("flow_bots", True)

    async def _quiet():
        return None

    task = asyncio.create_task(_quiet())
    supervisor._watch_polling(task, "flow_bots", "Боты конструктора")
    await task
    await asyncio.sleep(0)

    assert runtime_state.get_component_status()["flow_bots"] is False


async def test_cancelled_polling_is_not_reported_as_a_failure(caplog):
    """Остановка при выключении компонентов — не сбой, и пугать ею не надо.

    Проверяется и СОСТОЯНИЕ, и ЛОГ. Первая версия теста смотрела только на
    состояние и оказалась беззубой: без проверки на отмену обработчик падает
    на `.exception()` ещё до записи состояния, и тест этого не замечал —
    поймано диверсией.
    """
    import asyncio

    runtime_state.set_component_status("bot", True)

    async def _long():
        await asyncio.sleep(60)

    task = asyncio.create_task(_long())
    supervisor._watch_polling(task, "bot", "Бот модерации")
    task.cancel()
    with caplog.at_level("ERROR"):
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    assert runtime_state.get_component_status()["bot"] is True
    assert not [r for r in caplog.records if r.levelname == "ERROR"], (
        "отмена не должна выглядеть как поломка"
    )

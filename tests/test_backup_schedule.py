"""Резервные копии делаются сами (разбор архитектуры 2026-08-18).

НАЙДЕНО НА ЖИВОЙ СИСТЕМЕ. `run_backup` вызывался только из кнопки в админке, а
писались копии в каталог внутри контейнера, не смонтированный наружу. То есть
«хранение 14 последних копий» из кода не работало в Docker ни дня: каждый
деплой стирал их вместе со слоем контейнера. На стенде копий было ноль.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_repost.webui import supervisor


@pytest.fixture(autouse=True)
def _live_components():
    components = supervisor.get_components()
    before = (components.tele_client, components.moderation_bot)
    components.tele_client = object()
    components.moderation_bot = object()
    yield
    components.tele_client, components.moderation_bot = before


def _scheduler_with(settings):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    supervisor._sync_jobs(scheduler, settings)
    return scheduler


def test_backup_job_is_scheduled_by_default():
    """Копия нужна ровно тогда, когда о ней не подумали заранее, — поэтому
    расписание включено по умолчанию, а не «когда владелец вспомнит»."""
    settings = supervisor.get_settings()

    scheduler = _scheduler_with(settings)

    assert settings.backup_enabled is True
    assert scheduler.get_job("daily_backup") is not None


def test_backup_job_can_be_turned_off():
    settings = supervisor.get_settings().model_copy(update={"backup_enabled": False})

    scheduler = _scheduler_with(settings)

    assert scheduler.get_job("daily_backup") is None


def test_backup_job_does_not_depend_on_telegram():
    """Копия — про сохранность данных, а не про доставку. Отвалившийся
    Telegram не повод перестать беречь базу."""
    components = supervisor.get_components()
    components.tele_client = None
    components.moderation_bot = None
    settings = supervisor.get_settings()

    scheduler = _scheduler_with(settings)

    assert scheduler.get_job("daily_backup") is not None


async def test_backup_failure_does_not_kill_the_scheduler():
    """Сбой копии не должен уносить остальные джобы: к резервным копиям они
    отношения не имеют."""
    with patch(
        "tg_repost.tools.backup.run_backup", side_effect=RuntimeError("диск полон"),
    ):
        await supervisor._run_backup_job(14)  # не бросает


async def test_backup_runs_off_the_event_loop():
    """`run_backup` читает файлы базы и жмёт архив — это секунды блокирующей
    работы. В общем цикле она задержала бы и админку, и опрос ботов."""
    archive = MagicMock()
    archive.name = "backup_test.zip"
    with patch("tg_repost.tools.backup.run_backup", return_value=archive), \
            patch.object(supervisor.asyncio, "to_thread", new=AsyncMock(
                return_value=archive)) as to_thread:
        await supervisor._run_backup_job(14)

    assert to_thread.await_count == 1


def test_backups_directory_is_mounted_out_of_the_container():
    """САМА ПРИЧИНА ВСЕЙ ПРАВКИ. Копии внутри слоя контейнера исчезают при
    каждом `up --force-recreate`, то есть при каждом обновлении системы."""
    import pathlib

    compose = pathlib.Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "./data/backups:/app/backups" in compose

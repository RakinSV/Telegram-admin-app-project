"""Тесты порядка старта процесса (`tg_repost.main.run`).

Главный инвариант Фазы 5: веб-админка поднимается ВСЕГДА и переживает любые
проблемы с Telegram. Иначе при недоступности Telegram (провайдер режет, не
поднялся прокси, сервер только что перезагрузился) контейнер уходит в
crash-loop — и вместе с ним пропадает единственное место, где эту проблему
чинят: настройки прокси, сессии и токенов.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from tg_repost import main as main_module


class _FakeServer:
    """Уводит `uvicorn.Server.serve()` в управляемую задачу вместо сети."""

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.should_exit = False
        self.served = asyncio.Event()

    async def serve(self) -> None:
        self.served.set()
        # Держим «веб-сервер» живым ровно до отмены из run()/теста.
        await asyncio.Event().wait()


class _StubSettings:
    """Минимум, который читает `run()`: уровень логов и признак настроенности."""

    log_level = "WARNING"

    def __init__(self, configured: bool) -> None:
        self.is_minimally_configured = configured


@pytest.fixture
def _fake_web(monkeypatch):
    created: list[_FakeServer] = []

    def _factory(*args, **kwargs):
        server = _FakeServer(*args, **kwargs)
        created.append(server)
        return server

    monkeypatch.setattr(main_module.uvicorn, "Server", _factory)
    monkeypatch.setattr(main_module.uvicorn, "Config", lambda *a, **k: object())
    monkeypatch.setattr(main_module, "create_app", lambda: object())
    monkeypatch.setattr(main_module, "is_bootstrapped", lambda: True)
    monkeypatch.setattr(main_module, "setup_logging", lambda level: None)
    monkeypatch.setattr(main_module, "stop_components", _noop_async)
    return created


async def _noop_async(*args, **kwargs) -> None:
    del args, kwargs


def _configure(monkeypatch, *, configured: bool) -> None:
    monkeypatch.setattr(main_module, "get_settings", lambda: _StubSettings(configured))


async def _run_briefly(seconds: float = 0.15) -> None:
    """Дать `run()` доработать до ожидания веб-задачи и корректно свернуть.

    `run()` намеренно ГЛОТАЕТ CancelledError (штатное завершение по сигналу —
    не ошибка) и уходит в finally останавливать Telegram-часть, поэтому
    исключения здесь ждать не надо.
    """
    task = asyncio.create_task(main_module.run())
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_web_admin_survives_telegram_connection_failure(_fake_web, monkeypatch, caplog):
    """Регрессия с реального деплоя: ConnectionError из start_components
    долетал до run() и убивал ВЕСЬ процесс — админка исчезала ровно тогда,
    когда была нужнее всего."""
    async def _boom(settings):
        del settings
        raise ConnectionError("Connection to Telegram failed 5 time(s)")

    monkeypatch.setattr(main_module, "start_components", _boom)
    _configure(monkeypatch, configured=True)

    await _run_briefly()

    assert _fake_web, "веб-сервер вообще не создавался"
    assert _fake_web[0].served.is_set(), "веб-сервер не успел стартовать"
    assert "Не удалось запустить Telegram-компоненты" in caplog.text


@pytest.mark.asyncio
async def test_web_admin_starts_before_telegram_components(_fake_web, monkeypatch):
    """Порядок важен: сначала веб, потом Telegram. Иначе долгий (или вечный)
    коннект к Telegram задерживает подъём админки."""
    order: list[str] = []

    async def _record(settings):
        del settings
        order.append("components")

    monkeypatch.setattr(main_module, "start_components", _record)
    _configure(monkeypatch, configured=True)

    await _run_briefly()

    assert _fake_web[0].served.is_set()
    assert order == ["components"]


@pytest.mark.asyncio
async def test_telegram_components_skipped_when_not_configured(_fake_web, monkeypatch):
    called: list[str] = []

    async def _record(settings):
        del settings
        called.append("components")

    monkeypatch.setattr(main_module, "start_components", _record)
    _configure(monkeypatch, configured=False)

    await _run_briefly()

    assert called == []
    assert _fake_web[0].served.is_set()  # админка всё равно поднялась

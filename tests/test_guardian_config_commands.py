"""Тесты команд конфигурации через бота (G13): /setmode /setwarn /setcaptcha
/setmutime — альтернатива веб-панели, пишут через тот же settings_store."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from guardian.config import get_guardian_settings, invalidate_settings_cache
from guardian.db.models import BotConfig
from guardian.db.session import session_scope
from guardian.handlers import admin as admin_module


@pytest.fixture(autouse=True)
def _isolated():
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()


def _cmd(args: str) -> SimpleNamespace:
    return SimpleNamespace(args=args)


async def test_setmode_valid_value(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setmode(message, _cmd("hybrid"), AsyncMock())
    assert get_guardian_settings().spam_mode == "hybrid"
    message.reply.assert_awaited_once()


async def test_setmode_invalid_value_rejected(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setmode(message, _cmd("hybird"), AsyncMock())
    assert get_guardian_settings().spam_mode == "keywords"  # не изменилось
    reply_text = message.reply.call_args.args[0]
    assert "keywords" in reply_text


async def test_setcaptcha_valid_value(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setcaptcha(message, _cmd("button"), AsyncMock())
    assert get_guardian_settings().captcha_type == "button"


async def test_setwarn_ascending_thresholds(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setwarn(message, _cmd("2 3 4"), AsyncMock())
    settings = get_guardian_settings()
    assert (
        settings.warn_threshold_mute,
        settings.warn_threshold_kick,
        settings.warn_threshold_ban,
    ) == (2, 3, 4)


async def test_setwarn_rejects_non_ascending(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setwarn(message, _cmd("5 3 4"), AsyncMock())
    reply_text = message.reply.call_args.args[0]
    assert "возрастан" in reply_text
    settings = get_guardian_settings()
    assert settings.warn_threshold_mute == 2  # дефолт не тронут


async def test_setwarn_rejects_non_numeric(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setwarn(message, _cmd("a b c"), AsyncMock())
    reply_text = message.reply.call_args.args[0]
    assert "Использование" in reply_text


async def test_setmutime_valid(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setmutime(message, _cmd("5"), AsyncMock())
    assert get_guardian_settings().mute_duration_hours == 5
    reply_text = message.reply.call_args.args[0]
    assert "ч." in reply_text


async def test_setmutime_rejects_zero_or_negative(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_setmutime(message, _cmd("0"), AsyncMock())
    assert get_guardian_settings().mute_duration_hours == 1  # дефолт не тронут


async def test_config_commands_denied_for_non_admin(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=None))
    message = AsyncMock()
    await admin_module.cmd_setmode(message, _cmd("hybrid"), AsyncMock())
    assert get_guardian_settings().spam_mode == "keywords"

"""Тесты тихих часов / режима строгости (G16)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from guardian import settings_store
from guardian.bot import _apply_quiet_hours_schedule
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


def test_schedule_disabled_by_default_leaves_strict_mode_untouched():
    settings_store.save_setting("strict_mode", False, "bool")
    _apply_quiet_hours_schedule()
    assert get_guardian_settings().strict_mode is False  # не тронуто — расписание выключено


def test_schedule_sets_strict_during_quiet_window_same_day():
    settings_store.save_setting("quiet_hours_enabled", True, "bool")
    settings_store.save_setting("quiet_hours_start_hour", 10, "int")
    settings_store.save_setting("quiet_hours_end_hour", 14, "int")
    settings_store.save_setting("strict_mode", False, "bool")

    now = datetime.now(timezone.utc).replace(hour=12)
    import guardian.bot as bot_module

    original = bot_module.datetime

    class _FixedDatetime(original):
        @classmethod
        def now(cls, tz=None):
            return now

    bot_module.datetime = _FixedDatetime
    try:
        _apply_quiet_hours_schedule()
    finally:
        bot_module.datetime = original

    assert get_guardian_settings().strict_mode is True


def test_schedule_sets_soft_outside_quiet_window_same_day():
    settings_store.save_setting("quiet_hours_enabled", True, "bool")
    settings_store.save_setting("quiet_hours_start_hour", 10, "int")
    settings_store.save_setting("quiet_hours_end_hour", 14, "int")
    settings_store.save_setting("strict_mode", True, "bool")

    now = datetime.now(timezone.utc).replace(hour=20)
    import guardian.bot as bot_module

    original = bot_module.datetime

    class _FixedDatetime(original):
        @classmethod
        def now(cls, tz=None):
            return now

    bot_module.datetime = _FixedDatetime
    try:
        _apply_quiet_hours_schedule()
    finally:
        bot_module.datetime = original

    assert get_guardian_settings().strict_mode is False


def test_schedule_handles_window_crossing_midnight():
    # 22:00 -> 08:00 — типичный пример из спецификации G16.
    settings_store.save_setting("quiet_hours_enabled", True, "bool")
    settings_store.save_setting("quiet_hours_start_hour", 22, "int")
    settings_store.save_setting("quiet_hours_end_hour", 8, "int")

    import guardian.bot as bot_module

    original = bot_module.datetime

    for hour, expected in ((23, True), (2, True), (7, True), (8, False), (12, False), (21, False)):

        class _FixedDatetime(original):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(timezone.utc).replace(hour=hour)

        bot_module.datetime = _FixedDatetime
        try:
            _apply_quiet_hours_schedule()
        finally:
            bot_module.datetime = original
        assert get_guardian_settings().strict_mode is expected, hour


def _cmd(args: str) -> SimpleNamespace:
    return SimpleNamespace(args=args)


async def test_cmd_mode_strict(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_mode(message, _cmd("strict"), AsyncMock())
    assert get_guardian_settings().strict_mode is True


async def test_cmd_mode_soft(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_mode(message, _cmd("soft"), AsyncMock())
    assert get_guardian_settings().strict_mode is False


async def test_cmd_mode_rejects_invalid_value(monkeypatch):
    monkeypatch.setattr(admin_module, "_require_admin", AsyncMock(return_value=1))
    message = AsyncMock()
    await admin_module.cmd_mode(message, _cmd("bred"), AsyncMock())
    reply_text = message.reply.call_args.args[0]
    assert "strict|soft" in reply_text

"""Тесты /stats и /growth (G11/G17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from guardian.db.models import DailyStats, ModerationLog
from guardian.db.session import session_scope
from guardian.handlers import stats as stats_module
from guardian.services import daily_stats_repo

CHAT_ID = -100123


@pytest.fixture(autouse=True)
def _clear_tables():
    with session_scope() as session:
        session.query(DailyStats).delete()
        session.query(ModerationLog).delete()
    yield


def test_parse_period_known_values():
    assert stats_module._parse_period("день") == ("день", 1)
    assert stats_module._parse_period("неделя") == ("неделя", 7)
    assert stats_module._parse_period("месяц") == ("месяц", 30)


def test_parse_period_unknown_falls_back_to_week():
    assert stats_module._parse_period("") == ("неделя", 7)
    assert stats_module._parse_period("бред") == ("неделя", 7)


def test_format_stats_text_includes_all_sections():
    totals = {
        "deleted_msgs": 47, "warnings": 23, "mutes": 4, "kicks": 1, "bans": 2,
        "new_members": 41, "verified_members": 38, "ai_calls": 156, "ai_cost_usd": 0.18,
    }
    text = stats_module.format_stats_text("неделя", totals, [("купить", 12), ("заработок", 8)])
    assert "Удалено сообщений: 47" in text
    assert "Выдано варнов: 23" in text
    assert "Мутов: 4, Банов: 2, Киков: 1" in text
    assert "38/41 (93%)" in text
    assert "«купить» x12" in text
    assert "AI-вызовов: 156, стоимость: ~$0.18" in text


def test_format_stats_text_omits_empty_sections():
    totals = {
        "deleted_msgs": 0, "warnings": 0, "mutes": 0, "kicks": 0, "bans": 0,
        "new_members": 0, "verified_members": 0, "ai_calls": 0, "ai_cost_usd": 0.0,
    }
    text = stats_module.format_stats_text("день", totals, [])
    assert "верификац" not in text
    assert "AI-вызовов" not in text
    assert "Стоп-слова" not in text


def test_sparkline_shape():
    line = stats_module._sparkline([0, 1, 5, 10])
    assert len(line) == 4
    assert line[0] == "▁"  # минимум
    assert line[-1] == "█"  # максимум


def test_sparkline_empty_input():
    assert stats_module._sparkline([]) == ""


def test_format_growth_text_conversion_rate():
    today = datetime.now(timezone.utc).date()
    rows = [
        SimpleNamespace(date=today - timedelta(days=1), new_members=10, verified_members=8),
        SimpleNamespace(date=today, new_members=5, verified_members=5),
    ]
    text = stats_module.format_growth_text("неделя", rows)
    assert "Новых: 15" in text
    assert "13/15" in text
    assert "87%" in text


async def test_cmd_stats_replies_with_formatted_text(monkeypatch):
    monkeypatch.setattr(stats_module, "_require_admin", AsyncMock(return_value=111))
    with session_scope() as session:
        session.add(
            ModerationLog(action="ban", user_id=1, chat_id=CHAT_ID, created_at=datetime.now(timezone.utc))
        )

    message = AsyncMock()
    message.chat = SimpleNamespace(id=CHAT_ID)
    command = SimpleNamespace(args="неделя")
    bot = AsyncMock()

    await stats_module.cmd_stats(message, command, bot)

    message.reply.assert_awaited_once()
    reply_text = message.reply.call_args.args[0]
    assert "Банов: 1" in reply_text


async def test_cmd_stats_denied_for_non_admin(monkeypatch):
    monkeypatch.setattr(stats_module, "_require_admin", AsyncMock(return_value=None))
    message = AsyncMock()
    message.chat = SimpleNamespace(id=CHAT_ID)
    command = SimpleNamespace(args="")
    bot = AsyncMock()

    await stats_module.cmd_stats(message, command, bot)

    message.reply.assert_not_awaited()


async def test_cmd_growth_replies_with_sparkline(monkeypatch):
    monkeypatch.setattr(stats_module, "_require_admin", AsyncMock(return_value=111))
    message = AsyncMock()
    message.chat = SimpleNamespace(id=CHAT_ID)
    command = SimpleNamespace(args="неделя")
    bot = AsyncMock()

    await stats_module.cmd_growth(message, command, bot)

    message.reply.assert_awaited_once()
    assert "Прирост участников" in message.reply.call_args.args[0]

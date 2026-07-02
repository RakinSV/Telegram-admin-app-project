"""Тесты эвристик подозрительности Guardian (G10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from guardian.filters.heuristics import count_suspicion_signals


def _msg(text: str = "", forward_origin=None) -> SimpleNamespace:
    return SimpleNamespace(text=text, caption=None, forward_origin=forward_origin)


def test_no_signals_on_plain_message():
    assert count_suspicion_signals(_msg("Привет, как дела?"), None) == 0


def test_price_signal():
    assert count_suspicion_signals(_msg("Продам за 500₽"), None) == 1


def test_dm_phrase_signal():
    assert count_suspicion_signals(_msg("Пиши в личку для деталей"), None) == 1


def test_zero_width_signal():
    text = "заработок" + chr(0x200B) + "тест"
    assert count_suspicion_signals(_msg(text), None) == 1


def test_forward_signal():
    assert count_suspicion_signals(_msg("обычный текст", forward_origin=object()), None) == 1


def test_new_member_signal():
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    assert count_suspicion_signals(_msg("обычный текст"), recent) == 1


def test_new_member_signal_handles_naive_datetime():
    """SQLite отдаёт наивные datetime для DateTime(timezone=True) — известная
    ловушка проекта (см. smart_schedule.py). Функция обязана не падать и
    интерпретировать наивное значение как UTC."""
    recent_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    assert count_suspicion_signals(_msg("обычный текст"), recent_naive) == 1


def test_old_member_no_signal():
    old = datetime.now(timezone.utc) - timedelta(days=30)
    assert count_suspicion_signals(_msg("обычный текст"), old) == 0


def test_multiple_signals_accumulate():
    text = "Продам за 500$, пиши в личку"
    assert count_suspicion_signals(_msg(text), None) == 2


def test_all_signals_at_once():
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    text = "Продам за 500$, пиши в личку" + chr(0x200B)
    assert count_suspicion_signals(_msg(text, forward_origin=object()), recent) == 5

"""Тесты вспомогательных чистых функций публикации (F08)."""

from __future__ import annotations

from telegram.error import RetryAfter, TimedOut

from tg_repost.telegram.publisher import _retry_after_delay


def test_retry_after_delay_extracts_retry_after_seconds():
    exc = RetryAfter(retry_after=30)
    assert _retry_after_delay(exc) == 30


def test_retry_after_delay_returns_none_for_unrelated_exceptions():
    assert _retry_after_delay(TimedOut()) is None
    assert _retry_after_delay(ValueError("network error")) is None

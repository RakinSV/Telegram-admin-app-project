"""Тесты retry_async (F10) — экспоненциальный backoff + delay_override для
исключений, которые сами говорят, сколько ждать (RetryAfter/flood-wait)."""

from __future__ import annotations

import pytest

from tg_repost.retry import retry_async


async def test_retry_async_returns_on_first_success():
    async def _ok():
        return "done"

    assert await retry_async(_ok, attempts=3) == "done"


async def test_retry_async_retries_then_succeeds():
    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("temporary")
        return "ok"

    result = await retry_async(_flaky, attempts=3, base_delay=0.001)
    assert result == "ok"
    assert calls["n"] == 2


async def test_retry_async_raises_last_exception_after_exhausting_attempts():
    async def _always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        await retry_async(_always_fails, attempts=2, base_delay=0.001)


async def test_retry_async_rejects_zero_attempts():
    async def _noop():
        return None

    with pytest.raises(ValueError):
        await retry_async(_noop, attempts=0)


async def test_delay_override_used_when_provided(monkeypatch):
    # Регрессия (security-ревью): RetryAfter/flood-wait игнорировался
    # фиксированным backoff'ом — delay_override должен реально управлять
    # паузой, не только вычисляться и отбрасываться.
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", _fake_sleep)

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("flood")
        return "ok"

    await retry_async(
        _flaky, attempts=3, base_delay=1.0,
        delay_override=lambda exc: 42.0,
    )
    assert slept == [42.0]


async def test_delay_override_not_capped_by_max_delay(monkeypatch):
    # Telegram лучше знает, сколько реально нужно ждать — искусственный
    # потолок max_delay не должен обрезать явно указанную паузу.
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", _fake_sleep)

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("flood")
        return "ok"

    await retry_async(
        _flaky, attempts=3, base_delay=1.0, max_delay=5.0,
        delay_override=lambda exc: 120.0,
    )
    assert slept == [120.0]


async def test_delay_override_falls_back_to_backoff_when_none(monkeypatch):
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", _fake_sleep)

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("not flood-related")
        return "ok"

    await retry_async(
        _flaky, attempts=3, base_delay=1.0,
        delay_override=lambda exc: None,  # эта ошибка не про flood-wait
    )
    assert slept == [1.0]  # обычный base_delay, не override

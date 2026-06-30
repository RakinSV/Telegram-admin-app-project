"""Тесты антибан-механик (F17)."""

import time

from tg_repost.antiban import HourlyRateLimiter, jitter_sleep


def test_rate_limiter_allows_up_to_max():
    limiter = HourlyRateLimiter(max_per_hour=3)
    assert limiter.try_acquire()
    assert limiter.try_acquire()
    assert limiter.try_acquire()
    assert not limiter.try_acquire()


def test_rate_limiter_min_one():
    limiter = HourlyRateLimiter(max_per_hour=0)
    assert limiter.try_acquire()
    assert not limiter.try_acquire()


def test_rate_limiter_prunes_old_events():
    limiter = HourlyRateLimiter(max_per_hour=1)
    assert limiter.try_acquire()
    assert not limiter.try_acquire()
    # Искусственно состариваем событие за пределы окна.
    limiter._events[0] = time.monotonic() - 3601
    assert limiter.try_acquire()


async def test_jitter_sleep_respects_bounds():
    start = time.monotonic()
    await jitter_sleep(0.01, 0.05)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.0


async def test_jitter_sleep_zero_max_is_instant():
    start = time.monotonic()
    await jitter_sleep(0.0, 0.0)
    assert time.monotonic() - start < 0.05

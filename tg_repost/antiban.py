"""Антибан-механики для Telethon юзер-сессии (F17).

Telethon работает от имени юзер-аккаунта, поэтому агрессивный паттерн запросов
(резкие пики, мгновенная обработка пачки сообщений, частые скачивания медиа)
рискует привлечь антиспам Telegram. Здесь — рандомизированные паузы (джиттер)
и почасовой лимит «тяжёлых» действий.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


async def jitter_sleep(min_seconds: float, max_seconds: float) -> None:
    """Случайная пауза в диапазоне [min, max] секунд."""
    if max_seconds <= 0:
        return
    low = max(0.0, min(min_seconds, max_seconds))
    high = max(min_seconds, max_seconds)
    delay = random.uniform(low, high)
    await asyncio.sleep(delay)


class HourlyRateLimiter:
    """Скользящее окно на 1 час: не более `max_per_hour` действий.

    `acquire()` блокирует (ждёт), пока не освободится слот в окне — так
    «тяжёлые» действия (скачивание медиа, резолв сущностей) не превышают лимит.
    """

    def __init__(self, max_per_hour: int) -> None:
        self._max = max(1, max_per_hour)
        self._window = 3600.0
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0] >= self._window:
            self._events.popleft()

    def try_acquire(self) -> bool:
        """Неблокирующе занять слот. True — успех, False — лимит исчерпан."""
        now = time.monotonic()
        self._prune(now)
        if len(self._events) >= self._max:
            return False
        self._events.append(now)
        return True

    async def acquire(self) -> None:
        """Дождаться свободного слота и занять его."""
        while True:
            now = time.monotonic()
            self._prune(now)
            if len(self._events) < self._max:
                self._events.append(now)
                return
            wait = self._window - (now - self._events[0]) + 0.01
            logger.warning(
                "Достигнут лимит %d действий/час — пауза %.0f с", self._max, wait
            )
            await asyncio.sleep(max(1.0, wait))

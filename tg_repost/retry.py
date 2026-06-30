"""Ретрай сетевых вызовов с экспоненциальной задержкой (F10).

Лёгкая собственная реализация без внешних зависимостей — для обёртки вызовов
Telegram API и LLM API, которые могут давать временные сбои.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    description: str = "операция",
) -> T:
    """Выполнить корутину с ретраями и экспоненциальным backoff.

    Бросает последнее исключение, если все попытки исчерпаны.
    """
    if attempts < 1:
        raise ValueError(f"attempts должно быть >= 1, получено {attempts}")

    delay = base_delay
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except exceptions as exc:  # noqa: BLE001 — намеренно широкий по умолчанию
            last_exc = exc
            if attempt == attempts:
                logger.error("%s: попытка %d/%d провалена окончательно: %s",
                             description, attempt, attempts, exc)
                break
            logger.warning("%s: попытка %d/%d не удалась (%s), повтор через %.1f с",
                           description, attempt, attempts, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    if last_exc is None:
        # Недостижимо при attempts >= 1: цикл либо вернул значение, либо
        # установил last_exc. Явная проверка вместо assert — assert вырезается
        # при запуске с `python -O`, и `raise None` дал бы непонятный TypeError.
        raise RuntimeError("retry_async: внутренняя ошибка — нет ни результата, ни исключения")
    raise last_exc

"""Ретрай сетевых вызовов с экспоненциальной задержкой (F10).

Лёгкая собственная реализация без внешних зависимостей — для обёртки вызовов
Telegram API и LLM API, которые могут давать временные сбои.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tg_repost.logging_conf import get_logger, sanitize_proxy_error

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
    delay_override: Callable[[BaseException], float | None] | None = None,
) -> T:
    """Выполнить корутину с ретраями и экспоненциальным backoff.

    `delay_override` — хук для исключений, которые сами говорят, сколько
    ждать (например `telegram.error.RetryAfter.retry_after` — flood-wait от
    самого Telegram). Если возвращает не-`None` — используется ЭТА пауза
    вместо экспоненциальной, БЕЗ ограничения `max_delay` (Telegram лучше
    знает, сколько реально нужно ждать; искусственный потолок в 30с иначе
    мог бы дать повторную попытку раньше, чем разрешено, и снова словить
    flood-wait — найдено security-ревью: `retry_async`'s фиксированный
    backoff игнорировал `RetryAfter` целиком).

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
            # Ошибка МОЖЕТ быть сбоем подключения через BOT_API_PROXY_URL
            # (socks5://user:pass@host:port) — httpx/socksio не гарантируют,
            # что их исключения никогда не отразят URL целиком (найдено
            # security-ревью).
            safe_exc = sanitize_proxy_error(str(exc))
            if attempt == attempts:
                logger.error("%s: попытка %d/%d провалена окончательно: %s",
                             description, attempt, attempts, safe_exc)
                break
            override = delay_override(exc) if delay_override else None
            wait_for = override if override is not None else delay
            logger.warning("%s: попытка %d/%d не удалась (%s), повтор через %.1f с",
                           description, attempt, attempts, safe_exc, wait_for)
            await asyncio.sleep(wait_for)
            delay = min(delay * 2, max_delay)

    if last_exc is None:
        # Недостижимо при attempts >= 1: цикл либо вернул значение, либо
        # установил last_exc. Явная проверка вместо assert — assert вырезается
        # при запуске с `python -O`, и `raise None` дал бы непонятный TypeError.
        raise RuntimeError("retry_async: внутренняя ошибка — нет ни результата, ни исключения")
    raise last_exc

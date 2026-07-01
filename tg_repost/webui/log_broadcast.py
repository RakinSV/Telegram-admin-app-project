"""Стриминг логов в браузер через SSE, не WebSocket (F23, Фаза 5.4).

Поток строго однонаправленный (сервер → браузер) — SSE даёт браузеру
авто-реконнект бесплатно (`EventSource`) и требует меньше кода, чем WebSocket
(не нужен ConnectionManager/ping-pong). Кастомный `logging.Handler`
регистрируется в `setup_logging()` рядом со `StreamHandler`/
`RotatingFileHandler` (см. `logging_conf.py`) — пишет каждую запись в
ring-buffer (история для только что открытых вкладок) и рассылает в очереди
живых подписчиков (`/logs/stream`).

Весь процесс (Telethon listener/бот/планировщик/uvicorn) живёт в ОДНОМ
asyncio event loop в ОДНОМ потоке (архитектурное решение Фазы 5 — веб-сервер
встроен в тот же процесс, а не отдельный, см. план) — поэтому `emit()`
гарантированно вызывается из event-loop-потока, и `asyncio.Queue` здесь
безопасна без cross-thread синхронизации.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator

_BUFFER_SIZE = 1000
# deque(maxlen=...) и Queue(maxsize=...) ограничивают ЧИСЛО строк, но не их
# длину — запись со сколь угодно длинным сообщением (например, если когда-то
# в коде появится logger.info(..., raw_untrusted_text) без обрезки) может
# раздуть суммарный объём ring-buffer'а и очередей подписчиков далеко за
# расчётный бюджет "1000 строк". Обрезаем на входе, как и `audit.py`
# обрезает `detail` (см. `_MAX_DETAIL_LEN` там) — найдено при security-ревью
# Фазы 5.4.
_MAX_LINE_LEN = 4000

_buffer: deque[str] = deque(maxlen=_BUFFER_SIZE)
_subscribers: set[asyncio.Queue[str]] = set()


class SSELogHandler(logging.Handler):
    """Хендлер логирования, рассылающий записи подписчикам `/logs/stream`."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001 — хендлер логирования не должен падать
            return
        if len(msg) > _MAX_LINE_LEN:
            msg = msg[:_MAX_LINE_LEN] + "…[обрезано]"
        _buffer.append(msg)
        for queue in list(_subscribers):
            _push_drop_oldest(queue, msg)


def _push_drop_oldest(queue: asyncio.Queue[str], msg: str) -> None:
    """Положить сообщение в очередь подписчика, вытеснив старейшее при
    переполнении — лучше потерять строку, чем заблокировать `emit()`."""
    try:
        queue.put_nowait(msg)
    except asyncio.QueueFull:
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(msg)


def recent_logs() -> list[str]:
    """Последние сохранённые строки лога (для первичной отрисовки `/logs`)."""
    return list(_buffer)


@contextlib.asynccontextmanager
async def subscription() -> AsyncIterator[asyncio.Queue[str]]:
    """Зарегистрировать подписчика на новые строки лога и отдать саму очередь
    (а не обёрнутый в асинхронный генератор итератор) — вызывающий код сам
    делает `await asyncio.wait_for(queue.get(), timeout=...)` для heartbeat.

    ВАЖНО: раньше здесь был асинхронный генератор (`async def subscribe() ->
    AsyncIterator[str]: ... yield await queue.get()`), и `/logs/stream`
    оборачивал каждый вызов `gen.__anext__()` в `asyncio.wait_for(...)` для
    периодического heartbeat при отсутствии новых строк. Это ломало поток:
    таймаут `wait_for` отменяет обёрнутую задачу — отмена бросает
    `CancelledError` ВНУТРЬ тела генератора (в точке `await queue.get()`),
    что проходит через `finally` генератора (снятие подписки) и ЗАКРЫВАЕТ
    его — следующий `gen.__anext__()` на уже закрытом генераторе сразу
    бросает `StopAsyncIteration`, необработанное в `/logs/stream`, обрывая
    соединение при первом же периоде тишины (>15с без новых логов — обычное
    дело при низком трафике одного админа). Воспроизведено эмпирически при
    ревью Фазы 5.4. `asyncio.Queue.get()`, в отличие от async-generator
    `__anext__()`, безопасно переживает отмену через `wait_for` — это
    штатный идиоматичный паттерн опроса очереди с таймаутом в asyncio,
    поэтому очередь отдаётся напрямую.
    """
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_BUFFER_SIZE)
    _subscribers.add(queue)
    try:
        yield queue
    finally:
        _subscribers.discard(queue)

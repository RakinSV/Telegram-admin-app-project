"""Тесты SSE-рассылки логов веб-админки (F23, Фаза 5.4)."""

import asyncio
import logging

import pytest

from tg_repost.webui import log_broadcast


@pytest.fixture(autouse=True)
def _isolated_state():
    """Изоляция: `_buffer`/`_subscribers` — модульные синглтоны."""
    log_broadcast._buffer.clear()
    log_broadcast._subscribers.clear()
    yield
    log_broadcast._buffer.clear()
    log_broadcast._subscribers.clear()


def _make_record(msg: str = "тест", args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


def test_emit_appends_to_buffer():
    handler = log_broadcast.SSELogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_make_record("привет"))
    assert log_broadcast.recent_logs() == ["привет"]


def test_buffer_maxlen_matches_constant():
    assert log_broadcast._buffer.maxlen == log_broadcast._BUFFER_SIZE


def test_emit_truncates_oversized_line():
    """deque(maxlen=...)/Queue(maxsize=...) ограничивают ЧИСЛО строк, но не
    их длину — без явной обрезки одна аномально длинная запись (например,
    необрезанный untrusted-текст поста в будущем logger-вызове) может раздуть
    суммарный объём буфера/очередей далеко за расчётный бюджет. Найдено при
    security-ревью Фазы 5.4."""
    handler = log_broadcast.SSELogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_make_record("x" * 10_000))
    line = log_broadcast.recent_logs()[0]
    assert len(line) == log_broadcast._MAX_LINE_LEN + len("…[обрезано]")
    assert line.endswith("…[обрезано]")


def test_emit_broadcasts_to_subscriber_queue():
    handler = log_broadcast.SSELogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)
    log_broadcast._subscribers.add(queue)

    handler.emit(_make_record("событие"))

    assert queue.get_nowait() == "событие"


def test_emit_handles_formatting_errors_without_raising():
    handler = log_broadcast.SSELogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    # msg без плейсхолдеров + непустой args -> record.getMessage() внутри
    # format() бросает TypeError ("not all arguments converted").
    bad_record = _make_record("сообщение без плейсхолдеров", args=("лишний аргумент",))
    handler.emit(bad_record)  # не должно бросить
    assert log_broadcast.recent_logs() == []


async def test_subscription_yields_new_messages():
    handler = log_broadcast.SSELogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    async with log_broadcast.subscription() as queue:
        task = asyncio.ensure_future(queue.get())
        await asyncio.sleep(0)  # дать подписке зарегистрироваться в _subscribers
        handler.emit(_make_record("живое сообщение"))

        result = await asyncio.wait_for(task, timeout=1.0)
        assert result == "живое сообщение"


async def test_subscription_cleans_up_subscriber_on_exit():
    async with log_broadcast.subscription() as queue:
        assert queue in log_broadcast._subscribers
        assert len(log_broadcast._subscribers) == 1
    assert len(log_broadcast._subscribers) == 0


async def test_subscription_survives_repeated_wait_for_timeouts():
    """Регрессия: раньше подписка была асинхронным генератором
    (`subscribe()`), и `/logs/stream` оборачивал каждый `gen.__anext__()` в
    `asyncio.wait_for(..., timeout=...)` для heartbeat при простое. Таймаут
    `wait_for` отменяет обёрнутую задачу — отмена бросает `CancelledError`
    ВНУТРЬ тела генератора, что проходит через его `finally` (снятие
    подписки) и ЗАКРЫВАЕТ генератор; следующий `__anext__()` на закрытом
    генераторе сразу бросает `StopAsyncIteration` — соединение обрывалось
    при первом же периоде тишины >heartbeat (обычное дело при низком
    трафике одного админа). Воспроизведено эмпирически при ревью Фазы 5.4.
    `subscription()` отдаёт саму очередь — `asyncio.Queue.get()`, в отличие
    от `__anext__()` async-генератора, штатно переживает отмену через
    `wait_for` и может опрашиваться повторно сколько угодно раз."""
    async with log_broadcast.subscription() as queue:
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.05)

        handler = log_broadcast.SSELogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record("после нескольких таймаутов"))
        result = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert result == "после нескольких таймаутов"


def test_push_drop_oldest_when_full():
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
    queue.put_nowait("first")
    queue.put_nowait("second")

    log_broadcast._push_drop_oldest(queue, "third")

    remaining = [queue.get_nowait(), queue.get_nowait()]
    assert remaining == ["second", "third"]

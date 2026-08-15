"""Очередь долгих задач с курсором (фаза 11).

Тесты выстроены вокруг четырёх свойств, ради которых очередь и существует.
Если какое-то из них сломается, F64 (рассылки) отправит сообщения дважды
или потеряет половину получателей — а узнается это на живой аудитории.

1. возобновляемость после обрыва (курсор);
2. отложенный запуск (`run_after`);
3. переживание падения процесса (аренда);
4. ограниченные повторы.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import task_queue
from tg_repost.db.models import QueuedTask
from tg_repost.db.session import session_scope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(QueuedTask).delete()
        task_queue._handlers.clear()

    _wipe()
    yield
    _wipe()


async def _noop(view):
    """Обработчик-пустышка: работа закончена сразу."""
    return None


async def _always_more(view):
    """Никогда не заканчивается — для проверки предохранителя."""
    return "всегда есть ещё"


def _collect(bucket):
    async def _handler(view):
        bucket.append(view.payload)
        return None
    return _handler


def _collect_tag(bucket):
    async def _handler(view):
        bucket.append(view.payload["tag"])
        return None
    return _handler


def _collect_const(bucket, value):
    async def _handler(view):
        bucket.append(value)
        return None
    return _handler


def _task(task_id: int) -> QueuedTask:
    with session_scope() as session:
        row = session.get(QueuedTask, task_id)
        assert row is not None
        session.expunge(row)
        return row


# --- базовая механика ---


async def test_enqueue_and_run():
    seen: list[str] = []

    async def _handler(view):
        seen.append(view.payload["who"])
        return None  # работа закончена

    task_queue.register("greet", _handler)
    task_id = task_queue.enqueue("greet", {"who": "мир"})

    assert await task_queue.run_once() is True
    assert seen == ["мир"]
    assert _task(task_id).status == task_queue.STATUS_DONE


async def test_run_once_returns_false_on_empty_queue():
    assert await task_queue.run_once() is False


async def test_payload_survives_roundtrip_with_unicode():
    got: list[dict] = []
    task_queue.register("echo", _collect(got))
    task_queue.enqueue("echo", {"текст": "привет, мир", "n": 42})

    await task_queue.run_once()

    assert got == [{"текст": "привет, мир", "n": 42}]


def test_tenant_id_defaults_to_one():
    """Ключ арендатора закладывается сразу — решение 1."""
    task_id = task_queue.enqueue("noop")
    assert _task(task_id).tenant_id == 1


# --- свойство 1: возобновляемость ---


async def test_cursor_lets_task_continue_where_it_stopped():
    """Главное свойство очереди.

    Обработчик обрабатывает по одному получателю за проход и отдаёт курсор.
    Задача возвращается в очередь и продолжается, а не начинается заново.
    """
    recipients = ["a", "b", "c"]
    delivered: list[str] = []

    async def _handler(view):
        start = int(view.cursor or 0)
        delivered.append(recipients[start])
        nxt = start + 1
        return None if nxt >= len(recipients) else str(nxt)

    task_queue.register("broadcast", _handler)
    task_id = task_queue.enqueue("broadcast", total_count=3)

    for _ in range(3):
        await task_queue.run_once()

    assert delivered == ["a", "b", "c"]  # каждый ровно один раз
    assert _task(task_id).status == task_queue.STATUS_DONE


async def test_progress_persists_between_runs():
    async def _handler(view):
        view.progress(cursor="42", done_count=42)
        return "42"  # ещё не закончили

    task_queue.register("slow", _handler)
    task_id = task_queue.enqueue("slow")

    await task_queue.run_once()

    row = _task(task_id)
    assert row.cursor == "42"
    assert row.done_count == 42
    assert row.status == task_queue.STATUS_PENDING  # вернулась в очередь


async def test_cursor_is_not_reset_after_failure():
    """Сбой на середине не должен повторять уже сделанную работу.

    Иначе рассылка, упавшая на 9000-м получателе, начнётся с первого — и
    девять тысяч человек получат сообщение второй раз.
    """
    calls = {"n": 0}

    async def _handler(view):
        calls["n"] += 1
        if calls["n"] == 1:
            view.progress(cursor="5000", done_count=5000)
            raise RuntimeError("сеть отвалилась")
        assert view.cursor == "5000"  # продолжили, а не начали заново
        return None

    task_queue.register("broadcast", _handler)
    task_id = task_queue.enqueue("broadcast")

    await task_queue.run_once()
    assert _task(task_id).cursor == "5000"

    await task_queue.run_once()
    assert _task(task_id).status == task_queue.STATUS_DONE


# --- свойство 2: отложенный запуск ---


async def test_future_task_is_not_picked_yet():
    """Шаг воронки «через два дня» не должен выполниться сегодня."""
    task_queue.register("later", _noop)
    task_queue.enqueue("later", run_after=_utcnow() + timedelta(days=2))

    assert await task_queue.run_once() is False


async def test_due_task_is_picked():
    task_queue.register("later", _noop)
    task_queue.enqueue("later", run_after=_utcnow() - timedelta(minutes=1))

    assert await task_queue.run_once() is True


async def test_earliest_due_task_goes_first():
    order: list[str] = []
    task_queue.register("ordered", _collect_tag(order))
    task_queue.enqueue("ordered", {"tag": "поздняя"}, run_after=_utcnow() - timedelta(minutes=1))
    task_queue.enqueue("ordered", {"tag": "ранняя"}, run_after=_utcnow() - timedelta(hours=5))

    await task_queue.run_once()
    await task_queue.run_once()

    assert order == ["ранняя", "поздняя"]


# --- свойство 3: переживание падения процесса ---


def test_stale_running_task_is_reclaimed():
    """Задача от упавшего процесса не должна зависнуть навсегда.

    Самый неприятный вид поломки: снаружи всё выглядит рабочим, а работа
    стоит. Аренда протухает — следующий воркер подбирает задачу.
    """
    task_queue.register("broadcast", _noop)
    task_id = task_queue.enqueue("broadcast")
    with session_scope() as session:
        row = session.get(QueuedTask, task_id)
        assert row is not None
        row.status = task_queue.STATUS_RUNNING
        row.cursor = "777"
        row.updated_at = _utcnow() - timedelta(seconds=task_queue.LEASE_SECONDS + 60)

    view = task_queue.claim_next()

    assert view is not None
    assert view.id == task_id
    assert view.cursor == "777"  # продолжаем с места обрыва


def test_fresh_running_task_is_not_stolen():
    """Живой обработчик не должен потерять свою задачу.

    Иначе два воркера погонят одну рассылку параллельно, и получатели
    увидят сообщение дважды.
    """
    task_queue.register("broadcast", _noop)
    task_id = task_queue.enqueue("broadcast")
    with session_scope() as session:
        row = session.get(QueuedTask, task_id)
        assert row is not None
        row.status = task_queue.STATUS_RUNNING
        row.updated_at = _utcnow()

    assert task_queue.claim_next() is None


def test_progress_renews_the_lease():
    """Пока обработчик отчитывается, задачу не отбирают."""
    task_queue.register("broadcast", _noop)
    task_id = task_queue.enqueue("broadcast")
    view = task_queue.claim_next()
    assert view is not None

    with session_scope() as session:
        row = session.get(QueuedTask, task_id)
        assert row is not None
        row.updated_at = _utcnow() - timedelta(seconds=task_queue.LEASE_SECONDS + 60)

    view.progress(cursor="1")

    assert task_queue.claim_next() is None  # аренда продлена


def test_claim_is_atomic_between_workers():
    """Двое не могут взять одну задачу.

    Полагаться на «сначала прочитали, потом записали» нельзя — это
    классическая гонка, из-за которой рассылка уходит дважды.
    """
    task_queue.register("broadcast", _noop)
    task_queue.enqueue("broadcast")

    first = task_queue.claim_next()
    second = task_queue.claim_next()

    assert first is not None
    assert second is None


# --- свойство 4: ограниченные повторы ---


async def test_failing_task_is_retried_then_failed():
    """Вечно падающая задача не должна крутиться бесконечно, съедая воркер."""
    attempts = {"n": 0}

    async def _handler(view):
        attempts["n"] += 1
        raise RuntimeError("всегда падаю")

    task_queue.register("doomed", _handler)
    task_id = task_queue.enqueue("doomed")

    for _ in range(task_queue.MAX_ATTEMPTS + 2):
        await task_queue.run_once()

    row = _task(task_id)
    assert row.status == task_queue.STATUS_FAILED
    assert attempts["n"] == task_queue.MAX_ATTEMPTS
    assert row.last_error is not None and "всегда падаю" in row.last_error


async def test_transient_failure_recovers():
    calls = {"n": 0}

    async def _handler(view):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("разовый сбой")
        return None

    task_queue.register("flaky", _handler)
    task_id = task_queue.enqueue("flaky")

    await task_queue.run_once()
    assert _task(task_id).status == task_queue.STATUS_PENDING

    await task_queue.run_once()
    assert _task(task_id).status == task_queue.STATUS_DONE


async def test_missing_handler_fails_task_instead_of_crashing():
    """Обработчик мог не зарегистрироваться из-за порядка импортов.

    Потерять рассылку было бы худшим исходом, чем внятная ошибка в строке.
    """
    task_id = task_queue.enqueue("неизвестный_вид")

    assert await task_queue.run_once() is True

    row = _task(task_id)
    assert row.status == task_queue.STATUS_FAILED
    assert row.last_error is not None and "нет обработчика" in row.last_error


# --- отбор по виду, отмена, прокрутка ---


async def test_kinds_filter_picks_only_requested():
    done: list[str] = []
    task_queue.register("a", _collect_const(done, "a"))
    task_queue.register("b", _collect_const(done, "b"))
    task_queue.enqueue("a")
    task_queue.enqueue("b")

    await task_queue.run_once(kinds=["b"])

    assert done == ["b"]


async def test_cancel_prevents_execution():
    task_queue.register("stoppable", _noop)
    task_id = task_queue.enqueue("stoppable")

    assert task_queue.cancel(task_id) is True
    assert await task_queue.run_once() is False
    assert _task(task_id).status == task_queue.STATUS_CANCELED


async def test_cancel_does_not_touch_finished_task():
    task_queue.register("quick", _noop)
    task_id = task_queue.enqueue("quick")
    await task_queue.run_once()

    assert task_queue.cancel(task_id) is False
    assert _task(task_id).status == task_queue.STATUS_DONE


async def test_run_pending_processes_several_and_respects_cap():
    task_queue.register("many", _noop)
    for _ in range(5):
        task_queue.enqueue("many")

    assert await task_queue.run_pending(max_tasks=3) == 3
    assert await task_queue.run_pending() == 2


async def test_run_pending_cap_stops_endless_task():
    """Задача, всегда отдающая курсор, не должна занять воркер навсегда."""
    task_queue.register("endless", _always_more)
    task_queue.enqueue("endless")

    assert await task_queue.run_pending(max_tasks=4) == 4

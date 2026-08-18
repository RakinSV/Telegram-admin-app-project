"""Упавшие задачи очереди видны владельцу и повторяются (аудит 2026-08-18).

НАЙДЕНО ЗАМЕРОМ, А НЕ ЧТЕНИЕМ КОДА. В базе стенда `queued_tasks` пуста, зато
`grep` показал: за пределами `task_queue.py` на статус `failed` не смотрит
НИКТО — ни страница, ни уведомление, ни счётчик. А через очередь идут рассылки
(F64), доставка вебхуков (F73), ОПРОС ПЛАТЕЖЕЙ (F70) и шаги сценариев (F75).
То есть молча умирала и рассылка на половине получателей, и подтверждение
оплаты: снаружи «ничего не произошло» — худший вид поломки, потому что искать
некому и нечего.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import task_queue
from tg_repost.db.models import QueuedTask
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean_queue():
    with session_scope() as session:
        session.query(QueuedTask).delete()
    yield
    with session_scope() as session:
        session.query(QueuedTask).delete()


def _task(status: str, *, kind: str = "broadcast", age_days: float = 0,
          cursor: str | None = None, done: int = 0, error: str | None = None) -> int:
    moment = datetime.now(timezone.utc) - timedelta(days=age_days)
    with session_scope() as session:
        task = QueuedTask(
            kind=kind, payload="{}", status=status, run_after=moment,
            created_at=moment, updated_at=moment, cursor=cursor,
            done_count=done, last_error=error, attempts=task_queue.MAX_ATTEMPTS,
        )
        session.add(task)
        session.flush()
        return task.id


# --- видимость ---


def test_failed_tasks_are_listed_with_their_reason():
    """Без причины список бесполезен: «что-то упало» не даёт решить, что делать."""
    task_id = _task(task_queue.STATUS_FAILED, error="Telegram: chat not found")

    rows = task_queue.failed_tasks()

    assert [row.id for row in rows] == [task_id]
    assert rows[0].last_error == "Telegram: chat not found"
    assert task_queue.count_failed() == 1


def test_only_failed_tasks_are_listed():
    """Ждущая задача — это работа, а не поломка. Смешать их значило бы
    научить владельца не смотреть в этот список вовсе."""
    _task(task_queue.STATUS_PENDING)
    _task(task_queue.STATUS_RUNNING)
    _task(task_queue.STATUS_DONE)
    failed = _task(task_queue.STATUS_FAILED)

    assert [row.id for row in task_queue.failed_tasks()] == [failed]
    assert task_queue.count_failed() == 1


def test_freshest_failure_comes_first():
    """Свежая поломка важнее прошлогодней."""
    old = _task(task_queue.STATUS_FAILED, age_days=10)
    new = _task(task_queue.STATUS_FAILED, age_days=1)

    assert [row.id for row in task_queue.failed_tasks()] == [new, old]


# --- повтор ---


def test_retry_keeps_the_cursor():
    """ГЛАВНОЕ СВОЙСТВО. Рассылка упала на 4312-м получателе; повтор с начала
    отправил бы сообщение первым четырём тысячам во второй раз."""
    task_id = _task(task_queue.STATUS_FAILED, cursor="4312", done=4312)

    assert task_queue.retry(task_id) is True

    with session_scope() as session:
        task = session.get(QueuedTask, task_id)
        assert task.status == task_queue.STATUS_PENDING
        assert task.cursor == "4312", "курсор потерян — рассылка пойдёт заново"
        assert task.done_count == 4312
        assert task.attempts == 0, "без сброса попыток задача снова упадёт сразу"
        assert task.last_error is None


def test_retry_refuses_a_running_task():
    """Повтор работающей задачи отдал бы её второму воркеру: получатели
    увидели бы сообщение дважды."""
    task_id = _task(task_queue.STATUS_RUNNING)

    assert task_queue.retry(task_id) is False

    with session_scope() as session:
        assert session.get(QueuedTask, task_id).status == task_queue.STATUS_RUNNING


def test_retry_refuses_a_finished_task():
    task_id = _task(task_queue.STATUS_DONE)
    assert task_queue.retry(task_id) is False


def test_retry_of_a_missing_task_does_not_crash():
    assert task_queue.retry(999999) is False


# --- срок хранения ---


def test_finished_tasks_are_purged_by_age():
    old_done = _task(task_queue.STATUS_DONE, age_days=40)
    old_failed = _task(task_queue.STATUS_FAILED, age_days=40)
    old_canceled = _task(task_queue.STATUS_CANCELED, age_days=40)

    removed = task_queue.purge_finished(30)

    assert removed == 3
    with session_scope() as session:
        for task_id in (old_done, old_failed, old_canceled):
            assert session.get(QueuedTask, task_id) is None


def test_waiting_task_is_never_purged():
    """Отложенный шаг сценария «напомнить через месяц» выглядит ровно как
    старая задача. Удалить его — значит потерять напоминание."""
    waiting = _task(task_queue.STATUS_PENDING, age_days=400)
    running = _task(task_queue.STATUS_RUNNING, age_days=400)

    assert task_queue.purge_finished(30) == 0

    with session_scope() as session:
        assert session.get(QueuedTask, waiting) is not None
        assert session.get(QueuedTask, running) is not None


def test_fresh_failure_survives_the_purge():
    """Упавшую задачу нельзя удалять раньше, чем владелец мог её увидеть."""
    fresh = _task(task_queue.STATUS_FAILED, age_days=1)

    task_queue.purge_finished(30)

    with session_scope() as session:
        assert session.get(QueuedTask, fresh) is not None


def test_zero_days_disables_the_purge():
    task_id = _task(task_queue.STATUS_DONE, age_days=400)

    assert task_queue.purge_finished(0) == 0

    with session_scope() as session:
        assert session.get(QueuedTask, task_id) is not None

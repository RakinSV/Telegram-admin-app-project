"""Очередь долгих задач с курсором (фаза 11, решение 3).

Одна инфраструктура на три будущие фичи: рассылку по сегменту (F64), шаги
воронок (F71) и повторы постов (F55). Строится один раз — иначе получилось
бы три похожих механизма, которые со временем разойдутся, как разошлись
правила приёма постов до F51.

ЧЕТЫРЕ СВОЙСТВА, РАДИ КОТОРЫХ ЭТО ВООБЩЕ НУЖНО:

1. **Возобновляемость.** Рассылка на 10 000 человек идёт минутами и обязана
   продолжаться С МЕСТА ОБРЫВА. Даёт это `cursor` в строке БД, а не брокер:
   обработчик двигает его по мере работы.
2. **Отложенный запуск.** `run_after` — это будущие шаги воронок «через два
   дня напомнить».
3. **Переживание падения.** Задача в статусе `running` от процесса, который
   умер, иначе зависла бы навсегда — снаружи всё выглядит рабочим, а работа
   стоит. Решается арендой: `running` действителен, пока обработчик
   обновляет `updated_at`.
4. **Ограниченные повторы.** Задача, падающая всегда, не должна крутиться
   вечно, съедая воркер: после `MAX_ATTEMPTS` уходит в `failed` с текстом
   последней ошибки.

Redis и Celery НЕ вводятся сознательно: они дали бы второй сервис в
развёртывании ради свойств, которые здесь обеспечивает строка в таблице.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from tg_repost.db.models import QueuedTask
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"

# Сколько раз пробуем задачу, прежде чем признать её безнадёжной.
MAX_ATTEMPTS = 3
# Сколько живёт аренда без продления. Больше типичной паузы между шагами
# обработчика, но заметно меньше человеческого «что-то повисло».
LEASE_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Обработчик получает задачу и возвращает новый курсор (или None, если
# работа закончена). Так решение «продолжать или нет» остаётся у того, кто
# знает предметную область, а очередь остаётся про механику.
Handler = Callable[["TaskView"], "str | None"]

_handlers: dict[str, Handler] = {}


class TaskView:
    """Снимок задачи для обработчика — без живой сессии БД.

    Обработчик работает долго (сеть, Telegram API), и держать ради него
    открытую транзакцию нельзя: SQLite пускает одного писателя, и такая
    транзакция заблокировала бы всё остальное на время рассылки.
    """

    def __init__(self, task: QueuedTask) -> None:
        self.id = task.id
        self.kind = task.kind
        self.payload: dict[str, Any] = json.loads(task.payload or "{}")
        self.cursor = task.cursor
        self.done_count = task.done_count
        self.total_count = task.total_count
        self.attempts = task.attempts

    def progress(self, cursor: str | None, done_count: int | None = None) -> None:
        """Сохранить прогресс И ПРОДЛИТЬ АРЕНДУ.

        Обработчик обязан звать это периодически, а не только в конце: пока
        он молчит, аренда протухает, и задачу подберёт второй воркер —
        получатели рассылки увидят сообщение дважды.
        """
        with session_scope() as session:
            task = session.get(QueuedTask, self.id)
            if task is None:
                return
            task.cursor = cursor
            if done_count is not None:
                task.done_count = done_count
            task.updated_at = _utcnow()
        self.cursor = cursor
        if done_count is not None:
            self.done_count = done_count


def register(kind: str, handler: Handler) -> None:
    """Привязать обработчик к виду задач."""
    _handlers[kind] = handler


def enqueue(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    total_count: int | None = None,
) -> int:
    """Поставить задачу. Возвращает её id."""
    with session_scope() as session:
        task = QueuedTask(
            kind=kind,
            payload=json.dumps(payload or {}, ensure_ascii=False),
            run_after=run_after or _utcnow(),
            total_count=total_count,
        )
        session.add(task)
        session.flush()
        logger.info("Очередь: задача #%d (%s) поставлена", task.id, kind)
        return task.id


def claim_next(kinds: list[str] | None = None) -> TaskView | None:
    """Взять следующую задачу в работу. `None` — брать нечего.

    ЗАХВАТ АТОМАРЕН. `UPDATE ... WHERE id = ? AND status = ?` с проверкой
    числа изменённых строк: если между выборкой и захватом задачу забрал
    другой воркер, обновится ноль строк, и мы просто идём дальше. Полагаться
    на «сначала прочитали, потом записали» нельзя — это классическая гонка,
    из-за которой рассылка уходит получателям дважды.
    """
    now = _utcnow()
    stale_before = now - timedelta(seconds=LEASE_SECONDS)

    with session_scope() as session:
        query = session.query(QueuedTask).filter(
            QueuedTask.run_after <= now,
            # Либо ждёт своей очереди, либо арендована упавшим процессом.
            (QueuedTask.status == STATUS_PENDING)
            | (
                (QueuedTask.status == STATUS_RUNNING)
                & (QueuedTask.updated_at < stale_before)
            ),
        )
        if kinds:
            query = query.filter(QueuedTask.kind.in_(kinds))
        # Тай-брейк по `id`: при совпадении `run_after` порядок иначе не
        # определён — та же причина, что во всей работе с метриками.
        candidate = query.order_by(QueuedTask.run_after.asc(), QueuedTask.id.asc()).first()
        if candidate is None:
            return None

        previous_status = candidate.status
        claimed = (
            session.query(QueuedTask)
            .filter(QueuedTask.id == candidate.id, QueuedTask.status == previous_status)
            .update(
                {
                    "status": STATUS_RUNNING,
                    "attempts": QueuedTask.attempts + 1,
                    "updated_at": now,
                },
                synchronize_session=False,
            )
        )
        if not claimed:
            return None  # успел другой воркер

        # `synchronize_session=False` не трогает объект в памяти, а он уже
        # лежит в identity map после выборки выше — без refresh обработчик
        # увидел бы attempts на единицу меньше и получил бы лишнюю попытку.
        # Поймано тестом: задача выполнялась 4 раза при MAX_ATTEMPTS=3.
        session.refresh(candidate)
        task = candidate
        if previous_status == STATUS_RUNNING:
            logger.warning(
                "Очередь: задача #%d (%s) подобрана после обрыва, продолжаем "
                "с курсора %r", task.id, task.kind, task.cursor,
            )
        return TaskView(task)


def _finish(task_id: int, status: str, error: str | None = None) -> None:
    with session_scope() as session:
        task = session.get(QueuedTask, task_id)
        if task is None:
            return
        task.status = status
        task.last_error = error[:2000] if error else None
        task.updated_at = _utcnow()


def run_once(kinds: list[str] | None = None) -> bool:
    """Выполнить одну задачу. `False` — очередь пуста.

    Возвращает bool, а не число: вызывающий крутит это в цикле, пока есть
    работа, и ему нужно знать только «было ли что делать».
    """
    view = claim_next(kinds)
    if view is None:
        return False

    handler = _handlers.get(view.kind)
    if handler is None:
        # Не падаем и не теряем задачу: обработчик мог не зарегистрироваться
        # из-за порядка импортов, и тогда потерять рассылку было бы худшим
        # исходом. Задача уходит в failed с внятной причиной.
        _finish(view.id, STATUS_FAILED, f"нет обработчика для вида «{view.kind}»")
        logger.error("Очередь: нет обработчика для вида «%s» (задача #%d)", view.kind, view.id)
        return True

    try:
        next_cursor = handler(view)
    except Exception as exc:  # noqa: BLE001 — обработчик произвольный
        message = str(exc)[:2000]
        if view.attempts >= MAX_ATTEMPTS:
            _finish(view.id, STATUS_FAILED, message)
            logger.error(
                "Очередь: задача #%d (%s) провалена после %d попыток: %s",
                view.id, view.kind, view.attempts, message,
            )
        else:
            # Возвращаем в очередь. Курсор НЕ сбрасываем — уже сделанная часть
            # работы не должна повторяться из-за сбоя на середине.
            _finish(view.id, STATUS_PENDING, message)
            logger.warning(
                "Очередь: задача #%d (%s) упала (попытка %d из %d): %s",
                view.id, view.kind, view.attempts, MAX_ATTEMPTS, message,
            )
        return True

    if next_cursor is None:
        _finish(view.id, STATUS_DONE)
        logger.info("Очередь: задача #%d (%s) выполнена", view.id, view.kind)
    else:
        # Обработчик отдал курсор — работа не закончена, продолжим следующим
        # проходом. Так длинная рассылка не держит воркер часами и не мешает
        # другим задачам.
        with session_scope() as session:
            task = session.get(QueuedTask, view.id)
            if task is not None:
                task.cursor = next_cursor
                task.status = STATUS_PENDING
                task.updated_at = _utcnow()
    return True


def run_pending(kinds: list[str] | None = None, max_tasks: int = 20) -> int:
    """Прокрутить очередь. Возвращает число обработанных задач.

    `max_tasks` — предохранитель от бесконечного цикла: задача, возвращающая
    курсор всегда, иначе заняла бы воркер навсегда.
    """
    processed = 0
    while processed < max_tasks and run_once(kinds):
        processed += 1
    return processed


def cancel(task_id: int) -> bool:
    """Отменить задачу. Уже выполненную не трогаем."""
    with session_scope() as session:
        task = session.get(QueuedTask, task_id)
        if task is None or task.status in (STATUS_DONE, STATUS_FAILED):
            return False
        task.status = STATUS_CANCELED
        task.updated_at = _utcnow()
        return True

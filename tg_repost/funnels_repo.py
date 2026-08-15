"""Воронки: цепочки сообщений с задержками (F71).

Зачатки уже были: F45 (триггеры) и F46 (онбординг) — это воронка без
движка. Здесь появляется слой, который позволяет собирать цепочки без правки
кода, а отложенные шаги едут на очереди задач из фазы 11.

ЛИНЕЙНЫЕ ЦЕПОЧКИ, БЕЗ ВЕТВЛЕНИЙ — осознанный предел. Полноценный движок
сценариев разрастается бесконечно: за ветвлением просят циклы, за циклами
переменные, и получается плохой язык программирования внутри админки.
Реальные задачи владельца — онбординг новичка и цепочка напоминаний —
линейны. Если ветвление однажды понадобится, добавить его к линейному
движку легче, чем убрать лишнее из универсального.

ЧЕТЫРЕ ПРИЧИНЫ ОСТАНОВИТЬ ЦЕПОЧКУ, И КАЖДАЯ ОБЯЗАТЕЛЬНА:

* **человек отписался** — от рассылок он отказался, и воронка это тоже
  рассылка. Продолжать значит игнорировать прямой отказ;
* **человек стал недостижим** (заблокировал бота) — писать некуда;
* **воронку выключили** — владелец передумал, и цепочка не должна доигрывать
  сама по себе неделю после этого;
* **шаги изменились** и следующего больше нет. Молча продолжить с чужого
  места хуже, чем честно завершить.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost import subscribers_repo, task_queue
from tg_repost.db.models import Funnel, FunnelRun
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TASK_KIND = "funnel_step"

TRIGGER_START = "start"
KNOWN_TRIGGERS = (TRIGGER_START,)

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_STOPPED = "stopped"

MAX_STEPS = 20
MAX_TEXT = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvalidFunnel(ValueError):
    """Шаги воронки не прошли проверку."""


@dataclass(frozen=True)
class Step:
    delay_hours: int
    text: str


@dataclass(frozen=True)
class FunnelView:
    id: int
    name: str
    trigger: str
    steps: tuple[Step, ...]
    is_active: bool


def parse_steps(raw: object) -> tuple[Step, ...]:
    """Разобрать и ПРОВЕРИТЬ шаги.

    Проверка строгая: воронка шлёт сообщения живым людям по расписанию, и
    ошибка в ней обнаружится через сутки — когда исправлять поздно.
    """
    if not isinstance(raw, list) or not raw:
        raise InvalidFunnel("Нужен хотя бы один шаг")
    if len(raw) > MAX_STEPS:
        raise InvalidFunnel(f"Слишком много шагов, предел {MAX_STEPS}")

    steps: list[Step] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise InvalidFunnel(f"Шаг {index}: ожидался объект")
        text = str(item.get("text", "")).strip()
        if not text:
            raise InvalidFunnel(f"Шаг {index}: пустой текст")
        delay = item.get("delay_hours", 0)
        if not isinstance(delay, int) or delay < 0:
            raise InvalidFunnel(f"Шаг {index}: задержка должна быть целым числом часов")
        steps.append(Step(delay_hours=delay, text=text[:MAX_TEXT]))
    return tuple(steps)


def save(
    name: str,
    steps: list,
    *,
    funnel_id: int | None = None,
    trigger: str = TRIGGER_START,
    is_active: bool = False,
) -> int:
    """Создать или обновить воронку.

    Без `funnel_id` — upsert ПО ИМЕНИ: так удобно заводить воронку из кода,
    не заботясь, есть она уже или нет. С `funnel_id` — правка конкретной
    строки, включая переименование. Разница существенна: форма
    редактирования без этого превращала бы смену имени в создание второй
    воронки, и человек молча оказывался бы записан в обе.
    """
    clean_name = name.strip()
    if not clean_name:
        raise InvalidFunnel("Имя воронки не может быть пустым")
    if trigger not in KNOWN_TRIGGERS:
        raise InvalidFunnel(f"Неизвестный триггер: {trigger}")

    parsed = parse_steps(steps)
    payload = json.dumps(
        [{"delay_hours": s.delay_hours, "text": s.text} for s in parsed],
        ensure_ascii=False,
    )
    with session_scope() as session:
        row = None
        if funnel_id is not None:
            row = session.get(Funnel, funnel_id)
            if row is None:
                raise InvalidFunnel("Воронка не найдена")
            # Имя — не украшение: по нему идёт upsert из кода и по нему
            # владелец узнаёт воронку в журнале. Два одинаковых имени
            # сделали бы и то и другое неоднозначным.
            twin = (
                session.query(Funnel.id)
                .filter(Funnel.name == clean_name, Funnel.id != funnel_id)
                .first()
            )
            if twin is not None:
                raise InvalidFunnel(f"Воронка «{clean_name}» уже есть")
            row.name = clean_name
        else:
            row = session.query(Funnel).filter(Funnel.name == clean_name).first()
        if row is None:
            row = Funnel(name=clean_name, trigger=trigger, steps_json=payload)
            session.add(row)
            session.flush()
        else:
            row.trigger = trigger
            row.steps_json = payload
        row.is_active = is_active
        return row.id


def get(funnel_id: int) -> FunnelView | None:
    with session_scope() as session:
        row = session.get(Funnel, funnel_id)
        if row is None:
            return None
        return FunnelView(
            id=row.id, name=row.name, trigger=row.trigger,
            steps=parse_steps(json.loads(row.steps_json)) if row.steps_json != "[]" else (),
            is_active=row.is_active,
        )


def list_all() -> list[FunnelView]:
    with session_scope() as session:
        rows = session.query(Funnel).order_by(Funnel.name.asc()).all()
        ids = [row.id for row in rows]
    return [view for view in (get(i) for i in ids) if view is not None]


def set_active(funnel_id: int, active: bool) -> bool:
    with session_scope() as session:
        row = session.get(Funnel, funnel_id)
        if row is None:
            return False
        row.is_active = active
        return True


def delete(funnel_id: int) -> bool:
    """Удалить воронку вместе с её запусками.

    Запуски чистим ЯВНО, хотя во внешнем ключе стоит `ondelete="CASCADE"`:
    SQLite не включает `PRAGMA foreign_keys` по умолчанию (проверено —
    значение 0), поэтому каскад там декоративен. Без явной чистки остались
    бы висячие запуски в статусе «идёт» без воронки, а отложенные задачи
    молча завершались бы, не найдя её.
    """
    with session_scope() as session:
        row = session.get(Funnel, funnel_id)
        if row is None:
            return False
        session.query(FunnelRun).filter(FunnelRun.funnel_id == funnel_id).delete()
        session.delete(row)
        return True


# --- запуск ---


def enroll(user_id: int, trigger: str = TRIGGER_START) -> list[int]:
    """Записать человека во все активные воронки этого триггера.

    Возвращает id запусков. Повторная запись невозможна: человек, дважды
    нажавший «Запустить», иначе получил бы всю цепочку дважды.
    """
    started: list[int] = []
    with session_scope() as session:
        funnels = (
            session.query(Funnel)
            .filter(Funnel.trigger == trigger, Funnel.is_active.is_(True))
            .all()
        )
        for funnel in funnels:
            exists = (
                session.query(FunnelRun.id)
                .filter(
                    FunnelRun.funnel_id == funnel.id, FunnelRun.user_id == user_id,
                )
                .first()
            )
            if exists:
                continue
            run = FunnelRun(funnel_id=funnel.id, user_id=user_id)
            session.add(run)
            session.flush()
            started.append(run.id)
            delay = parse_steps(json.loads(funnel.steps_json))[0].delay_hours
            task_queue.enqueue(
                TASK_KIND,
                {"run_id": run.id},
                run_after=_utcnow() + timedelta(hours=delay),
            )
            logger.info(
                "F71: человек %s записан в воронку «%s» (запуск #%d)",
                user_id, funnel.name, run.id,
            )
    return started


def _stop(run_id: int, reason: str) -> None:
    with session_scope() as session:
        run = session.get(FunnelRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            return
        run.status = STATUS_STOPPED
        run.stop_reason = reason
        run.finished_at = _utcnow()
    logger.info("F71: запуск #%d остановлен: %s", run_id, reason)


def _finish(run_id: int) -> None:
    with session_scope() as session:
        run = session.get(FunnelRun, run_id)
        if run is None:
            return
        run.status = STATUS_DONE
        run.finished_at = _utcnow()


async def handle_step_task(view: task_queue.TaskView) -> str | None:
    """Обработчик очереди: отправить очередной шаг и поставить следующий.

    Возвращает `None` всегда: следующий шаг ставится ОТДЕЛЬНОЙ задачей с
    собственным `run_after`, а не курсором внутри этой. Курсор годится для
    порции работы подряд, а здесь между шагами сутки — держать ради этого
    задачу в очереди значило бы занять воркер на день.
    """
    run_id = int(view.payload["run_id"])

    with session_scope() as session:
        run = session.get(FunnelRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            return None
        funnel = session.get(Funnel, run.funnel_id)
        if funnel is None:
            return None
        user_id = run.user_id
        step_index = run.next_step
        is_active = funnel.is_active
        steps = parse_steps(json.loads(funnel.steps_json))

    if not is_active:
        _stop(run_id, "воронка выключена")
        return None
    if step_index >= len(steps):
        # Шаги изменились и следующего больше нет. Продолжить с чужого места
        # хуже, чем честно завершить.
        _finish(run_id)
        return None
    if not subscribers_repo.is_reachable(user_id):
        # Отписался или заблокировал бота. Первое — прямой отказ, второе —
        # писать физически некуда.
        _stop(run_id, "человек недоступен")
        return None

    from tg_repost.webui.supervisor import get_components

    bot = get_components().application.bot  # type: ignore[union-attr]
    try:
        await bot.send_message(user_id, steps[step_index].text)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "blocked" in message.lower():
            subscribers_repo.mark_blocked(user_id)
            _stop(run_id, "заблокировал бота")
            return None
        # Прочие сбои — не повод рвать цепочку: очередь повторит задачу.
        raise

    with session_scope() as session:
        run = session.get(FunnelRun, run_id)
        if run is None:
            return None
        run.next_step = step_index + 1
        finished = run.next_step >= len(steps)

    if finished:
        _finish(run_id)
        logger.info("F71: запуск #%d завершён", run_id)
        return None

    task_queue.enqueue(
        TASK_KIND,
        {"run_id": run_id},
        run_after=_utcnow() + timedelta(hours=steps[step_index + 1].delay_hours),
    )
    return None


def register_handler() -> None:
    task_queue.register(TASK_KIND, handle_step_task)


def runs_of(funnel_id: int) -> dict[str, int]:
    """Сводка по воронке: сколько идёт, дошло и сорвалось."""
    with session_scope() as session:
        rows = (
            session.query(FunnelRun.status)
            .filter(FunnelRun.funnel_id == funnel_id)
            .all()
        )
    counts = {STATUS_RUNNING: 0, STATUS_DONE: 0, STATUS_STOPPED: 0}
    for (status,) in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts

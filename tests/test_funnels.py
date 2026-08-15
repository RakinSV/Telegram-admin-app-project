"""Воронки: цепочки сообщений с задержками (F71).

Воронка шлёт сообщения живым людям по расписанию, растянутому на дни. Ошибка
в ней обнаружится через сутки — когда исправлять поздно, а сообщения уже
ушли. Поэтому тесты в основном про ЧЕТЫРЕ ПРИЧИНЫ ОСТАНОВКИ и про то, что
человек не получит цепочку дважды.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tg_repost import funnels_repo, subscribers_repo, task_queue
from tg_repost.db.models import BotSubscriber, Funnel, FunnelRun, QueuedTask
from tg_repost.db.session import session_scope

ALICE = 7001
BOB = 7002

STEPS = [
    {"delay_hours": 0, "text": "Привет! Спасибо, что подписались."},
    {"delay_hours": 24, "text": "Через день: вот что у нас есть."},
    {"delay_hours": 48, "text": "Через два дня: заходите ещё."},
]


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FunnelRun).delete()
            session.query(Funnel).delete()
            session.query(QueuedTask).delete()
            session.query(BotSubscriber).delete()
        task_queue._handlers.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _bot(monkeypatch) -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    class _Components:
        application = type("App", (), {"bot": bot})()

    monkeypatch.setattr(
        "tg_repost.webui.supervisor.get_components", lambda: _Components(),
    )
    funnels_repo.register_handler()
    return bot


def _funnel(*, active: bool = True, steps=None) -> int:
    return funnels_repo.save(
        "Онбординг", steps if steps is not None else STEPS, is_active=active,
    )


# --- проверка шагов ---


def test_empty_steps_are_rejected():
    """Воронка без шагов — это ничего не делающая рассылка в расписании."""
    with pytest.raises(funnels_repo.InvalidFunnel):
        funnels_repo.parse_steps([])


def test_step_without_text_is_rejected():
    with pytest.raises(funnels_repo.InvalidFunnel) as exc:
        funnels_repo.parse_steps([{"delay_hours": 1, "text": "  "}])

    assert "Шаг 1" in str(exc.value)


def test_negative_delay_is_rejected():
    """Отрицательная задержка означала бы отправку «в прошлом» — то есть
    сразу, вместе со следующим шагом."""
    with pytest.raises(funnels_repo.InvalidFunnel):
        funnels_repo.parse_steps([{"delay_hours": -5, "text": "текст"}])


def test_too_many_steps_are_rejected():
    with pytest.raises(funnels_repo.InvalidFunnel):
        funnels_repo.parse_steps(
            [{"delay_hours": 1, "text": "x"}] * (funnels_repo.MAX_STEPS + 1)
        )


def test_unknown_trigger_is_rejected():
    """Каждый триггер — точка, где воронка может выстрелить неожиданно."""
    with pytest.raises(funnels_repo.InvalidFunnel):
        funnels_repo.save("Тест", STEPS, trigger="что_угодно")


def test_broken_funnel_is_never_saved():
    with pytest.raises(funnels_repo.InvalidFunnel):
        funnels_repo.save("Плохая", [{"text": ""}])

    assert funnels_repo.list_all() == []


# --- запись в воронку ---


def test_enroll_starts_active_funnel():
    funnel_id = _funnel(active=True)

    runs = funnels_repo.enroll(ALICE)

    assert len(runs) == 1
    assert funnels_repo.runs_of(funnel_id)["running"] == 1


def test_inactive_funnel_does_not_enroll():
    _funnel(active=False)

    assert funnels_repo.enroll(ALICE) == []


def test_second_enroll_does_not_duplicate():
    """ГЛАВНАЯ ЗАЩИТА.

    Человек, дважды нажавший «Запустить», иначе получил бы всю цепочку
    дважды — и это выглядело бы как поломка бота.
    """
    _funnel()
    funnels_repo.enroll(ALICE)

    assert funnels_repo.enroll(ALICE) == []


def test_first_step_task_is_queued():
    _funnel()

    funnels_repo.enroll(ALICE)

    with session_scope() as session:
        task = session.query(QueuedTask).one()
        assert task.kind == funnels_repo.TASK_KIND


# --- прохождение ---


async def test_steps_are_sent_in_order(_bot):
    _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    # Три прохода: каждый шаг ставит следующую задачу с собственной паузой,
    # поэтому «промотать» их надо по одному.
    for _ in range(3):
        with session_scope() as session:
            for task in session.query(QueuedTask).all():
                task.run_after = task.created_at  # приблизили срок
        await task_queue.run_pending()

    texts = [call.args[1] for call in _bot.send_message.await_args_list]
    assert texts == [step["text"] for step in STEPS]


async def test_run_finishes_after_last_step(_bot):
    funnel_id = _funnel(steps=[{"delay_hours": 0, "text": "единственный"}])
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    await task_queue.run_pending()

    assert funnels_repo.runs_of(funnel_id)["done"] == 1


# --- четыре причины остановки ---


async def test_unsubscribed_person_stops_the_chain(_bot):
    """От рассылок человек отказался, а воронка — тоже рассылка.

    Продолжать значит игнорировать прямой отказ.
    """
    funnel_id = _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)
    subscribers_repo.unsubscribe(ALICE)

    await task_queue.run_pending()

    assert _bot.send_message.await_count == 0
    assert funnels_repo.runs_of(funnel_id)["stopped"] == 1


async def test_unreachable_person_stops_the_chain(_bot):
    funnel_id = _funnel()
    funnels_repo.enroll(ALICE)  # бота не запускал вовсе

    await task_queue.run_pending()

    assert _bot.send_message.await_count == 0
    assert funnels_repo.runs_of(funnel_id)["stopped"] == 1


async def test_disabling_funnel_stops_running_chains(_bot):
    """Владелец передумал — цепочка не должна доигрывать неделю после этого."""
    funnel_id = _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)
    funnels_repo.set_active(funnel_id, False)

    await task_queue.run_pending()

    assert _bot.send_message.await_count == 0
    assert funnels_repo.runs_of(funnel_id)["stopped"] == 1


async def test_shortened_steps_finish_the_run(_bot):
    """Шаги изменились, следующего больше нет.

    Продолжить с чужого места хуже, чем честно завершить.
    """
    funnel_id = _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)
    with session_scope() as session:
        run = session.query(FunnelRun).one()
        run.next_step = 99

    await task_queue.run_pending()

    assert _bot.send_message.await_count == 0
    assert funnels_repo.runs_of(funnel_id)["done"] == 1


async def test_stop_reason_is_recorded(_bot):
    """Без причины «остановлена» выглядит как сбой системы."""
    _funnel()
    funnels_repo.enroll(ALICE)

    await task_queue.run_pending()

    with session_scope() as session:
        assert session.query(FunnelRun).one().stop_reason is not None


async def test_blocking_the_bot_stops_and_marks_blocked(_bot):
    _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)
    _bot.send_message.side_effect = Exception("Forbidden: bot was blocked by the user")

    await task_queue.run_pending()

    assert subscribers_repo.is_reachable(ALICE) is False


# --- независимость людей ---


async def test_people_progress_independently(_bot):
    _funnel()
    subscribers_repo.record_contact(ALICE)
    subscribers_repo.record_contact(BOB)
    funnels_repo.enroll(ALICE)
    funnels_repo.enroll(BOB)
    subscribers_repo.unsubscribe(BOB)

    await task_queue.run_pending()

    recipients = [call.args[0] for call in _bot.send_message.await_args_list]
    assert recipients == [ALICE]


# --- редактирование ---


def test_save_updates_existing_by_name():
    first = funnels_repo.save("Онбординг", STEPS)
    second = funnels_repo.save("Онбординг", [{"delay_hours": 0, "text": "новый"}])

    assert first == second
    view = funnels_repo.get(first)
    assert len(view.steps) == 1


def test_delete_removes_funnel():
    funnel_id = _funnel()

    assert funnels_repo.delete(funnel_id) is True
    assert funnels_repo.get(funnel_id) is None

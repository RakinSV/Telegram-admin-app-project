"""Исполнение сценария (F75).

Проверяется ТОТ САМЫЙ трек, из которого выросла фича: видео → тест → следующий
этап, а неверный ответ возвращает к материалу.

Главное здесь — три места, где движок может испортить человеку жизнь:
предохранитель от циклов (сотня сообщений за секунды), нажатие старой кнопки
(увело бы на чужую ветку) и просроченное ожидание (прохождение зависает
навсегда).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from tg_repost import flow_engine as engine
from tg_repost import flows_repo as flows
from tg_repost.db.models import (
    Flow,
    FlowEdge,
    FlowNode,
    FlowRun,
    ManagedBot,
    QueuedTask,
    UserActivity,
)
from tg_repost.db.session import session_scope

ALICE = 10501
CHAT = -100777


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FlowRun).delete()
            session.query(FlowEdge).delete()
            session.query(FlowNode).delete()
            session.query(Flow).delete()
            session.query(ManagedBot).delete()
            session.query(QueuedTask).delete()
            session.query(UserActivity).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _bot() -> AsyncMock:
    return AsyncMock()


def _flow_id() -> int:
    with session_scope() as session:
        bot = ManagedBot(name="Бот", token_encrypted="x", token_hint="••••")
        session.add(bot)
        session.flush()
        bot_id = bot.id
    return flows.create(bot_id, "Трек")


def _node(key: str, kind: str, **config) -> dict:
    return {"node_key": key, "kind": kind, "config": config, "x": 0, "y": 0}


def _edge(a: str, b: str, condition: str = flows.ALWAYS, value=None) -> dict:
    return {
        "from_key": a, "to_key": b,
        "condition": condition, "condition_value": value,
    }


def _publish(flow_id: int, nodes: list[dict], edges: list[dict]) -> int:
    flows.save_draft(flow_id, nodes, edges)
    return flows.publish(flow_id)


def _run(flow_id: int) -> FlowRun | None:
    with session_scope() as session:
        row = session.query(FlowRun).filter(FlowRun.flow_id == flow_id).first()
        if row is not None:
            session.expunge(row)
        return row


def _texts(bot: AsyncMock) -> list[str]:
    return [c.args[1] for c in bot.send_message.await_args_list if len(c.args) > 1]


# --- обучающий трек целиком ---


async def _training_track() -> tuple[int, int]:
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("intro", flows.SHOW_TEXT, text="Начнём урок"),
            _node("video", flows.SHOW_VIDEO, file_id="VID1", caption="Урок 1"),
            _node("quiz", flows.ASK_QUIZ, question="Сколько будет 2+2?",
                  options=["3", "4"], correct_index=1,
                  explanation="Верно, четыре", wrong_text="Пересмотрите урок",
                  timeout_hours=24),
            _node("next", flows.SHOW_TEXT, text="Этап 2"),
            _node("reward", flows.DO_POINTS, points=10, chat_id=CHAT),
        ],
        [
            _edge("intro", "video"),
            _edge("video", "quiz"),
            _edge("quiz", "next", flows.ON_CORRECT),
            _edge("quiz", "video", flows.ON_WRONG),
            _edge("next", "reward"),
        ],
    )
    run_id = engine.start(flow_id, ALICE)
    assert run_id is not None
    return flow_id, run_id


async def test_track_runs_to_the_question_and_stops(_bot):
    """Показ идёт подряд, а на вопросе движок останавливается.

    Иначе владельцу пришлось бы ставить таймер между картинкой и текстом.
    """
    _flow, run_id = await _training_track()

    await engine.advance(run_id, _bot)

    assert _texts(_bot) == ["Начнём урок", "Сколько будет 2+2?"]
    assert _bot.send_video.await_count == 1
    run = _run(_flow)
    assert run is not None and run.waiting_for == "quiz"


async def test_correct_answer_moves_to_the_next_stage(_bot):
    """ГЛАВНЫЙ СЦЕНАРИЙ ЗАДАЧИ ВЛАДЕЛЬЦА."""
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    handled = await engine.handle_button(run_id, "quiz", "1", _bot)

    assert handled is True
    assert "Верно, четыре" in _texts(_bot)
    assert "Этап 2" in _texts(_bot)
    run = _run(flow_id)
    assert run is not None and run.status == engine.STATUS_DONE


async def test_wrong_answer_returns_to_the_material(_bot):
    """Смысл трека в том, чтобы человек понял, а не в том, чтобы отсеять."""
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    await engine.handle_button(run_id, "quiz", "0", _bot)

    assert _bot.send_video.await_count == 1, "материал не повторён"
    run = _run(flow_id)
    assert run is not None and run.status == engine.STATUS_RUNNING


async def test_wrong_answer_does_not_get_praised(_bot):
    """Человек ошибся — он не должен прочитать текст на верный ответ.

    Иначе он получает «Верно, четыре» за промах и остаётся в уверенности, что
    ответил правильно; после этого возврат к материалу выглядит поломкой.
    """
    _flow, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    await engine.handle_button(run_id, "quiz", "0", _bot)

    assert "Верно, четыре" not in _texts(_bot)
    assert "Пересмотрите урок" in _texts(_bot)


async def test_answer_is_remembered_for_later_branching(_bot):
    """Без этого ветвиться дальше не по чему."""
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)

    await engine.handle_button(run_id, "quiz", "1", _bot)

    run = _run(flow_id)
    assert run is not None
    variables = json.loads(run.variables_json)
    assert variables["quiz_correct"] is True
    assert variables["quiz_answer"] == "1"


async def test_points_are_awarded_even_without_previous_activity(_bot):
    """Человек мог прийти в сценарий, ни разу не ответив на викторину в
    группе. Молча уронить начисление значило бы, что владелец поставил узел
    «дать очки», а очков никто не увидел."""
    _flow, run_id = await _training_track()
    await engine.advance(run_id, _bot)

    await engine.handle_button(run_id, "quiz", "1", _bot)

    with session_scope() as session:
        row = (
            session.query(UserActivity)
            .filter(UserActivity.user_id == ALICE, UserActivity.chat_id == CHAT)
            .one()
        )
        assert row.points == 10


# --- предохранитель от циклов ---


async def test_loop_guard_stops_a_flood(_bot):
    """ГЛАВНАЯ ЗАЩИТА ЧЕЛОВЕКА.

    Проверка графа ловит закольцованность при публикации, но версия могла быть
    опубликована раньше, чем появилась проверка. Цена ошибки — сотня
    сообщений живому человеку за секунды.
    """
    flow_id = _flow_id()
    # Кольцо собирается в обход публикации: именно такие данные и опасны.
    flows.save_draft(
        flow_id,
        [_node("a", flows.SHOW_TEXT, text="снова"), _node("b", flows.SHOW_TEXT, text="и снова")],
        [_edge("a", "b"), _edge("b", "a")],
    )
    with session_scope() as session:
        for row in session.query(FlowNode).filter(FlowNode.flow_id == flow_id).all():
            row.version = 1
        for row in session.query(FlowEdge).filter(FlowEdge.flow_id == flow_id).all():
            row.version = 1
        session.get(Flow, flow_id).published_version = 1

    run_id = engine.start(flow_id, ALICE)
    assert run_id is None, "у кольца нет начала — записывать некуда"


async def test_loop_guard_limits_messages_in_a_broken_version(_bot):
    """То же кольцо, но с входом снаружи: движок обязан упереться в предел."""
    flow_id = _flow_id()
    flows.save_draft(
        flow_id,
        [
            _node("in", flows.SHOW_TEXT, text="вход"),
            _node("a", flows.SHOW_TEXT, text="круг"),
        ],
        [_edge("in", "a"), _edge("a", "a")],
    )
    with session_scope() as session:
        for row in session.query(FlowNode).filter(FlowNode.flow_id == flow_id).all():
            row.version = 1
        for row in session.query(FlowEdge).filter(FlowEdge.flow_id == flow_id).all():
            row.version = 1
        session.get(Flow, flow_id).published_version = 1

    run_id = engine.start(flow_id, ALICE)
    assert run_id is not None
    await engine.advance(run_id, _bot)

    assert _bot.send_message.await_count <= engine.MAX_STEPS
    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_STOPPED
    assert "закольцован" in (run.stop_reason or "")


# --- нажатие не к месту ---


async def test_button_from_an_old_message_is_ignored(_bot):
    """Старые сообщения в Telegram не исчезают: без сверки узла нажатие увело
    бы человека на ветку из другого места сценария."""
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    handled = await engine.handle_button(run_id, "video", "1", _bot)

    assert handled is False
    assert _bot.send_message.await_count == 0
    run = _run(flow_id)
    assert run is not None and run.current_node_key == "quiz"


async def test_button_after_the_run_finished_is_ignored(_bot):
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    await engine.handle_button(run_id, "quiz", "1", _bot)
    _bot.reset_mock()

    handled = await engine.handle_button(run_id, "quiz", "0", _bot)

    assert handled is False
    del flow_id


def test_callback_carries_run_and_node():
    data = engine.build_callback(42, "quiz", "1")

    assert engine.parse_callback(data) == (42, "quiz", "1")


@pytest.mark.parametrize("raw", ["", "мусор", "flow:нечисло:a:b", "other:1:a:b"])
def test_broken_callback_is_rejected(raw):
    assert engine.parse_callback(raw) is None


# --- запись в сценарий ---


async def test_unpublished_flow_cannot_be_started(_bot):
    """Черновик — не сценарий: запускать по нему нечего."""
    flow_id = _flow_id()
    flows.save_draft(flow_id, [_node("a", flows.SHOW_TEXT, text="1")], [])

    assert engine.start(flow_id, ALICE) is None


async def test_second_start_while_running_does_not_duplicate(_bot):
    """Дважды нажатый «Запустить» иначе повёл бы человека по двум копиям
    сценария одновременно."""
    flow_id, first = await _training_track()

    assert engine.start(flow_id, ALICE) is None
    del first


async def test_finished_track_can_be_taken_again(_bot):
    """«Прошёл обучение, хочу пройти снова» — обычная просьба.

    Отказ выглядел бы поломкой бота: человек пишет «/start», а в ответ тишина
    навсегда, потому что строка прохождения занята прошлым разом.
    """
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    await engine.handle_button(run_id, "quiz", "1", _bot)
    assert _run(flow_id).status == engine.STATUS_DONE
    _bot.reset_mock()

    again = engine.start(flow_id, ALICE)

    assert again == run_id, "новая попытка идёт по той же строке"
    await engine.advance(again, _bot)
    assert "Начнём урок" in _texts(_bot)
    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_RUNNING
    assert json.loads(run.variables_json) == {}, "ответы прошлого раза не сброшены"


async def test_a_stopped_track_can_be_taken_again(_bot):
    """Человек заблокировал бота, потом разблокировал и написал снова —
    прохождение обязано начаться, а не остаться в «остановлено» навсегда."""
    flow_id, run_id = await _training_track()
    _bot.send_message.side_effect = Exception("Forbidden: bot was blocked by the user")
    await engine.advance(run_id, _bot)
    assert _run(flow_id).status == engine.STATUS_STOPPED

    assert engine.start(flow_id, ALICE) == run_id
    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_RUNNING
    assert run.stop_reason is None, "прошлая причина осталась висеть"


async def test_button_of_a_forwarded_message_cannot_move_someone_elses_track(_bot):
    """ГЛАВНАЯ ДЫРА, найденная при подключении к живым ботам.

    Пересланное сообщение СОХРАНЯЕТ кнопки вместе с их данными. Получатель
    пересылки нажимает — и двигает чужое прохождение, а сообщения сценария
    летят тому, кто его начал.
    """
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    handled = await engine.handle_button(
        run_id, "quiz", "1", _bot, by_user_id=ALICE + 1,
    )

    assert handled is False
    assert _bot.send_message.await_count == 0
    run = _run(flow_id)
    assert run is not None and run.current_node_key == "quiz"


async def test_own_button_still_works_with_the_check(_bot):
    """Обратная проверка: сверка хозяина не должна ломать обычное нажатие."""
    _flow, run_id = await _training_track()
    await engine.advance(run_id, _bot)

    assert await engine.handle_button(
        run_id, "quiz", "1", _bot, by_user_id=ALICE,
    ) is True


async def test_run_remembers_its_version(_bot):
    """Человек, начавший вчера, доигрывает по вчерашней схеме."""
    flow_id, run_id = await _training_track()
    flows.save_draft(flow_id, [_node("other", flows.SHOW_TEXT, text="всё иначе")], [])
    flows.publish(flow_id)

    await engine.advance(run_id, _bot)

    assert "Начнём урок" in _texts(_bot), "прохождение поехало по новой версии"


# --- свободный текст ---


async def test_free_text_is_saved_into_a_named_variable(_bot):
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_TEXT, text="Как вас зовут?", variable="имя"),
            _node("hi", flows.SHOW_TEXT, text="Приятно познакомиться"),
        ],
        [_edge("ask", "hi")],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)

    handled = await engine.handle_text(run_id, "Сергей", _bot)

    assert handled is True
    run = _run(flow_id)
    assert run is not None
    assert json.loads(run.variables_json)["имя"] == "Сергей"


async def test_text_when_nothing_is_expected_is_ignored(_bot):
    """Иначе обычное сообщение боту утаскивало бы человека по сценарию."""
    flow_id, run_id = await _training_track()
    await engine.advance(run_id, _bot)

    assert await engine.handle_text(run_id, "просто пишу", _bot) is False


def _asking_flow() -> tuple[int, int]:
    """Сценарий из одного вопроса текстом. Возвращает (flow_id, bot_id)."""
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_TEXT, text="Имя?", variable="имя"),
            _node("hi", flows.SHOW_TEXT, text="Привет"),
        ],
        [_edge("ask", "hi")],
    )
    with session_scope() as session:
        return flow_id, session.get(Flow, flow_id).bot_id


async def test_waiting_run_is_found_by_kind():
    """Обработчик входящего сообщения должен находить адресата одним
    запросом, а не разбирать граф на каждое сообщение в личке."""
    flow_id, bot_id = _asking_flow()
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, AsyncMock())

    assert engine.waiting_run_for(ALICE, bot_id, "text") == run_id
    assert engine.waiting_run_for(ALICE, bot_id, "buttons") is None


async def test_answer_written_to_one_bot_does_not_go_to_another():
    """Человек может проходить сценарии у ДВУХ ботов сразу, и оба могут ждать
    текст. Ответ, написанный одному, не должен уходить в прохождение у
    другого: человек увидел бы продолжение чужой ветки от чужого имени."""
    first_flow, first_bot = _asking_flow()
    second_flow, second_bot = _asking_flow()
    first_run = engine.start(first_flow, ALICE)
    second_run = engine.start(second_flow, ALICE)
    await engine.advance(first_run, AsyncMock())
    await engine.advance(second_run, AsyncMock())

    assert engine.waiting_run_for(ALICE, first_bot, "text") == first_run
    assert engine.waiting_run_for(ALICE, second_bot, "text") == second_run


async def test_person_can_leave_the_track():
    """Человек, попавший в автоматическую цепочку, обязан иметь способ выйти:
    иначе единственный выход — заблокировать бота, а это стоит владельцу
    подписчика."""
    flow_id, bot_id = _asking_flow()
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, AsyncMock())

    assert engine.running_run_for(ALICE, bot_id) == run_id
    engine.stop_by_person(run_id)

    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_STOPPED
    assert run.stop_reason == "человек вышел сам"
    assert engine.running_run_for(ALICE, bot_id) is None


# --- условия ---


async def test_condition_branches_on_a_previous_answer(_bot):
    """Смысл конструктора: третий узел знает, что человек ответил в первом."""
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_BUTTONS, text="Опыт есть?",
                  buttons=[{"label": "Да", "value": "yes"},
                           {"label": "Нет", "value": "no"}]),
            _node("check", flows.DECIDE_CONDITION,
                  variable="ask", operator="eq", value="yes"),
            _node("pro", flows.SHOW_TEXT, text="Тогда сразу к практике"),
            _node("basic", flows.SHOW_TEXT, text="Начнём с азов"),
        ],
        [
            _edge("ask", "check", flows.ON_BUTTON),
            _edge("check", "pro", flows.ON_TRUE),
            _edge("check", "basic", flows.ON_FALSE),
        ],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)
    _bot.reset_mock()

    await engine.handle_button(run_id, "ask", "no", _bot)

    assert "Начнём с азов" in _texts(_bot)
    assert "Тогда сразу к практике" not in _texts(_bot)


@pytest.mark.parametrize(
    "operator,stored,expected,outcome",
    [
        ("eq", "да", "да", True),
        ("ne", "да", "нет", True),
        ("contains", "москва и питер", "питер", True),
        ("gt", "10", "5", True),
        ("lt", "3", "5", True),
        ("is_set", "что-то", None, True),
        ("is_empty", "", None, True),
        ("gt", "не число", "5", False),
        ("телепортация", "что-то", "что-то", False),
    ],
)
def test_condition_operators(operator, stored, expected, outcome):
    """Неизвестный оператор — ложь, а не падение: ронять прохождение живого
    человека из-за опечатки владельца хуже, чем увести по ветке «иначе»."""
    result = engine._evaluate(
        {"variable": "x", "operator": operator, "value": expected},
        {"x": stored},
    )

    assert result is outcome


# --- просроченное ожидание ---


async def test_timeout_follows_its_branch(_bot):
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_BUTTONS, text="Ответите?",
                  buttons=[{"label": "Да", "value": "yes"}], timeout_hours=1),
            _node("ok", flows.SHOW_TEXT, text="спасибо"),
            _node("nudge", flows.SHOW_TEXT, text="Напоминаю про урок"),
        ],
        [
            _edge("ask", "ok", flows.ON_BUTTON),
            _edge("ask", "nudge", flows.ON_TIMEOUT),
        ],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)
    _expire(run_id)
    _bot.reset_mock()

    handled = await engine.sweep_timeouts(lambda _id: _bot)

    assert handled == 1
    assert "Напоминаю про урок" in _texts(_bot)


async def test_timeout_without_a_branch_stops_the_run(_bot):
    """Прохождения без срока зависают навсегда: у человека висит вопрос, у
    владельца — вечное «идёт»."""
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_BUTTONS, text="Ответите?",
                  buttons=[{"label": "Да", "value": "yes"}], timeout_hours=1),
            _node("ok", flows.SHOW_TEXT, text="спасибо"),
        ],
        [_edge("ask", "ok", flows.ON_BUTTON)],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)
    _expire(run_id)

    await engine.sweep_timeouts(lambda _id: _bot)

    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_STOPPED
    assert "не ответил" in (run.stop_reason or "")


async def test_run_without_a_bot_is_not_lost(_bot):
    """Выключенный бот не должен стоить человеку прохождения.

    Просроченный срок — ЕДИНСТВЕННЫЙ признак, по которому такой проход вообще
    находится. Сдвинуть его, не имея чем отправить сообщение, значило бы
    потерять человека навсегда: ждать он перестал, а искать его нечем.
    """
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("ask", flows.ASK_BUTTONS, text="?",
                  buttons=[{"label": "Да", "value": "yes"}], timeout_hours=1),
            _node("ok", flows.SHOW_TEXT, text="ок"),
            _node("late", flows.SHOW_TEXT, text="поздно"),
        ],
        [
            _edge("ask", "ok", flows.ON_BUTTON),
            _edge("ask", "late", flows.ON_TIMEOUT),
        ],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)
    _expire(run_id)

    assert await engine.sweep_timeouts(lambda _id: None) == 0

    run = _run(flow_id)
    assert run is not None and run.status == engine.STATUS_RUNNING
    assert run.wait_until is not None, "признак просрочки стёрт — прохождение потеряно"

    # Бота включили — тот же проход обязан поехать дальше.
    _bot.reset_mock()
    assert await engine.sweep_timeouts(lambda _id: _bot) == 1
    assert "поздно" in _texts(_bot)


async def test_timer_fired_twice_does_not_cut_the_run_short(_bot):
    """Срок таймера сторожат ДВА механизма: задача в очереди и подметание
    просроченных. Второй сработавший обязан ничего не делать — иначе он
    закрывает прохождение, которое первый уже увёл дальше."""
    flow_id = _flow_id()
    _publish(
        flow_id,
        [
            _node("wait", flows.WAIT_TIMER, hours=1),
            _node("after", flows.SHOW_TEXT, text="прошёл час"),
            _node("ask", flows.ASK_TEXT, text="Как дела?", variable="дела"),
            _node("bye", flows.SHOW_TEXT, text="до связи"),
        ],
        [_edge("wait", "after"), _edge("after", "ask"), _edge("ask", "bye")],
    )
    run_id = engine.start(flow_id, ALICE)
    await engine.advance(run_id, _bot)
    _expire(run_id)

    await engine.sweep_timeouts(lambda _id: _bot)
    # Та же задача из очереди — уже после того, как подметание всё сделало.
    from types import SimpleNamespace

    import tg_repost.flow_bots as flow_bots

    original = flow_bots.bot_for
    flow_bots.bot_for = lambda _id: _bot  # type: ignore[assignment]
    try:
        await engine.handle_timer_task(SimpleNamespace(payload={"run_id": run_id}))
    finally:
        flow_bots.bot_for = original  # type: ignore[assignment]

    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_RUNNING, "прохождение закрыли на середине"
    assert run.waiting_for == "text", "человек больше не ждёт вопроса"


def _expire(run_id: int) -> None:
    from datetime import datetime, timedelta, timezone

    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        run.wait_until = datetime.now(timezone.utc) - timedelta(hours=1)


# --- недостижимый человек ---


async def test_blocked_person_stops_the_run(_bot):
    flow_id, run_id = await _training_track()
    _bot.send_message.side_effect = Exception("Forbidden: bot was blocked by the user")

    await engine.advance(run_id, _bot)

    run = _run(flow_id)
    assert run is not None
    assert run.status == engine.STATUS_STOPPED
    assert "недоступен" in (run.stop_reason or "")

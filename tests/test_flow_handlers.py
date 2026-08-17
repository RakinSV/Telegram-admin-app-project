"""Апдейт → движок сценария (F75).

Апдейты идут через НАСТОЯЩИЙ диспетчер aiogram, а не в обработчик напрямую:
половина смысла этого файла — в фильтрах и порядке. «Только личка» и «сначала
ответ, потом повод» проверить прямым вызовом невозможно, а сломать легко.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from tg_repost import flow_bots, flow_engine, flow_handlers
from tg_repost import flows_repo as flows
from tg_repost.db.models import (
    Flow,
    FlowEdge,
    FlowNode,
    FlowRun,
    ManagedBot,
    QueuedTask,
)
from tg_repost.db.session import session_scope

ALICE = 30301
GROUP = -1009999


@pytest.fixture(autouse=True)
async def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FlowRun).delete()
            session.query(FlowEdge).delete()
            session.query(FlowNode).delete()
            session.query(Flow).delete()
            session.query(ManagedBot).delete()
            session.query(QueuedTask).delete()

    _wipe()
    await flow_bots.forget_all()
    yield
    _wipe()
    await flow_bots.forget_all()


@pytest.fixture
def dispatcher() -> Dispatcher:
    """Свежий диспетчер на каждый тест.

    Router в aiogram — модульный синглтон: оставленная привязка к диспетчеру
    прошлого теста ломает следующий («router is already attached»), поэтому
    после теста она снимается.
    """
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(flow_handlers.router)
    try:
        yield dp
    finally:
        flow_handlers.router._parent_router = None


@pytest.fixture
def bot() -> AsyncMock:
    """Поддельный бот, ЗАРЕГИСТРИРОВАННЫЙ в реестре живых экземпляров.

    Иначе обработчик не сможет пройти от апдейта к строке реестра, и это
    правильно: отвечать от имени бота, которого нет в реестре, нельзя.
    """
    fake = AsyncMock()
    fake.id = 777
    # `getMe` подделывается НАСТОЯЩИМ объектом: фильтр команд aiogram сверяет
    # адресата в «/urok@my_bot» с именем бота, и на автоматической заглушке
    # сравнение молча уходит в сравнение двух заглушек.
    fake.me = AsyncMock(return_value=User(
        id=777, is_bot=True, first_name="Конструктор", username="my_bot",
    ))
    with session_scope() as session:
        row = ManagedBot(name="Конструктор", token_encrypted="x", token_hint="••••")
        session.add(row)
        session.flush()
        bot_id = row.id
    flow_bots._instances[bot_id] = fake
    fake.registry_id = bot_id
    return fake


def _published(bot_id: int, *, trigger: str = "start",
               trigger_value: str | None = None) -> int:
    flow_id = flows.create(bot_id, "Урок", trigger=trigger,
                           trigger_value=trigger_value)
    flows.save_draft(
        flow_id,
        [
            {"node_key": "hi", "kind": flows.SHOW_TEXT,
             "config": {"text": "Здравствуйте"}, "x": 0, "y": 0},
            {"node_key": "ask", "kind": flows.ASK_TEXT,
             "config": {"text": "Как вас зовут?", "variable": "имя"}, "x": 0, "y": 0},
            {"node_key": "bye", "kind": flows.SHOW_TEXT,
             "config": {"text": "Спасибо"}, "x": 0, "y": 0},
        ],
        [
            {"from_key": "hi", "to_key": "ask", "condition": flows.ALWAYS},
            {"from_key": "ask", "to_key": "bye", "condition": flows.ALWAYS},
        ],
    )
    flows.publish(flow_id)
    return flow_id


def _message(text: str, *, chat_id: int = ALICE, chat_type: str = "private") -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=10, date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type=chat_type),
            from_user=User(id=ALICE, is_bot=False, first_name="Алиса"),
            text=text,
        ),
    )


def _press(data: str, *, by: int = ALICE) -> Update:
    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb1", from_user=User(id=by, is_bot=False, first_name="Алиса"),
            chat_instance="ci", data=data,
        ),
    )


def _sent(bot: AsyncMock) -> list[str]:
    """Тексты, отправленные ботом.

    Обработчик отвечает через `message.answer`, а тот уходит в бота вызовом
    метода `SendMessage` — сюда и смотрим.
    """
    texts = []
    for call in bot.call_args_list:
        if call.args and isinstance(call.args[0], SendMessage):
            texts.append(call.args[0].text)
    texts.extend(
        c.args[1] for c in bot.send_message.await_args_list if len(c.args) > 1
    )
    return texts


# --- запуск ---


async def test_start_launches_the_published_flow(dispatcher, bot):
    _published(bot.registry_id)

    await dispatcher.feed_update(bot, _message("/start"))

    sent = _sent(bot)
    assert "Здравствуйте" in sent
    assert "Как вас зовут?" in sent


async def test_start_without_a_flow_says_so_instead_of_going_silent(dispatcher, bot):
    """Тишина в ответ на «/start» человек читает как «бот сломан» и уходит."""
    await dispatcher.feed_update(bot, _message("/start"))

    assert flow_handlers.NOTHING_SET_UP in _sent(bot)


async def test_group_chatter_is_ignored(dispatcher, bot):
    """Бота-конструктора могут добавить в группу. Вести сценарий посреди
    чужого разговора — последнее, чего от него ждут."""
    _published(bot.registry_id, trigger="keyword", trigger_value="урок")

    await dispatcher.feed_update(
        bot, _message("урок", chat_id=GROUP, chat_type="supergroup"),
    )

    assert _sent(bot) == []
    with session_scope() as session:
        assert session.query(FlowRun).count() == 0


async def test_keyword_starts_the_flow(dispatcher, bot):
    _published(bot.registry_id, trigger="keyword", trigger_value="урок")

    await dispatcher.feed_update(bot, _message("Урок"))

    assert "Здравствуйте" in _sent(bot), "слово-повод должно ловиться без регистра"


async def test_unknown_word_gets_no_reply(dispatcher, bot):
    """Отвечать «не понял» на каждое слово — верный способ, чтобы человек
    перестал писать вовсе."""
    _published(bot.registry_id, trigger="keyword", trigger_value="урок")

    await dispatcher.feed_update(bot, _message("привет, как дела"))

    assert _sent(bot) == []


async def test_command_trigger_ignores_the_bot_suffix(dispatcher, bot):
    _published(bot.registry_id, trigger="command", trigger_value="urok")

    await dispatcher.feed_update(bot, _message("/urok@my_bot"))

    assert "Здравствуйте" in _sent(bot)


# --- ответ важнее повода ---


async def test_answer_wins_over_the_trigger_word(dispatcher, bot):
    """ГЛАВНЫЙ ПОРЯДОК В ЭТОМ ФАЙЛЕ.

    Человека спросили «как вас зовут». Он может ответить словом, совпадающим с
    поводом для запуска — понять это как команду значило бы бросить начатое на
    полпути и начать заново.
    """
    flow_id = _published(bot.registry_id, trigger="keyword", trigger_value="урок")
    await dispatcher.feed_update(bot, _message("урок"))
    bot.reset_mock()

    await dispatcher.feed_update(bot, _message("урок"))

    assert "Спасибо" in _sent(bot), "ответ не принят"
    with session_scope() as session:
        run = session.query(FlowRun).filter(FlowRun.flow_id == flow_id).one()
        assert '"имя": "урок"' in run.variables_json.replace("\\u", "u")


async def test_repeated_start_does_not_restart_a_running_track(dispatcher, bot):
    _published(bot.registry_id)
    await dispatcher.feed_update(bot, _message("/start"))
    bot.reset_mock()

    await dispatcher.feed_update(bot, _message("/start"))

    assert flow_handlers.ALREADY_INSIDE in _sent(bot)
    assert "Здравствуйте" not in _sent(bot)


# --- выход ---


async def test_person_can_leave_with_stop(dispatcher, bot):
    flow_id = _published(bot.registry_id)
    await dispatcher.feed_update(bot, _message("/start"))
    bot.reset_mock()

    await dispatcher.feed_update(bot, _message("/stop"))

    assert flow_handlers.STOPPED in _sent(bot)
    with session_scope() as session:
        run = session.query(FlowRun).filter(FlowRun.flow_id == flow_id).one()
        assert run.status == flow_engine.STATUS_STOPPED
        assert run.stop_reason == "человек вышел сам"


async def test_stop_answers_even_without_a_track(dispatcher, bot):
    """Человек мог уже выйти и написать «/stop» второй раз — молчание в ответ
    выглядит поломкой."""
    await dispatcher.feed_update(bot, _message("/stop"))

    assert flow_handlers.STOPPED in _sent(bot)


# --- кнопки ---


async def test_stale_button_gets_an_answer(dispatcher, bot):
    """Непогашенная кнопка оставляет человеку вечные часики, и он жмёт ещё раз.

    Ответ приходит на сам callback: `answer_callback_query`.
    """
    _published(bot.registry_id)
    await dispatcher.feed_update(bot, _message("/start"))
    bot.reset_mock()

    await dispatcher.feed_update(
        bot, _press(flow_engine.build_callback(999, "нет-такого", "1")),
    )

    answered = [
        call.args[0] for call in bot.call_args_list
        if call.args and type(call.args[0]).__name__ == "AnswerCallbackQuery"
    ]
    assert answered, "кнопка не погашена"
    assert answered[0].text == flow_handlers.STALE_BUTTON


async def test_broken_callback_data_is_answered_and_dropped(dispatcher, bot):
    await dispatcher.feed_update(bot, _press("flow:мусор"))

    answered = [
        call.args[0] for call in bot.call_args_list
        if call.args and type(call.args[0]).__name__ == "AnswerCallbackQuery"
    ]
    assert answered and not answered[0].text


async def test_update_from_a_bot_outside_the_registry_is_ignored(dispatcher):
    """Связать апдейт со сценарием нечем — отвечать от чужого имени нельзя."""
    stranger = AsyncMock()
    stranger.id = 12345

    await dispatcher.feed_update(stranger, _message("/start"))

    assert stranger.call_args_list == []

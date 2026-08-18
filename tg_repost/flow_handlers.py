"""Обработчики ботов-конструкторов: апдейт → движок сценария (F75).

ОДИН ROUTER НА ВСЕ БОТЫ РЕЕСТРА. Диспетчер aiogram ведёт несколько ботов, и
обработчик получает тот бот, которому пришёл апдейт; по нему находится строка
реестра, а по строке — сценарии. Отдельных обработчиков на каждого бота не
нужно, и это же главная причина, по которой боты живут в одном процессе.

ТОЛЬКО ЛИЧКА. Бота-конструктора могут добавить в группу; реагировать там на
каждое сообщение значило бы вести сценарий посреди чужого разговора.

ЭТИ ОБРАБОТЧИКИ НЕ СМЕШИВАЮТСЯ С ENGAGE. У Engage свой диспетчер, и его
обработчик поддержки ловит ЛЮБОЕ личное сообщение. Подмешай сюда его router —
и человек, отвечающий боту-конструктору, попадёт в переписку с поддержкой.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from tg_repost import flow_bots, flow_engine
from tg_repost import flows_repo as flows
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

router = Router(name="flow_constructor")
router.message.filter(F.chat.type == ChatType.PRIVATE)

# Команда выхода. Человек, попавший в автоматическую цепочку, обязан иметь
# способ из неё выйти, не блокируя бота: блокировка — единственная
# альтернатива, и она стоит владельцу подписчика.
STOP_COMMAND = "/stop"

NOTHING_SET_UP = (
    "Пока здесь ничего не настроено. Владелец бота ещё не опубликовал сценарий."
)
ALREADY_INSIDE = "Вы уже проходите сценарий — ответьте на последний вопрос выше."
STOPPED = "Хорошо, остановил. Напишите /start, когда захотите начать заново."
STALE_BUTTON = "Этот шаг уже пройден"


def _bot_id(bot) -> int | None:  # aiogram Bot
    bot_id = flow_bots.bot_id_of(bot)
    if bot_id is None:
        # Экземпляр не из реестра: опрос запущен помимо `flow_bots`, и связать
        # апдейт со сценарием нечем. Молчим — отвечать от чужого имени хуже.
        logger.warning("F75: апдейт от бота вне реестра — пропущен")
    return bot_id


def _user_id(message: Message) -> int | None:
    """Кто написал. `None` — писавшего нет (например пост от имени канала):
    сценарий ведут человеку, а не каналу."""
    return message.from_user.id if message.from_user is not None else None


async def _launch(message: Message, bot, flow_id: int, user_id: int) -> None:
    run_id = flow_engine.start(flow_id, user_id)
    if run_id is None:
        await message.answer(ALREADY_INSIDE)
        return
    await flow_engine.advance(run_id, bot)


@router.callback_query(F.data.startswith(f"{flow_engine.CALLBACK_PREFIX}:"))
async def on_button(callback: CallbackQuery, bot) -> None:
    """Нажатие кнопки сценария.

    Кнопка ГАСИТСЯ ВСЕГДА, чем бы дело ни кончилось: непогашенная оставляет у
    человека вечные часики, и он жмёт ещё раз.
    """
    parsed = flow_engine.parse_callback(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    run_id, node_key, value = parsed
    handled = await flow_engine.handle_button(
        run_id, node_key, value, bot, by_user_id=callback.from_user.id,
    )
    await callback.answer() if handled else await callback.answer(STALE_BUTTON)


@router.message(CommandStart())
async def on_start(message: Message, bot) -> None:
    bot_id = _bot_id(bot)
    user_id = _user_id(message)
    if bot_id is None or user_id is None:
        return
    flow = flows.find_by_trigger(bot_id, "start")
    if flow is None:
        logger.info("F75: боту #%d написали /start, а сценария нет", bot_id)
        await message.answer(NOTHING_SET_UP)
        return
    await _launch(message, bot, flow.id, user_id)


@router.message(F.text)
async def on_text(message: Message, bot) -> None:
    """Текст: сначала как ОТВЕТ на вопрос, потом как повод начать.

    Порядок именно такой. Человек, которого спросили «как вас зовут», может
    ответить словом, совпадающим с поводом для запуска другого сценария; понять
    его ответ как команду значило бы бросить начатое на полпути.
    """
    bot_id = _bot_id(bot)
    user_id = _user_id(message)
    if bot_id is None or user_id is None:
        return
    text = (message.text or "").strip()

    if text.lower() == STOP_COMMAND:
        run_id = flow_engine.running_run_for(user_id, bot_id)
        if run_id is not None:
            flow_engine.stop_by_person(run_id)
        await message.answer(STOPPED)
        return

    is_command = text.startswith("/")
    if not is_command:
        run_id = flow_engine.waiting_run_for(user_id, bot_id, "text")
        if run_id is not None and await flow_engine.handle_text(run_id, text, bot):
            return

    if is_command:
        # «/urok@my_bot» в личке тоже бывает — обрезаем адресата.
        trigger, value = "command", text[1:].split()[0].split("@")[0]
    else:
        trigger, value = "keyword", text

    flow = flows.find_by_trigger(bot_id, trigger, value)
    if flow is None:
        # Ни ответ, ни повод: молчим. Отвечать «не понял» на каждое слово —
        # верный способ, чтобы человек перестал писать вовсе.
        return
    await _launch(message, bot, flow.id, user_id)

"""Приём обращений в поддержку (F68).

Ловит ЛИЧНЫЕ сообщения, не подошедшие ни одному обработчику выше, и кладёт
их в инбокс.

ЭТОТ РОУТЕР РЕГИСТРИРУЕТСЯ ПОСЛЕДНИМ — иначе он проглотит и команды, и
текст, который ждёт предложка (F47 держит его через FSM-состояние). Порядок
здесь не стилистика: перепутав его, мы сломаем всё, что бот умеет, и
обнаружим это по тишине в ответ на `/quiz`.

ТОЛЬКО ЛИЧКА. Сообщения в группе — работа модерации (Guardian), а не
поддержки; тащить их сюда значило бы превратить инбокс в копию чата.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from tg_repost import support_repo
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="support")

_ACK = (
    "Получил, спасибо. Отвечу, как только смогу — ответ придёт сюда же."
)


@router.message(F.chat.type == "private", F.text)
async def on_private_message(message: Message) -> None:
    """Любое личное сообщение, не разобранное выше, — обращение в поддержку."""
    if message.from_user is None or message.from_user.is_bot:
        return
    text = message.text or ""
    # Команду, до которой не дошёл ни один обработчик, в поддержку не пишем:
    # это опечатка в команде, а не вопрос, и оператору она ничего не скажет.
    if text.startswith("/"):
        return

    thread_id = support_repo.record_incoming(
        message.from_user.id, text, username=message.from_user.username,
    )
    if thread_id is None:
        return

    # F64: раз человек написал в личку, боту разрешено ему отвечать —
    # фиксируем это, иначе он не попадёт в рассылки, даже согласившись.
    from tg_repost import subscribers_repo

    subscribers_repo.record_contact(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    # Подтверждение обязательно: без него человек не знает, дошло ли, и
    # пишет второй раз — а потом уходит, решив, что тут никого нет.
    await message.answer(_ACK)

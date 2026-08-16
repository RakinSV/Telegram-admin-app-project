"""`/start` с deep-link — точка входа участника в Engage.

Telegram позволяет привести человека в бота ссылкой `t.me/<bot>?start=PAYLOAD`
(payload до 64 символов), и бот получает этот payload первым же сообщением.
Это фундамент сразу трёх фич:
  • F42 рефералы   — `ref_<user_id>`: кто пригласил;
  • F44 конкурсы   — `contest_<id>`: участие по кнопке из поста;
  • F47 предложка  — `suggest`: сразу открыть приём поста.

Здесь только разбор payload и маршрутизация: сами фичи подключаются
обработчиками ниже по мере реализации. Неизвестный payload — НЕ ошибка:
ссылку могли скопировать из старого поста, человеку надо ответить по-людски,
а не молчать.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="start")

# Префиксы deep-link. Отделяются ПЕРВЫМ подчёркиванием: сам payload может
# содержать подчёркивания (например, base64-подобные идентификаторы).
PAYLOAD_REFERRAL = "ref"
PAYLOAD_CONTEST = "contest"
PAYLOAD_SUGGEST = "suggest"

_WELCOME = (
    "Привет! Я помогаю с активностями канала: викторины по постам, "
    "конкурсы и приглашения друзей.\n\n"
    "Команды:\n"
    "/me — мои очки\n"
    "/top — таблица лидеров"
)


@dataclass(frozen=True)
class DeepLink:
    """Разобранный payload: тип и аргумент."""

    kind: str
    value: str


def parse_payload(payload: str | None) -> DeepLink | None:
    """Разобрать payload deep-link. None — ссылка без payload (обычный /start).

    Разделяем по ПЕРВОМУ подчёркиванию: `ref_12345` → ("ref", "12345"),
    `contest_7` → ("contest", "7"), `suggest` → ("suggest", "").
    """
    if not payload:
        return None
    kind, _, value = payload.partition("_")
    if not kind:
        return None
    return DeepLink(kind=kind, value=value)


@router.callback_query(F.data == "bcast:off")
async def on_unsubscribe(callback: CallbackQuery) -> None:
    """Отписка от рассылок кнопкой из самого сообщения (F64).

    Кнопка есть в каждой рассылке намеренно: без неё единственным способом
    прекратить поток осталась бы блокировка бота — а это потеря человека
    целиком, включая ответы на его собственные вопросы.

    Отписка НЕ мешает боту отвечать: человек отказался от рассылок, а не от
    общения.
    """
    from tg_repost import subscribers_repo

    changed = subscribers_repo.unsubscribe(callback.from_user.id)
    # Путь назад называется ЗДЕСЬ и только здесь. Возможность вернуться,
    # о которой человек не знает, — это отсутствие возможности: он отпишется
    # один раз и останется отписанным навсегда, даже если передумает через
    # день. Найдено аудитом: функция возврата была написана и не имела ни
    # одного входа.
    await callback.answer(
        "Больше не буду присылать рассылки. Отвечать на вопросы продолжу.\n\n"
        "Передумаете — команда /mailing вернёт их."
        if changed
        else "Вы уже отписаны от рассылок. Команда /mailing вернёт их.",
        show_alert=True,
    )


@router.message(Command("mailing"))
async def on_mailing(message: Message) -> None:
    """Вернуть рассылки, от которых человек отказался (F64).

    Отдельная команда, а не кнопка в сообщении: кнопка живёт в конкретной
    рассылке, а отписавшемуся рассылки больше не приходят — нажимать было
    бы негде.
    """
    from tg_repost import subscribers_repo

    user = message.from_user
    if user is None:
        return
    if subscribers_repo.resubscribe(user.id):
        await message.answer("Готово, рассылки снова включены.")
    else:
        await message.answer("Рассылки и так включены.")


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, bot: Bot) -> None:
    """Приветствие + маршрутизация deep-link."""
    link = parse_payload(command.args)
    user = message.from_user
    user_id = user.id if user is not None else 0

    # F64: с этого момента боту РАЗРЕШЕНО писать человеку — Telegram не даёт
    # заговорить первым, и `/start` это единственный момент, когда разрешение
    # появляется. Не записать его здесь значит навсегда потерять получателя.
    if user is not None and user_id:
        from tg_repost import subscribers_repo

        subscribers_repo.record_contact(
            user_id, username=user.username, first_name=user.first_name,
        )
        # F71: запуск воронок. Повторное нажатие «Запустить» цепочку не
        # дублирует — защита стоит в самом `enroll`, а не здесь: сюда можно
        # попасть и по deep-link, и обычным стартом.
        from tg_repost import funnels_repo

        try:
            funnels_repo.enroll(user_id)
        except Exception as exc:  # noqa: BLE001
            # Сбой воронки не должен ломать приветствие: человек пришёл по
            # ссылке на конкурс, и молчание вместо ответа он свяжет с ней.
            logger.warning("F71: не удалось записать %s в воронки: %s", user_id, exc)

    if link is None:
        await message.answer(_WELCOME)
        return

    if link.kind == PAYLOAD_REFERRAL:
        from engage.handlers.referral import handle_referral_start
        from tg_repost import targets_repo

        targets = [t for t in targets_repo.list_targets() if t.is_active]
        if targets and user_id:
            await handle_referral_start(bot, link.value, user_id, targets[0].chat_id)
    elif link.kind == PAYLOAD_CONTEST:
        from engage.handlers.contest import handle_contest_start

        if user is not None:
            await handle_contest_start(bot, link.value, user, message)
            return  # ответ уже отправлен обработчиком конкурса
    elif link.kind == PAYLOAD_SUGGEST:
        logger.info("Deep-link предложки от %s", user_id)
        await message.answer(f"{_WELCOME}\n\nЧтобы предложить пост: /suggest")
        return
    else:
        # Ссылку могли скопировать из старого поста — молчать нельзя.
        logger.info("Неизвестный deep-link '%s' от %s", link.kind, user_id)

    await message.answer(_WELCOME)

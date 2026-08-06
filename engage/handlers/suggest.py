"""Предложка: посты от подписчиков (F47).

Красота решения в том, что нового пайплайна не нужно: предложенный пост
кладётся в ТУ ЖЕ очередь модерации, что и рерайты, со статусом `rewritten` —
дальше он идёт обычным путём (владелец видит его в боте и на /moderation,
одобряет, пост публикуется в целевые группы). Новый здесь только источник
поступления.

Онбординг новичка (F46) живёт здесь же: и то, и другое — короткий диалог с
участником в личке, разносить их по модулям не за что.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="suggest")

# Слишком короткое «предложение» — это не пост, а случайное сообщение боту.
MIN_SUGGESTION_LEN = 30
# Потолок: Telegram и так режет по 4096, но пускать в очередь простыню незачем.
MAX_SUGGESTION_LEN = 3000


class SuggestState(StatesGroup):
    waiting_text = State()


ONBOARDING_TEXT = (
    "Привет! Коротко, что тут есть:\n\n"
    "• По постам иногда бывают викторины — за правильные ответы дают очки "
    "(/me покажет твои, /top — таблицу лидеров).\n"
    "• Можно приглашать друзей своей ссылкой: /invite.\n"
    "• Есть что предложить в канал? Команда /suggest.\n\n"
    "Приятного чтения!"
)


async def send_onboarding(bot: Bot, user_id: int) -> bool:
    """F46: короткий онбординг новичку в личку.

    Пишем ТОЛЬКО тем, кто уже стартовал бота: Telegram не даёт писать первым,
    и попытка вернёт ошибку — это нормальный, ожидаемый случай, а не сбой.
    """
    try:
        await bot.send_message(user_id, ONBOARDING_TEXT, disable_notification=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Онбординг не доставлен %s: %s", user_id, exc)
        return False
    return True


def create_suggested_post(text: str, author_id: int, author_name: str) -> int | None:
    """Положить предложенный пост в очередь модерации.

    Статус сразу `rewritten`: рерайтить пользовательский текст не надо — его
    предложили именно таким. Дальше пост идёт обычным путём, как AD/DIGEST
    (те тоже создаются готовыми, минуя NEW и дедуп).
    """
    cleaned = text.strip()
    if len(cleaned) < MIN_SUGGESTION_LEN:
        return None
    cleaned = cleaned[:MAX_SUGGESTION_LEN]
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE,
            status=PostStatus.REWRITTEN,
            original_text=cleaned,
            rewritten_text=cleaned,
            # Автор виден владельцу при модерации: публиковать чужой текст без
            # понимания, кто его прислал, — плохая идея.
            status_reason=f"предложка от {author_name} (id{author_id})",
        )
        session.add(post)
        session.flush()
        return post.id


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext) -> None:
    if not get_settings().suggestions_enabled:
        await message.answer("Предложка сейчас закрыта.")
        return
    await state.set_state(SuggestState.waiting_text)
    await message.answer(
        "Пришли текст поста одним сообщением — я передам его владельцу канала "
        "на модерацию. Опубликуют не всё и не сразу.\n\n"
        "Отменить: /cancel",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Отменил.")


@router.message(SuggestState.waiting_text)
async def on_suggestion_text(message: Message, state: FSMContext) -> None:
    """Принять текст предложки и положить в общую очередь модерации."""
    user = message.from_user
    text = message.text or message.caption or ""
    if user is None:
        await state.clear()
        return

    post_id = create_suggested_post(
        text, user.id, user.username and f"@{user.username}" or user.full_name,
    )
    await state.clear()
    if post_id is None:
        await message.answer(
            f"Слишком короткий текст — нужно хотя бы {MIN_SUGGESTION_LEN} символов. "
            "Попробуй ещё раз: /suggest",
        )
        return
    logger.info("Предложка от %s принята как пост %s", user.id, post_id)
    await message.answer(
        "Спасибо, отправил владельцу на модерацию. Если пост подойдёт — он "
        "появится в канале.",
    )

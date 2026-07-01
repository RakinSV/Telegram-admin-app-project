"""Верификация новых участников капчей (G01) — подход A из GUARDIAN.md:
мут сразу при вступлении, снимается после правильного ответа, тайм-аут —
кик.

НЕ использует aiogram FSM. Более ранняя версия полагалась на то, что aiogram
ключует FSM-состояние по (chat_id, user_id) САМОГО КЛИКНУВШЕГО — это верно
для `callback_query`, но НЕ для `chat_member`-апдейтов: aiogram резолвит
`user` для них как `event.chat_member.from_user` (см.
`aiogram/dispatcher/middlewares/user_context.py::resolve_event_context`) —
т.е. того, кто СОВЕРШИЛ действие над участником, а не самого нового
участника (`new_chat_member.user`). Для обычного добровольного входа по
инвайт-ссылке они совпадают (пользователь — сам себе "исполнитель"), но
когда участника добавляет кто-то другой (админ, другой участник через
"Добавить в группу"), `from_user` — это ДОБАВИВШИЙ, и капча-состояние
записывалось бы под его ключ, а не под ключ реально замученного нового
участника — тот, кто добавил, мог бы кликнуть чужую капчу и "верифицировать"
сам себя вместо реального новичка (найдено при security-аудите).

Вместо FSM — явный словарь `_pending`, ключ (chat_id, user_id) РЕАЛЬНОГО
нового участника (`new_chat_member.user.id`), плюс `target_user_id`,
закодированный прямо в `callback_data` кнопок (см. `services/captcha.py`) —
`on_captcha_answer` явно сверяет `callback.from_user.id` с этим id ДО того,
как вообще посмотреть в `_pending`. Атомарность между "ответили правильно" и
"истёк тайм-аут" обеспечивается тем, что оба пути ПЕРВЫМ действием делают
`_pending.pop(...)` без `await` до этого — в однопоточном asyncio-цикле это
исключает гонку (кто первый выполнится, тот и заберёт запись; awaits внутри
`_kick_unverified`/`on_captcha_answer` наступают уже ПОСЛЕ pop, так что
второй обработчик, если всё же будет вызван, увидит `None` и тихо выйдет).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.types import CallbackQuery, ChatMemberUpdated, ChatPermissions, User
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from guardian.config import get_guardian_settings
from guardian.db.models import Member, ModerationLog
from guardian.db.session import session_scope
from guardian.logging_conf import get_logger
from guardian.services.captcha import generate_captcha, make_captcha_keyboard
from guardian.services.log_channel import log_action

logger = get_logger(__name__)
router = Router(name="join")

_MUTED_PERMISSIONS = ChatPermissions(can_send_messages=False)
_WELCOME_TTL_SECONDS = 120


@dataclass
class _PendingCaptcha:
    correct_answer: str
    options: list[str]
    captcha_message_id: int


# (chat_id, user_id) РЕАЛЬНОГО нового участника -> ожидаемый ответ.
# Состояние только в памяти процесса (перезапуск Guardian во время открытой
# капчи потеряет её — участник получит кик по тайм-ауту при следующем
# срабатывании джобы; APScheduler-джобы тоже in-memory, см. bot.py, так что
# это уже существующее ограничение, не новое).
_pending: dict[tuple[int, int], _PendingCaptcha] = {}


def _timeout_job_id(chat_id: int, user_id: int) -> str:
    return f"captcha_timeout_{chat_id}_{user_id}"


def _display_name(user: User) -> str:
    raw = f"@{user.username}" if user.username else user.full_name
    return escape(raw)


@router.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER)
)
async def on_new_member(
    event: ChatMemberUpdated, bot: Bot, scheduler: AsyncIOScheduler
) -> None:
    settings = get_guardian_settings()
    chat_id, user_id = event.chat.id, event.new_chat_member.user.id
    if chat_id != settings.guardian_group_id or event.new_chat_member.user.is_bot:
        return

    with session_scope() as session:
        row = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if row is not None and row.is_trusted:
            return  # доверенный участник (например переприглашённый) — без капчи

    try:
        await bot.restrict_chat_member(chat_id, user_id, permissions=_MUTED_PERMISSIONS)
    except TelegramBadRequest as exc:
        # Бот не админ / нет прав restrict_members — без этого верификация
        # физически невозможна (см. GUARDIAN.md "Права бота в группе").
        logger.error(
            "Не удалось замутить нового участника %s в %s: %s", user_id, chat_id, exc
        )
        return

    with session_scope() as session:
        row = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        if row is None:
            session.add(
                Member(
                    user_id=user_id,
                    chat_id=chat_id,
                    username=event.new_chat_member.user.username,
                    first_name=event.new_chat_member.user.first_name,
                    is_verified=False,
                )
            )
        else:
            row.is_verified = False
            row.username = event.new_chat_member.user.username
            row.first_name = event.new_chat_member.user.first_name

    with session_scope() as session:
        captcha = generate_captcha(settings.captcha_type, session=session)
    keyboard, options = make_captcha_keyboard(captcha, target_user_id=user_id)
    mention = _display_name(event.new_chat_member.user)
    sent = await bot.send_message(
        chat_id,
        f"{mention}, добро пожаловать! Ответь на вопрос, чтобы получить доступ к чату:\n\n"
        f"{escape(captcha.question)}\n\nУ тебя {settings.captcha_timeout_minutes} мин.",
        reply_markup=keyboard,
    )

    _pending[(chat_id, user_id)] = _PendingCaptcha(
        correct_answer=captcha.correct_answer,
        options=options,
        captcha_message_id=sent.message_id,
    )

    run_date = datetime.now(timezone.utc) + timedelta(
        minutes=settings.captcha_timeout_minutes
    )
    scheduler.add_job(
        _kick_unverified,
        "date",
        run_date=run_date,
        args=[bot, chat_id, user_id],
        id=_timeout_job_id(chat_id, user_id),
        replace_existing=True,
    )


@router.callback_query(F.data.startswith("captcha:"))
async def on_captcha_answer(
    callback: CallbackQuery, bot: Bot, scheduler: AsyncIOScheduler
) -> None:
    assert callback.data is not None  # гарантировано фильтром выше
    parts = callback.data.split(":", 2)
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await callback.answer()
        return
    target_user_id, index = int(parts[1]), int(parts[2])

    # Явная проверка владения — до любого обращения к `_pending`. Кнопки в
    # группе видны и кликабельны всем, Telegram сам это не ограничивает.
    if callback.from_user.id != target_user_id:
        await callback.answer("Эта капча не для тебя.", show_alert=True)
        return

    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id

    pending = _pending.get((chat_id, target_user_id))
    if pending is None:
        await callback.answer("Капча уже неактуальна.", show_alert=True)
        return
    if index >= len(pending.options):
        await callback.answer()
        return
    chosen = pending.options[index]

    if chosen != pending.correct_answer:
        await callback.answer("Неверно, попробуй ещё раз.", show_alert=True)
        return

    # Атомарный "захват" (см. docstring модуля) — синхронно, без await между
    # проверкой выше и pop, конкурирует с `_kick_unverified`.
    claimed = _pending.pop((chat_id, target_user_id), None)
    if claimed is None:
        await callback.answer()  # тайм-аут успел забрать запись первым
        return

    await callback.answer("Верно! Добро пожаловать 🎉")

    try:
        job_id = _timeout_job_id(chat_id, target_user_id)
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            pass  # уже сработал/удалён — безопасно игнорировать

        chat = await bot.get_chat(chat_id)
        await bot.restrict_chat_member(
            chat_id,
            target_user_id,
            permissions=chat.permissions or ChatPermissions(can_send_messages=True),
        )

        try:
            await bot.delete_message(chat_id, claimed.captcha_message_id)
        except TelegramBadRequest:
            pass

        welcome = await bot.send_message(
            chat_id,
            f"Добро пожаловать, {_display_name(callback.from_user)}! "
            "Запрещено: реклама, ссылки без разрешения, спам. "
            "За нарушение — предупреждение → мут → бан.",
        )
        scheduler.add_job(
            _delete_message_safe,
            "date",
            run_date=datetime.now(timezone.utc)
            + timedelta(seconds=_WELCOME_TTL_SECONDS),
            args=[bot, chat_id, welcome.message_id],
            id=f"welcome_cleanup_{chat_id}_{welcome.message_id}",
        )
    finally:
        with session_scope() as session:
            row = (
                session.query(Member)
                .filter(Member.user_id == target_user_id, Member.chat_id == chat_id)
                .one_or_none()
            )
            if row is not None:
                row.is_verified = True
            session.add(
                ModerationLog(
                    action="verify",
                    user_id=target_user_id,
                    chat_id=chat_id,
                    actor="auto",
                )
            )
        await log_action(
            bot,
            "verify",
            user_id=target_user_id,
            chat_id=chat_id,
            username=callback.from_user.username,
        )


async def _kick_unverified(bot: Bot, chat_id: int, user_id: int) -> None:
    # Тот же атомарный "захват", что и в `on_captcha_answer` — см. docstring
    # модуля. `None` значит пользователь уже успешно верифицировался.
    claimed = _pending.pop((chat_id, user_id), None)
    if claimed is None:
        return

    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except TelegramBadRequest as exc:
        logger.warning(
            "Не удалось кикнуть непрошедшего верификацию %s из %s: %s",
            user_id,
            chat_id,
            exc,
        )

    await _delete_message_safe(bot, chat_id, claimed.captcha_message_id)

    with session_scope() as session:
        session.add(
            ModerationLog(
                action="kick",
                user_id=user_id,
                chat_id=chat_id,
                reason="не прошёл капчу за отведённое время",
                actor="auto",
            )
        )
    await log_action(
        bot, "kick", user_id=user_id, chat_id=chat_id, reason="тайм-аут капчи"
    )


async def _delete_message_safe(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass

"""Пайплайн фильтров на входящее сообщение группы (G03/G04/G06/G09/G10).

Порядок проверок — от дешёвых к дорогим: trusted-байпас → форварды → флуд →
дубли → ссылки → стоп-слова (`keywords`/`hybrid`) → эвристики+AI (`hybrid`,
только для подозрительных ~20%) → AI на каждое сообщение (`ai`-режим,
дороже всего, поэтому последний и опциональный).
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from guardian import spam_reviews_repo
from guardian.config import GuardianSettings, get_guardian_settings
from guardian.db.models import Member, ModerationLog, TrustedUser
from guardian.db.session import session_scope
from guardian.filters import ai_filter, heuristics
from guardian.filters.flood_filter import FloodFilter
from guardian.filters.keyword_filter import KeywordFilter
from guardian.filters.link_filter import LinkFilter
from guardian.logging_conf import get_logger
from guardian.services import chat_admins, daily_stats_repo, log_channel
from guardian.services.warn_system import add_warn

logger = get_logger(__name__)
router = Router(name="messages")

# Синглтоны на процесс — `reload()` вызывается при старте бота (bot.py) и
# после мутирующих команд администратора (/addword, /addomain — handlers/admin.py).
keyword_filter = KeywordFilter()
link_filter = LinkFilter()
_settings = get_guardian_settings()
flood_filter = FloodFilter(
    max_messages=_settings.flood_max_messages,
    window_seconds=_settings.flood_window_seconds,
)

# Минимум признаков подозрительности (G10), чтобы передать сообщение в AI —
# см. guardian/filters/heuristics.py. Не вынесено в SETTINGS_GROUPS (веб-
# админка) намеренно — это внутренний параметр алгоритма, не то, что
# оператору обычно нужно тюнить, в отличие от ai_spam_confidence_threshold.
_HYBRID_SUSPICION_THRESHOLD = 2


def _is_trusted(user_id: int, chat_id: int) -> bool:
    with session_scope() as session:
        return (
            session.query(TrustedUser)
            .filter(TrustedUser.user_id == user_id, TrustedUser.chat_id == chat_id)
            .count()
            > 0
        )


def _member_join_date(user_id: int, chat_id: int):
    with session_scope() as session:
        member = (
            session.query(Member)
            .filter(Member.user_id == user_id, Member.chat_id == chat_id)
            .one_or_none()
        )
        return member.join_date if member is not None else None


async def _delete_and_warn(bot: Bot, message: Message, user_id: int, reason: str) -> None:
    """`user_id` берётся аргументом, а не `message.from_user.id` — вызывающий
    (`on_message`) уже проверил `from_user is not None` до вызова, но эта
    проверка в другой функции, mypy не может её учесть."""
    deleted = True
    try:
        await message.delete()
    except TelegramBadRequest as exc:
        deleted = False
        logger.warning(
            "Не удалось удалить сообщение %s в %s: %s",
            message.message_id,
            message.chat.id,
            exc,
        )
    await add_warn(bot, user_id, message.chat.id, reason)
    if deleted:
        # Отдельная запись от того, что уже пишет `add_warn` (action="warn") —
        # нужна для точного счётчика "удалено сообщений" в /stats (G11):
        # не каждый warn сопровождается удалением (например варн за флуд),
        # так что age(warn) != age(deleted_msgs) (найдено при добавлении G11).
        with session_scope() as session:
            session.add(
                ModerationLog(
                    action="delete_msg",
                    user_id=user_id,
                    chat_id=message.chat.id,
                    reason=reason,
                    actor="auto",
                )
            )


async def _ai_check(
    bot: Bot, message: Message, user_id: int, text: str, settings: GuardianSettings
) -> bool:
    """Вернуть True, если сообщение обработано (удалено) — вызывающий код
    должен прекратить дальнейшую обработку."""
    result = await ai_filter.classify(text)
    if result is None:
        # Таймаут/ошибка/невалидный ответ — fail-open, пропускаем. Решение
        # прежнее: лучше пропустить спам, чем удалить живого человека.
        # F57 добавляет только НАБЛЮДЕНИЕ — раньше такая ошибка исчезала
        # бесследно, и фильтр не становился точнее никогда.
        await _queue_for_review(bot, message, user_id, text, kind="no_verdict")
        return False

    daily_stats_repo.record_ai_call(message.chat.id, result.cost_usd)
    if result.is_spam and result.confidence >= settings.ai_spam_confidence_threshold:
        await _delete_and_warn(bot, message, user_id, f"AI: {result.reason}")
        return True

    if result.is_spam:
        # Модель считает это спамом, но уверенности не хватило до порога.
        # Сообщение остаётся (порог для того и нужен), но именно на этой
        # границе разметка владельца полезнее всего: она двигает границу
        # под его аудиторию.
        await _queue_for_review(
            bot, message, user_id, text, kind="low_confidence",
            model_said_spam=True, confidence=result.confidence,
        )
    return False


async def _queue_for_review(
    bot: Bot,
    message: Message,
    user_id: int,
    text: str,
    *,
    kind: str,
    model_said_spam: bool | None = None,
    confidence: float | None = None,
) -> None:
    """Отдать спорный вердикт владельцу на разметку (F57).

    Ничего не удаляет и не банит — только наблюдает. Любой сбой здесь
    проглатывается: очередь на разметку не может быть причиной, по которой
    сломается модерация.
    """
    settings = get_guardian_settings()
    if not settings.spam_learning_enabled:
        return

    try:
        review_id = spam_reviews_repo.enqueue(
            chat_id=message.chat.id, user_id=user_id, text=text, kind=kind,
            model_said_spam=model_said_spam, confidence=confidence,
        )
        if review_id is None:
            return  # такой же текст уже ждёт разметки — лог-канал не засоряем

        note = (
            "классификатор не ответил"
            if kind == "no_verdict"
            else f"похоже на спам, но уверенность {confidence:.2f} ниже порога"
        )
        await log_channel.log_action(
            bot, "spam_review", user_id, message.chat.id,
            reason=f"Нужно решение: {note}",
            username=message.from_user.username if message.from_user else None,
            message_text=text,
            inline_kb=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🚫 Спам", callback_data=f"sr:spam:{review_id}"),
                InlineKeyboardButton(text="✅ Не спам", callback_data=f"sr:ham:{review_id}"),
            ]]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("F57: не удалось поставить вердикт на разметку: %s", exc)


@router.callback_query(F.data.startswith("sr:"))
async def on_spam_review(callback: CallbackQuery, bot: Bot) -> None:
    """Решение по спорному вердикту (F57).

    Кнопки живут в приватном лог-канале, но проверку прав это не отменяет:
    в канал могут быть добавлены другие люди, а разметка — обучающая выборка,
    от которой зависит поведение фильтра дальше.

    Право размечать = права администратора В ИСХОДНОМ ЧАТЕ, том, чью
    аудиторию эта разметка и настраивает. Переиспользуем ту же проверку, что
    у остальных админ-команд Guardian, а не заводим второй способ решать один
    и тот же вопрос.
    """
    assert callback.data is not None  # гарантировано фильтром выше
    parts = callback.data.split(":", 2)
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer()
        return
    label, review_id = parts[1], int(parts[2])

    source_chat_id = spam_reviews_repo.chat_of(review_id)
    if source_chat_id is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    if not await chat_admins.is_chat_admin(bot, source_chat_id, callback.from_user.id):
        await callback.answer(
            "Размечать может только администратор чата.", show_alert=True,
        )
        return

    if not spam_reviews_repo.set_label(review_id, label):
        await callback.answer("Не удалось записать решение.", show_alert=True)
        return

    human = "спам" if label == spam_reviews_repo.LABEL_SPAM else "не спам"
    await callback.answer(f"Записано: {human}")
    # Кнопки убираем, чтобы одна и та же запись не размечалась дважды и чтобы
    # в канале было видно, что решение уже принято. `InaccessibleMessage` —
    # сообщение старше суток или удалённое: редактировать его нельзя, но
    # решение уже записано, так что это не повод для ошибки.
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_message(message: Message, bot: Bot) -> None:
    settings = get_guardian_settings()
    if message.from_user is None or message.from_user.is_bot:
        return
    # F28: список защищаемых чатов, не одна группа — см. config.py про
    # protected_chat_ids.
    if message.chat.id not in settings.protected_chat_ids:
        return

    user_id = message.from_user.id
    if _is_trusted(user_id, message.chat.id):
        return

    if message.forward_origin is not None and not settings.allow_forwards:
        await _delete_and_warn(bot, message, user_id, "пересланное сообщение (форварды запрещены)")
        return

    if flood_filter.check_flood(message.chat.id, user_id):
        await add_warn(bot, user_id, message.chat.id, "флуд (слишком много сообщений подряд)")
        return

    text = message.text or message.caption or ""
    if text and flood_filter.check_duplicate(message.chat.id, user_id, text):
        await _delete_and_warn(bot, message, user_id, "дублирующееся сообщение подряд")
        return

    is_bad_link, domain = link_filter.check(message, message.chat.id)
    if is_bad_link:
        if settings.strict_mode:
            await _delete_and_warn(bot, message, user_id, f"ссылка на неразрешённый домен: {domain}")
            return
        # G16, soft-режим: ссылки только логируются, не удаляются и не
        # варнятся — см. GUARDIAN_FEATURES.md ("ссылки только логируются
        # (не удаляются)"). Стоп-слова ниже soft-режим НЕ смягчает — по
        # плану G16 они "работают" как обычно в обоих режимах.
        with session_scope() as session:
            session.add(
                ModerationLog(
                    action="link_flagged",
                    user_id=user_id,
                    chat_id=message.chat.id,
                    reason=f"ссылка на неразрешённый домен: {domain} (soft-режим — не удалено)",
                    actor="auto",
                )
            )

    if settings.spam_mode in ("keywords", "hybrid") and text:
        hit, word = keyword_filter.check(text, message.chat.id)
        if hit:
            await _delete_and_warn(bot, message, user_id, f"стоп-слово: {word}")
            return

    if not text:
        return

    if settings.spam_mode == "ai":
        await _ai_check(bot, message, user_id, text, settings)
    elif settings.spam_mode == "hybrid":
        join_date = _member_join_date(user_id, message.chat.id)
        if heuristics.count_suspicion_signals(message, join_date) >= _HYBRID_SUSPICION_THRESHOLD:
            await _ai_check(bot, message, user_id, text, settings)

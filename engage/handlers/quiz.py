"""Викторины: публикация, приём ответов, лидерборд (F43).

Разделение труда: вопрос СОСТАВЛЯЕТ tg_repost (у него текст статьи и
LLM-клиент, см. `tg_repost/rewriter/quiz.py`), а ПУБЛИКУЕТ и собирает ответы
Engage — он и есть бот, который говорит с участниками.

Публикуем нативным quiz-poll (`send_poll(type="quiz")`): Telegram сам
проверяет ответ, показывает верный вариант с пояснением и не даёт
переголосовать. Ноль LLM-вызовов на проверку и ноль споров «я это и имел в
виду».
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import PollType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InputPollOption, Message, PollAnswer

from tg_repost import quiz_repo
from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="quiz")


async def publish_pending_quizzes(bot: Bot) -> int:
    """Опубликовать созревшие квизы. Возвращает число отправленных.

    Зовётся джобой планировщика. Пауза после поста — часть механики: вопрос
    задаётся ПОСЛЕ того, как у людей была возможность прочитать, иначе это не
    проверка чтения, а угадайка.
    """
    settings = get_settings()
    if not settings.quiz_enabled:
        return 0
    sent = 0
    for quiz in quiz_repo.pending_quizzes(settings.quiz_delay_minutes):
        try:
            message = await bot.send_poll(
                chat_id=quiz.chat_id,
                question=quiz.question,
                # InputPollOption, а не голые строки: так тип совпадает с
                # тем, что ждёт aiogram 3.x (список инвариантен).
                options=[InputPollOption(text=o) for o in quiz.options],
                type=PollType.QUIZ,
                correct_option_id=quiz.correct_index,
                explanation=quiz.explanation or None,
                is_anonymous=False,  # иначе не узнаем, КОМУ начислять очки
            )
        except TelegramBadRequest as exc:
            # Чаще всего: бота нет в чате или он не может слать опросы. Помечаем
            # опубликованным, чтобы не долбиться в тот же квиз каждую минуту.
            logger.warning("Квиз %s не отправлен в %s: %s", quiz.id, quiz.chat_id, exc)
            quiz_repo.mark_published(quiz.id, poll_id="", message_id=0)
            continue
        poll = message.poll
        if poll is not None:
            quiz_repo.mark_published(quiz.id, poll_id=poll.id, message_id=message.message_id)
            sent += 1
    return sent


@router.poll_answer()
async def on_poll_answer(poll_answer: PollAnswer) -> None:
    """Начислить очки за ответ.

    `is_anonymous=False` у опроса — обязательное условие: у анонимного
    Telegram не сообщает, кто ответил, и начислять было бы некому.
    """
    user = poll_answer.user
    if user is None or not poll_answer.option_ids:
        return
    result = quiz_repo.record_answer(
        poll_id=poll_answer.poll_id,
        user_id=user.id,
        option_index=poll_answer.option_ids[0],
        username=user.username,
        full_name=user.full_name,
    )
    if result is None:
        return  # чужой опрос или повторный апдейт
    is_correct, earned = result
    logger.info(
        "Ответ на квиз: user=%s, верно=%s, начислено=%d", user.id, is_correct, earned,
    )


def _format_me(row: quiz_repo.LeaderRow | None) -> str:
    if row is None or row.total_answers == 0:
        return (
            "У тебя пока нет очков. Они начисляются за правильные ответы на "
            "викторины по постам — следи за вопросами в группе."
        )
    accuracy = round(row.correct_answers / row.total_answers * 100)
    lines = [
        f"🎯 Очки: {row.points} (уровень {row.level})",
        f"✅ Верных ответов: {row.correct_answers} из {row.total_answers} ({accuracy}%)",
    ]
    if row.streak_days > 1:
        lines.append(f"🔥 Серия: {row.streak_days} дней подряд")
    return "\n".join(lines)


def _format_top(rows: list[quiz_repo.LeaderRow]) -> str:
    if not rows:
        return "Таблица лидеров пока пуста — никто не отвечал на викторины."
    medals = ("🥇", "🥈", "🥉")
    lines = ["🏆 Топ участников:"]
    for i, row in enumerate(rows):
        prefix = medals[i] if i < len(medals) else f"{i + 1}."
        lines.append(f"{prefix} {row.display_name} — {row.points}")
    return "\n".join(lines)


@router.message(Command("me"))
async def cmd_me(message: Message) -> None:
    """Мои очки. В личке чат не тот, где играют, — берём первую целевую
    группу: у одного владельца обычно одна игровая группа, а спрашивать
    участника «в каком чате?» — лишний шаг."""
    user = message.from_user
    if user is None:
        return
    chat_id = _game_chat_id(message.chat.id)
    if chat_id is None:
        await message.answer("Игровые группы не настроены.")
        return
    await message.answer(_format_me(quiz_repo.get_activity(chat_id, user.id)))


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    chat_id = _game_chat_id(message.chat.id)
    if chat_id is None:
        await message.answer("Игровые группы не настроены.")
        return
    await message.answer(_format_top(quiz_repo.leaderboard(chat_id)))


def _game_chat_id(current_chat_id: int) -> int | None:
    """В какой группе считать очки. В самой группе — она же; в личке — первая
    активная целевая группа."""
    if current_chat_id < 0:  # группы/каналы в Telegram всегда с минусом
        return current_chat_id
    from tg_repost import targets_repo

    targets = [t for t in targets_repo.list_targets() if t.is_active]
    return targets[0].chat_id if targets else None

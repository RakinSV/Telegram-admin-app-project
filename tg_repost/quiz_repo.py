"""Хранение викторин и очков участников (F43).

Живёт в пакете tg_repost, потому что таблицы — в его БД (см. `engage/config.py`
про решение не заводить Engage отдельную базу). Читают и пишут сюда оба
процесса: tg_repost создаёт квиз после публикации поста, Engage публикует его
и принимает ответы.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from tg_repost.db.models import Quiz, QuizAnswer, UserActivity
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Очки. Держим здесь, а не в настройках: это правила игры, а не параметр
# эксплуатации — менять их на ходу означало бы обесценить уже набранные очки.
POINTS_CORRECT = 10
POINTS_STREAK_BONUS = 5  # за каждый день серии, но не больше потолка ниже
MAX_STREAK_BONUS = 25

# Уровень считается из очков формулой, а не хранится: смена правил не
# потребует миграции данных.
_LEVEL_STEP = 100


def level_for_points(points: int) -> int:
    """Уровень участника. 1-й — стартовый, дальше каждые `_LEVEL_STEP` очков."""
    return max(1, points // _LEVEL_STEP + 1)


@dataclass(frozen=True)
class QuizView:
    """Квиз в виде, удобном для публикации (варианты уже разобраны)."""

    id: int
    chat_id: int
    question: str
    options: list[str]
    correct_index: int
    explanation: str | None


@dataclass(frozen=True)
class LeaderRow:
    user_id: int
    display_name: str
    points: int
    correct_answers: int
    total_answers: int
    streak_days: int

    @property
    def level(self) -> int:
        return level_for_points(self.points)


def create_quiz(
    *, post_id: int | None, chat_id: int, question: str, options: list[str],
    correct_index: int, explanation: str | None,
) -> int | None:
    """Сохранить составленный квиз (ещё не опубликованный). Возвращает id."""
    if not options or not 0 <= correct_index < len(options):
        return None
    with session_scope() as session:
        quiz = Quiz(
            post_id=post_id, chat_id=chat_id, question=question,
            options_json=json.dumps(options, ensure_ascii=False),
            correct_index=correct_index, explanation=explanation,
        )
        session.add(quiz)
        session.flush()
        return quiz.id


def pending_quizzes(delay_minutes: int, limit: int = 5) -> list[QuizView]:
    """Квизы, которые пора опубликовать: созданы раньше чем `delay_minutes`
    назад и ещё не отправлены.

    Пауза нужна по сути механики: вопрос задаётся ПОСЛЕ того, как у людей была
    возможность прочитать пост, иначе это не проверка чтения, а угадайка.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(0, delay_minutes))
    with session_scope() as session:
        rows = (
            session.query(Quiz)
            .filter(Quiz.published_at.is_(None), Quiz.created_at <= cutoff)
            .order_by(Quiz.created_at.asc())
            .limit(limit)
            .all()
        )
        return [
            QuizView(
                id=r.id, chat_id=r.chat_id, question=r.question,
                options=json.loads(r.options_json), correct_index=r.correct_index,
                explanation=r.explanation,
            )
            for r in rows
        ]


def mark_published(quiz_id: int, poll_id: str, message_id: int) -> bool:
    """Отметить квиз опубликованным и запомнить poll_id — по нему потом
    сопоставляется входящий `poll_answer`."""
    with session_scope() as session:
        quiz = session.get(Quiz, quiz_id)
        if quiz is None:
            return False
        quiz.poll_id = poll_id
        quiz.message_id = message_id
        quiz.published_at = datetime.now(timezone.utc)
        return True


def _award(
    session, *, chat_id: int, user_id: int, username: str | None,
    full_name: str | None, is_correct: bool, today: date,
) -> int:
    """Начислить очки и обновить серию. Возвращает начисленное."""
    activity = (
        session.query(UserActivity)
        .filter(UserActivity.chat_id == chat_id, UserActivity.user_id == user_id)
        .one_or_none()
    )
    if activity is None:
        # Счётчики задаём ЯВНО: `default=0` в модели применяется при INSERT,
        # а мы прибавляем к ним ещё до flush — на свежем объекте там был бы
        # None и арифметика падала бы с TypeError.
        activity = UserActivity(
            chat_id=chat_id, user_id=user_id, points=0,
            correct_answers=0, total_answers=0, streak_days=0,
        )
        session.add(activity)
    # Имя обновляем, ТОЛЬКО если пришло новое: у части апдейтов username
    # отсутствует, и присваивание None стирало бы уже известное имя — в
    # лидерборде участник превращался обратно в «id123».
    if username:
        activity.username = username
    if full_name:
        activity.full_name = full_name
    activity.total_answers += 1
    activity.updated_at = datetime.now(timezone.utc)

    if not is_correct:
        # Серия рвётся только при неверном ответе, а не при пропуске дня:
        # наказывать за отпуск — верный способ растерять участников.
        activity.streak_days = 0
        return 0

    # Серия считается по ДАТЕ: человек не должен терять её из-за того, что
    # вчера отвечал утром, а сегодня вечером.
    if activity.last_correct_date == today:
        pass  # второй правильный за день серию не растит
    elif activity.last_correct_date == today - timedelta(days=1):
        activity.streak_days += 1
    else:
        activity.streak_days = 1
    activity.last_correct_date = today

    bonus = min(MAX_STREAK_BONUS, POINTS_STREAK_BONUS * max(0, activity.streak_days - 1))
    earned = POINTS_CORRECT + bonus
    activity.points += earned
    activity.correct_answers += 1
    return earned


def record_answer(
    *, poll_id: str, user_id: int, option_index: int,
    username: str | None = None, full_name: str | None = None,
) -> tuple[bool, int] | None:
    """Записать ответ и начислить очки.

    Возвращает (верно ли, начислено очков) либо None — если квиз не найден или
    человек уже отвечал. Повтор не начисляет ничего: Telegram и сам не даёт
    переголосовать в quiz-режиме, но апдейт может прийти дважды.
    """
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        quiz = session.query(Quiz).filter(Quiz.poll_id == poll_id).one_or_none()
        if quiz is None:
            return None
        already = (
            session.query(QuizAnswer)
            .filter(QuizAnswer.quiz_id == quiz.id, QuizAnswer.user_id == user_id)
            .one_or_none()
        )
        if already is not None:
            return None

        is_correct = option_index == quiz.correct_index
        session.add(
            QuizAnswer(
                quiz_id=quiz.id, user_id=user_id, option_index=option_index,
                is_correct=is_correct,
            )
        )
        earned = _award(
            session, chat_id=quiz.chat_id, user_id=user_id, username=username,
            full_name=full_name, is_correct=is_correct, today=today,
        )
        return is_correct, earned


def _display_name(row: UserActivity) -> str:
    if row.username:
        return f"@{row.username}"
    return row.full_name or f"id{row.user_id}"


def get_activity(chat_id: int, user_id: int) -> LeaderRow | None:
    with session_scope() as session:
        row = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == chat_id, UserActivity.user_id == user_id)
            .one_or_none()
        )
        if row is None:
            return None
        return LeaderRow(
            user_id=row.user_id, display_name=_display_name(row), points=row.points,
            correct_answers=row.correct_answers, total_answers=row.total_answers,
            streak_days=row.streak_days,
        )


def leaderboard(chat_id: int, limit: int = 10) -> list[LeaderRow]:
    """Топ участников чата по очкам."""
    with session_scope() as session:
        rows = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == chat_id, UserActivity.points > 0)
            .order_by(UserActivity.points.desc(), UserActivity.correct_answers.desc())
            .limit(limit)
            .all()
        )
        return [
            LeaderRow(
                user_id=r.user_id, display_name=_display_name(r), points=r.points,
                correct_answers=r.correct_answers, total_answers=r.total_answers,
                streak_days=r.streak_days,
            )
            for r in rows
        ]

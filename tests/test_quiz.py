"""Викторины по постам (F43): разбор ответа модели, начисление очков,
серии, лидерборд.

Главное, что защищаем: очки идут за ПРАВИЛЬНЫЙ ОТВЕТ, повтор не начисляет
ничего, а серия считается по дате (человек не должен терять её из-за того, что
вчера отвечал утром, а сегодня вечером).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from tg_repost import quiz_repo
from tg_repost.db.models import Quiz, QuizAnswer, UserActivity
from tg_repost.db.session import session_scope
from tg_repost.rewriter.quiz import parse_quiz_json

CHAT = -100555


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as session:
        session.query(QuizAnswer).delete()
        session.query(Quiz).delete()
        session.query(UserActivity).delete()
    yield
    with session_scope() as session:
        session.query(QuizAnswer).delete()
        session.query(Quiz).delete()
        session.query(UserActivity).delete()


def _valid_json(**overrides) -> str:
    data = {
        "question": "Сколько было уязвимостей?",
        "options": ["Одна", "Две", "Три", "Четыре"],
        "correct_index": 2,
        "explanation": "В тексте прямо сказано «три».",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _make_quiz(poll_id: str = "poll-1", correct_index: int = 2) -> int:
    quiz_id = quiz_repo.create_quiz(
        post_id=None, chat_id=CHAT, question="Q?",
        options=["A", "B", "C", "D"], correct_index=correct_index, explanation=None,
    )
    assert quiz_id is not None
    quiz_repo.mark_published(quiz_id, poll_id=poll_id, message_id=1)
    return quiz_id


# --- разбор ответа модели ---


def test_parse_valid_quiz():
    draft = parse_quiz_json(_valid_json())
    assert draft is not None
    assert draft.correct_index == 2
    assert len(draft.options) == 4


def test_parse_strips_markdown_fence():
    """Модели обрамляют JSON в ```json вопреки инструкции — это норма жизни."""
    draft = parse_quiz_json(f"```json\n{_valid_json()}\n```")
    assert draft is not None


def test_parse_rejects_non_json():
    assert parse_quiz_json("Вот вам вопрос: сколько будет 2+2?") is None


def test_parse_rejects_index_out_of_range():
    assert parse_quiz_json(_valid_json(correct_index=9)) is None


def test_parse_rejects_duplicate_options():
    """Дубли делают «правильный» неотличимым от «неправильного» — такой
    вопрос хуже отсутствия вопроса."""
    assert parse_quiz_json(_valid_json(options=["Да", "Да", "Нет", "Может"])) is None


def test_parse_rejects_too_few_options():
    assert parse_quiz_json(_valid_json(options=["Единственный"])) is None


def test_parse_clips_long_fields_instead_of_dropping():
    """Длинный вопрос лучше обрезать, чем потерять весь квиз."""
    draft = parse_quiz_json(_valid_json(question="Ы" * 500))
    assert draft is not None
    assert len(draft.question) <= 300


def test_parse_rejects_missing_correct_index():
    data = json.loads(_valid_json())
    del data["correct_index"]
    assert parse_quiz_json(json.dumps(data)) is None


# --- очки ---


def test_correct_answer_awards_points():
    _make_quiz()
    result = quiz_repo.record_answer(poll_id="poll-1", user_id=1, option_index=2)
    assert result == (True, quiz_repo.POINTS_CORRECT)
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.points == quiz_repo.POINTS_CORRECT
    assert row.correct_answers == 1


def test_wrong_answer_awards_nothing_but_counts():
    _make_quiz()
    assert quiz_repo.record_answer(poll_id="poll-1", user_id=1, option_index=0) == (False, 0)
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.points == 0
    assert row.total_answers == 1


def test_second_answer_from_same_user_is_ignored():
    """Telegram и сам не даёт переголосовать, но апдейт может прийти дважды."""
    _make_quiz()
    quiz_repo.record_answer(poll_id="poll-1", user_id=1, option_index=2)
    assert quiz_repo.record_answer(poll_id="poll-1", user_id=1, option_index=2) is None
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.points == quiz_repo.POINTS_CORRECT  # не удвоилось


def test_answer_to_unknown_poll_is_ignored():
    assert quiz_repo.record_answer(poll_id="чужой", user_id=1, option_index=0) is None


# --- серии ---


def _set_last_correct(user_id: int, day: date, streak: int) -> None:
    with session_scope() as session:
        row = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == CHAT, UserActivity.user_id == user_id)
            .one()
        )
        row.last_correct_date = day
        row.streak_days = streak


def test_streak_grows_on_consecutive_days():
    _make_quiz("p1")
    quiz_repo.record_answer(poll_id="p1", user_id=1, option_index=2)
    _set_last_correct(1, date.today() - timedelta(days=1), streak=1)

    _make_quiz("p2")
    _, earned = quiz_repo.record_answer(poll_id="p2", user_id=1, option_index=2)  # type: ignore[misc]
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.streak_days == 2
    assert earned == quiz_repo.POINTS_CORRECT + quiz_repo.POINTS_STREAK_BONUS


def test_streak_resets_after_gap():
    _make_quiz("p1")
    quiz_repo.record_answer(poll_id="p1", user_id=1, option_index=2)
    _set_last_correct(1, date.today() - timedelta(days=5), streak=4)

    _make_quiz("p2")
    quiz_repo.record_answer(poll_id="p2", user_id=1, option_index=2)
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.streak_days == 1


def test_wrong_answer_breaks_streak():
    _make_quiz("p1")
    quiz_repo.record_answer(poll_id="p1", user_id=1, option_index=2)
    _set_last_correct(1, date.today() - timedelta(days=1), streak=3)

    _make_quiz("p2")
    quiz_repo.record_answer(poll_id="p2", user_id=1, option_index=0)
    row = quiz_repo.get_activity(CHAT, 1)
    assert row is not None
    assert row.streak_days == 0


def test_streak_bonus_is_capped():
    """Потолок бонуса не даёт «старожилам» оторваться навсегда."""
    _make_quiz("p1")
    quiz_repo.record_answer(poll_id="p1", user_id=1, option_index=2)
    _set_last_correct(1, date.today() - timedelta(days=1), streak=100)

    _make_quiz("p2")
    _, earned = quiz_repo.record_answer(poll_id="p2", user_id=1, option_index=2)  # type: ignore[misc]
    assert earned == quiz_repo.POINTS_CORRECT + quiz_repo.MAX_STREAK_BONUS


# --- лидерборд и уровни ---


def test_leaderboard_sorted_by_points():
    for i, user_id in enumerate((10, 20, 30), start=1):
        _make_quiz(f"poll-{user_id}")
        for _ in range(i):
            pass
        quiz_repo.record_answer(
            poll_id=f"poll-{user_id}", user_id=user_id, option_index=2,
            username=f"user{user_id}",
        )
    # у всех по одному верному — добавим одному ещё
    _make_quiz("poll-extra")
    quiz_repo.record_answer(poll_id="poll-extra", user_id=30, option_index=2)

    top = quiz_repo.leaderboard(CHAT)
    assert top[0].user_id == 30
    assert top[0].display_name == "@user30"


def test_leaderboard_skips_zero_points():
    _make_quiz()
    quiz_repo.record_answer(poll_id="poll-1", user_id=1, option_index=0)  # неверно
    assert quiz_repo.leaderboard(CHAT) == []


@pytest.mark.parametrize(
    ("points", "level"), [(0, 1), (50, 1), (100, 2), (250, 3), (1000, 11)],
)
def test_level_formula(points, level):
    assert quiz_repo.level_for_points(points) == level


# --- публикация ---


def test_pending_quizzes_respects_delay():
    """Пауза — часть механики: спрашивать сразу значит проверять не чтение,
    а скорость реакции."""
    quiz_repo.create_quiz(
        post_id=None, chat_id=CHAT, question="Q?", options=["A", "B"],
        correct_index=0, explanation=None,
    )
    assert quiz_repo.pending_quizzes(delay_minutes=60) == []
    assert len(quiz_repo.pending_quizzes(delay_minutes=0)) == 1


def test_published_quiz_is_not_returned_again():
    quiz_id = quiz_repo.create_quiz(
        post_id=None, chat_id=CHAT, question="Q?", options=["A", "B"],
        correct_index=0, explanation=None,
    )
    assert quiz_id is not None
    quiz_repo.mark_published(quiz_id, poll_id="p", message_id=1)
    assert quiz_repo.pending_quizzes(delay_minutes=0) == []


def test_create_quiz_rejects_bad_index():
    assert quiz_repo.create_quiz(
        post_id=None, chat_id=CHAT, question="Q?", options=["A", "B"],
        correct_index=5, explanation=None,
    ) is None

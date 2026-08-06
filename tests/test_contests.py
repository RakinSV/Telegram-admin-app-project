"""Конкурсы и розыгрыши (F44).

Главное, что доказываем: розыгрыш ВОСПРОИЗВОДИМ. Имея seed (опубликованный до
старта), список участников и алгоритм, любой получает тех же победителей —
именно это делает конкурс честным в глазах аудитории, а не обещание.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import contests_repo, referrals_repo
from tg_repost.db.models import (
    Contest,
    ContestEntry,
    Referral,
    UserActivity,
)
from tg_repost.db.session import session_scope

CHAT = -100333


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as session:
        session.query(ContestEntry).delete()
        session.query(Contest).delete()
        session.query(UserActivity).delete()
        session.query(Referral).delete()
    yield
    with session_scope() as session:
        session.query(ContestEntry).delete()
        session.query(Contest).delete()
        session.query(UserActivity).delete()
        session.query(Referral).delete()


def _make_contest(**kwargs) -> int:
    params = {
        "chat_id": CHAT, "title": "Розыгрыш подписки", "prize": "Premium на месяц",
        "winners_count": 1,
        "ends_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    params.update(kwargs)
    contest_id = contests_repo.create_contest(**params)
    assert contest_id is not None
    return contest_id


def _finish(contest_id: int) -> None:
    """Перевести конкурс в «срок вышел»."""
    with session_scope() as session:
        session.get(Contest, contest_id).ends_at = (  # type: ignore[union-attr]
            datetime.now(timezone.utc) - timedelta(minutes=1)
        )


# --- воспроизводимость розыгрыша (сердце фичи) ---


def test_draw_is_reproducible_with_same_seed():
    """Тот же seed + тот же список = те же победители. Это и есть проверяемость."""
    participants = [101, 55, 3000, 42, 777]
    first = contests_repo.pick_winners("deadbeef", participants, 2)
    second = contests_repo.pick_winners("deadbeef", participants, 2)
    assert first == second


def test_draw_is_independent_of_input_order():
    """Порядок строк в БД не воспроизводим — без сортировки один и тот же seed
    давал бы разных победителей, и проверить результат было бы нельзя."""
    a = contests_repo.pick_winners("seed-1", [1, 2, 3, 4, 5], 2)
    b = contests_repo.pick_winners("seed-1", [5, 4, 3, 2, 1], 2)
    assert a == b


def test_different_seeds_give_different_results():
    participants = list(range(1, 50))
    a = contests_repo.pick_winners("seed-a", participants, 3)
    b = contests_repo.pick_winners("seed-b", participants, 3)
    assert a != b


def test_draw_handles_fewer_participants_than_winners():
    """Победителей просили троих, а пришёл один — не падаем и не выдумываем."""
    assert contests_repo.pick_winners("s", [7], 3) == [7]


def test_draw_ignores_duplicates():
    winners = contests_repo.pick_winners("s", [5, 5, 5, 9], 2)
    assert sorted(winners) == [5, 9]


def test_draw_of_empty_list():
    assert contests_repo.pick_winners("s", [], 1) == []


# --- проведение розыгрыша ---


def test_draw_saves_verifiable_protocol():
    contest_id = _make_contest(winners_count=2)
    for user_id in (1, 2, 3, 4, 5):
        contests_repo.join_contest(contest_id, user_id)
    _finish(contest_id)

    protocol = contests_repo.draw_contest(contest_id)
    assert protocol is not None
    assert len(protocol["winners"]) == 2
    assert protocol["participants"] == [1, 2, 3, 4, 5]
    assert protocol["seed"]  # seed в протоколе — иначе проверить нечем
    assert protocol["algorithm"] == contests_repo.DRAW_ALGORITHM

    # Публичная проверка: посторонний повторяет розыгрыш по протоколу.
    assert contests_repo.pick_winners(
        protocol["seed"], protocol["participants"], 2,
    ) == protocol["winners"]


def test_seed_exists_before_any_participant():
    """Seed рождается при создании — подобрать его под нужного победителя
    невозможно даже теоретически."""
    contest_id = _make_contest()
    contest = contests_repo.get_contest(contest_id)
    assert contest is not None
    assert len(contest.draw_seed) >= 16
    assert contests_repo.list_entries(contest_id) == []


def test_contest_cannot_be_drawn_twice():
    """Протокол зафиксирован — переигрывать нельзя, иначе вся прозрачность
    теряет смысл."""
    contest_id = _make_contest()
    contests_repo.join_contest(contest_id, 1)
    _finish(contest_id)
    assert contests_repo.draw_contest(contest_id) is not None
    assert contests_repo.draw_contest(contest_id) is None


def test_draw_without_participants_returns_none():
    contest_id = _make_contest()
    _finish(contest_id)
    assert contests_repo.draw_contest(contest_id) is None


def test_draw_respects_recheck_of_conditions():
    """Повторная проверка на момент розыгрыша: нельзя подписаться, записаться
    и тут же отписаться."""
    contest_id = _make_contest(winners_count=3)
    for user_id in (1, 2, 3):
        contests_repo.join_contest(contest_id, user_id)
    _finish(contest_id)

    protocol = contests_repo.draw_contest(contest_id, eligible_user_ids=[2])
    assert protocol is not None
    assert protocol["winners"] == [2]
    assert protocol["participants"] == [2]


# --- участие и условия ---


def test_join_twice_is_rejected():
    contest_id = _make_contest()
    assert contests_repo.join_contest(contest_id, 1) is True
    assert contests_repo.join_contest(contest_id, 1) is False


def test_join_after_deadline_is_rejected():
    contest_id = _make_contest()
    _finish(contest_id)
    assert contests_repo.join_contest(contest_id, 1) is False


def test_join_after_draw_is_rejected():
    contest_id = _make_contest()
    contests_repo.join_contest(contest_id, 1)
    _finish(contest_id)
    contests_repo.draw_contest(contest_id)
    assert contests_repo.join_contest(contest_id, 2) is False


def test_conditions_pass_when_none_set():
    contest_id = _make_contest()
    contest = contests_repo.get_contest(contest_id)
    assert contest is not None
    assert contests_repo.check_local_conditions(contest, 1).ok is True


def test_points_condition_blocks_and_explains():
    """Отказ должен объяснять, чего не хватает, — иначе человек просто уходит."""
    contest_id = _make_contest(require_min_points=100)
    contest = contests_repo.get_contest(contest_id)
    assert contest is not None
    result = contests_repo.check_local_conditions(contest, 1)
    assert result.ok is False
    assert "100" in result.missing[0]


def test_points_condition_passes_with_enough_points():
    with session_scope() as session:
        session.add(
            UserActivity(
                chat_id=CHAT, user_id=1, points=150,
                correct_answers=15, total_answers=15, streak_days=1,
            )
        )
    contest_id = _make_contest(require_min_points=100)
    contest = contests_repo.get_contest(contest_id)
    assert contest is not None
    assert contests_repo.check_local_conditions(contest, 1).ok is True


def test_referral_condition_counts_only_confirmed():
    """Условие «привести N человек» должно считать засчитанных, иначе его
    закрывают мультиаккаунтами."""
    referrals_repo.register_referral(1, 50, CHAT)  # перешёл, но не подтверждён
    contest_id = _make_contest(require_min_referrals=1)
    contest = contests_repo.get_contest(contest_id)
    assert contest is not None
    assert contests_repo.check_local_conditions(contest, 1).ok is False


def test_create_contest_rejects_bad_input():
    assert contests_repo.create_contest(
        chat_id=CHAT, title="", prize="Приз", winners_count=1,
        ends_at=datetime.now(timezone.utc) + timedelta(days=1),
    ) is None
    assert contests_repo.create_contest(
        chat_id=CHAT, title="T", prize="P", winners_count=0,
        ends_at=datetime.now(timezone.utc) + timedelta(days=1),
    ) is None


def test_due_contests_only_returns_expired_and_undrawn():
    active = _make_contest(title="Идёт")
    expired = _make_contest(title="Пора")
    _finish(expired)
    due_ids = [c.id for c in contests_repo.due_contests()]
    assert expired in due_ids
    assert active not in due_ids

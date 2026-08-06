"""Реферальная программа (F42).

Половина тестов — про АНТИНАКРУТКУ: без неё механика за день превращается в
ферму мультиаккаунтов, и все остальные свойства не имеют значения.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import referrals_repo
from tg_repost.db.models import Referral, UserActivity
from tg_repost.db.session import session_scope

CHAT = -100444
INVITER = 111
INVITED = 222


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as session:
        session.query(Referral).delete()
        session.query(UserActivity).delete()
    yield
    with session_scope() as session:
        session.query(Referral).delete()
        session.query(UserActivity).delete()


def _backdate_join(invited_user_id: int, days: int) -> None:
    with session_scope() as session:
        row = (
            session.query(Referral)
            .filter(Referral.invited_user_id == invited_user_id)
            .one()
        )
        row.joined_at = datetime.now(timezone.utc) - timedelta(days=days)


def _full_referral(invited: int = INVITED, days_ago: int = 10) -> None:
    """Реферал, выполнивший ВСЕ условия: вступил, написал, выждал срок."""
    referrals_repo.register_referral(INVITER, invited, CHAT)
    referrals_repo.mark_joined(invited)
    referrals_repo.mark_first_message(invited)
    _backdate_join(invited, days_ago)


# --- антинакрутка ---


def test_self_referral_rejected():
    """Пригласить самого себя — очевидная накрутка."""
    assert referrals_repo.register_referral(INVITER, INVITER, CHAT) is False
    assert referrals_repo.stats_for(INVITER).invited == 0


def test_second_inviter_cannot_steal_referral():
    """Первый, кто привёл, тот и привёл — иначе началась бы гонка
    «перебей чужого реферала»."""
    assert referrals_repo.register_referral(INVITER, INVITED, CHAT) is True
    assert referrals_repo.register_referral(999, INVITED, CHAT) is False
    assert referrals_repo.stats_for(INVITER).invited == 1
    assert referrals_repo.stats_for(999).invited == 0


def test_not_confirmed_without_joining():
    """Перешёл по ссылке, но в группу не вступил — не считается."""
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_first_message(INVITED)
    assert referrals_repo.confirm_matured_referrals(min_days=0) == 0


def test_not_confirmed_without_message():
    """Вступил, но молчит — самый частый признак мультиаккаунта."""
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_joined(INVITED)
    _backdate_join(INVITED, 30)
    assert referrals_repo.confirm_matured_referrals(min_days=3) == 0


def test_not_confirmed_before_min_days():
    """Вступил и написал, но только что — срок ещё не выдержан."""
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_joined(INVITED)
    referrals_repo.mark_first_message(INVITED)
    assert referrals_repo.confirm_matured_referrals(min_days=3) == 0


def test_confirmed_when_all_conditions_met():
    _full_referral()
    assert referrals_repo.confirm_matured_referrals(min_days=3) == 1
    assert referrals_repo.stats_for(INVITER).confirmed == 1


def test_confirmation_is_not_repeated():
    """Повторный прогон джобы не должен начислять очки второй раз."""
    _full_referral()
    referrals_repo.confirm_matured_referrals(min_days=3)
    assert referrals_repo.confirm_matured_referrals(min_days=3) == 0

    with session_scope() as session:
        activity = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == CHAT, UserActivity.user_id == INVITER)
            .one()
        )
        assert activity.points == referrals_repo.POINTS_PER_REFERRAL


# --- начисление и статистика ---


def test_points_awarded_to_inviter():
    _full_referral()
    referrals_repo.confirm_matured_referrals(min_days=3)
    with session_scope() as session:
        activity = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == CHAT, UserActivity.user_id == INVITER)
            .one()
        )
        assert activity.points == referrals_repo.POINTS_PER_REFERRAL


def test_points_added_to_existing_activity():
    """Пригласивший мог уже иметь очки за викторины — они не должны затереться."""
    with session_scope() as session:
        session.add(
            UserActivity(
                chat_id=CHAT, user_id=INVITER, points=30,
                correct_answers=3, total_answers=3, streak_days=1,
            )
        )
    _full_referral()
    referrals_repo.confirm_matured_referrals(min_days=3)
    with session_scope() as session:
        activity = (
            session.query(UserActivity)
            .filter(UserActivity.chat_id == CHAT, UserActivity.user_id == INVITER)
            .one()
        )
        assert activity.points == 30 + referrals_repo.POINTS_PER_REFERRAL
        assert activity.correct_answers == 3  # квизовая статистика не тронута


def test_stats_show_funnel():
    referrals_repo.register_referral(INVITER, 1, CHAT)          # только перешёл
    referrals_repo.register_referral(INVITER, 2, CHAT)
    referrals_repo.mark_joined(2)                                # вступил
    _full_referral(invited=3)                                    # полный путь
    referrals_repo.confirm_matured_referrals(min_days=3)

    stats = referrals_repo.stats_for(INVITER)
    assert (stats.invited, stats.joined, stats.confirmed) == (3, 2, 1)
    assert stats.points_earned == referrals_repo.POINTS_PER_REFERRAL


def test_top_inviters_counts_only_confirmed():
    """Иначе первое место займёт тот, кто нагнал мультиаккаунтов."""
    for invited in (1, 2, 3):
        referrals_repo.register_referral(999, invited, CHAT)  # много, но пустых
    _full_referral(invited=50)                                # один настоящий
    referrals_repo.confirm_matured_referrals(min_days=3)

    top = referrals_repo.top_inviters(CHAT)
    assert top == [(INVITER, 1)]


def test_mark_joined_is_idempotent():
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    assert referrals_repo.mark_joined(INVITED) is True
    assert referrals_repo.mark_joined(INVITED) is False


def test_mark_message_for_unknown_user_is_noop():
    """Написал человек, который пришёл сам — реферала нет, и это нормально."""
    assert referrals_repo.mark_first_message(777) is False


def test_payload_roundtrip():
    assert referrals_repo.build_referral_payload(12345) == "ref_12345"

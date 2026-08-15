"""Карточка участника — CRM (F63).

Главное, что защищаем: карточка СОБИРАЕТСЯ ЧТЕНИЕМ из четырёх источников, а
не хранится копией. Если кто-то заведёт «таблицу контактов» и начнёт писать
туда имя или очки, эти тесты должны стать бессмысленными — и это будет
видно.

Отдельно: недоступность Guardian не должна ронять карточку. Это разные БД и
разные процессы, и молчание одного из них не повод не показать владельцу
всё остальное, что мы про человека знаем.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import contacts_repo
from tg_repost.db.models import (
    ContactNote,
    ContactTag,
    MemberOrigin,
    Referral,
    UserActivity,
)
from tg_repost.db.session import session_scope

USER = 555001
CHAT = -100555001


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ContactTag).delete()
            session.query(ContactNote).delete()
            session.query(MemberOrigin).delete()
            session.query(Referral).delete()
            session.query(UserActivity).delete()

    _wipe()
    yield
    _wipe()


# --- теги ---


def test_tag_is_normalized():
    """«VIP», «vip» и «vip » — один тег.

    Иначе сегмент по одному написанию молча потеряет две трети людей, и
    заметить это можно будет только по недоставленной рассылке.
    """
    assert contacts_repo.normalize_tag("  VIP  ") == "vip"
    assert contacts_repo.normalize_tag("Постоянный   Покупатель") == "постоянный покупатель"


def test_add_and_list_tags():
    assert contacts_repo.add_tag(USER, "VIP") is True
    assert contacts_repo.add_tag(USER, "покупатель") is True

    assert contacts_repo.tags_of(USER) == ["vip", "покупатель"]


def test_duplicate_tag_is_rejected():
    contacts_repo.add_tag(USER, "vip")

    assert contacts_repo.add_tag(USER, "  VIP ") is False
    assert contacts_repo.tags_of(USER) == ["vip"]


def test_empty_tag_is_rejected():
    assert contacts_repo.add_tag(USER, "   ") is False
    assert contacts_repo.tags_of(USER) == []


def test_remove_tag():
    contacts_repo.add_tag(USER, "vip")

    assert contacts_repo.remove_tag(USER, "VIP") is True
    assert contacts_repo.remove_tag(USER, "vip") is False
    assert contacts_repo.tags_of(USER) == []


def test_users_with_tag_is_basis_for_segments():
    contacts_repo.add_tag(USER, "vip")
    contacts_repo.add_tag(USER + 1, "vip")
    contacts_repo.add_tag(USER + 2, "новичок")

    assert contacts_repo.users_with_tag("VIP") == [USER, USER + 1]


def test_all_tags_counts_people():
    contacts_repo.add_tag(USER, "vip")
    contacts_repo.add_tag(USER + 1, "vip")
    contacts_repo.add_tag(USER + 2, "новичок")

    assert contacts_repo.all_tags() == [("vip", 2), ("новичок", 1)]


def test_tag_is_per_person_not_per_chat():
    """Тег вешается на ЧЕЛОВЕКА.

    «Постоянный покупатель» остаётся таковым во всех группах владельца —
    иначе пришлось бы размечать одного и того же человека заново в каждом
    чате, и смысл CRM теряется.
    """
    contacts_repo.add_tag(USER, "vip")

    with session_scope() as session:
        row = session.query(ContactTag).filter(ContactTag.user_id == USER).one()
        assert not hasattr(row, "chat_id")
        assert row.tenant_id == 1


# --- заметка ---


def test_note_roundtrip():
    contacts_repo.set_note(USER, "  Просил скидку  ")
    assert contacts_repo.note_of(USER) == "Просил скидку"

    contacts_repo.set_note(USER, "Уже купил")
    assert contacts_repo.note_of(USER) == "Уже купил"


def test_empty_note_deletes_it():
    contacts_repo.set_note(USER, "было")
    contacts_repo.set_note(USER, "   ")

    assert contacts_repo.note_of(USER) is None


def test_missing_note_is_none():
    assert contacts_repo.note_of(USER) is None


# --- карточка ---


def _add_origin(*, invite_name: str | None = None, left: bool = False) -> None:
    with session_scope() as session:
        session.add(
            MemberOrigin(
                chat_id=CHAT,
                user_id=USER,
                invite_link="https://t.me/+abc" if invite_name else None,
                invite_name=invite_name,
                joined_at=_utcnow() - timedelta(days=10),
                left_at=_utcnow() if left else None,
            )
        )


def _add_activity(points: int, *, chat_id: int = CHAT, streak: int = 0, correct: int = 0) -> None:
    with session_scope() as session:
        session.add(
            UserActivity(
                chat_id=chat_id, user_id=USER, points=points,
                streak_days=streak, correct_answers=correct,
            )
        )


def test_card_of_unknown_person_is_not_an_error():
    """Человек, о котором мы ничего не знаем, — обычный случай.

    Владелец может открыть карточку по id из чужого сообщения, и падать
    здесь нельзя.
    """
    card = contacts_repo.build_card(999_999_999)

    assert card.user_id == 999_999_999
    assert card.display_name == "id999999999"
    assert card.points == 0
    assert card.tags == []


def test_card_collects_origin():
    _add_origin(invite_name="Реклама у блогера")

    card = contacts_repo.build_card(USER)

    assert card.origin == "Реклама у блогера"
    assert card.is_active_member is True
    assert card.first_seen_at is not None


def test_organic_arrival_has_no_origin():
    """NULL в обоих полях ссылки — содержательный ответ «органика»,
    а не «данных нет»."""
    _add_origin(invite_name=None)

    card = contacts_repo.build_card(USER)

    assert card.origin is None
    assert card.first_seen_at is not None  # про человека мы всё же знаем


def test_left_member_is_marked_inactive():
    _add_origin(invite_name="Кампания", left=True)

    assert contacts_repo.build_card(USER).is_active_member is False


def test_points_are_summed_across_chats():
    """Для владельца это ОДИН человек, а не несколько независимых участников."""
    _add_activity(100, chat_id=CHAT, streak=3, correct=5)
    _add_activity(50, chat_id=-100999, streak=7, correct=2)

    card = contacts_repo.build_card(USER)

    assert card.points == 150
    assert card.correct_answers == 7
    assert card.streak_days == 7  # лучшая серия, а не сумма


def test_level_is_derived_from_points():
    _add_activity(250)

    card = contacts_repo.build_card(USER)

    assert card.level == contacts_repo.level_for_points(250)


def test_card_shows_who_invited_and_how_many_confirmed():
    with session_scope() as session:
        session.add(Referral(inviter_user_id=777, invited_user_id=USER, chat_id=CHAT))
        session.add(
            Referral(
                inviter_user_id=USER, invited_user_id=901, chat_id=CHAT,
                confirmed_at=_utcnow(),
            )
        )
        session.add(Referral(inviter_user_id=USER, invited_user_id=902, chat_id=CHAT))

    card = contacts_repo.build_card(USER)

    assert card.invited_by == 777
    # Только подтверждённые: неподтверждённый реферал ещё не доказал, что он
    # живой человек (F42), и показывать его как приведённого рано.
    assert card.confirmed_invites == 1


def test_card_includes_tags_and_note():
    contacts_repo.add_tag(USER, "vip")
    contacts_repo.set_note(USER, "звонил в марте")

    card = contacts_repo.build_card(USER)

    assert card.tags == ["vip"]
    assert card.note == "звонил в марте"


def test_card_survives_guardian_being_unavailable(monkeypatch):
    """Guardian — отдельная БД и отдельный процесс.

    Его недоступность не повод не показать владельцу всё остальное, что мы
    про человека знаем. Без этого сбой модератора обрушил бы всю CRM.
    """
    def _boom(*_args, **_kwargs):
        raise RuntimeError("guardian.db недоступна")

    monkeypatch.setattr(
        "guardian.db.session.session_scope", _boom, raising=True,
    )
    _add_activity(70)
    contacts_repo.add_tag(USER, "vip")

    card = contacts_repo.build_card(USER)

    assert card.points == 70
    assert card.tags == ["vip"]
    assert card.moderation.known is False


def test_identity_falls_back_to_activity_username(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("guardian.db недоступна")

    monkeypatch.setattr("guardian.db.session.session_scope", _boom, raising=True)
    with session_scope() as session:
        session.add(UserActivity(chat_id=CHAT, user_id=USER, points=0, username="serega"))

    assert contacts_repo.build_card(USER).display_name == "@serega"

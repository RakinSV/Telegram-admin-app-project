"""Сегменты участников — сохранённые запросы (F63).

Половина файла — про ОДНУ опасность: сегмент, который по ошибке совпадает
со всей базой. Опечатка в имени условия, пустой фильтр, потерянное при
сохранении поле — и рассылка (F64) уходит всем подряд. Отменить это
невозможно: сообщения уже доставлены.

Поэтому «все» здесь — отдельное явное условие, которое надо написать
руками, а всё непонятное отвергается, а не игнорируется.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import contacts_repo, segments_repo
from tg_repost.db.models import (
    ContactSegment,
    ContactTag,
    MemberOrigin,
    UserActivity,
)
from tg_repost.db.session import session_scope

CHAT = -100666001


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ContactSegment).delete()
            session.query(ContactTag).delete()
            session.query(MemberOrigin).delete()
            session.query(UserActivity).delete()

    _wipe()
    yield
    _wipe()


def _member(user_id: int, *, invite_name: str | None = None, left: bool = False,
            chat_id: int = CHAT) -> None:
    with session_scope() as session:
        session.add(
            MemberOrigin(
                chat_id=chat_id, user_id=user_id,
                invite_name=invite_name,
                joined_at=_utcnow() - timedelta(days=5),
                left_at=_utcnow() if left else None,
            )
        )


def _points(user_id: int, points: int, *, chat_id: int = CHAT) -> None:
    with session_scope() as session:
        session.add(UserActivity(chat_id=chat_id, user_id=user_id, points=points))


# --- защита от «всей базы» ---


def test_empty_filter_is_rejected():
    """Пустой фильтр совпал бы со всеми. Это должно быть невозможно."""
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate({})


def test_non_dict_filter_is_rejected():
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate(None)  # type: ignore[arg-type]


def test_unknown_key_is_rejected_not_ignored():
    """САМЫЙ ВАЖНЫЙ ТЕСТ ФАЙЛА.

    Молча проигнорированная опечатка превращает узкий сегмент во «всю базу»:
    условие не применилось — значит не сузило. Рассылка ушла всем, и отозвать
    её нельзя.
    """
    with pytest.raises(segments_repo.InvalidFilter) as exc:
        segments_repo.validate({"tagg": "vip"})

    assert "tagg" in str(exc.value)


def test_unknown_key_rejected_even_alongside_valid_one():
    """Одно верное условие не оправдывает второе непонятное."""
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate({"tag": "vip", "min_poinst": 10})


def test_everyone_must_be_explicit_and_alone():
    """«Все» — осознанное решение, а не побочный эффект."""
    assert segments_repo.validate({"everyone": True})

    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate({"everyone": True, "tag": "vip"})


def test_wrong_types_are_rejected():
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate({"min_points": "много"})
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.validate({"tag": "   "})


def test_evaluate_validates_too():
    """Фильтр, собранный на лету, проверяется так же строго.

    Опечатка в нём стоила бы ровно столько же, сколько в сохранённом.
    """
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.evaluate({"tagg": "vip"})


# --- вычисление ---


def test_tag_segment():
    contacts_repo.add_tag(1, "vip")
    contacts_repo.add_tag(2, "vip")
    contacts_repo.add_tag(3, "новичок")

    assert segments_repo.evaluate({"tag": "VIP"}) == [1, 2]


def test_min_points_segment():
    _points(1, 500)
    _points(2, 50)

    assert segments_repo.evaluate({"min_points": 100}) == [1]


def test_origin_segment():
    _member(1, invite_name="Блогер")
    _member(2, invite_name="Реклама")

    assert segments_repo.evaluate({"origin": "Блогер"}) == [1]


def test_active_only_excludes_those_who_left():
    """Ушедшему рассылку слать бессмысленно и вредно."""
    _member(1)
    _member(2, left=True)

    assert segments_repo.evaluate({"active_only": True}) == [1]


def test_conditions_are_combined_with_and():
    """Условия СУЖАЮТ выборку, а не расширяют её.

    Если бы они складывались, сегмент «VIP и с 500 очками» оказался бы шире
    каждого из них по отдельности — прямо противоположно ожиданию.
    """
    contacts_repo.add_tag(1, "vip")
    contacts_repo.add_tag(2, "vip")
    _points(1, 500)
    _points(2, 10)

    assert segments_repo.evaluate({"tag": "vip", "min_points": 100}) == [1]


def test_chat_id_scopes_the_segment():
    _member(1, chat_id=CHAT)
    _member(2, chat_id=-100999)

    assert segments_repo.evaluate({"chat_id": CHAT, "active_only": True}) == [1]


def test_everyone_unions_members_and_active_users():
    """Человек мог отвечать на викторины, не имея записи о входе."""
    _member(1)
    _points(2, 10)

    assert segments_repo.evaluate({"everyone": True}) == [1, 2]


def test_segment_with_no_matches_is_empty_not_everyone():
    """Ноль подходящих — это ноль, а не «раз никого, значит все»."""
    contacts_repo.add_tag(1, "vip")

    assert segments_repo.evaluate({"tag": "несуществующий"}) == []


# --- сохранение ---


def test_save_and_read_back():
    segment_id = segments_repo.save("VIP-клиенты", {"tag": "vip"})

    view = segments_repo.get(segment_id)

    assert view is not None
    assert view.name == "VIP-клиенты"
    assert view.filter == {"tag": "vip"}


def test_save_updates_existing_by_name():
    first = segments_repo.save("Активные", {"min_points": 10})
    second = segments_repo.save("Активные", {"min_points": 500})

    assert first == second
    view = segments_repo.get(first)
    assert view is not None and view.filter == {"min_points": 500}


def test_invalid_filter_is_never_saved():
    """Проверка стоит ПЕРЕД записью: битый сегмент не должен попасть в базу
    даже на секунду — его могли бы успеть использовать."""
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.save("Плохой", {"опечатка": 1})

    assert segments_repo.list_all() == []


def test_empty_name_is_rejected():
    with pytest.raises(segments_repo.InvalidFilter):
        segments_repo.save("   ", {"tag": "vip"})


def test_delete_segment():
    segment_id = segments_repo.save("Временный", {"tag": "vip"})

    assert segments_repo.delete(segment_id) is True
    assert segments_repo.delete(segment_id) is False
    assert segments_repo.get(segment_id) is None


def test_members_are_computed_not_stored():
    """ГЛАВНОЕ СВОЙСТВО: состав сегмента вычисляется в момент обращения.

    Человек получил тег после сохранения сегмента — и сразу в него попал.
    Материализованный список пришлось бы пересчитывать, и он молча
    устаревал бы между пересчётами.
    """
    segment_id = segments_repo.save("VIP", {"tag": "vip"})
    assert segments_repo.members_of(segment_id) == []

    contacts_repo.add_tag(42, "vip")

    assert segments_repo.members_of(segment_id) == [42]


def test_members_of_missing_segment_is_empty():
    assert segments_repo.members_of(999999) == []


def test_filter_survives_json_roundtrip_with_unicode():
    segment_id = segments_repo.save("Кампания", {"origin": "Реклама у блогера"})

    view = segments_repo.get(segment_id)

    assert view is not None
    assert view.filter["origin"] == "Реклама у блогера"

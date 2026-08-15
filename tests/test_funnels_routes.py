"""Веб-интерфейс воронок (F71).

Воронка пишет живым людям по расписанию, растянутому на дни, поэтому тесты
в основном про то, где интерфейс обязан ПРЕДУПРЕДИТЬ, а не сделать молча:
правка шагов у воронки, по которой уже идут люди; включение; удаление
вместе с историей. Плюс переименование — форма правит строку по id, иначе
смена имени тихо создавала бы вторую воронку.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import funnels_repo, subscribers_repo
from tg_repost.db.models import BotSubscriber, Funnel, FunnelRun, QueuedTask
from tg_repost.db.session import session_scope

ALICE = 8101


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FunnelRun).delete()
            session.query(Funnel).delete()
            session.query(QueuedTask).delete()
            session.query(BotSubscriber).delete()

    _wipe()
    yield
    _wipe()


STEPS = [
    {"delay_hours": 0, "text": "Привет!"},
    {"delay_hours": 24, "text": "Через день."},
]


# --- список ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/funnels").status_code == 200


def test_listing_shows_counts():
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS, is_active=True)
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    response = client.get("/funnels")

    assert "Онбординг" in response.text
    assert "идут: 1" in response.text
    assert f"/funnels/{funnel_id}" in response.text


def test_listing_warns_that_bot_cannot_write_first():
    """Иначе «воронка включена, а писем нет» выглядит как поломка."""
    client = _client()
    _bootstrap(client)

    assert "не даёт боту написать первым" in client.get("/funnels").text


# --- создание и правка ---


def test_form_saves_steps_dropping_empty_rows():
    """Пустая строка — способ не заполнять запас, а не ошибка ввода."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/funnels/save",
        data={
            "name": "Онбординг",
            "delay_hours": ["0", "24", "48"],
            "text": ["Привет!", "  ", "Через два дня."],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    views = funnels_repo.list_all()
    assert len(views) == 1
    assert [s.text for s in views[0].steps] == ["Привет!", "Через два дня."]


def test_new_funnel_is_created_switched_off():
    """Включение — отдельное решение: включённая воронка сразу пишет людям."""
    client = _client()
    _bootstrap(client)

    client.post(
        "/funnels/save",
        data={"name": "Онбординг", "delay_hours": ["0"], "text": ["Привет!"]},
    )

    assert funnels_repo.list_all()[0].is_active is False


def test_editing_does_not_switch_funnel_off():
    """Правка текста не должна незаметно останавливать работающую воронку."""
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS, is_active=True)

    client.post(
        "/funnels/save",
        data={
            "funnel_id": str(funnel_id),
            "name": "Онбординг",
            "delay_hours": ["0"],
            "text": ["Другой текст"],
        },
    )

    view = funnels_repo.get(funnel_id)
    assert view is not None
    assert view.is_active is True


def test_rename_edits_the_same_funnel():
    """ГЛАВНАЯ ЛОВУШКА ФОРМЫ.

    Сохранение по имени сделало бы из переименования создание второй
    воронки — и человек молча оказался бы записан в обе.
    """
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS)

    client.post(
        "/funnels/save",
        data={
            "funnel_id": str(funnel_id),
            "name": "Приветствие",
            "delay_hours": ["0"],
            "text": ["Привет!"],
        },
    )

    views = funnels_repo.list_all()
    assert len(views) == 1
    assert views[0].id == funnel_id
    assert views[0].name == "Приветствие"


def test_rename_into_existing_name_is_rejected():
    client = _client()
    _bootstrap(client)
    funnels_repo.save("Онбординг", STEPS)
    second_id = funnels_repo.save("Напоминания", STEPS)

    response = client.post(
        "/funnels/save",
        data={
            "funnel_id": str(second_id),
            "name": "Онбординг",
            "delay_hours": ["0"],
            "text": ["Привет!"],
        },
    )

    assert response.status_code == 400
    assert len(funnels_repo.list_all()) == 2
    view = funnels_repo.get(second_id)
    assert view is not None
    assert view.name == "Напоминания"


def test_form_rejects_funnel_without_steps():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/funnels/save", data={"name": "Пустая", "delay_hours": ["0"], "text": ["  "]},
    )

    assert response.status_code == 400
    assert funnels_repo.list_all() == []


def test_form_rejects_non_numeric_delay():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/funnels/save",
        data={"name": "Кривая", "delay_hours": ["завтра"], "text": ["Привет!"]},
    )

    assert response.status_code == 400
    assert funnels_repo.list_all() == []


def test_edit_page_warns_about_people_in_flight():
    """Позиция человека хранится НОМЕРОМ шага, а не текстом.

    Правка середины сдвигает всех, кто уже идёт, — об этом надо сказать до
    того, как они получат чужое сообщение.
    """
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS, is_active=True)
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    response = client.get(f"/funnels/{funnel_id}")

    assert "идут 1" in response.text


def test_edit_page_of_missing_funnel_redirects():
    client = _client()
    _bootstrap(client)

    response = client.get("/funnels/999999", follow_redirects=False)

    assert response.status_code == 303


def test_new_page_opens():
    client = _client()
    _bootstrap(client)

    assert client.get("/funnels/new").status_code == 200


# --- включение ---


def test_toggle_switches_funnel_on_and_off():
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS)

    client.post(f"/funnels/{funnel_id}/toggle")
    view = funnels_repo.get(funnel_id)
    assert view is not None and view.is_active is True

    client.post(f"/funnels/{funnel_id}/toggle")
    view = funnels_repo.get(funnel_id)
    assert view is not None and view.is_active is False


def test_funnel_without_steps_cannot_be_switched_on():
    """Иначе людей записывали бы в цепочку, которая ничего им не пришлёт."""
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        row = Funnel(name="Пустая", trigger="start", steps_json="[]")
        session.add(row)
        session.flush()
        funnel_id = row.id

    response = client.post(f"/funnels/{funnel_id}/toggle")

    assert response.status_code == 400
    view = funnels_repo.get(funnel_id)
    assert view is not None and view.is_active is False


# --- удаление ---


def test_delete_removes_funnel_with_its_runs():
    """Висячие запуски были бы «идут» без воронки — вечная строка в отчётах.

    Каскад во внешнем ключе тут не спасает: SQLite не включает
    `PRAGMA foreign_keys` по умолчанию.
    """
    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS, is_active=True)
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    client.post(f"/funnels/{funnel_id}/delete")

    assert funnels_repo.get(funnel_id) is None
    with session_scope() as session:
        assert session.query(FunnelRun).count() == 0


def test_pages_require_login():
    client = _client()

    assert client.get("/funnels", follow_redirects=False).status_code in (302, 303, 307)


# --- полнота переводов ---


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    funnel_id = funnels_repo.save("Онбординг", STEPS, is_active=True)
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    client.get(f"/lang/{lang}?next=/funnels", follow_redirects=False)
    listing = client.get("/funnels")
    edit = client.get(f"/funnels/{funnel_id}")

    missing = re.compile(r"\[[a-z_]+\.[a-z_]+\]")
    assert not missing.findall(listing.text), f"список ({lang})"
    assert not missing.findall(edit.text), f"форма ({lang})"

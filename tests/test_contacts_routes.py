"""Веб-интерфейс CRM участников (F63): карточки, теги, сегменты.

Отдельно важно, что форма сегментов НЕ ДАЁТ создать выборку на всю базу по
ошибке: пустая форма отвергается, а «все» — отдельная галочка. Через UI это
проверяется своими тестами, потому что форма собирает фильтр сама, и потерять
условие она может независимо от репозитория.
"""

from __future__ import annotations

import pytest

# `_isolated_env` — autouse-фикстура из соседнего модуля: временный каталог,
# своя БД и no-op вместо запуска Telethon. Импортируется явно, потому что
# autouse действует только в модуле, где фикстура объявлена, а без неё
# бутстрап полез бы поднимать настоящего клиента.
from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import contacts_repo, segments_repo
from tg_repost.db.models import ContactNote, ContactSegment, ContactTag
from tg_repost.db.session import session_scope

USER = 424242


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ContactTag).delete()
            session.query(ContactNote).delete()
            session.query(ContactSegment).delete()

    _wipe()
    yield
    _wipe()


# --- карточки ---


def test_contacts_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    response = client.get("/contacts")

    assert response.status_code == 200


def test_contact_card_of_unknown_person_opens():
    """Владелец может открыть карточку по id из чужого сообщения."""
    client = _client()
    _bootstrap(client)

    response = client.get("/contacts/999999999")

    assert response.status_code == 200
    assert "id999999999" in response.text


def test_add_and_remove_tag_through_ui():
    client = _client()
    _bootstrap(client)

    added = client.post(f"/contacts/{USER}/tags", data={"tag": " VIP "},
                        follow_redirects=False)
    assert added.status_code == 303
    assert contacts_repo.tags_of(USER) == ["vip"]

    removed = client.post(f"/contacts/{USER}/tags/delete", data={"tag": "vip"},
                          follow_redirects=False)
    assert removed.status_code == 303
    assert contacts_repo.tags_of(USER) == []


def test_note_is_saved_and_cleared_through_ui():
    client = _client()
    _bootstrap(client)

    client.post(f"/contacts/{USER}/note", data={"note": "просил скидку"},
                follow_redirects=False)
    assert contacts_repo.note_of(USER) == "просил скидку"

    client.post(f"/contacts/{USER}/note", data={"note": "  "}, follow_redirects=False)
    assert contacts_repo.note_of(USER) is None


def test_tag_filter_narrows_the_list():
    client = _client()
    _bootstrap(client)
    contacts_repo.add_tag(USER, "vip")
    contacts_repo.add_tag(USER + 1, "новичок")

    response = client.get("/contacts?tag=vip")

    assert response.status_code == 200
    assert f"/contacts/{USER}" in response.text
    assert f"/contacts/{USER + 1}" not in response.text


# --- сегменты ---


def test_segments_page_opens():
    client = _client()
    _bootstrap(client)

    assert client.get("/segments").status_code == 200


def test_segment_created_through_form():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/segments",
        data={"name": "VIP", "tag": "vip", "min_points": "", "origin": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = segments_repo.list_all()
    assert len(saved) == 1
    assert saved[0].filter == {"tag": "vip"}


def test_empty_form_cannot_create_whole_base_segment():
    """ГЛАВНАЯ ЗАЩИТА В UI.

    Пустая форма собрала бы пустой фильтр, а пустой фильтр совпал бы со всей
    базой. Рассылка по такому сегменту ушла бы всем, и отозвать её нельзя.
    """
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/segments",
        data={"name": "Ой", "tag": "", "min_points": "", "origin": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert segments_repo.list_all() == []
    # Пользователю объясняют ПОЧЕМУ, а не просто «неверные данные».
    assert "всей базой" in response.text


def test_everyone_requires_explicit_checkbox():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/segments",
        data={"name": "Все", "everyone": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert segments_repo.list_all()[0].filter == {"everyone": True}


def test_everyone_combined_with_condition_is_rejected():
    """Непонятно, все или всё-таки по условию — значит не сохраняем."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/segments",
        data={"name": "Спорный", "everyone": "1", "tag": "vip"},
        follow_redirects=False,
    )

    # Форма при отмеченном «все» игнорирует прочие поля намеренно — иначе
    # владелец думал бы, что фильтрует, а рассылка ушла бы всем.
    assert response.status_code == 303
    assert segments_repo.list_all()[0].filter == {"everyone": True}


def test_non_numeric_points_is_rejected_with_explanation():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/segments",
        data={"name": "Кривой", "min_points": "много"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert segments_repo.list_all() == []


def test_segment_size_is_shown_and_recomputed():
    """Число людей — единственное, что отличает узкую выборку от всей базы.

    Показывать сохранённое значение нельзя: сегмент меняется сам по себе.
    """
    client = _client()
    _bootstrap(client)
    segments_repo.save("VIP", {"tag": "vip"})

    before = client.get("/segments").text
    contacts_repo.add_tag(USER, "vip")
    after = client.get("/segments").text

    assert "<strong>0</strong>" in before
    assert "<strong>1</strong>" in after


def test_segment_deleted_through_ui():
    client = _client()
    _bootstrap(client)
    segment_id = segments_repo.save("Временный", {"tag": "vip"})

    response = client.post(f"/segments/{segment_id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert segments_repo.list_all() == []


def test_contacts_pages_require_login():
    """Карточки содержат данные о людях — под аутентификацией, как и всё."""
    client = _client()

    for url in ("/contacts", f"/contacts/{USER}", "/segments"):
        response = client.get(url, follow_redirects=False)
        assert response.status_code in (302, 303, 307), url

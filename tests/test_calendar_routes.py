"""Веб-интерфейс контент-календаря (F72).

Главное, что проверяем: РЕДАКТОР НЕ МОЖЕТ ПОДТВЕРДИТЬ СВОЙ ЖЕ ПОСТ. Иначе
второй уровень согласования — декорация: тот, кто одобрил, сам же и снимает
ограничение, и владелец узнаёт о публикации из ленты.

Работает это за счёт правила «побеждает самый длинный префикс» из политики
доступа: `/calendar` открыт редактору, `/calendar/approve` — только
владельцу.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import AdminUser, Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Post).delete()

    _wipe()
    yield
    _wipe()


def _post(*, needs_owner: bool = False, scheduled: date | None = None) -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE,
            original_text="текст",
            rewritten_text="текст",
            status=PostStatus.APPROVED,
            needs_owner_approval=needs_owner,
            scheduled_for=scheduled,
        )
        session.add(post)
        session.flush()
        return post.id


def _as_editor(client) -> None:
    with session_scope() as session:
        session.add(
            AdminUser(
                username="editor1", role=access.ROLE_EDITOR,
                password_hash=hash_password("another-strong-pass"),
            )
        )
    client.post("/logout", follow_redirects=False)
    client.post(
        "/login", data={"username": "editor1", "password": "another-strong-pass"},
        follow_redirects=False,
    )


# --- доступ ---


def test_editor_can_open_calendar():
    """Планировать контент — работа редактора."""
    client = _client()
    _bootstrap(client)
    _as_editor(client)

    assert client.get("/calendar").status_code == 200


def test_editor_cannot_confirm_post():
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА.

    Если бы редактор подтверждал сам себя, второй уровень согласования был
    бы декорацией, а владелец узнавал о публикации из ленты.
    """
    client = _client()
    _bootstrap(client)
    post_id = _post(needs_owner=True)
    _as_editor(client)

    response = client.post(f"/calendar/approve/{post_id}", follow_redirects=False)

    assert response.status_code == 403
    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is True


def test_owner_can_confirm_post():
    client = _client()
    _bootstrap(client)
    post_id = _post(needs_owner=True)

    response = client.post(f"/calendar/approve/{post_id}", follow_redirects=False)

    assert response.status_code == 303
    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False


def test_analyst_cannot_open_calendar():
    """Аналитик считает эффективность, а не планирует публикации."""
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(
            AdminUser(
                username="analyst1", role=access.ROLE_ANALYST,
                password_hash=hash_password("another-strong-pass"),
            )
        )
    client.post("/logout", follow_redirects=False)
    client.post(
        "/login", data={"username": "analyst1", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/calendar").status_code == 403


# --- перенос даты ---


def test_editor_can_move_post():
    client = _client()
    _bootstrap(client)
    post_id = _post(scheduled=date.today())
    _as_editor(client)
    target = date.today() + timedelta(days=5)

    response = client.post(
        f"/calendar/{post_id}/schedule", data={"day": target.isoformat()},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_scope() as session:
        assert session.get(Post, post_id).scheduled_for == target


def test_empty_date_removes_the_restriction():
    """Снять дату — вернуть пост в общую очередь."""
    client = _client()
    _bootstrap(client)
    post_id = _post(scheduled=date.today() + timedelta(days=3))

    client.post(
        f"/calendar/{post_id}/schedule", data={"day": ""}, follow_redirects=False,
    )

    with session_scope() as session:
        assert session.get(Post, post_id).scheduled_for is None


def test_bad_date_changes_nothing():
    client = _client()
    _bootstrap(client)
    original = date.today() + timedelta(days=2)
    post_id = _post(scheduled=original)

    client.post(
        f"/calendar/{post_id}/schedule", data={"day": "не дата"},
        follow_redirects=False,
    )

    with session_scope() as session:
        assert session.get(Post, post_id).scheduled_for == original


# --- содержимое страницы ---


def test_page_shows_queue_and_awaiting_counts():
    client = _client()
    _bootstrap(client)
    _post()
    _post()
    _post(needs_owner=True)

    response = client.get("/calendar")

    assert "в очереди без даты: 2" in response.text
    assert "ждут владельца: 1" in response.text


def test_scheduled_post_is_visible_on_the_grid():
    client = _client()
    _bootstrap(client)
    day = date.today() + timedelta(days=4)
    post_id = _post(scheduled=day)

    response = client.get("/calendar")

    assert f"#{post_id}" in response.text
    assert day.strftime("%d.%m") in response.text


def test_confirm_button_hidden_from_editor():
    """Кнопки, которая всё равно не сработает, быть не должно.

    Показать её значило бы предложить редактору действие и отказать в нём —
    это раздражает сильнее, чем отсутствие кнопки.
    """
    client = _client()
    _bootstrap(client)
    _post(needs_owner=True)
    _as_editor(client)

    response = client.get("/calendar")

    assert "/calendar/approve/" not in response.text
    # Но объяснение, почему кнопки нет, показать надо.
    assert "только владелец" in response.text


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    _post(scheduled=date.today() + timedelta(days=2))
    _post(needs_owner=True)

    client.get(f"/lang/{lang}?next=/calendar", follow_redirects=False)
    response = client.get("/calendar")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)

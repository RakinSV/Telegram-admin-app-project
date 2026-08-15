"""Управление пользователями и проверка ролей на живых роутах (F37).

Политика проверена отдельно (`test_access_roles.py`), здесь — что она
РЕАЛЬНО применяется к запросам: middleware легко подключить неправильно, и
тогда все аккуратные правила останутся декларацией.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password


def _add_user(username: str, role: str, password: str = "another-strong-pass") -> int:
    with session_scope() as session:
        row = AdminUser(
            username=username, role=role, password_hash=hash_password(password),
        )
        session.add(row)
        session.flush()
        return row.id


def _login(client, username: str, password: str):
    return client.post(
        "/login", data={"username": username, "password": password},
        follow_redirects=False,
    )


# --- вход ---


def test_owner_created_by_setup_has_owner_role():
    client = _client()
    _bootstrap(client)

    with session_scope() as session:
        row = session.query(AdminUser).one()
        assert row.role == access.ROLE_OWNER
        assert row.username == "owner"


def test_login_without_username_works_for_single_user():
    """Обновление не должно ломать вход тем, кто ставил систему до ролей."""
    client = _client()
    _bootstrap(client)
    client.post("/logout", follow_redirects=False)

    response = client.post(
        "/login", data={"password": "smoke-test-password-123"},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_login_with_username_works():
    client = _client()
    _bootstrap(client)
    client.post("/logout", follow_redirects=False)

    assert _login(client, "owner", "smoke-test-password-123").status_code == 303


def test_wrong_username_is_rejected():
    client = _client()
    _bootstrap(client)
    client.post("/logout", follow_redirects=False)

    assert _login(client, "нетакого", "smoke-test-password-123").status_code == 401


# --- применение политики ---


def test_editor_is_blocked_from_settings():
    """Главное: правила применяются к живым запросам, а не только на бумаге."""
    client = _client()
    _bootstrap(client)
    _add_user("editor1", access.ROLE_EDITOR)
    client.post("/logout", follow_redirects=False)
    _login(client, "editor1", "another-strong-pass")

    assert client.get("/settings").status_code == 403
    assert client.get("/users").status_code == 403


def test_editor_can_reach_content_pages():
    client = _client()
    _bootstrap(client)
    _add_user("editor2", access.ROLE_EDITOR)
    client.post("/logout", follow_redirects=False)
    _login(client, "editor2", "another-strong-pass")

    assert client.get("/sources").status_code == 200
    assert client.get("/segments").status_code == 200


def test_analyst_can_read_but_not_publish():
    client = _client()
    _bootstrap(client)
    _add_user("analyst1", access.ROLE_ANALYST)
    client.post("/logout", follow_redirects=False)
    _login(client, "analyst1", "another-strong-pass")

    assert client.get("/stats").status_code == 200
    assert client.get("/moderation").status_code == 403
    assert client.get("/broadcasts").status_code == 403


def test_owner_reaches_everything():
    client = _client()
    _bootstrap(client)

    for url in ("/settings", "/users", "/sources", "/stats"):
        assert client.get(url).status_code == 200, url


def test_not_logged_in_is_redirected_not_forbidden():
    """Не вошедшему нужен вход, а не «недостаточно прав».

    403 вместо переадресации сбивал бы с толку: человек решил бы, что у него
    отняли доступ, хотя он просто не залогинен.
    """
    client = _client()

    response = client.get("/settings", follow_redirects=False)

    assert response.status_code in (302, 303, 307)


# --- управление пользователями ---


def test_owner_can_add_editor():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/users",
        data={"username": "Redaktor", "password": "very-strong-password",
              "role": access.ROLE_EDITOR},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_scope() as session:
        row = (
            session.query(AdminUser)
            .filter(AdminUser.username == "redaktor")  # имя приводится к нижнему
            .one()
        )
        assert row.role == access.ROLE_EDITOR


def test_short_password_is_rejected():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/users",
        data={"username": "weak", "password": "123", "role": access.ROLE_EDITOR},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_duplicate_username_is_rejected():
    client = _client()
    _bootstrap(client)
    client.post(
        "/users",
        data={"username": "dup", "password": "very-strong-password",
              "role": access.ROLE_EDITOR},
        follow_redirects=False,
    )

    response = client.post(
        "/users",
        data={"username": "dup", "password": "another-strong-pass",
              "role": access.ROLE_EDITOR},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_unknown_role_is_rejected():
    """Роль приходит из формы — подставить произвольную строку тривиально.

    Учётка с неизвестной ролью не прошла бы никуда, то есть доступ оказался
    бы сломан молча вместо явной ошибки.
    """
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/users",
        data={"username": "hacker", "password": "very-strong-password",
              "role": "superadmin"},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_last_owner_cannot_be_deleted():
    """ВТОРОЙ ГЛАВНЫЙ ТЕСТ.

    Система без владельца — это система, куда некому войти за настройками,
    и выбраться из этого через интерфейс невозможно: страницу пользователей
    тоже открывает только владелец.
    """
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        owner_id = session.query(AdminUser).one().id

    response = client.post(f"/users/{owner_id}/delete", follow_redirects=False)

    assert response.status_code == 400
    with session_scope() as session:
        assert session.query(AdminUser).count() == 1


def test_owner_can_be_deleted_when_another_owner_exists():
    client = _client()
    _bootstrap(client)
    second = _add_user("owner2", access.ROLE_OWNER)
    with session_scope() as session:
        first = (
            session.query(AdminUser)
            .filter(AdminUser.username == "owner")
            .one()
            .id
        )
    assert second != first

    response = client.post(f"/users/{first}/delete", follow_redirects=False)

    assert response.status_code == 303


def test_editor_can_be_deleted():
    client = _client()
    _bootstrap(client)
    editor_id = _add_user("temp", access.ROLE_EDITOR)

    response = client.post(f"/users/{editor_id}/delete", follow_redirects=False)

    assert response.status_code == 303


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    _add_user("editor3", access.ROLE_EDITOR)

    client.get(f"/lang/{lang}?next=/users", follow_redirects=False)
    response = client.get("/users")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)

"""Дыры в правах доступа, найденные аудитом 2026-08-16.

Политика доступа — «запрещено, если не разрешено явно»: путь, которого нет
в `_POLICY`, доступен только владельцу. Правило хорошее, но у него есть
обратная сторона: страницу можно ЗАБЫТЬ внести, и она молча станет
недоступной тем, для кого писалась. Молча — потому что тесты фичи ходят под
владельцем, и всё выглядит рабочим.

Здесь проверяются именно такие случаи: маршруты, которые обслуживают
страницы редактора, но сами в политику не попали.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import AdminUser, Post
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password

EDITOR_PASSWORD = "another-strong-pass"


def _as_editor(client) -> None:
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_gap", role=access.ROLE_EDITOR,
            password_hash=hash_password(EDITOR_PASSWORD),
        ))
    client.post(
        "/login", data={"username": "editor_gap", "password": EDITOR_PASSWORD},
        follow_redirects=False,
    )


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as session:
        session.query(Post).delete()
    yield
    with session_scope() as session:
        session.query(Post).delete()


def test_editor_can_load_post_media():
    """КАРТИНКА НА СТРАНИЦЕ МОДЕРАЦИИ.

    `/moderation/{id}` открыт редактору и рисует `<img src="/media/...">`.
    Если сам `/media` в политику не внесён, редактор видит страницу с
    БИТОЙ картинкой — то есть не видит того, что модерирует, а система
    выглядит сломанной.
    """
    client = _client()
    _bootstrap(client)
    _as_editor(client)

    response = client.get("/media/none.jpg")

    # Файла нет — 404 это нормально. Недопустим именно ОТКАЗ ПО ПРАВАМ.
    assert response.status_code != 403


def test_editor_can_open_support_inbox():
    """Поддержка — ежедневная работа того же уровня, что контакты и рассылки.

    `/contacts`, `/broadcasts`, `/calendar` открыты редактору; `/support`
    выпал из политики и остался у владельца, хотя ссылка на него показана
    всем ролям — то есть редактор жмёт пункт меню и получает отказ.
    """
    client = _client()
    _bootstrap(client)
    _as_editor(client)

    assert client.get("/support").status_code == 200


def test_analyst_cannot_reach_support():
    """Аналитик — «только смотреть», переписка с людьми не его дело."""
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="analyst_gap", role=access.ROLE_ANALYST,
            password_hash=hash_password(EDITOR_PASSWORD),
        ))
    client.post(
        "/login", data={"username": "analyst_gap", "password": EDITOR_PASSWORD},
        follow_redirects=False,
    )

    assert client.get("/support").status_code == 403


def test_menu_hides_what_the_role_cannot_open():
    """Пункт меню, ведущий на отказ, — это не защита, а обман.

    Раньше меню было одинаковым для всех ролей: аналитик видел «Настройки»,
    «Пользователи», «Журнал» и получал 403 на каждый клик.
    """
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="analyst_menu", role=access.ROLE_ANALYST,
            password_hash=hash_password(EDITOR_PASSWORD),
        ))
    client.post(
        "/login", data={"username": "analyst_menu", "password": EDITOR_PASSWORD},
        follow_redirects=False,
    )

    body = client.get("/stats").text

    assert 'href="/settings"' not in body
    assert 'href="/users"' not in body
    assert 'href="/stats"' in body


def test_owner_still_sees_everything():
    client = _client()
    _bootstrap(client)

    body = client.get("/").text

    for path in ("/settings", "/users", "/audit", "/support", "/funnels"):
        assert f'href="{path}"' in body, path

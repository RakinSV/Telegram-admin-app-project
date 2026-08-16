"""Страница интеграций: ключи API и вебхуки (F73).

Ключ показывается ОДИН раз в жизни, поэтому главное здесь — что он не
утекает ни в адресную строку, ни в повторный показ, ни в список.
"""

from __future__ import annotations

import re

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import api_keys_repo as keys
from tg_repost import webhooks_repo as hooks
from tg_repost.db.models import AdminUser, ApiKey, Webhook
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ApiKey).delete()
            session.query(Webhook).delete()
        keys.reset_rate_limits()

    _wipe()
    yield
    _wipe()


@pytest.fixture(autouse=True)
def _external_dns(monkeypatch):
    monkeypatch.setattr(
        hooks.socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )


# --- страница ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/integrations").status_code == 200


def test_page_is_owner_only():
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_int", role=access.ROLE_EDITOR,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login", data={"username": "editor_int", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/integrations").status_code == 403


# --- ключи ---


def test_created_key_is_shown_once():
    client = _client()
    _bootstrap(client)

    # Ответ на POST — это уже страница после переадресации: именно на ней
    # ключ показывается первый и последний раз.
    first = client.post(
        "/integrations/keys", data={"name": "Дашборд", "scope": "read"},
    ).text
    second = client.get("/integrations").text

    shown = re.search(r"[0-9a-f]{8}\.[A-Za-z0-9_\-]{20,}", first)
    assert shown is not None, "ключ не показан после создания"
    assert shown.group(0) not in second, "ключ показан повторно"


def test_key_never_goes_into_the_address_bar():
    """Параметры адреса оседают в истории браузера, логах прокси и
    реферерах — ключ утекал бы сам собой."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/integrations/keys", data={"name": "Дашборд", "scope": "read"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "?" not in response.headers["location"]


def test_listing_shows_only_the_prefix():
    client = _client()
    _bootstrap(client)
    view, raw = keys.create("Существующий")

    body = client.get("/integrations").text

    assert view.prefix in body
    assert raw.split(".", 1)[1] not in body


def test_invalid_rate_limit_is_refused():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/integrations/keys",
        data={"name": "Ключ", "scope": "read", "rate_limit": "ноль"},
    )

    assert response.status_code == 400
    assert keys.list_keys() == []


def test_revoke_from_the_page():
    client = _client()
    _bootstrap(client)
    view, _ = keys.create("Ключ")

    client.post(f"/integrations/keys/{view.id}/revoke")

    assert keys.list_keys()[0].is_active is False


# --- вебхуки ---


def test_webhook_is_created():
    client = _client()
    _bootstrap(client)

    client.post(
        "/integrations/webhooks",
        data={"url": "https://example.com/hook", "events": [hooks.EVENT_PAYMENT]},
    )

    rows = hooks.list_all()
    assert len(rows) == 1
    assert rows[0].events == (hooks.EVENT_PAYMENT,)


def test_internal_address_is_refused_with_explanation(monkeypatch):
    """Владелец должен понять, почему адрес не приняли, — иначе он решит,
    что форма сломана, и будет пробовать снова."""
    monkeypatch.setattr(
        hooks.socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/integrations/webhooks", data={"url": "http://localhost/hook"},
    )

    assert response.status_code == 400
    assert "внутренний" in response.text
    assert hooks.list_all() == []


def test_webhook_secret_is_never_shown():
    """Секрет подписи знают только мы и получатель. На странице его быть
    не должно — скриншот настроек ходит по переписке."""
    client = _client()
    _bootstrap(client)
    webhook_id = hooks.save("https://example.com/hook", events=[])
    with session_scope() as session:
        secret = session.get(Webhook, webhook_id).secret

    assert secret not in client.get("/integrations").text


def test_webhook_delete_from_the_page():
    client = _client()
    _bootstrap(client)
    webhook_id = hooks.save("https://example.com/hook", events=[])

    client.post(f"/integrations/webhooks/{webhook_id}/delete")

    assert hooks.list_all() == []


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    keys.create("Ключ")
    hooks.save("https://example.com/hook", events=[hooks.EVENT_PAYMENT])

    client.get(f"/lang/{lang}?next=/integrations", follow_redirects=False)
    body = client.get("/integrations").text

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(body)

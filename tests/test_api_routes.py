"""Публичный REST API (F73).

⚠️ ВТОРАЯ ПУБЛИЧНАЯ ПОВЕРХНОСТЬ СИСТЕМЫ. Поэтому тесты проверяют не «метод
отвечает», а границы: без ключа не пускает, читающий ключ не пишет, секретов
наружу нет, а освобождение `/api` от ролей не приоткрыло админку.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import api_keys_repo as keys
from tg_repost.db.models import ApiKey, Post
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ApiKey).delete()
        keys.reset_rate_limits()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _read_key() -> str:
    return keys.create("Чтение")[1]


@pytest.fixture
def _write_key() -> str:
    return keys.create("Запись", scope=keys.SCOPE_WRITE)[1]


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


# --- аутентификация ---


def test_valid_key_passes(_read_key):
    client = _client()

    response = client.get("/api/v1/ping", headers=_auth(_read_key))

    assert response.status_code == 200
    assert response.json()["scope"] == keys.SCOPE_READ


def test_without_key_nothing_works():
    client = _client()

    assert client.get("/api/v1/ping").status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        # Заголовки обязаны быть ASCII — нелатиница сюда физически не
        # попадёт, поэтому и проверяем ровно то, что реально дойдёт.
        {"Authorization": "garbage"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer guessed.key"},
        {"Authorization": "Basic abc"},
    ],
)
def test_broken_authorization_is_refused(header):
    client = _client()

    assert client.get("/api/v1/ping", headers=header).status_code == 401


def test_revoked_key_stops_working(_read_key):
    client = _client()
    keys.revoke(keys.list_keys()[0].id)

    assert client.get("/api/v1/ping", headers=_auth(_read_key)).status_code == 401


def test_refusal_does_not_explain_why(_read_key):
    """«Нет такого ключа» и «ключ отозван» для вызывающего одно и то же:
    разница помогала бы перебирать."""
    client = _client()
    keys.revoke(keys.list_keys()[0].id)

    revoked = client.get("/api/v1/ping", headers=_auth(_read_key))
    missing = client.get("/api/v1/ping", headers=_auth("aaaaaaaa.nope"))

    assert revoked.json() == missing.json()


# --- области прав ---


def test_read_key_cannot_write(_read_key):
    """Ключ настоящий, прав не хватает — 403, а не 401."""
    client = _client()

    response = client.post(
        "/api/v1/posts", json={"text": "Привет"}, headers=_auth(_read_key),
    )

    assert response.status_code == 403


def test_write_key_can_read(_write_key):
    """Права вложены: пишущий ключ умеет и читать."""
    client = _client()

    assert client.get("/api/v1/ping", headers=_auth(_write_key)).status_code == 200


def test_created_post_goes_to_moderation_not_to_the_channel(_write_key):
    """ГЛАВНАЯ ГРАНИЦА ЗАПИСИ.

    Ключ утекает вместе с чужим репозиторием, и цена ошибки — пост от лица
    канала. Одобряет по-прежнему человек.
    """
    client = _client()

    response = client.post(
        "/api/v1/posts", json={"text": "Из внешней системы"}, headers=_auth(_write_key),
    )

    assert response.status_code == 200
    with session_scope() as session:
        row = session.get(Post, response.json()["id"])
        assert row.status.value != "posted"


def test_empty_text_is_refused(_write_key):
    client = _client()

    response = client.post("/api/v1/posts", json={"text": "  "}, headers=_auth(_write_key))

    assert response.status_code == 422


# --- чего наружу нет ---


def test_api_has_no_secret_endpoints():
    """Ключ API даёт доступ к ДАННЫМ, а не к учётным записям: иначе одна
    утёкшая строка отдавала бы вместе с ней все системы владельца."""
    from tg_repost.webui.app import create_app

    paths = [p for p in create_app().openapi()["paths"] if p.startswith("/api/")]

    for forbidden in ("secret", "token", "session", "settings", "password", "user"):
        assert not any(forbidden in p for p in paths), f"{forbidden}: {paths}"


def test_api_never_deletes():
    """Ошибка в чужом скрипте не должна быть необратимой."""
    from tg_repost.webui.app import create_app

    spec = create_app().openapi()["paths"]
    api = {p: ops for p, ops in spec.items() if p.startswith("/api/")}

    assert not [p for p, ops in api.items() if "delete" in ops]


def test_audience_returns_counters_not_people(_read_key):
    """«Сколько подписчиков» — интеграция. «Отдай список с контактами» —
    экспорт базы через ключ, лежащий в чужом скрипте."""
    client = _client()

    body = client.get("/api/v1/audience", headers=_auth(_read_key)).json()

    assert set(body) == {
        "total", "reachable", "never_started", "blocked", "unsubscribed",
    }
    assert all(isinstance(v, int) for v in body.values())


# --- ограничение частоты ---


def test_too_many_requests_get_429():
    client = _client()
    _, raw = keys.create("Частый", rate_limit=2)

    for _ in range(2):
        client.get("/api/v1/ping", headers=_auth(raw))
    response = client.get("/api/v1/ping", headers=_auth(raw))

    assert response.status_code == 429


def test_429_says_how_long_to_wait():
    """Без `Retry-After` вызывающий не знает, сколько ждать, и начинает
    долбиться чаще — ровно наоборот от нужного."""
    client = _client()
    _, raw = keys.create("Частый", rate_limit=1)
    client.get("/api/v1/ping", headers=_auth(raw))

    response = client.get("/api/v1/ping", headers=_auth(raw))

    assert int(response.headers["Retry-After"]) >= 1


# --- освобождение /api не открыло админку ---


@pytest.mark.parametrize(
    "path", ["/", "/settings", "/secrets", "/users", "/subscriptions"],
)
def test_admin_pages_still_require_login(path):
    """РЕГРЕССИЯ НА ГЛАВНЫЙ РИСК.

    `/api` внесён в список освобождённых от проверки ролей. Ошибка в
    префиксе — и вместе с ним открылась бы вся админка.
    """
    client = _client()

    assert client.get(path, follow_redirects=False).status_code in (302, 303, 307, 403)


def test_api_key_does_not_open_the_admin(_write_key):
    """Ключ — пропуск в API, а не в браузерную админку."""
    client = _client()

    response = client.get("/settings", headers=_auth(_write_key), follow_redirects=False)

    assert response.status_code in (302, 303, 307, 403)

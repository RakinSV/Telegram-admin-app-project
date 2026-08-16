"""Страница приёма криптовалюты (F70).

Ключи от денег. Поэтому проверяется не «форма сохраняет», а что ключ никуда
не утекает и что привязка кошелька к группе действительно работает — ради
неё фича и делалась.
"""

from __future__ import annotations

import re

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import crypto_rails_repo as rails
from tg_repost.crypto_rails import KIND_CRYPTOBOT, KIND_TON_DIRECT
from tg_repost.db.models import AdminUser, CryptoRail, Product, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password

CHAT = -100931
TOKEN = "очень-секретный-токен-провайдера"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(CryptoRail).delete()
            session.query(Product).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _group() -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT, title="Основной канал"))


# --- доступ ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/crypto").status_code == 200


def test_page_is_owner_only():
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_crypto", role=access.ROLE_EDITOR,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login",
        data={"username": "editor_crypto", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/crypto").status_code == 403


# --- ключи не утекают ---


def test_provider_token_is_never_rendered():
    """ГЛАВНОЕ. Токен провайдера — доступ к деньгам."""
    client = _client()
    _bootstrap(client)
    client.post(
        "/crypto",
        data={"name": "Касса", "kind": KIND_CRYPTOBOT, "credential": TOKEN,
              "is_active": "1"},
    )

    body = client.get("/crypto").text

    assert TOKEN not in body


def test_ton_address_is_rendered_openly():
    """Адрес не секрет: по нему владелец сверяется с кошельком."""
    client = _client()
    _bootstrap(client)
    client.post(
        "/crypto",
        data={"name": "Кошелёк", "kind": KIND_TON_DIRECT,
              "credential": "EQpublicaddress", "is_active": "1"},
    )

    assert "EQpublicaddress" in client.get("/crypto").text


def test_credential_does_not_go_into_the_address_bar():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/crypto",
        data={"name": "Касса", "kind": KIND_CRYPTOBOT, "credential": TOKEN},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert TOKEN not in response.headers["location"]


def test_broken_kind_is_refused_with_explanation():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/crypto", data={"name": "Что-то", "kind": "монеты", "credential": "x"},
    )

    assert response.status_code == 400
    assert rails.list_all() == []


# --- привязка к группам ---


def test_group_can_be_bound_to_a_wallet():
    """То, ради чего фича и делалась."""
    client = _client()
    _bootstrap(client)
    _group()
    rail_id = rails.save(name="Кошелёк A", kind=KIND_TON_DIRECT, credential="EQaaa")

    client.post("/crypto/bind", data={"chat_id": str(CHAT), "rail_id": str(rail_id)})

    with session_scope() as session:
        row = session.query(TargetGroup).filter(TargetGroup.chat_id == CHAT).one()
        assert row.crypto_rail_id == rail_id


def test_group_can_be_returned_to_the_default():
    client = _client()
    _bootstrap(client)
    _group()
    rail_id = rails.save(name="Кошелёк A", kind=KIND_TON_DIRECT, credential="EQaaa")
    rails.bind_to_group(CHAT, rail_id)

    client.post("/crypto/bind", data={"chat_id": str(CHAT), "rail_id": ""})

    with session_scope() as session:
        row = session.query(TargetGroup).filter(TargetGroup.chat_id == CHAT).one()
        assert row.crypto_rail_id is None


def test_binding_shows_up_on_the_page():
    client = _client()
    _bootstrap(client)
    _group()
    rail_id = rails.save(name="Кошелёк A", kind=KIND_TON_DIRECT, credential="EQaaa")
    rails.bind_to_group(CHAT, rail_id)

    body = client.get("/crypto").text

    assert "Основной канал" in body
    assert "Кошелёк A" in body


def test_deleting_a_wallet_frees_the_group():
    client = _client()
    _bootstrap(client)
    _group()
    rail_id = rails.save(name="Кошелёк A", kind=KIND_TON_DIRECT, credential="EQaaa")
    rails.bind_to_group(CHAT, rail_id)

    client.post(f"/crypto/{rail_id}/delete")

    with session_scope() as session:
        row = session.query(TargetGroup).filter(TargetGroup.chat_id == CHAT).one()
        assert row.crypto_rail_id is None


def test_page_warns_that_crypto_is_for_physical_goods_only():
    """Обход правила Telegram стоит бана бота — это должно быть на экране,
    а не только в плане."""
    client = _client()
    _bootstrap(client)

    body = client.get("/crypto").text

    assert "физические" in body.lower()
    assert "Stars" in body


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    _group()
    rails.save(name="Касса", kind=KIND_CRYPTOBOT, credential="t")

    client.get(f"/lang/{lang}?next=/crypto", follow_redirects=False)
    body = client.get("/crypto").text

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(body)

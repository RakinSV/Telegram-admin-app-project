"""Сообщение, переживающее переадресацию (юзабилити, 2026-08-17).

После POST страница отвечает переадресацией — иначе обновление повторяет
действие. Но вместе с ответом терялось и объяснение: обработчик, наткнувшийся
на неверный ввод, возвращал человека на ту же страницу без единого слова, и
тот не понимал, случилось ли что-нибудь вообще.

Аудит путей нашёл 53 таких перехода. Большинство — переадресация ПОСЛЕ
УСПЕХА, там объяснять нечего: результат виден на самой странице. Опасны
остальные — отказ, выглядящий как бездействие.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import crypto_rails_repo as rails
from tg_repost.db.models import CryptoRail
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(CryptoRail).delete()

    _wipe()
    yield
    _wipe()


def test_refusal_explains_itself_after_the_redirect():
    """ГЛАВНОЕ СВОЙСТВО.

    Раньше здесь человек получал ту же страницу без изменений и без слов.
    """
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/crypto/bind", data={"chat_id": "не число", "rail_id": ""},
        follow_redirects=True,
    )

    assert "Не понял, какой это чат" in response.text


def test_message_is_shown_once():
    """Иначе оно висело бы на каждой следующей странице, объясняя давно
    забытое действие."""
    client = _client()
    _bootstrap(client)
    client.post(
        "/crypto/bind", data={"chat_id": "мусор", "rail_id": ""},
        follow_redirects=True,
    )

    again = client.get("/crypto")

    assert "Не понял, какой это чат" not in again.text


def test_message_does_not_leak_into_the_address():
    """Параметры адреса оседают в истории браузера и логах прокси — вместе с
    текстом ошибки."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/crypto/bind", data={"chat_id": "мусор", "rail_id": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "?" not in response.headers["location"]


def test_successful_action_says_nothing_extra():
    """Успех виден на самой странице; лишнее сообщение — шум."""
    client = _client()
    _bootstrap(client)
    rails.save(name="Кошелёк", kind="ton_direct", credential="EQtest")

    response = client.get("/crypto")

    assert "Не понял" not in response.text


def test_broadcast_says_when_the_segment_disappeared():
    """Человек уверен, что рассылка ушла, и узнает обратное только по
    отсутствию ответов."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/broadcasts/send",
        data={"segment_id": "999999", "text": "Привет", "expected_reachable": "1"},
        follow_redirects=True,
    )

    assert "НЕ" in response.text and "отправлена" in response.text

"""Тесты одноразового токена настройки /setup* (F23, аудит Фазы 5)."""

import pytest

from tg_repost.webui import setup_token


@pytest.fixture(autouse=True)
def _reset_token():
    setup_token._token = None
    yield
    setup_token._token = None


def test_get_or_create_setup_token_generates_once():
    token1 = setup_token.get_or_create_setup_token()
    token2 = setup_token.get_or_create_setup_token()
    assert token1 == token2
    assert len(token1) > 16


def test_verify_setup_token_accepts_correct_token():
    token = setup_token.get_or_create_setup_token()
    assert setup_token.verify_setup_token(token) is True


def test_verify_setup_token_rejects_wrong_token():
    setup_token.get_or_create_setup_token()
    assert setup_token.verify_setup_token("wrong-token") is False


def test_verify_setup_token_rejects_none_and_empty():
    setup_token.get_or_create_setup_token()
    assert setup_token.verify_setup_token(None) is False
    assert setup_token.verify_setup_token("") is False

"""Тесты веб-обвязки Telethon-логина (F23, Фаза 5.2).

Telethon-функции (`start_telethon_login` и т.д.) подменяются моками —
никаких реальных сетевых вызовов к Telegram. Проверяется только логика
конечного автомата и перевод исключений в понятные сообщения.
"""

from dataclasses import dataclass

import pytest
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
)

from tg_repost.webui import telethon_login


@dataclass
class _FakeClient:
    disconnected: bool = False

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def _reset_login_state():
    telethon_login._current_login = None
    yield
    telethon_login._current_login = None


async def test_begin_success(monkeypatch):
    fake_state = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="hash123"
    )

    async def fake_start(api_id, api_hash, phone):
        return fake_state

    monkeypatch.setattr(telethon_login, "start_telethon_login", fake_start)
    ok, message = await telethon_login.begin(1, "hash", "+1")
    assert ok is True
    assert telethon_login.is_in_progress() is True


async def test_begin_phone_invalid(monkeypatch):
    async def fake_start(api_id, api_hash, phone):
        raise PhoneNumberInvalidError(request=None)

    monkeypatch.setattr(telethon_login, "start_telethon_login", fake_start)
    ok, message = await telethon_login.begin(1, "hash", "bad-phone")
    assert ok is False
    assert "номер" in message.lower()
    assert telethon_login.is_in_progress() is False


async def test_begin_flood_wait(monkeypatch):
    async def fake_start(api_id, api_hash, phone):
        raise FloodWaitError(request=None, capture=30)

    monkeypatch.setattr(telethon_login, "start_telethon_login", fake_start)
    ok, message = await telethon_login.begin(1, "hash", "+1")
    assert ok is False
    assert "30" in message


async def test_begin_cancels_previous_in_progress_login(monkeypatch):
    old_client = _FakeClient()
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=old_client, phone="+0", phone_code_hash="old"
    )

    new_state = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="new"
    )

    async def fake_start(api_id, api_hash, phone):
        return new_state

    monkeypatch.setattr(telethon_login, "start_telethon_login", fake_start)
    await telethon_login.begin(1, "hash", "+1")
    assert old_client.disconnected is True


async def test_submit_code_done(monkeypatch):
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="h"
    )

    async def fake_submit_code(state, code):
        return "SESSION_STRING_VALUE"

    monkeypatch.setattr(telethon_login, "submit_telethon_code", fake_submit_code)
    status, payload = await telethon_login.submit_code("12345")
    assert status == "done"
    assert payload == "SESSION_STRING_VALUE"
    assert telethon_login.is_in_progress() is False


async def test_submit_code_need_password(monkeypatch):
    state = telethon_login.TelethonLoginState(client=_FakeClient(), phone="+1", phone_code_hash="h")
    telethon_login._current_login = state

    async def fake_submit_code(state, code):
        state.awaiting_password = True
        return state

    monkeypatch.setattr(telethon_login, "submit_telethon_code", fake_submit_code)
    status, payload = await telethon_login.submit_code("12345")
    assert status == "need_password"
    assert payload is None
    assert telethon_login.awaiting_password() is True


async def test_submit_code_invalid(monkeypatch):
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="h"
    )

    async def fake_submit_code(state, code):
        raise PhoneCodeInvalidError(request=None)

    monkeypatch.setattr(telethon_login, "submit_telethon_code", fake_submit_code)
    status, payload = await telethon_login.submit_code("00000")
    assert status == "error"
    assert "код" in payload.lower()
    # Состояние логина не теряется — пользователь может попробовать снова.
    assert telethon_login.is_in_progress() is True


async def test_submit_code_expired_resets_state(monkeypatch):
    client = _FakeClient()
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=client, phone="+1", phone_code_hash="h"
    )

    async def fake_submit_code(state, code):
        raise PhoneCodeExpiredError(request=None)

    monkeypatch.setattr(telethon_login, "submit_telethon_code", fake_submit_code)
    status, payload = await telethon_login.submit_code("00000")
    assert status == "error"
    assert telethon_login.is_in_progress() is False
    assert client.disconnected is True


async def test_submit_code_without_active_login():
    status, payload = await telethon_login.submit_code("12345")
    assert status == "error"


async def test_submit_password_done(monkeypatch):
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="h", awaiting_password=True
    )

    async def fake_submit_password(state, password):
        return "SESSION_STRING_VALUE"

    monkeypatch.setattr(telethon_login, "submit_telethon_password", fake_submit_password)
    status, payload = await telethon_login.submit_password("secret2fa")
    assert status == "done"
    assert payload == "SESSION_STRING_VALUE"
    assert telethon_login.is_in_progress() is False


async def test_submit_password_invalid(monkeypatch):
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=_FakeClient(), phone="+1", phone_code_hash="h", awaiting_password=True
    )

    async def fake_submit_password(state, password):
        raise PasswordHashInvalidError(request=None)

    monkeypatch.setattr(telethon_login, "submit_telethon_password", fake_submit_password)
    status, payload = await telethon_login.submit_password("wrong")
    assert status == "error"
    assert "пароль" in payload.lower()


async def test_submit_password_without_active_login():
    status, payload = await telethon_login.submit_password("anything")
    assert status == "error"


async def test_cancel_disconnects_active_login():
    client = _FakeClient()
    telethon_login._current_login = telethon_login.TelethonLoginState(
        client=client, phone="+1", phone_code_hash="h"
    )
    await telethon_login.cancel()
    assert client.disconnected is True
    assert telethon_login.is_in_progress() is False


async def test_cancel_noop_when_nothing_in_progress():
    await telethon_login.cancel()  # не должно падать
    assert telethon_login.is_in_progress() is False


def test_is_in_progress_false_by_default():
    assert telethon_login.is_in_progress() is False


def test_awaiting_password_false_by_default():
    assert telethon_login.awaiting_password() is False

"""Генерация Telethon session string (Фаза 0, шаг 7; Фаза 5.2 — веб-визард).

Два способа использования:
  1. Интерактивно в терминале: `python -m tg_repost.tools.gen_session` —
     логинится под юзер-аккаунтом через `TelegramClient.start()` (сам
     спрашивает телефон/код/пароль через `input()`), печатает session string
     для ручной вставки в `.env`.
  2. Пошагово из веб-визарда `/setup` (см. `tg_repost/webui/telethon_login.py`)
     — через `start_telethon_login`/`submit_telethon_code`/
     `submit_telethon_password` ниже: `input()` недопустим внутри обработчика
     HTTP-запроса, поэтому используется низкоуровневый Telethon API
     (`send_code_request`/`sign_in`) вместо `client.start()`.

Запуск (интерактивно):  python -m tg_repost.tools.gen_session
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from tg_repost.config import get_settings
from tg_repost.logging_conf import ensure_utf8_stdout


@dataclass
class TelethonLoginState:
    """Незавершённый пошаговый вход — держит живое соединение между шагами
    (нужно для `sign_in`: код и пароль проверяются на том же соединении,
    которым был запрошен код)."""

    client: TelegramClient
    phone: str
    phone_code_hash: str
    awaiting_password: bool = False


async def start_telethon_login(api_id: int, api_hash: str, phone: str) -> TelethonLoginState:
    """Шаг 1: подключиться и запросить код подтверждения на телефон.

    Бросает исключения Telethon как есть (`PhoneNumberInvalidError`,
    `FloodWaitError` и т.д.) — обработка и перевод в человеко-понятные
    сообщения на уровне `webui/telethon_login.py`.
    """
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    sent = await client.send_code_request(phone)
    return TelethonLoginState(client=client, phone=phone, phone_code_hash=sent.phone_code_hash)


async def submit_telethon_code(state: TelethonLoginState, code: str) -> str | TelethonLoginState:
    """Шаг 2: код из Telegram.

    Возвращает session string при успехе, либо тот же `state` с
    `awaiting_password=True`, если аккаунт защищён паролем 2FA (нужен шаг 3).
    """
    try:
        await state.client.sign_in(
            phone=state.phone, code=code, phone_code_hash=state.phone_code_hash
        )
    except SessionPasswordNeededError:
        state.awaiting_password = True
        return state
    return state.client.session.save()


async def submit_telethon_password(state: TelethonLoginState, password: str) -> str:
    """Шаг 3 (только если потребовался): пароль 2FA. Возвращает session string."""
    await state.client.sign_in(password=password)
    return state.client.session.save()


async def cancel_telethon_login(state: TelethonLoginState) -> None:
    """Отменить незавершённый вход — отключить соединение, не оставляя висеть."""
    await state.client.disconnect()


async def _main() -> None:
    ensure_utf8_stdout()
    settings = get_settings()
    print("Логин в Telegram под юзер-аккаунтом (Telethon).")
    print("Понадобится номер телефона, код из Telegram и, при наличии, пароль 2FA.\n")

    async with TelegramClient(
        StringSession(), settings.tg_api_id, settings.tg_api_hash
    ) as client:
        session_string = client.session.save()
        me = await client.get_me()
        print("\n✅ Авторизация успешна. Вошли как:",
              getattr(me, "username", None) or me.id)
        print("\nВставь это значение в .env как TG_SESSION_STRING:\n")
        print(session_string)
        print("\n⚠️  Это секрет — не коммить и не показывай никому.")


if __name__ == "__main__":
    asyncio.run(_main())

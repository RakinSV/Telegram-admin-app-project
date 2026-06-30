"""Генерация Telethon session string (Фаза 0, шаг 7).

Интерактивно логинится под юзер-аккаунтом и печатает session string, который
нужно вставить в `.env` (`TG_SESSION_STRING`). После этого пароль/код больше
не запрашиваются.

Запуск:  python -m tg_repost.tools.gen_session
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from tg_repost.config import get_settings
from tg_repost.logging_conf import ensure_utf8_stdout


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

"""Проверка авторизации Telethon (Фаза 0, критерий готовности).

Логинится по session string из .env и печатает первые диалоги — подтверждение,
что юзер-сессия живая.

Запуск:  python -m tg_repost.tools.check_telethon
"""

from __future__ import annotations

import asyncio

from tg_repost.logging_conf import setup_logging
from tg_repost.telegram.listener import build_client


async def _main() -> None:
    setup_logging("INFO")
    client = build_client()
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ Не авторизован. Сгенерируй session: "
              "python -m tg_repost.tools.gen_session")
        return
    me = await client.get_me()
    print("✅ Авторизован как:", getattr(me, "username", None) or me.id)
    print("\nПервые диалоги:")
    async for dialog in client.iter_dialogs(limit=10):
        print(f"  - {dialog.name} (id={dialog.id})")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())

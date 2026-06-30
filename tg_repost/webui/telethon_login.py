"""Веб-обвязка над пошаговым визардом Telethon-логина (F23, Фаза 5.2).

Хранит ОДНО незавершённое состояние входа в памяти процесса — один админ,
не нужна более сложная привязка к HTTP-сессии. Если стартует новый вход,
пока предыдущий не завершён, старое соединение аккуратно закрывается.
Используется и из `/setup` (до создания администратора), и из `/components`
(повторный вход, если сессия истекла — после создания администратора).
"""

from __future__ import annotations

from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
)

from tg_repost.logging_conf import get_logger
from tg_repost.tools.gen_session import (
    TelethonLoginState,
    cancel_telethon_login,
    start_telethon_login,
    submit_telethon_code,
    submit_telethon_password,
)

logger = get_logger(__name__)

_current_login: TelethonLoginState | None = None


async def begin(api_id: int, api_hash: str, phone: str) -> tuple[bool, str]:
    """Шаг 1: запросить код. Возвращает (успех, сообщение для пользователя)."""
    global _current_login
    if _current_login is not None:
        await cancel_telethon_login(_current_login)
        _current_login = None

    try:
        _current_login = await start_telethon_login(api_id, api_hash, phone)
    except PhoneNumberInvalidError:
        return False, "Некорректный номер телефона."
    except FloodWaitError as exc:
        return False, f"Telegram просит подождать {exc.seconds} секунд перед повтором."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telethon login (send_code) ошибка: %s", exc)
        return False, f"Не удалось отправить код: {exc}"
    return True, "Код отправлен в Telegram."


async def submit_code(code: str) -> tuple[str, str | None]:
    """Шаг 2: код из Telegram.

    Возвращает (статус, payload):
      "done"          — payload = готовая session string
      "need_password" — payload = None, нужен шаг 3 (вызвать submit_password)
      "error"         — payload = сообщение об ошибке для пользователя
    """
    global _current_login
    if _current_login is None:
        return "error", "Сессия входа истекла или не начата — начни заново."

    try:
        result = await submit_telethon_code(_current_login, code)
    except PhoneCodeInvalidError:
        return "error", "Неверный код."
    except PhoneCodeExpiredError:
        await cancel_telethon_login(_current_login)
        _current_login = None
        return "error", "Код истёк — начни заново."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telethon login (sign_in code) ошибка: %s", exc)
        return "error", f"Ошибка входа: {exc}"

    if isinstance(result, str):
        _current_login = None
        return "done", result
    return "need_password", None


async def submit_password(password: str) -> tuple[str, str | None]:
    """Шаг 3 (только если потребовался пароль 2FA)."""
    global _current_login
    if _current_login is None:
        return "error", "Сессия входа истекла или не начата — начни заново."

    try:
        session_string = await submit_telethon_password(_current_login, password)
    except PasswordHashInvalidError:
        return "error", "Неверный пароль 2FA."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telethon login (sign_in password) ошибка: %s", exc)
        return "error", f"Ошибка входа: {exc}"

    _current_login = None
    return "done", session_string


async def cancel() -> None:
    """Отменить незавершённый вход (например, пользователь ушёл со страницы)."""
    global _current_login
    if _current_login is not None:
        await cancel_telethon_login(_current_login)
        _current_login = None


def is_in_progress() -> bool:
    """Есть ли незавершённый вход (для рендеринга нужной формы)."""
    return _current_login is not None


def awaiting_password() -> bool:
    """Текущий шаг — ввод пароля 2FA?"""
    return _current_login is not None and _current_login.awaiting_password

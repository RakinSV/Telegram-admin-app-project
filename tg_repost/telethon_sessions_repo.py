"""CRUD и расшифровка дополнительных Telethon-сессий (F26).

Основная сессия (`TG_SESSION_STRING`) остаётся в `secrets`/`.env` как есть —
этот модуль только для ДОПОЛНИТЕЛЬНЫХ аккаунтов, добавляемых по мере роста
числа источников за пределы разумного для одной сессии (см. `db.models.
TelethonSession`). Шифрование — тем же `WEBUI_MASTER_KEY`, что и обычные
секреты (`webui/settings_store.py::ensure_master_key`), той же логикой
Fernet (`crypto.py`) — секреты этого типа тоже write-only: расшифрованное
значение возвращается только `get_decrypted_session_string()`, вызываемому
исключительно из `telegram/listener.py` при подключении клиентов, никогда
из веб-роутов.
"""

from __future__ import annotations

from tg_repost import crypto
from tg_repost.config import get_settings
from tg_repost.db.models import TelethonSession
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.webui.settings_store import ensure_master_key

logger = get_logger(__name__)


def add_session(label: str, session_string: str) -> TelethonSession:
    """Добавить дополнительную Telethon-сессию (уже сгенерированную —
    `python -m tg_repost.tools.gen_session`, тот же приём, что и для
    основной сессии в Фазе 5.1, см. план: полноценный визард телефон/код в
    браузере для КАЖДОЙ дополнительной сессии — избыточное усложнение,
    когда команда для генерации уже есть и используется для основной)."""
    if not session_string.strip():
        raise ValueError("Пустая session string не сохраняется")
    master_key = ensure_master_key()
    encrypted = crypto.encrypt(session_string.strip(), master_key)
    masked_hint = crypto.mask(session_string.strip())
    with session_scope() as session:
        row = TelethonSession(
            label=label.strip() or "без названия",
            encrypted_session_string=encrypted,
            masked_hint=masked_hint,
            is_active=True,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return row


def list_sessions() -> list[TelethonSession]:
    with session_scope() as session:
        return session.query(TelethonSession).order_by(TelethonSession.id).all()


def get_session(session_id: int) -> TelethonSession | None:
    with session_scope() as session:
        return session.get(TelethonSession, session_id)


def deactivate_session(session_id: int) -> bool:
    """Мягкое удаление (is_active=False). False, если сессия не найдена."""
    with session_scope() as session:
        row = session.get(TelethonSession, session_id)
        if row is None:
            return False
        row.is_active = False
        return True


def get_decrypted_session_string(row: TelethonSession) -> str | None:
    """Расшифровать session string для подключения Telethon-клиента
    (`telegram/listener.py`). None, если ключ недоступен или токен
    повреждён/зашифрован другим ключом — вызывающий код пропускает эту
    сессию, не роняя весь листенер из-за одного плохого аккаунта."""
    settings_key = get_settings().webui_master_key
    if not settings_key:
        logger.warning(
            "F26: WEBUI_MASTER_KEY недоступен — сессия '%s' пропущена", row.label,
        )
        return None
    try:
        return crypto.decrypt(row.encrypted_session_string, settings_key)
    except Exception as exc:  # noqa: BLE001
        # Не только `InvalidToken` (неверный ключ) — запись в БД может быть
        # повреждена на уровне самих байт (например, обрезанная строка),
        # что Fernet способен обернуть в другие исключения (`binascii.Error`
        # и т.п.). Цель функции — НИКОГДА не уронить листенер из-за одной
        # плохой сессии, поэтому ловим широко (найдено при код-ревью).
        logger.warning(
            "F26: не удалось расшифровать сессию '%s' (%s) — пропущена",
            row.label, exc,
        )
        return None


def list_active_decrypted_sessions() -> list[tuple[str, str]]:
    """(label, session_string) для всех активных дополнительных сессий,
    успешно расшифрованных — используется `telegram/listener.py` при
    подключении дополнительных клиентов (F26)."""
    result: list[tuple[str, str]] = []
    for row in list_sessions():
        if not row.is_active:
            continue
        decrypted = get_decrypted_session_string(row)
        if decrypted:
            result.append((row.label, decrypted))
    return result

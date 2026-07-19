"""Тесты `guardian/config.py::_secret_override` (аудит-фикс) — токен бота
Guardian теперь можно задать из веб-админки tg_repost (`/settings`, группа
"Guardian"), а не только правкой `.env` на сервере. Хранится зашифрованным
в таблице `secrets` процесса tg_repost (кросс-пакетное чтение, тот же
приём, что `webui/guardian_routes.py` использует в обратную сторону)."""

from __future__ import annotations

import pytest

from guardian.config import get_guardian_settings, invalidate_settings_cache
from tg_repost import crypto
from tg_repost.db.models import Secret
from tg_repost.db.session import session_scope as tg_repost_session_scope


@pytest.fixture(autouse=True)
def _isolated():
    with tg_repost_session_scope() as session:
        session.query(Secret).delete()
    invalidate_settings_cache()
    yield
    with tg_repost_session_scope() as session:
        session.query(Secret).delete()
    invalidate_settings_cache()


def test_no_master_key_falls_back_to_env_token(monkeypatch):
    """Без WEBUI_MASTER_KEY оверлей — no-op, действует .env-значение
    (conftest.py задаёт GUARDIAN_BOT_TOKEN=test)."""
    monkeypatch.delenv("WEBUI_MASTER_KEY", raising=False)
    assert get_guardian_settings().guardian_bot_token == "test"


def test_master_key_but_no_saved_secret_falls_back_to_env_token(monkeypatch):
    monkeypatch.setenv("WEBUI_MASTER_KEY", crypto.generate_key())
    assert get_guardian_settings().guardian_bot_token == "test"


def test_saved_secret_overrides_env_token(monkeypatch):
    key = crypto.generate_key()
    monkeypatch.setenv("WEBUI_MASTER_KEY", key)
    encrypted = crypto.encrypt("123456:REAL-GUARDIAN-TOKEN", key)
    with tg_repost_session_scope() as session:
        session.add(
            Secret(key="guardian_bot_token", encrypted_value=encrypted, masked_hint="••••OKEN")
        )

    assert get_guardian_settings().guardian_bot_token == "123456:REAL-GUARDIAN-TOKEN"


def test_wrong_master_key_falls_back_to_env_token_not_crash(monkeypatch):
    """Токен зашифрован ОДНИМ ключом, WEBUI_MASTER_KEY в окружении — другой
    (например .env потерял/перезаписал ключ) — не должно падать, откат на
    .env-значение (то же поведение, что `tg_repost.config._apply_secret_overrides`
    для собственных секретов)."""
    real_key = crypto.generate_key()
    other_key = crypto.generate_key()
    encrypted = crypto.encrypt("some-token", real_key)
    with tg_repost_session_scope() as session:
        session.add(
            Secret(key="guardian_bot_token", encrypted_value=encrypted, masked_hint="••••oken")
        )
    monkeypatch.setenv("WEBUI_MASTER_KEY", other_key)

    assert get_guardian_settings().guardian_bot_token == "test"


def test_reads_fresh_on_every_call_not_cached(monkeypatch):
    """Кросс-процессная свежесть (см. docstring `get_guardian_settings`) —
    сохранение секрета ПОСЛЕ первого чтения должно быть видно на следующем
    вызове без явной инвалидации кэша (в отличие от `_env_settings`,
    `_secret_override` не декорирован `@lru_cache`)."""
    key = crypto.generate_key()
    monkeypatch.setenv("WEBUI_MASTER_KEY", key)
    assert get_guardian_settings().guardian_bot_token == "test"

    encrypted = crypto.encrypt("later-token", key)
    with tg_repost_session_scope() as session:
        session.add(
            Secret(key="guardian_bot_token", encrypted_value=encrypted, masked_hint="••••oken")
        )

    assert get_guardian_settings().guardian_bot_token == "later-token"

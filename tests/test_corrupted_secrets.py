"""Повреждённая запись секрета не должна ронять систему.

Найдено при написании тестов реестра ботов (F75): все места расшифровки ловили
только `InvalidToken` — «зашифровано другим ключом». Но запись в БД может быть
испорчена НА УРОВНЕ БАЙТ: обрезанная строка, чужие символы, ручная правка
базы. Тогда Fernet бросает `binascii.Error` или `UnicodeEncodeError`, и они
проходили мимо перехвата.

Цена по каждому месту разная, и именно она определяет, почему перехват
широкий: оверлей настроек читается на импорте почти каждым модулем, реестр
ботов — при старте процесса, а способ приёма оплаты — на странице владельца.
"""

from __future__ import annotations

import pytest

from tg_repost import crypto
from tg_repost.db.models import Secret
from tg_repost.db.session import session_scope

# Не base64 и не ASCII — ровно то, чего прежний перехват не ожидал.
GARBAGE = "не-шифротекст-вовсе"


@pytest.fixture(autouse=True)
def _clean():
    with session_scope() as session:
        session.query(Secret).delete()
    yield
    with session_scope() as session:
        session.query(Secret).delete()


def test_settings_overlay_survives_a_corrupted_secret(monkeypatch):
    """Исключение отсюда не «портит один секрет», а не даёт подняться всей
    системе: оверлей выполняется внутри `get_settings()`."""
    from tg_repost.config import Settings, _apply_secret_overrides

    with session_scope() as session:
        session.add(Secret(
            key="openai_api_key", encrypted_value=GARBAGE, masked_hint="••••!!!!",
        ))

    settings = Settings(webui_master_key=crypto.generate_key())
    before = settings.openai_api_key

    _apply_secret_overrides(settings)

    assert settings.openai_api_key == before, "значение из .env должно остаться"


def test_guardian_falls_back_to_env_on_a_corrupted_token(monkeypatch):
    from guardian.config import get_guardian_settings, invalidate_settings_cache

    monkeypatch.setenv("WEBUI_MASTER_KEY", crypto.generate_key())
    with session_scope() as session:
        session.add(Secret(
            key="guardian_bot_token", encrypted_value=GARBAGE, masked_hint="••••!!!!",
        ))
    invalidate_settings_cache()
    try:
        assert get_guardian_settings().guardian_bot_token == "test"
    finally:
        invalidate_settings_cache()


def test_crypto_rail_reports_a_corrupted_key_as_a_rail_problem():
    """Владелец должен прочитать объяснение на странице приёма оплаты, а не
    получить 500: вызывающий код ловит `InvalidRail` и только его."""
    from tg_repost import crypto_rails_repo
    from tg_repost.db.models import CryptoRail

    with session_scope() as session:
        row = CryptoRail(
            name="Кошелёк", kind="ton_direct", credential_encrypted=GARBAGE,
            public_address="EQAtest",
        )
        session.add(row)
        session.flush()
        rail_id = row.id

    with pytest.raises(crypto_rails_repo.InvalidRail):
        crypto_rails_repo.build(rail_id)

    with session_scope() as session:
        session.query(CryptoRail).delete()

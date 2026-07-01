"""Тесты CRUD и расшифровки дополнительных Telethon-сессий (F26)."""

import os

import pytest

from tg_repost import telethon_sessions_repo
from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import AppSetting, Secret, TelethonSession
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Изоляция — тот же паттерн, что и test_settings_store.py: `add_session`
    вызывает `ensure_master_key()`, который пишет `WEBUI_MASTER_KEY` в `.env`
    относительно CWD."""
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
        session.query(TelethonSession).delete()
    os.environ.pop("WEBUI_MASTER_KEY", None)
    invalidate_settings_cache()
    yield


def test_add_session_creates_row():
    row = telethon_sessions_repo.add_session("account-2", "1BVtsOK...fake-session-string")
    assert row.label == "account-2"
    assert row.is_active is True
    assert row.encrypted_session_string != "1BVtsOK...fake-session-string"


def test_add_session_rejects_empty_string():
    with pytest.raises(ValueError):
        telethon_sessions_repo.add_session("account-2", "   ")


def test_add_session_default_label_when_blank():
    row = telethon_sessions_repo.add_session("  ", "session-string-value")
    assert row.label == "без названия"


def test_list_sessions_ordered_by_id():
    telethon_sessions_repo.add_session("first", "session-a")
    telethon_sessions_repo.add_session("second", "session-b")
    sessions = telethon_sessions_repo.list_sessions()
    assert [s.label for s in sessions] == ["first", "second"]


def test_get_session_returns_none_for_missing():
    assert telethon_sessions_repo.get_session(999999) is None


def test_deactivate_session():
    row = telethon_sessions_repo.add_session("account-2", "session-value")
    assert telethon_sessions_repo.deactivate_session(row.id) is True
    assert telethon_sessions_repo.get_session(row.id).is_active is False
    assert telethon_sessions_repo.deactivate_session(999999) is False


def test_get_decrypted_session_string_round_trip():
    row = telethon_sessions_repo.add_session("account-2", "the-real-session-string")
    decrypted = telethon_sessions_repo.get_decrypted_session_string(row)
    assert decrypted == "the-real-session-string"


def test_get_decrypted_session_string_none_when_master_key_missing(tmp_path):
    row = telethon_sessions_repo.add_session("account-2", "the-real-session-string")
    # Симулируем "ключ потерян, БД осталась" — `add_session` уже записал
    # WEBUI_MASTER_KEY в физический .env (через ensure_master_key), поэтому
    # мало убрать переменную из os.environ — pydantic-settings всё равно
    # прочитает её обратно из файла на диске. Нужно удалить сам файл.
    (tmp_path / ".env").unlink()
    os.environ.pop("WEBUI_MASTER_KEY", None)
    invalidate_settings_cache()
    assert get_settings().webui_master_key == ""
    assert telethon_sessions_repo.get_decrypted_session_string(row) is None


def test_get_decrypted_session_string_none_on_wrong_key():
    row = telethon_sessions_repo.add_session("account-2", "the-real-session-string")
    # "Сменить" ключ вручную, минуя нормальный флоу — токен станет невалидным
    # для текущего WEBUI_MASTER_KEY.
    from tg_repost import crypto
    with session_scope() as session:
        db_row = session.get(TelethonSession, row.id)
        db_row.encrypted_session_string = crypto.encrypt("value", crypto.generate_key())
    # Перечитать строку заново — `row` в памяти всё ещё держит СТАРОЕ
    # значение `encrypted_session_string` (expire_on_commit=False, а
    # мутация выше шла через ДРУГОЙ ORM-объект в новой сессии).
    fresh = telethon_sessions_repo.get_session(row.id)
    assert telethon_sessions_repo.get_decrypted_session_string(fresh) is None


def test_list_active_decrypted_sessions_skips_inactive():
    active = telethon_sessions_repo.add_session("active-one", "session-a")
    inactive = telethon_sessions_repo.add_session("inactive-one", "session-b")
    telethon_sessions_repo.deactivate_session(inactive.id)

    result = telethon_sessions_repo.list_active_decrypted_sessions()

    assert result == [(active.label, "session-a")]


def test_list_active_decrypted_sessions_empty_when_none_added():
    assert telethon_sessions_repo.list_active_decrypted_sessions() == []

"""Тесты слоя записи настроек/секретов веб-админки (F23, Фаза 5.1)."""

import os

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import AppSetting, Secret, TelethonSession
from tg_repost.db.session import session_scope
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Изоляция для каждого теста этого файла:

    1. CWD переключается на временный каталог — `ensure_master_key()`/
       `crypto.append_env_var()` пишут `WEBUI_MASTER_KEY` в `./.env` ОТНОСИТЕЛЬНО
       CWD по дизайну (так и должно быть в проде). Без этой изоляции тест,
       вызывающий `set_secret()`, реально записал бы ключ в `.env` корня
       проекта — что и произошло один раз при первой версии этого файла.
    2. Таблицы `app_settings`/`secrets` чистятся — общий sqlite-engine на весь
       pytest-процесс (см. tests/conftest.py).
    """
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
        session.query(TelethonSession).delete()
    os.environ.pop("WEBUI_MASTER_KEY", None)
    invalidate_settings_cache()
    yield


def test_save_setting_int_round_trip():
    field = next(
        f for g in settings_store.SETTINGS_GROUPS for f in g.fields if f.name == "ad_every_nth_post"
    )
    settings_store.save_setting("ad_every_nth_post", 9, "int")
    assert settings_store.effective_value(field) == 9
    assert get_settings().ad_every_nth_post == 9


def test_save_setting_csv_list_round_trip():
    settings_store.save_setting("filter_stop_words", ["spam", "scam"], "csv_list")
    assert get_settings().filter_stop_words == ["spam", "scam"]


def test_save_setting_bool_round_trip():
    settings_store.save_setting("auto_post_enabled", True, "bool")
    assert get_settings().auto_post_enabled is True


def test_save_setting_overwrites_existing():
    settings_store.save_setting("ad_every_nth_post", 3, "int")
    settings_store.save_setting("ad_every_nth_post", 7, "int")
    assert get_settings().ad_every_nth_post == 7
    with session_scope() as session:
        assert session.query(AppSetting).filter(AppSetting.key == "ad_every_nth_post").count() == 1


def test_save_setting_rejects_unknown_key():
    with pytest.raises(ValueError):
        settings_store.save_setting("totally_not_a_field", 1, "int")


def test_save_setting_rejects_secret_field():
    with pytest.raises(ValueError):
        settings_store.save_setting("openai_api_key", "sk-x", "str")


def test_set_secret_and_list_status_db_source():
    settings_store.set_secret("openai_api_key", "sk-test-abcd1234")
    assert get_settings().openai_api_key == "sk-test-abcd1234"

    statuses = {s.key: s for s in settings_store.list_secret_status()}
    status = statuses["openai_api_key"]
    assert status.is_set is True
    assert status.source == "db"
    assert status.masked_hint.endswith("1234")
    assert "sk-test-abcd1234" not in status.masked_hint


def test_proxy_host_port_are_plain_settings_not_secrets():
    field = next(
        f for g in settings_store.SETTINGS_GROUPS for f in g.fields if f.name == "mtproto_proxy_host"
    )
    settings_store.save_setting("mtproto_proxy_host", "1.2.3.4", "str")
    assert settings_store.effective_value(field) == "1.2.3.4"
    assert get_settings().mtproto_proxy_host == "1.2.3.4"


def test_mtproto_proxy_secret_is_a_write_only_secret():
    with pytest.raises(ValueError):
        settings_store.save_setting("mtproto_proxy_secret", "deadbeef", "str")
    settings_store.set_secret("mtproto_proxy_secret", "deadbeefdeadbeefdeadbeefdeadbeef")
    assert get_settings().mtproto_proxy_secret == "deadbeefdeadbeefdeadbeefdeadbeef"
    statuses = {s.key: s for s in settings_store.list_secret_status()}
    assert statuses["mtproto_proxy_secret"].is_set is True
    assert "deadbeef" not in statuses["mtproto_proxy_secret"].masked_hint[:-4]


def test_bot_api_proxy_url_is_a_write_only_secret():
    settings_store.set_secret("bot_api_proxy_url", "socks5://user:pass@1.2.3.4:1080")
    assert get_settings().bot_api_proxy_url == "socks5://user:pass@1.2.3.4:1080"


def test_set_secret_rejects_unknown_key():
    with pytest.raises(ValueError):
        settings_store.set_secret("not_a_secret_field", "value")


def test_set_secret_rejects_empty_value():
    with pytest.raises(ValueError):
        settings_store.set_secret("openai_api_key", "")


def test_list_secret_status_unset_by_default():
    statuses = {s.key: s for s in settings_store.list_secret_status()}
    assert statuses["brave_api_key"].is_set is False
    assert statuses["brave_api_key"].source == "unset"


def test_list_secret_status_env_source():
    os.environ["BRAVE_API_KEY"] = "env-only-key-9999"
    try:
        invalidate_settings_cache()
        statuses = {s.key: s for s in settings_store.list_secret_status()}
        status = statuses["brave_api_key"]
        assert status.is_set is True
        assert status.source == "env"
        assert status.masked_hint.endswith("9999")
    finally:
        os.environ.pop("BRAVE_API_KEY", None)
        invalidate_settings_cache()


def test_ensure_master_key_generates_once_and_persists(tmp_path):
    # tmp_path здесь — тот же каталог, что и в autouse-фикстуре (pytest
    # переиспользует один tmp_path на тест при множественных запросах).
    env_path = tmp_path / ".env"
    key1 = settings_store.ensure_master_key()
    assert env_path.exists()
    assert "WEBUI_MASTER_KEY=" in env_path.read_text(encoding="utf-8")

    # Повторный вызов не генерирует новый ключ — возвращает уже заданный.
    key2 = settings_store.ensure_master_key()
    assert key1 == key2


def test_ensure_master_key_raises_if_secrets_exist_without_key():
    # Кладём секрет напрямую (минуя set_secret) — симулируем "ключ потерян,
    # БД осталась".
    with session_scope() as session:
        session.add(Secret(key="openai_api_key", encrypted_value="irrelevant", masked_hint="••••0000"))
    with pytest.raises(RuntimeError):
        settings_store.ensure_master_key()


def test_ensure_master_key_raises_if_telethon_sessions_exist_without_key():
    """F26: дополнительные Telethon-сессии шифруются тем же ключом — та же
    защита от "ключ потерян, БД осталась", что и для обычных секретов."""
    with session_scope() as session:
        session.add(TelethonSession(
            label="account-2", encrypted_session_string="irrelevant", masked_hint="••••0000",
        ))
    with pytest.raises(RuntimeError):
        settings_store.ensure_master_key()

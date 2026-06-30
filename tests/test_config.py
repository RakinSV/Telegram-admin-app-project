"""Тесты конфигурации (F23, Фаза 5): мягкая обработка пустых .env-плейсхолдеров."""

from tg_repost.config import Settings


def test_blank_tg_api_id_does_not_crash(monkeypatch):
    # Ровно то, что в .env.example: "TG_API_ID=" (пусто, плейсхолдер).
    monkeypatch.setenv("TG_API_ID", "")
    monkeypatch.setenv("TG_OWNER_USER_ID", "")
    settings = Settings()
    assert settings.tg_api_id == 0
    assert settings.tg_owner_user_id == 0


def test_blank_tg_api_id_means_not_minimally_configured(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "")
    monkeypatch.setenv("TG_OWNER_USER_ID", "")
    settings = Settings()
    assert settings.is_minimally_configured is False


def test_real_tg_api_id_parses_normally(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "12345")
    settings = Settings()
    assert settings.tg_api_id == 12345


def test_settings_constructs_with_completely_empty_env(monkeypatch):
    # Симулируем процесс без .env вообще — ни одна переменная не задана.
    for key in (
        "TG_API_ID", "TG_API_HASH", "TG_SESSION_STRING", "TG_BOT_TOKEN",
        "TG_OWNER_USER_ID", "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.is_minimally_configured is False

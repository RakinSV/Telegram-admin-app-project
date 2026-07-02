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


def test_blank_filter_stop_words_does_not_crash(monkeypatch):
    # Регрессия: ровно то, что в .env.example ("FILTER_STOP_WORDS=", пусто) —
    # без NoDecode pydantic-settings пытался json.loads("") ДО field_validator
    # и падал с SettingsError. Впервые найдено при первом реальном запуске
    # через Docker (env_file → os.environ, тот же путь, что monkeypatch.setenv
    # эмулирует здесь) — юнит-тесты раньше никогда не задавали эту переменную.
    monkeypatch.setenv("FILTER_STOP_WORDS", "")
    settings = Settings()
    assert settings.filter_stop_words == []


def test_csv_filter_stop_words_parses_without_crash(monkeypatch):
    monkeypatch.setenv("FILTER_STOP_WORDS", "спам, Реклама , крипта")
    settings = Settings()
    assert settings.filter_stop_words == ["спам", "реклама", "крипта"]


def test_csv_posting_slots_parses_without_crash(monkeypatch):
    # Ровно то, что в .env.example: "POSTING_SLOTS=10:00,14:00,19:00" —
    # не валидный JSON, тот же класс бага, что и filter_stop_words выше.
    monkeypatch.setenv("POSTING_SLOTS", "10:00,14:00,19:00")
    settings = Settings()
    assert settings.posting_slots == ["10:00", "14:00", "19:00"]

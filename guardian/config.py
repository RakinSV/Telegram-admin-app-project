"""Конфигурация Guardian через pydantic-settings.

Отдельный класс от `tg_repost.config.Settings` (Guardian — независимый
сервис, свой процесс, своя БД по умолчанию) — см. guardian/GUARDIAN.md.
Читает тот же файл `.env`, что и репост-бот (общий docker-compose), но
только свои `GUARDIAN_*`/специфичные для Guardian поля — `extra="ignore"`
не даёт полям репост-бота мешать валидации.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GuardianSettings(BaseSettings):
    """Типизированные настройки Guardian."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Идентичность бота и чата ---
    guardian_bot_token: str = Field("", alias="GUARDIAN_BOT_TOKEN")
    guardian_group_id: int = Field(0, alias="GUARDIAN_GROUP_ID")
    guardian_log_channel_id: int = Field(0, alias="GUARDIAN_LOG_CHANNEL_ID")

    # --- БД (отдельная от репост-бота — независимые alembic-цепочки) ---
    guardian_database_url: str = Field(
        "sqlite:///guardian.db", alias="GUARDIAN_DATABASE_URL"
    )

    # --- Верификация (G01) ---
    captcha_timeout_minutes: int = Field(5, alias="CAPTCHA_TIMEOUT_MINUTES")
    captcha_type: str = Field("math", alias="CAPTCHA_TYPE")  # math | button | question

    # --- Спам-фильтр (G03/G09/G10) ---
    spam_mode: str = Field("keywords", alias="SPAM_MODE")  # keywords | ai | hybrid
    ai_spam_confidence_threshold: float = Field(
        0.8, alias="AI_SPAM_CONFIDENCE_THRESHOLD"
    )

    # --- Варны (G05) ---
    warn_threshold_mute: int = Field(2, alias="WARN_THRESHOLD_MUTE")
    warn_threshold_kick: int = Field(3, alias="WARN_THRESHOLD_KICK")
    warn_threshold_ban: int = Field(4, alias="WARN_THRESHOLD_BAN")
    warn_ttl_days: int = Field(30, alias="WARN_TTL_DAYS")
    mute_duration_hours: int = Field(1, alias="MUTE_DURATION_HOURS")

    # --- Антифлуд (G06) ---
    flood_max_messages: int = Field(5, alias="FLOOD_MAX_MESSAGES")
    flood_window_seconds: int = Field(10, alias="FLOOD_WINDOW_SECONDS")
    allow_forwards: bool = Field(True, alias="ALLOW_FORWARDS")

    # --- Антирейд (G14, Фаза G3) ---
    raid_join_threshold: int = Field(5, alias="RAID_JOIN_THRESHOLD")
    raid_join_window_minutes: int = Field(2, alias="RAID_JOIN_WINDOW_MINUTES")
    raid_cooldown_minutes: int = Field(10, alias="RAID_COOLDOWN_MINUTES")

    # --- Trusted (G12) ---
    auto_trust_after_days: int = Field(30, alias="AUTO_TRUST_AFTER_DAYS")
    # Юзернейм или числовой id репост-бота — автоматически идёт в trusted при
    # старте Guardian (см. bot.py), чтобы его посты со ссылками не удалялись
    # спам-фильтром (см. GUARDIAN.md "Интеграция с репост-ботом").
    repost_bot_id: str = Field("", alias="REPOST_BOT_ID")

    # --- Рерайт/AI (переиспользует те же ключи, что и репост-бот, G09) ---
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")

    @field_validator("guardian_group_id", "guardian_log_channel_id", mode="before")
    @classmethod
    def _blank_int_to_zero(cls, value: object) -> object:
        """Пустая строка (плейсхолдер из .env.example) не должна валить
        GuardianSettings() — тот же паттерн, что и в tg_repost.config."""
        if value == "":
            return 0
        return value

    @property
    def is_configured(self) -> bool:
        """Достаточно ли секретов, чтобы запускать Guardian."""
        return bool(self.guardian_bot_token and self.guardian_group_id)


@lru_cache
def get_guardian_settings() -> GuardianSettings:
    return GuardianSettings()  # type: ignore[call-arg]


def invalidate_settings_cache() -> None:
    """Сбросить `lru_cache` — нужно после смены `os.environ` в тестах, иначе
    следующий `get_guardian_settings()` вернёт закэшированный старый объект."""
    get_guardian_settings.cache_clear()

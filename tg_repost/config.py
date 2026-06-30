"""Конфигурация приложения через pydantic-settings.

Все параметры читаются из `.env` (см. `.env.example`). Никаких голых
`os.environ` по коду — только этот объект `settings`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Типизированные настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram: Telethon (юзер-сессия для чтения) ---
    tg_api_id: int = Field(..., alias="TG_API_ID")
    tg_api_hash: str = Field(..., alias="TG_API_HASH")
    tg_session_string: str = Field("", alias="TG_SESSION_STRING")

    # --- Telegram: Bot API (постинг и модерация) ---
    tg_bot_token: str = Field(..., alias="TG_BOT_TOKEN")
    tg_owner_user_id: int = Field(..., alias="TG_OWNER_USER_ID")
    tg_target_chat_id: int = Field(..., alias="TG_TARGET_CHAT_ID")

    # --- Рерайт (OpenAI-совместимое API) ---
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")

    # --- БД ---
    database_url: str = Field("sqlite:///tg_repost.db", alias="DATABASE_URL")

    # --- Фильтрация (F03) ---
    filter_stop_words: list[str] = Field(default_factory=list, alias="FILTER_STOP_WORDS")
    filter_required_words: list[str] = Field(default_factory=list, alias="FILTER_REQUIRED_WORDS")

    # --- Поведение пайплайна ---
    pipeline_interval_seconds: int = Field(30, alias="PIPELINE_INTERVAL_SECONDS")
    auto_post_enabled: bool = Field(False, alias="AUTO_POST_ENABLED")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # --- F17: антибан-механики ---
    listener_min_delay_seconds: float = Field(0.5, alias="LISTENER_MIN_DELAY_SECONDS")
    listener_max_delay_seconds: float = Field(3.0, alias="LISTENER_MAX_DELAY_SECONDS")
    max_reads_per_hour: int = Field(200, alias="MAX_READS_PER_HOUR")

    # --- F11: авто-постинг по расписанию (слоты) ---
    scheduled_posting_enabled: bool = Field(False, alias="SCHEDULED_POSTING_ENABLED")
    # Временные слоты публикации в формате HH:MM, через запятую.
    posting_slots: list[str] = Field(default_factory=list, alias="POSTING_SLOTS")
    # Сколько одобренных постов выпускать за один слот.
    posting_batch_per_slot: int = Field(1, alias="POSTING_BATCH_PER_SLOT")

    # --- F13: семантический дубль-чек (эмбеддинги) ---
    semantic_dedup_enabled: bool = Field(False, alias="SEMANTIC_DEDUP_ENABLED")
    openai_embedding_model: str = Field(
        "text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    semantic_similarity_threshold: float = Field(
        0.92, alias="SEMANTIC_SIMILARITY_THRESHOLD"
    )
    dedup_window_days: int = Field(3, alias="DEDUP_WINDOW_DAYS")

    # --- F14: статистика ---
    stats_enabled: bool = Field(False, alias="STATS_ENABLED")
    stats_interval_minutes: int = Field(60, alias="STATS_INTERVAL_MINUTES")
    stats_window_days: int = Field(7, alias="STATS_WINDOW_DAYS")

    # --- F15: стиль-профили рерайта ---
    # Профиль по умолчанию, если у источника не задан свой (имя файла промпта).
    default_style_profile: str = Field("default", alias="DEFAULT_STYLE_PROFILE")

    # --- F16: поиск дополнительных источников (Brave Search) ---
    enable_source_enrichment: bool = Field(False, alias="ENABLE_SOURCE_ENRICHMENT")
    brave_api_key: str = Field("", alias="BRAVE_API_KEY")
    brave_search_url: str = Field(
        "https://api.search.brave.com/res/v1/web/search", alias="BRAVE_SEARCH_URL"
    )
    # Сколько результатов запрашивать у Brave и сколько максимум вставлять в пост.
    enrichment_max_results: int = Field(8, alias="ENRICHMENT_MAX_RESULTS")
    enrichment_max_sources: int = Field(3, alias="ENRICHMENT_MAX_SOURCES")

    @field_validator("filter_stop_words", "filter_required_words", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> list[str]:
        """Разбить строку из .env вида "a, b, c" в список нормализованных слов."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [w.strip().lower() for w in value.split(",") if w.strip()]
        if isinstance(value, list):
            return [str(w).strip().lower() for w in value if str(w).strip()]
        return []

    @field_validator("posting_slots", mode="before")
    @classmethod
    def _split_slots(cls, value: object) -> list[str]:
        """Разбить слоты "10:00, 14:00" в список без приведения регистра."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        if isinstance(value, list):
            return [str(s).strip() for s in value if str(s).strip()]
        return []

    @property
    def media_dir(self) -> str:
        """Каталог для скачанных медиа источников."""
        return "media"


@lru_cache
def get_settings() -> Settings:
    """Кэшированный синглтон настроек."""
    return Settings()  # type: ignore[call-arg]

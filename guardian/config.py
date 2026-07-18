"""Конфигурация Guardian через pydantic-settings.

Отдельный класс от `tg_repost.config.Settings` (Guardian — независимый
сервис, свой процесс, своя БД по умолчанию) — см. guardian/GUARDIAN.md.
Читает тот же файл `.env`, что и репост-бот (общий docker-compose), но
только свои `GUARDIAN_*`/специфичные для Guardian поля — `extra="ignore"`
не даёт полям репост-бота мешать валидации.

С добавлением веб-админки (см. `guardian/settings_store.py`) часть полей
живёт с оверлеем поверх .env — значениями из таблицы `bot_config`
(изменяются командами Guardian ИЛИ веб-панелью tg_repost). В отличие от
`tg_repost.config.get_settings()` (см. комментарий там про `@lru_cache` +
`invalidate_settings_cache()`), здесь оверлей пере-читается из БД НА КАЖДЫЙ
вызов, не кэшируется целиком: Guardian и веб-админка tg_repost — РАЗНЫЕ ОС-
процессы (разные контейнеры), поэтому явная инвалидация кэша из процесса
веб-панели никак не достучится до процесса Guardian. Свежее чтение из
SQLite — единственный вариант, одинаково корректный независимо от того, кто
записал изменение."""

from __future__ import annotations

import json
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
    # F28 (аудит ведения групп, 2026-07-17): раньше Guardian защищал РОВНО
    # одну группу через это поле. Теперь список чатов приходит из
    # `protected_chat_ids` (galочка на TargetGroup в веб-админке tg_repost,
    # см. `webui/crud_routes.py::targets_toggle_guardian` и
    # `guardian/settings_store.py::sync_protected_chat_ids`). Поле оставлено
    # в .env/классе ТОЛЬКО для одноразовой миграции данных при первом деплое
    # этой фичи (см. `tg_repost/db/migrations/versions/
    # 0013_target_group_use_guardian.py`) — хендлеры/антирейд/джобы больше
    # его не читают напрямую.
    guardian_group_id: int = Field(0, alias="GUARDIAN_GROUP_ID")
    guardian_log_channel_id: int = Field(0, alias="GUARDIAN_LOG_CHANNEL_ID")
    # Список chat_id защищаемых групп — единственный источник истины для
    # join.py/messages.py/raid_detector.py/bot.py-джоб. Пустой список —
    # штатное состояние (ни одна цель не отмечена галочкой), не ошибка.
    # ТОЛЬКО оверлей из bot_config (см. _db_overrides) — нет смысла задавать
    # через .env, синхронизируется исключительно из tg_repost.
    protected_chat_ids: list[int] = Field(default_factory=list)

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

    # --- Анализ профиля нового участника (G15) ---
    # Сумма сигналов (нет username +1, нет фото +1, новый аккаунт +1, био с
    # ключевыми словами +2) >= порога -> усиленная (math) капча вместо
    # сконфигурированного CAPTCHA_TYPE. НЕ используется для бана/автоотказа —
    # см. GUARDIAN_FEATURES.md G15: "не банить только за профиль".
    profile_suspicion_threshold: int = Field(3, alias="PROFILE_SUSPICION_THRESHOLD")

    # --- Тихие часы / режимы строгости (G16) ---
    # strict — все нарушения (в т.ч. ссылки) удаляются с варном (поведение
    # по умолчанию, как до G16). soft — стоп-слова работают как раньше, но
    # ссылки вне whitelist только логируются, не удаляются (см.
    # handlers/messages.py). Переключается вручную (/mode) или по расписанию.
    strict_mode: bool = Field(True, alias="STRICT_MODE")
    quiet_hours_enabled: bool = Field(False, alias="QUIET_HOURS_ENABLED")
    quiet_hours_start_hour: int = Field(22, alias="QUIET_HOURS_START_HOUR")  # UTC, 0-23
    quiet_hours_end_hour: int = Field(8, alias="QUIET_HOURS_END_HOUR")  # UTC, 0-23

    # --- Рерайт/AI (переиспользует те же ключи, что и репост-бот, G09) ---
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")

    # --- Прокси для Bot API ---
    # SOCKS5, не MTProto — Bot API ходит по HTTPS (см. bot.py::main про
    # AiohttpSession). Намеренно ТОЛЬКО .env, не в SETTINGS_GROUPS/
    # bot_config (см. settings_store.py docstring про "живой оверлей без
    # перезапуска") — Bot() строится один раз при старте процесса, как и
    # guardian_bot_token; веб-форма для этого поля выглядела бы так, будто
    # применяется сразу, а на деле требует перезапуска Guardian.
    bot_api_proxy_url: str = Field("", alias="GUARDIAN_BOT_API_PROXY_URL")

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
        """Достаточно ли секретов, чтобы запускать Guardian.

        F28: `guardian_group_id` больше НЕ обязателен — Guardian может
        стартовать вообще без единой отмеченной галочкой цели (штатный
        no-op, а не ошибка конфигурации) и получить первую защищаемую
        группу позже через `/targets` без рестарта процесса. Токен бота —
        единственное, что действительно нужно для подключения к Bot API."""
        return bool(self.guardian_bot_token)


@lru_cache
def _env_settings() -> GuardianSettings:
    """Только .env-часть, кэшируется — .env не меняется в рантайме процесса
    (в отличие от `bot_config`, см. docstring модуля)."""
    return GuardianSettings()  # type: ignore[call-arg]


def _db_overrides() -> dict[str, object]:
    """Оверлей значений `bot_config` поверх .env-дефолтов — ТОЛЬКО для ключей,
    совпадающих с полями `GuardianSettings` (в `bot_config` есть и другие
    записи не про настройки — `captcha_questions`/`allowed_domains`, они
    сюда не попадают, т.к. таких полей у `GuardianSettings` нет). Любая
    ошибка (БД недоступна/таблицы ещё нет) не должна ронять процесс —
    работаем на чистых .env-дефолтах, тот же приём что и в `tg_repost.config`."""
    try:
        from guardian.db.models import BotConfig
        from guardian.db.session import session_scope

        with session_scope() as session:
            rows = [(r.key, r.value) for r in session.query(BotConfig).all()]
    except Exception:  # noqa: BLE001
        return {}

    base = _env_settings()
    overrides: dict[str, object] = {}
    for key, raw_value in rows:
        if key not in base.model_fields:
            continue
        try:
            overrides[key] = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            continue
    return overrides


def get_guardian_settings() -> GuardianSettings:
    """Настройки: .env-дефолты + свежий оверлей из `bot_config` на каждый
    вызов (см. docstring модуля про кросс-процессную свежесть). `model_copy`
    не перевалидирует поля — запись в БД ожидается уже правильно типизированной
    (см. `guardian/settings_store.py::save_setting`), так же как `bot_config.
    value` — JSON-сериализованное значение того же типа, что и .env-поле."""
    overrides = _db_overrides()
    base = _env_settings()
    return base.model_copy(update=overrides) if overrides else base


def invalidate_settings_cache() -> None:
    """Сбросить `lru_cache` .env-части — нужно после смены `os.environ` в
    тестах, иначе следующий вызов вернёт закэшированный старый объект.
    Оверлей `bot_config` в кэше не участвует (см. `_db_overrides`), сбрасывать
    нечего."""
    _env_settings.cache_clear()

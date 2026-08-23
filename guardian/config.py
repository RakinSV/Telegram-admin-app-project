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
import os
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

    # --- Обязательная подписка на канал (F61) ---
    # Участник не может писать в группе, пока не подписан на связанный канал.
    # Прямая воронка «участник группы → подписчик канала».
    # ВЫКЛЮЧЕНО по умолчанию: это барьер на входе в общение, и включать его
    # надо осознанно. Администраторы группы освобождены — владелец, забывший
    # подписаться на собственный канал, не должен упереться в свой же запрет.
    force_subscribe_enabled: bool = Field(False, alias="FORCE_SUBSCRIBE_ENABLED")
    # @username канала или его chat_id. Бот обязан быть админом В КАНАЛЕ,
    # иначе проверка не отработает — и тогда сообщения ПРОПУСКАЮТСЯ
    # (fail-open), а не блокируются.
    force_subscribe_channel: str = Field("", alias="FORCE_SUBSCRIBE_CHANNEL")

    # --- Петля обучения антиспама (F57) ---
    # Спорные вердикты AI-фильтра уходят в лог-канал с кнопками «спам / не
    # спам», а размеченные примеры подмешиваются в промпт few-shot.
    # НИЧЕГО НЕ УДАЛЯЕТ И НЕ БАНИТ: поведение модерации не меняется, добавлено
    # только наблюдение. Раньше ошибка фильтра исчезала бесследно, и точность
    # не росла никогда.
    spam_learning_enabled: bool = Field(False, alias="SPAM_LEARNING_ENABLED")
    # Сколько примеров КАЖДОЙ метки уходит в промпт. Поровну спама и
    # не-спама: перекос в сторону спама научит модель называть спамом всё
    # подряд, то есть сделает фильтр агрессивнее, а не точнее.
    spam_learning_examples_per_label: int = Field(
        5, alias="SPAM_LEARNING_EXAMPLES_PER_LABEL"
    )

    # --- Premium как сигнал доверия (F52) ---
    # Поле `is_premium` приходит в апдейтах бесплатно и не требует ни одного
    # лишнего запроса к Bot API — в отличие от фото и био выше. Уменьшает
    # score, то есть работает В ПОЛЬЗУ участника: у скам-ботов платной
    # подписки обычно нет, потому что она стоит денег и привязана к аккаунту.
    #
    # ПО УМОЛЧАНИЮ ВЫКЛЮЧЕНО. Это ослабление защиты, а Premium ПОКУПАЕТСЯ:
    # мотивированный спамер оплатит подписку и обойдёт смягчение. Поэтому
    # сигнал в общий скоринг, а НЕ пропуск капчи — включать осознанно.
    premium_trust_enabled: bool = Field(False, alias="PREMIUM_TRUST_ENABLED")
    # Насколько смягчаем. 2 — столько же, сколько даёт подозрительная био,
    # то есть Premium гасит ровно один сильный негативный сигнал, а не все.
    premium_trust_bonus: int = Field(2, alias="PREMIUM_TRUST_BONUS")

    # --- Тихие часы / режимы строгости (G16) ---
    # strict — все нарушения (в т.ч. ссылки) удаляются с варном (поведение
    # по умолчанию, как до G16). soft — стоп-слова работают как раньше, но
    # ссылки вне whitelist только логируются, не удаляются (см.
    # handlers/messages.py). Переключается вручную (/mode) или по расписанию.
    strict_mode: bool = Field(True, alias="STRICT_MODE")
    quiet_hours_enabled: bool = Field(False, alias="QUIET_HOURS_ENABLED")
    quiet_hours_start_hour: int = Field(22, alias="QUIET_HOURS_START_HOUR")  # UTC, 0-23
    quiet_hours_end_hour: int = Field(8, alias="QUIET_HOURS_END_HOUR")  # UTC, 0-23

    # --- Служебная гигиена группы (F48) ---
    # Чистка служебных сообщений: в активной группе «вошёл/вышел» забивают
    # ленту сильнее самого общения.
    delete_join_leave_messages: bool = Field(False, alias="DELETE_JOIN_LEAVE_MESSAGES")
    # Уведомление о закрепе — отдельной настройкой: иногда это единственный
    # способ участнику узнать о закреплённом, и чистить его не всегда верно.
    delete_pin_notifications: bool = Field(False, alias="DELETE_PIN_NOTIFICATIONS")
    # Прочая служебка: смена названия/аватара, видеочаты.
    delete_service_messages: bool = Field(False, alias="DELETE_SERVICE_MESSAGES")

    # Ночной режим: на ночь чат закрывается на запись, утром открывается.
    # ВНИМАНИЕ: Telegram не хранит прежние права чата — при открытии
    # выставляется стандартный набор (писать/медиа/опросы/приглашать), а не
    # «как было». Если у группы кастомные ограничения, включать не стоит.
    night_mode_enabled: bool = Field(False, alias="NIGHT_MODE_ENABLED")
    night_mode_start_hour: int = Field(23, alias="NIGHT_MODE_START_HOUR")  # UTC, 0-23
    night_mode_end_hour: int = Field(7, alias="NIGHT_MODE_END_HOUR")  # UTC, 0-23
    # Служебное: закрыт ли чат ПРЯМО СЕЙЧАС ночным режимом. Пишется джобой, не
    # руками (в /settings не выводится). Хранится в БД, а не в памяти: рестарт
    # контейнера посреди ночи не должен приводить к тому, что утренний переход
    # не сработает, потому что процесс «забыл», что закрывал чат.
    night_mode_closed_now: bool = Field(False, alias="NIGHT_MODE_CLOSED_NOW")

    # Напоминание правил: правила в закрепе никто не открывает.
    rules_reminder_enabled: bool = Field(False, alias="RULES_REMINDER_ENABLED")
    rules_reminder_hours: int = Field(24, alias="RULES_REMINDER_HOURS")
    rules_reminder_text: str = Field("", alias="RULES_REMINDER_TEXT")

    # --- Автоответчик по ключевым словам (F45) ---
    # Снимает рутину: «как купить», «где правила» спрашивают каждый день.
    # Правила — JSON-массив: [{"triggers": ["правила"], "reply": "В закрепе"}].
    autoreply_enabled: bool = Field(False, alias="AUTOREPLY_ENABLED")
    autoreply_rules: str = Field("", alias="AUTOREPLY_RULES")
    # Пауза на правило и чат: если десять человек подряд спросят одно и то же,
    # бот ответит один раз, а не десять.
    autoreply_cooldown_seconds: int = Field(600, alias="AUTOREPLY_COOLDOWN_SECONDS")

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


def _secret_override() -> dict[str, object]:
    """Оверлей `guardian_bot_token` из ЗАШИФРОВАННОЙ таблицы `secrets`
    процесса tg_repost — токен теперь можно задать из веб-админки
    (`/settings`, группа "Guardian"), а не только правкой `.env` на
    сервере (найдено по жалобе пользователя: "мне надо чтобы в админке
    указывалось апи бота"). Кросс-пакетное чтение чужой БД — тот же приём,
    что `webui/guardian_routes.py` использует в обратную сторону (см. его
    docstring). Шифруется общим `WEBUI_MASTER_KEY` (тот же файл `.env`,
    смонтирован в оба контейнера) — читаем его СВЕЖО из `.env` на каждый
    вызов через `load_dotenv()`, а не из закэшированных pydantic-настроек:
    иначе пришлось бы рестартовать И tg_repost (генерирует ключ), И
    guardian в строго правильном порядке, просто чтобы Guardian увидел уже
    сгенерированный ключ в СВОЁМ `os.environ`, который Docker выставляет
    один раз при старте контейнера."""
    from dotenv import load_dotenv

    load_dotenv()
    master_key = os.environ.get("WEBUI_MASTER_KEY", "")
    if not master_key:
        return {}
    try:
        from tg_repost.crypto import decrypt
        from tg_repost.db.models import Secret
        from tg_repost.db.session import session_scope as tg_repost_session_scope

        with tg_repost_session_scope() as session:
            row = (
                session.query(Secret)
                .filter(Secret.key == "guardian_bot_token")
                .one_or_none()
            )
    except Exception:  # noqa: BLE001
        return {}
    if row is None:
        return {}
    try:
        return {"guardian_bot_token": decrypt(row.encrypted_value, master_key)}
    except Exception:  # noqa: BLE001
        # Не только `InvalidToken` (чужой ключ): повреждённая на уровне байт
        # запись даёт `binascii.Error`/`UnicodeEncodeError`, а исключение отсюда
        # уронило бы весь Guardian на чтении настроек. Откат на .env-значение.
        return {}


def _shared_ai_override() -> dict[str, object]:
    """Адрес и ключ AI-провайдера — ИЗ АДМИНКИ РЕПОСТ-БОТА.

    ПОЧЕМУ НЕ СВОИ ПОЛЯ. Комментарий у самих настроек говорит прямо:
    «переиспользует те же ключи, что и репост-бот». Так и было задумано, но
    на деле Guardian читал только `.env`, а владелец настраивает провайдера в
    админке — и туда Guardian не смотрел. Замер на стенде 2026-08-22: в
    админке стоял OmniRoute, а Guardian видел `https://api.openai.com/v1` с
    ПУСТЫМ ключом. При `spam_mode=ai` это не ошибка на экране, а тишина:
    вызов падает, срабатывает fail-open, и спам идёт в группу как ни в чём не
    бывало.

    Два одинаковых поля в двух админках были бы хуже: их забывают
    синхронизировать, и расходятся они молча.

    МОДЕЛЬ — ИСКЛЮЧЕНИЕ. Её Guardian может задать свою (`/guardian/settings`,
    группа «Спам-фильтр»): классификация спама — задача простая, и на ней
    разумно держать модель подешевле, чем на рерайте. Пустое значение
    означает «как у репост-бота» и сюда не попадает.

    Читаем ту же зашифрованную таблицу `secrets`, что и токен бота, тем же
    мастер-ключом. Любая ошибка — молчаливый откат на `.env`: уронить
    Guardian на чтении настроек нельзя.
    """
    from dotenv import load_dotenv

    load_dotenv()
    master_key = os.environ.get("WEBUI_MASTER_KEY", "")
    result: dict[str, object] = {}
    try:
        from tg_repost.crypto import decrypt
        from tg_repost.db.models import AppSetting, Secret
        from tg_repost.db.session import session_scope as tg_repost_session_scope

        with tg_repost_session_scope() as session:
            base_url_row = (
                session.query(AppSetting)
                .filter(AppSetting.key == "openai_base_url")
                .one_or_none()
            )
            model_row = (
                session.query(AppSetting)
                .filter(AppSetting.key == "openai_model")
                .one_or_none()
            )
            key_row = (
                session.query(Secret)
                .filter(Secret.key == "openai_api_key")
                .one_or_none()
            ) if master_key else None
            base_url_raw = base_url_row.value if base_url_row else None
            model_raw = model_row.value if model_row else None
            key_encrypted = key_row.encrypted_value if key_row else None
    except Exception:  # noqa: BLE001 — БД недоступна: работаем на .env
        return {}

    for field, raw in (("openai_base_url", base_url_raw), ("openai_model", model_raw)):
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, str) and value.strip():
            result[field] = value

    if key_encrypted:
        try:
            result["openai_api_key"] = decrypt(key_encrypted, master_key)
        except Exception as exc:  # noqa: BLE001 — см. `_secret_override`
            # Молчать здесь нельзя: без ключа AI-фильтр спама тихо
            # пропускает всё (fail-open), и понять почему будет не по чему.
            from guardian.logging_conf import get_logger

            get_logger(__name__).warning(
                "Ключ AI-провайдера из админки не расшифровался (%s) — "
                "спам-фильтр останется на значении из .env", type(exc).__name__,
            )
    return result


def get_guardian_settings() -> GuardianSettings:
    """Настройки: .env-дефолты + свежий оверлей из `bot_config`/`secrets`
    на каждый вызов (см. docstring модуля про кросс-процессную свежесть).
    `model_copy` не перевалидирует поля — запись в БД ожидается уже
    правильно типизированной (см. `guardian/settings_store.py::save_setting`),
    так же как `bot_config.value` — JSON-сериализованное значение того же
    типа, что и .env-поле. Секретный токен из `secrets` имеет ПРИОРИТЕТ над
    `bot_config`/`.env` (маловероятная коллизия ключей, но явный порядок
    важнее угадывания)."""
    # Порядок важен: общие настройки провайдера от репост-бота идут ПЕРВЫМИ,
    # собственный оверлей Guardian их перекрывает (так пин своей модели в
    # `/guardian/settings` побеждает), а секретный токен бота — последним.
    overrides = _shared_ai_override()
    own = _db_overrides()
    # ПУСТОЕ ПОЛЕ МОДЕЛИ — ЭТО «КАК У РЕПОСТ-БОТА», А НЕ «ПУСТАЯ МОДЕЛЬ».
    # Форма настроек отправляет ВСЕ поля группы, включая незаполненные, так
    # что пустая строка попадает в `bot_config` сама собой при первом же
    # сохранении спам-фильтра. Без этой строки включение фильтра ломало бы
    # его же: модель становилась пустой, и вызов уходил в никуда.
    model = own.get("openai_model")
    if isinstance(model, str) and not model.strip():
        own.pop("openai_model")
    overrides.update(own)
    overrides.update(_secret_override())
    base = _env_settings()
    # ВНИМАНИЕ НА РАЗНИЦУ. Пока в `bot_config` пусто, возвращается САМ
    # закэшированный объект — один и тот же на все вызовы; как только там
    # появляется хоть одна строка, каждый вызов отдаёт СВЕЖУЮ КОПИЮ. Отсюда
    # два следствия, на которых легко обжечься:
    #   * менять поля возвращённого объекта нельзя — в первом случае это
    #     правка глобального кэша для всего процесса;
    #   * подменять поля «для теста» надо у ФУНКЦИИ, а не у объекта: во
    #     втором случае патч исчезнет со следующим вызовом.
    # Оба уже случались в тестах и стоили падения целого файла.
    return base.model_copy(update=overrides) if overrides else base


def invalidate_settings_cache() -> None:
    """Сбросить `lru_cache` .env-части — нужно после смены `os.environ` в
    тестах, иначе следующий вызов вернёт закэшированный старый объект.
    Оверлей `bot_config` в кэше не участвует (см. `_db_overrides`), сбрасывать
    нечего."""
    _env_settings.cache_clear()

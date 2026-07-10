"""Слой записи настроек/секретов из веб-админки (F23, Фаза 5).

Чтение (с оверлеем поверх .env) — в `tg_repost.config.get_settings()`,
прозрачно для всех существующих 30+ мест вызова. Этот модуль — путь ЗАПИСИ:
вызывается только из роутов `webui/app.py` (`/settings`, `/secrets`).

Аудит-лог (`AuditLog`) сюда НЕ подключается — это явный скоуп Фазы 5.4 по
плану (единый проход по всем мутирующим роутам разом, а не по частям).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from tg_repost import crypto
from tg_repost.config import (
    SECRET_FIELD_NAMES,
    Settings,
    get_settings,
    invalidate_settings_cache,
)
from tg_repost.db.models import AppSetting, Secret, TelethonSession
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SettingField:
    """Описание одного поля настройки для рендеринга в `/settings`."""

    name: str  # snake_case-атрибут Settings
    label: str
    value_type: str  # int | float | bool | str | csv_list
    # Требует resync_scheduler_jobs() (Фаза 5.2), а не просто живого чтения —
    # т.к. меняет состав/параметры уже зарегистрированных APScheduler-джобов.
    needs_resync: bool = False
    # Для строковых полей с закрытым набором значений (cover_strategy и
    # т.п.) — рендерится как <select>, роут отклоняет значения не из списка
    # ДО записи. Тот же паттерн, что уже применён в guardian/settings_store.py
    # (найдено при code-ревью: без этого опечатка вида "Comfyui" молча
    # проходила валидацию — value_type="str" принимает любую непустую строку —
    # и код, сравнивающий через `==`, тихо переставал работать).
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SettingsGroup:
    key: str
    title: str
    fields: tuple[SettingField, ...]
    description: str = ""


SETTINGS_GROUPS: tuple[SettingsGroup, ...] = (
    SettingsGroup(
        "telegram", "Telegram (идентичность)",
        (
            SettingField("tg_api_id", "API ID", "int"),
            SettingField("tg_owner_user_id", "Owner user ID", "int"),
        ),
        "Данные Telethon-приложения (my.telegram.org) — НЕ токен бота, "
        "другой тип credentials. Owner user ID — твой личный Telegram id "
        "(узнать у @userinfobot), кому бот шлёт посты на модерацию.",
    ),
    SettingsGroup(
        "proxy", "Прокси (host/port — секрет см. /secrets)",
        (
            # host/port сами по себе не секрет (бесполезны без mtproto_proxy_secret
            # с /secrets) — тот же класс полей, что "телеграм-идентичность" выше:
            # применяются к НОВОМУ клиенту, для уже запущенного listener'а нужен
            # ручной рестарт на /components (не needs_resync — тот флаг только про
            # состав джобов планировщика, не про пересборку Telethon-клиента).
            SettingField("mtproto_proxy_host", "MTProto proxy host (для Telethon)", "str"),
            SettingField("mtproto_proxy_port", "MTProto proxy port", "int"),
        ),
        "Если Telegram зарезан у провайдера/на сервере. Только для Telethon "
        "(юзер-сессия читает каналы) — Bot API ботов идёт через отдельный "
        "SOCKS5-прокси на /secrets, это разные протоколы.",
    ),
    SettingsGroup(
        "rewrite", "Рерайт — F06",
        (
            SettingField("openai_base_url", "Base URL", "str"),
            SettingField("openai_model", "Модель", "str"),
        ),
        "Куда идут запросы на переписывание постов. Любой OpenAI-совместимый "
        "провайдер — не обязательно сам OpenAI (локальная Ollama, прокси и т.д.).",
    ),
    SettingsGroup(
        "filtering", "Фильтрация по словам — F03",
        (
            SettingField("filter_stop_words", "Стоп-слова", "csv_list"),
            SettingField("filter_required_words", "Обязательные слова", "csv_list"),
        ),
        "Через запятую. Пост со стоп-словом помечается filtered_out и не "
        "идёт дальше по пайплайну; если задано хоть одно обязательное "
        "слово — пост без НИ ОДНОГО из них тоже отфильтровывается.",
    ),
    SettingsGroup(
        "pipeline", "Пайплайн",
        (
            SettingField("pipeline_interval_seconds", "Интервал тика, сек", "int", needs_resync=True),
            SettingField("auto_post_enabled", "Авто-постинг без модерации", "bool"),
            SettingField("log_level", "Уровень логирования", "str"),
        ),
        "Как часто и в каком режиме идёт основной цикл обработки постов. "
        "«Авто-постинг без модерации» — публикует рерайченные посты сразу, "
        "БЕЗ кнопок ✅/❌/✏️ в личке — включай осознанно.",
    ),
    SettingsGroup(
        "antiban", "Антибан — F17",
        (
            SettingField("listener_min_delay_seconds", "Мин. задержка, сек", "float"),
            SettingField("listener_max_delay_seconds", "Макс. задержка, сек", "float"),
            SettingField("max_reads_per_hour", "Лимит чтений в час", "int"),
        ),
        "Джиттер между запросами Telethon и почасовой лимит — снижают риск "
        "ограничений юзер-сессии Telegram при чтении многих каналов. Не "
        "стоит выкручивать в 0 ради скорости.",
    ),
    SettingsGroup(
        "posting_schedule", "Расписание публикации — F11",
        (
            SettingField("scheduled_posting_enabled", "Публикация по слотам", "bool", needs_resync=True),
            SettingField("posting_slots", "Слоты (HH:MM)", "csv_list", needs_resync=True),
            SettingField("posting_batch_per_slot", "Постов за слот", "int"),
        ),
        "Если включено — одобренные посты выходят не мгновенно, а по "
        "расписанию (время — UTC, без поправки на твой часовой пояс).",
    ),
    SettingsGroup(
        "semantic_dedup", "Семантический дубль-чек — F13",
        (
            SettingField("semantic_dedup_enabled", "Включён", "bool"),
            SettingField("openai_embedding_model", "Модель эмбеддингов", "str"),
            SettingField("semantic_similarity_threshold", "Порог сходства", "float"),
            SettingField("dedup_window_days", "Окно сравнения, дней", "int"),
        ),
        "Ловит ПЕРЕФРАЗИРОВАННЫЕ повторы (не только точные дубли, как "
        "базовый хэш-дедуп) через эмбеддинги — тратит токены на каждый пост, "
        "поэтому выключено по умолчанию.",
    ),
    SettingsGroup(
        "stats", "Статистика — F14",
        (
            SettingField("stats_enabled", "Сбор статистики включён", "bool", needs_resync=True),
            SettingField("stats_interval_minutes", "Период опроса, мин", "int", needs_resync=True),
            SettingField("stats_window_days", "Окно для /stats, дней", "int"),
        ),
        "Сбор просмотров/пересылок/реакций опубликованных постов через "
        "Telethon — нужно для команды бота /stats и умного расписания ниже.",
    ),
    SettingsGroup(
        "negative_reactions", "Реакция на негатив — F25",
        (
            SettingField(
                "negative_reaction_threshold", "Порог негативных реакций (0 = выкл.)", "int",
            ),
            SettingField("auto_delete_on_negative", "Авто-удалять пост при превышении", "bool"),
            SettingField("max_auto_deletes_per_hour", "Потолок авто-удалений в час", "int"),
        ),
        "При превышении порога негативных реакций (👎💩🤮😡🤬😢😭) шлёт "
        "уведомление владельцу; авто-удаление — отдельная опция, с потолком "
        "в час на случай скоординированного бригадинга.",
    ),
    SettingsGroup(
        "style_profiles", "Стиль-профили — F15",
        (SettingField("default_style_profile", "Профиль по умолчанию", "str"),),
        "default | news | opinion | instruction | humor — какой промпт "
        "рерайта использовать, если у источника нет своего (см. CLI "
        "set-source-style).",
    ),
    SettingsGroup(
        "enrichment", "Добор источников — F16",
        (
            SettingField("enable_source_enrichment", "Включён глобально", "bool"),
            SettingField("brave_search_url", "Brave Search URL", "str"),
            SettingField("enrichment_max_results", "Макс. результатов поиска", "int"),
            SettingField("enrichment_max_sources", "Макс. источников в посте", "int"),
            SettingField(
                "version_comparison_enabled", "Сравнение версий источников — F24", "bool",
            ),
        ),
        "Ищет через Brave Search доп. ссылки по теме поста, добавляет блок "
        "«📚 Источники» — рост доверия к посту. Нужен ключ Brave Search API "
        "на /secrets, иначе блок просто не добавляется.",
    ),
    SettingsGroup(
        "covers", "Авто-обложки — F18",
        (
            SettingField("enable_auto_cover", "Включены", "bool"),
            SettingField(
                "cover_strategy", "Стратегия", "str", choices=("unsplash", "comfyui"),
            ),
            SettingField("unsplash_api_url", "Unsplash API URL", "str"),
            SettingField("comfyui_base_url", "ComfyUI base URL", "str"),
            SettingField("comfyui_workflow_path", "Путь к workflow JSON", "str"),
            SettingField("comfyui_positive_node_id", "ID узла промпта", "str"),
            SettingField("comfyui_poll_attempts", "Попыток опроса", "int"),
            SettingField("comfyui_poll_interval_seconds", "Интервал опроса, сек", "float"),
        ),
        "Если у поста нет своей картинки: unsplash — стоковое фото по "
        "ключевым словам (быстро, бесплатно, не уникально); comfyui — "
        "AI-генерация через твою локальную установку (нужны workflow JSON "
        "в API-формате и ID узла промпта — специфично для конкретной установки).",
    ),
    SettingsGroup(
        "smart_schedule", "Умное расписание — F19",
        (
            SettingField("smart_schedule_min_posts", "Мин. постов для рекомендации", "int"),
            SettingField("smart_schedule_top_n", "Топ-N часов", "int"),
            SettingField("smart_schedule_window_days", "Окно анализа, дней", "int"),
            SettingField(
                "smart_schedule_auto_apply", "Автоприменение раз в сутки", "bool", needs_resync=True,
            ),
        ),
        "Анализирует накопленную статистику просмотров и рекомендует часы "
        "публикации (см. /stats/best-times); без «автоприменения» только "
        "советует, слоты меняешь сам.",
    ),
    SettingsGroup(
        "digest", "Авто-дайджест — F20",
        (
            SettingField("digest_enabled", "Включён", "bool", needs_resync=True),
            SettingField("digest_day_of_week", "День недели (mon..sun)", "str", needs_resync=True),
            SettingField("digest_hour", "Час", "int", needs_resync=True),
            SettingField("digest_minute", "Минута", "int", needs_resync=True),
            SettingField("digest_top_n", "Постов в дайджест", "int"),
            SettingField("digest_window_days", "Окно отбора, дней", "int"),
        ),
        "Раз в неделю LLM сам собирает топ постов за период в один сводный "
        "обзор и ставит его в обычный пайплайн модерации/публикации.",
    ),
    SettingsGroup(
        "ads", "Нативная реклама — F21",
        (SettingField("ad_every_nth_post", "Каждый N-й пост (0=выкл)", "int"),),
        "Каждый N-й опубликованный обычный пост сопровождается рекламным "
        "(из брифов — см. страницу «Реклама» в меню), сгенерированным ИИ. 0 = выключено.",
    ),
    SettingsGroup(
        "growth", "Growth-трекер — F22",
        (
            SettingField("growth_tracking_enabled", "Включён", "bool", needs_resync=True),
            SettingField("growth_snapshot_interval_minutes", "Период снимков, мин", "int", needs_resync=True),
            SettingField("growth_min_snapshots", "Мин. снимков для отчёта", "int"),
            SettingField("growth_report_window_days", "Окно отчёта, дней", "int"),
        ),
        "Снимает число подписчиков целевых каналов через Telethon — команда "
        "бота /growth показывает прирост за период (счётчики, не "
        "статистическая корреляция).",
    ),
)

SECRET_LABELS: dict[str, str] = {
    "tg_api_hash": "Telegram API Hash",
    "tg_session_string": "Telethon Session String",
    "tg_bot_token": "Telegram Bot Token",
    "openai_api_key": "OpenAI API Key",
    "brave_api_key": "Brave Search API Key",
    "unsplash_access_key": "Unsplash Access Key",
    "mtproto_proxy_secret": "MTProto Proxy Secret",
    "telethon_proxy_url": "Telethon SOCKS5 Proxy URL (socks5://[user:pass@]host:port)",
    "bot_api_proxy_url": "Bot API Proxy URL (socks5://user:pass@host:port)",
}

# Что это и где взять — показывается на /secrets рядом с полем, чтобы не
# приходилось лезть в README/CLAUDE.md за расшифровкой техн. названия поля
# (найдено по реальной путанице пользователя: не с первого раза понятно,
# что TG_API_ID/HASH и TG_BOT_TOKEN — это два РАЗНЫХ места получения).
SECRET_HINTS: dict[str, str] = {
    "tg_api_hash": (
        "Пара с API ID (см. группу «Telegram (идентичность)» в /settings). "
        "Получить: my.telegram.org → API development tools → создать приложение."
    ),
    "tg_session_string": (
        "Привязка твоего Telegram-аккаунта к Telethon (юзер-сессия, читает "
        "каналы-источники). Проще всего — кнопка «Войти через Telegram» справа, "
        "а не вручную сюда."
    ),
    "tg_bot_token": (
        "Токен БОТА для публикации/модерации — НЕ то же самое, что API ID/Hash "
        "выше. Получить: диалог с @BotFather в Telegram → /newbot."
    ),
    "openai_api_key": (
        "Ключ для рерайта постов через LLM. Подходит любой OpenAI-совместимый "
        "провайдер (см. Base URL в /settings) — сам OpenAI, локальная Ollama и т.д."
    ),
    "brave_api_key": "Для добора источников (F16) — поиск по теме поста через Brave Search API. Без ключа этот блок просто не добавляется в пост.",
    "unsplash_access_key": "Для авто-обложек (F18), если выбрана стратегия unsplash в /settings. Без ключа обложка не генерируется, пост публикуется без неё.",
    "mtproto_proxy_secret": (
        "Секрет-часть MTProto-прокси для Telethon (не для ботов — Bot API "
        "прокси ниже, отдельно). Host/port — в /settings, группа «Прокси». "
        "Внимание: секреты с префиксом ee (fake-TLS) Telethon НЕ поддерживает "
        "— используй SOCKS5-прокси ниже вместо этого."
    ),
    "telethon_proxy_url": (
        "SOCKS5-туннель для Telethon (юзер-сессия) — рекомендуемая замена "
        "MTProto-прокси, БЕЗ ограничения fake-TLS. Если задан, имеет приоритет "
        "над MTProto-прокси. Формат: socks5://[user:pass@]host:port."
    ),
    "bot_api_proxy_url": (
        "SOCKS5-прокси для Bot API репост-бота (постинг/модерация) — НЕ "
        "MTProto, другой протокол. Формат целиком: socks5://user:pass@host:port."
    ),
}


def effective_value(field: SettingField) -> object:
    """Текущее эффективное значение поля (.env + оверлей из БД)."""
    return getattr(get_settings(), field.name)


def save_setting(key: str, value: object, value_type: str) -> None:
    """Сохранить настройку в `app_settings` и сразу применить (live)."""
    if key not in Settings.model_fields:
        raise ValueError(f"Неизвестная настройка: {key}")
    if key in SECRET_FIELD_NAMES:
        raise ValueError(f"'{key}' — секрет, используй set_secret()")

    encoded = json.dumps(value)
    with session_scope() as session:
        existing = session.query(AppSetting).filter(AppSetting.key == key).one_or_none()
        if existing:
            existing.value = encoded
            existing.value_type = value_type
        else:
            session.add(AppSetting(key=key, value=encoded, value_type=value_type))
    invalidate_settings_cache()
    logger.info("Настройка '%s' обновлена через веб-админку", key)


@dataclass(frozen=True)
class SecretStatus:
    """Статус секрета для отображения в `/secrets` (никогда не сам секрет)."""

    key: str
    label: str
    is_set: bool
    masked_hint: str
    source: str  # "db" | "env" | "unset"
    description: str = ""  # что это и где взять — см. SECRET_HINTS


def list_secret_status() -> list[SecretStatus]:
    """Статус всех секретов: задан ли (и где), маска — без расшифровки."""
    settings = get_settings()
    with session_scope() as session:
        db_rows = {r.key: r.masked_hint for r in session.query(Secret).all()}

    result: list[SecretStatus] = []
    for key in SECRET_FIELD_NAMES:
        label = SECRET_LABELS.get(key, key)
        description = SECRET_HINTS.get(key, "")
        if key in db_rows:
            result.append(SecretStatus(key, label, True, db_rows[key], "db", description))
            continue
        raw_value = getattr(settings, key, "")
        if raw_value:
            result.append(SecretStatus(key, label, True, crypto.mask(raw_value), "env", description))
        else:
            result.append(SecretStatus(key, label, False, "", "unset", description))
    return result


def ensure_master_key() -> str:
    """Вернуть текущий WEBUI_MASTER_KEY, сгенерировав его при самом первом
    сохранении секрета. Бросает, если ключа нет, а секреты в БД уже есть —
    это значило бы, что .env потерял ключ независимо от БД (см. план Фазы 5,
    раздел "Архитектурное решение: секреты").

    Без подчёркивания в имени (было `_ensure_master_key`) — переиспользуется
    `telethon_sessions_repo.py` (F26), не только этим модулем: дополнительные
    Telethon-сессии шифруются тем же ключом, что и обычные секреты.
    """
    settings = get_settings()
    if settings.webui_master_key:
        return settings.webui_master_key

    with session_scope() as session:
        existing_count = session.query(Secret).count()
        # F26: дополнительные Telethon-сессии шифруются тем же ключом — та же
        # защита от "ключ потерян, а зашифрованные данные в БД остались".
        existing_count += session.query(TelethonSession).count()
    if existing_count > 0:
        raise RuntimeError(
            "WEBUI_MASTER_KEY отсутствует, но в БД уже есть зашифрованные "
            "секреты — новый ключ автоматически не генерируется (это сделало "
            "бы существующие секреты невосстановимыми). Восстанови "
            "WEBUI_MASTER_KEY в .env из бэкапа."
        )

    new_key = crypto.generate_key()
    crypto.append_env_var("WEBUI_MASTER_KEY", new_key)
    invalidate_settings_cache()
    logger.info("Сгенерирован новый WEBUI_MASTER_KEY (первый секрет в системе)")
    return new_key


def set_secret(key: str, plaintext: str) -> None:
    """Зашифровать и сохранить секрет; write-only — значение не возвращается."""
    if key not in SECRET_FIELD_NAMES:
        raise ValueError(f"Неизвестный секрет: {key}")
    if not plaintext:
        raise ValueError("Пустое значение секрета не сохраняется")

    master_key = ensure_master_key()
    encrypted = crypto.encrypt(plaintext, master_key)
    masked_hint = crypto.mask(plaintext)

    with session_scope() as session:
        existing = session.query(Secret).filter(Secret.key == key).one_or_none()
        if existing:
            existing.encrypted_value = encrypted
            existing.masked_hint = masked_hint
        else:
            session.add(Secret(key=key, encrypted_value=encrypted, masked_hint=masked_hint))
    invalidate_settings_cache()
    logger.info("Секрет '%s' обновлён через веб-админку", key)

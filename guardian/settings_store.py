"""Слой записи "живых" настроек Guardian — сохраняются в `bot_config`
(таблица уже существовала под G13/`/setmode` и т.п. из плана, здесь её
занимает веб-админка tg_repost вместо ещё не реализованных Telegram-команд).

Чтение (с оверлеем поверх .env) — `guardian.config.get_guardian_settings()`.
Идентификационные/секретные поля (`guardian_bot_token`, `guardian_database_url`,
`openai_*` — последние вообще общие с репост-ботом, редактируются через его
собственную `/secrets`) сюда намеренно не входят: `guardian_bot_token` нужен
один раз при конструировании `Bot()` в `bot.py`, живой оверлей его не
подхватит без рестарта процесса — включать его в этот список было бы
обманчиво (выглядело бы как "применяется сразу", а на деле нет).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from guardian.config import GuardianSettings, get_guardian_settings
from guardian.db.models import BotConfig
from guardian.db.session import session_scope


@dataclass(frozen=True)
class SettingField:
    name: str  # snake_case-атрибут GuardianSettings
    label: str
    value_type: str  # int | float | bool | str
    # Для строковых полей с закрытым набором значений (spam_mode, captcha_type)
    # — рендерится как <select>, и веб-роут отклоняет значения не из списка
    # ДО записи. Без этого опечатка вида "hybird" молча проходила бы валидацию
    # (str — любая непустая строка) и спам-фильтр тихо переставал бы работать,
    # т.к. `messages.py` сверяет `spam_mode` с конкретными строками через `in
    # (...)` (найдено при код-ревью).
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SettingsGroup:
    key: str
    title: str
    fields: tuple[SettingField, ...]
    description: str = ""


# Всё здесь читается заново на каждый вызов get_guardian_settings() (см. его
# docstring) — в отличие от tg_repost, отдельного "needs_resync"-состояния
# нет: ни одна настройка Guardian не меняет состав APScheduler-джобов, все
# читаются прямо в обработчике сообщения/команды.
SETTINGS_GROUPS: tuple[SettingsGroup, ...] = (
    SettingsGroup(
        "identity",
        "Идентичность (G01)",
        (
            SettingField("guardian_group_id", "id защищаемой группы", "int"),
            SettingField(
                "guardian_log_channel_id", "id канала для лога модерации", "int"
            ),
        ),
        "Отрицательные числа (chat_id групп/каналов всегда отрицательный). "
        "Узнать id — переслать любое сообщение из группы/канала боту "
        "@getidsbot. Guardian должен быть добавлен в оба администратором.",
    ),
    SettingsGroup(
        "spam_filter",
        "Спам-фильтр — AI (G09/G10)",
        (
            SettingField(
                "spam_mode", "Режим", "str", choices=("keywords", "ai", "hybrid")
            ),
            SettingField(
                "ai_spam_confidence_threshold", "Порог уверенности AI", "float"
            ),
        ),
        "keywords — бесплатно, только стоп-слова. ai — каждое сообщение "
        "через LLM (дороже всего). hybrid (рекомендуется) — эвристики "
        "отбирают ~20% подозрительных, только они идут в AI.",
    ),
    SettingsGroup(
        "captcha",
        "Капча (G01)",
        (
            SettingField(
                "captcha_type", "Тип", "str", choices=("math", "button", "question")
            ),
            SettingField("captcha_timeout_minutes", "Тайм-аут, мин", "int"),
        ),
        "Что видит новый участник при входе, пока не ответит — math "
        "(пример, «сколько будет 7+4»), button («я не робот»), question "
        "(тематический вопрос про канал). Не ответил за тайм-аут — кик.",
    ),
    SettingsGroup(
        "warns",
        "Варны и эскалация (G05)",
        (
            SettingField("warn_threshold_mute", "Варнов до мута", "int"),
            SettingField("warn_threshold_kick", "Варнов до кика", "int"),
            SettingField("warn_threshold_ban", "Варнов до бана", "int"),
            SettingField("warn_ttl_days", "Сброс варнов через, дней", "int"),
            SettingField(
                "mute_duration_hours", "Длительность мута по умолчанию, ч", "int"
            ),
        ),
        "Каждое нарушение (стоп-слово, ссылка вне whitelist, флуд) — варн. "
        "При достижении порога — автоматический мут/кик/бан. Пороги должны "
        "идти по возрастанию: мут < кик < бан.",
    ),
    SettingsGroup(
        "flood",
        "Антифлуд (G06)",
        (
            SettingField("flood_max_messages", "Сообщений за окно", "int"),
            SettingField("flood_window_seconds", "Окно, сек", "int"),
            SettingField("allow_forwards", "Разрешить форварды", "bool"),
        ),
        "Слишком много сообщений за короткое окно — варн. Одинаковый текст "
        "подряд ловится отдельно, всегда. Форварды из других каналов можно "
        "запретить целиком.",
    ),
    SettingsGroup(
        "raid",
        "Антирейд (G14)",
        (
            SettingField("raid_join_threshold", "Участников за период", "int"),
            SettingField("raid_join_window_minutes", "Период наблюдения, мин", "int"),
            SettingField(
                "raid_cooldown_minutes", "Тишина для снятия режима, мин", "int"
            ),
        ),
        "Всплеск вступлений (больше порога за период) замораживает права "
        "ВСЕЙ группы (никто не может писать), с сохранением прежних прав "
        "для восстановления. Снимается автоматически после тишины или "
        "вручную кнопкой в лог-канале.",
    ),
    SettingsGroup(
        "trust",
        "Доверенные (G12)",
        (SettingField("auto_trust_after_days", "Автодоверие через, дней", "int"),),
        "Участники без единого нарушения N дней автоматически обходят все "
        "фильтры (снижает нагрузку на AI-режим для уже проверенной аудитории).",
    ),
    SettingsGroup(
        "profile",
        "Анализ профиля (G15)",
        (SettingField("profile_suspicion_threshold", "Порог для усиленной капчи", "int"),),
        "При вступлении новичка: нет username/фото, подозрительное био, "
        "свежий аккаунт — каждый признак добавляет балл. Порог — только "
        "усиливает капчу до math, НЕ банит и не отклоняет автоматически.",
    ),
    SettingsGroup(
        "quiet_hours",
        "Тихие часы / режим строгости (G16)",
        (
            SettingField("strict_mode", "Строгий режим сейчас", "bool"),
            SettingField("quiet_hours_enabled", "Расписание тихих часов включено", "bool"),
            SettingField("quiet_hours_start_hour", "Начало строгого режима, час UTC", "int"),
            SettingField("quiet_hours_end_hour", "Конец строгого режима, час UTC", "int"),
        ),
        "Строгий режим — варн за любое нарушение (в т.ч. ссылки). Мягкий — "
        "ссылки вне whitelist только логируются, не удаляются. Время — "
        "UTC, без поправки на твой часовой пояс.",
    ),
)


def effective_value(field: SettingField) -> object:
    """Текущее эффективное значение поля (.env + оверлей `bot_config`)."""
    return getattr(get_guardian_settings(), field.name)


def save_setting(
    key: str, value: object, value_type: str, updated_by: str = "webui"
) -> None:
    """Сохранить настройку в `bot_config`, применяется без перезапуска —
    следующий `get_guardian_settings()` (в ЛЮБОМ процессе, читающем ту же
    БД) её увидит. `value_type` в сигнатуре только ради симметрии с вызовом
    (`_coerce_form_value(field.value_type, ...)`, см. `webui/guardian_routes.py`)
    — `bot_config` не хранит тип отдельной колонкой, `json.dumps(value)` уже
    сохраняет его неявно (int/float/bool/str различимы после `json.loads`)."""
    if key not in GuardianSettings.model_fields:
        raise ValueError(f"Неизвестная настройка Guardian: {key}")
    encoded = json.dumps(value)
    with session_scope() as session:
        existing = session.query(BotConfig).filter(BotConfig.key == key).one_or_none()
        if existing is not None:
            existing.value = encoded
            existing.updated_by = updated_by
        else:
            session.add(BotConfig(key=key, value=encoded, updated_by=updated_by))

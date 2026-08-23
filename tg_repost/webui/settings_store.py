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
from tg_repost.telegram import newsroom

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
    # Пределы для чисел. Заданы НЕ у всех полей — только там, где неверное
    # значение ломает конкретное поведение (см. `_LIMITS` ниже).
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class SettingsGroup:
    key: str
    title: str
    fields: tuple[SettingField, ...]
    description: str = ""
    # Секреты, тематически относящиеся к этой группе — рендерятся в том же
    # блоке `/settings`, а не на отдельной странице `/secrets` (раньше
    # настройки и секреты были разнесены по двум страницам, что пользователь
    # называл путаницей: "в одной указан один, в другой другой"). Каждый ключ
    # из SECRET_FIELD_NAMES должен входить РОВНО в одну группу — см.
    # регресс-тест test_every_secret_field_belongs_to_exactly_one_group.
    secret_keys: tuple[str, ...] = ()



# ПРЕДЕЛЫ ЧИСЛОВЫХ НАСТРОЕК (перебор ввода 2026-08-19).
#
# Пустое поле в форме превращается в 0 — так задумано для галочек и списков,
# но для интервала это беда: `IntervalTrigger(seconds=0)` APScheduler молча
# подменяет на ОДНУ СЕКУНДУ, и такт пайплайна вместо тридцати секунд идёт
# каждую секунду — вместе со всеми запросами к платному провайдеру.
# Отрицательное значение ещё хуже: время следующего запуска оказывается в
# прошлом, и джоба крутится без остановки.
#
# Час вне 0-23 и минута вне 0-59 роняют `CronTrigger` прямо при сохранении
# настроек — то есть владелец получает пятисотку.
#
# Правила по суффиксу имени НЕ ГОДЯТСЯ, это проверено: `max_reads_per_hour` —
# счётчик, а не час суток, а `paid_access_chat_id` отрицателен по природе
# (у Telegram id групп начинаются с -100). Поэтому список явный.
_LIMITS: dict[str, tuple[float | None, float | None]] = {
    # Час суток и минута — иначе CronTrigger падает при сохранении.
    "backup_hour": (0, 23),
    "digest_hour": (0, 23),
    "digest_minute": (0, 59),
    # Периодические джобы: ноль превращается в секунду, минус — в вечный цикл.
    "pipeline_interval_seconds": (1, None),
    "task_queue_interval_seconds": (1, None),
    "comfyui_poll_interval_seconds": (1, None),
    "rss_poll_interval_minutes": (1, None),
    "stats_interval_minutes": (1, None),
    "channel_stats_interval_hours": (1, None),
    "recycle_interval_hours": (1, None),
    # Таймауты сети: ноль означает «не ждать вовсе», то есть отменить запрос.
    "openai_timeout_seconds": (1, None),
    "link_fetch_timeout_seconds": (1, None),
    # Температура вне 0..2 отвергается самим провайдером — но уже в бою, на
    # каждом посте, и выглядит это как «рерайт перестал работать».
    "rewrite_temperature": (0, 2),
    # Сроки хранения и окна: отрицательный срок бессмысленен.
    "media_retention_days": (0, None),
    "queue_retention_days": (0, None),
    "audit_retention_days": (0, None),
    "dedup_window_days": (0, None),
    "stats_window_days": (0, None),
    "recycle_window_days": (0, None),
    "recycle_min_age_days": (0, None),
}


def _with_limits(group: SettingsGroup) -> SettingsGroup:
    """Проставить пределы полям группы по таблице выше."""
    from dataclasses import replace

    fields = tuple(
        replace(f, min_value=_LIMITS[f.name][0], max_value=_LIMITS[f.name][1])
        if f.name in _LIMITS else f
        for f in group.fields
    )
    return replace(group, fields=fields)


def check_limits(field: SettingField, value: object) -> None:
    """Бросить ValueError, если значение вне предела поля.

    ValueError, а не свой тип: сохранение настроек уже ловит его и показывает
    понятную форму с ошибкой вместо пятисотки.
    """
    if field.min_value is None and field.max_value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    if field.min_value is not None and value < field.min_value:
        raise ValueError(
            f"{field.name}: {value} меньше допустимого {field.min_value}"
        )
    if field.max_value is not None and value > field.max_value:
        raise ValueError(
            f"{field.name}: {value} больше допустимого {field.max_value}"
        )


_RAW_GROUPS: tuple[SettingsGroup, ...] = (
    SettingsGroup(
        "telegram", "Telegram (идентичность)",
        (
            SettingField("tg_api_id", "API ID", "int"),
            SettingField("tg_owner_user_id", "Owner user ID", "int"),
        ),
        "Данные Telethon-приложения (my.telegram.org) — НЕ токен бота, "
        "другой тип credentials. Owner user ID — твой личный Telegram id "
        "(узнать у @userinfobot), кому бот шлёт посты на модерацию.",
        secret_keys=("tg_api_hash", "tg_bot_token", "tg_session_string"),
    ),
    SettingsGroup(
        "proxy", "Прокси",
        (
            # Единый прокси-раздел: три ТИПА (каждый со своей галочкой включения
            # и полями) + три галочки применения. Вся логика выбора — в
            # tg_repost/proxy.py. Адрес/логин — обычные редактируемые поля (не
            # секрет: бесполезны без пароля/секрета из карточки секретов ниже).
            # Применяются к НОВЫМ клиентам — для уже запущенного listener'а/бота
            # нужен ручной рестарт на /components (не needs_resync: тот флаг
            # только про состав джобов планировщика, не про пересборку клиентов).
            #
            # MTProto — только для Telethon (fake-TLS, секрет вместо логина/пароля).
            SettingField("proxy_mtproto_enabled", "MTProto: включить", "bool"),
            SettingField("proxy_mtproto_address", "MTProto: адрес (host:port)", "str"),
            # SOCKS5 — универсальный туннель (Telethon, Bot API, нейросети).
            SettingField("proxy_socks5_enabled", "SOCKS5: включить", "bool"),
            SettingField("proxy_socks5_address", "SOCKS5: адрес (host:port)", "str"),
            SettingField("proxy_socks5_login", "SOCKS5: логин", "str"),
            # HTTP(S) — универсальный, предпочтителен для нейросетей (HTTP-трафик).
            SettingField("proxy_http_enabled", "HTTP(S): включить", "bool"),
            SettingField("proxy_http_address", "HTTP(S): адрес (host:port)", "str"),
            SettingField("proxy_http_login", "HTTP(S): логин", "str"),
            # Галочки применения: какой трафик гнать через прокси.
            SettingField("proxy_use_for_telegram", "Применять для Telegram (Telethon + бот)", "bool"),
            SettingField("proxy_use_for_rewrite", "Применять для нейросети рерайта", "bool"),
            SettingField("proxy_use_for_images", "Применять для картиночной нейросети", "bool"),
        ),
        "Один прокси-раздел на всё. Включи нужный ТИП (MTProto / SOCKS5 / "
        "HTTP(S)), впиши его адрес и, если нужно, логин + пароль (пароль/секрет "
        "— в карточке секретов ниже, скрыт до кнопки «показать»), затем отметь, "
        "для чего его применять: Telegram, нейросеть рерайта, картиночная "
        "нейросеть. MTProto годится только для Telegram; для нейросетей — SOCKS5 "
        "или HTTP(S). Приоритет при нескольких включённых: у Telegram SOCKS5 → "
        "HTTP → MTProto, у нейросетей HTTP → SOCKS5.",
        secret_keys=("proxy_mtproto_secret", "proxy_socks5_password", "proxy_http_password"),
    ),
    SettingsGroup(
        "rewrite", "Рерайт — F06",
        (
            # needs_resync=True — RewriterClient кэширует base_url/model в
            # конструкторе (см. rewriter/client.py::__init__: self._model =
            # settings.openai_model), не перечитывает на каждый вызов.
            # Раньше resync триггерился ТОЛЬКО сменой openai_api_key
            # (см. app.py::_resync_if_openai_key) — смена модели/base_url
            # молча не применялась до полного рестарта контейнера, хотя
            # текст на /settings обещает "применяется сразу" (найдено на
            # реальном деплое: смена модели на OpenRouter-совместимый
            # провайдер повисла в БД, рерайт продолжал падать со старой).
            SettingField("openai_base_url", "Base URL", "str", needs_resync=True),
            SettingField("openai_model", "Модель", "str", needs_resync=True),
            # Ролевые переопределения. Пусто = основная модель выше. Отдельные
            # поля появились затем, что задачи разной сложности: фактчек
            # выигрывает от модели посильнее, а выбор поискового запроса
            # прекрасно делается дешёвой.
            SettingField("openai_model_editor",
                         "Модель редактора-фактчекера (пусто — основная)", "str"),
            SettingField("openai_model_quiz",
                         "Модель квизов (пусто — основная)", "str"),
            SettingField("openai_model_aux",
                         "Модель вспомогательных задач (пусто — основная)", "str"),
            SettingField("openai_timeout_seconds", "Таймаут запроса, сек", "float", needs_resync=True),
            SettingField("openai_max_retries", "Повторов запроса при сбое", "int", needs_resync=True),
            SettingField("rewrite_min_source_chars", "Минимум материала для рерайта", "int"),
            # Живое поле — RewriterClient.rewrite() читает его из get_settings()
            # на каждый вызов, needs_resync не нужен (в отличие от base_url/
            # model выше, которые сидят в конструкторе клиента).
            SettingField("rewrite_temperature", "Температура", "float"),
            # Живое поле — читается в scheduler/jobs.py на каждый тик, не
            # кэшируется ни в каком клиенте, needs_resync не нужен.
            SettingField("rewrite_variant_count", "Вариантов текста на пост", "int"),
            # --- Переход по ссылке из поста ---
            # Без этого рерайт неизбежно синонимайзит короткий тизер вместо
            # пересказа по существу — лимит символов и таймаут раньше вообще
            # не доходили до админки, хотя именно лимит определяет, сколько
            # статьи реально увидит модель.
            SettingField("fetch_link_content_enabled", "Переходить по ссылке в посте", "bool"),
            SettingField("link_content_max_chars", "Лимит текста статьи, символов", "int"),
            SettingField("link_fetch_timeout_seconds", "Таймаут загрузки статьи, сек", "float"),
            # --- Анти-ИИ ---
            SettingField("rewrite_humanize_enabled", "Убирать признаки ИИ-текста", "bool"),
            SettingField("rewrite_humanize_instructions", "Правила «не как нейросеть»", "text"),
            # --- Промпты всех пяти стиль-профилей (F15) ---
            # Раньше редактировался только "default", остальные четыре молча
            # читались из файлов — источник со style_profile="news" полностью
            # игнорировал то, что владелец правил в админке.
            SettingField("rewrite_prompt_template", "Промпт: базовый (default)", "text"),
            SettingField("rewrite_prompt_news", "Промпт: новость (news)", "text"),
            SettingField("rewrite_prompt_opinion", "Промпт: мнение (opinion)", "text"),
            SettingField("rewrite_prompt_instruction", "Промпт: инструкция (instruction)", "text"),
            SettingField("rewrite_prompt_humor", "Промпт: юмор (humor)", "text"),
        ),
        "Куда идут запросы на переписывание постов. Любой OpenAI-совместимый "
        "провайдер — не обязательно сам OpenAI (локальная Ollama, прокси и т.д.).",
        secret_keys=("openai_api_key",),
    ),
    SettingsGroup(
        "editorial", "Редакция из двух агентов — F40",
        (
            # Все поля живые — читаются в scheduler/jobs.py и rewriter/editorial.py
            # из get_settings() на каждый пост, ни в каком клиенте не кэшируются.
            SettingField("editorial_enabled", "Включить редакцию (журналист + редактор)", "bool"),
            SettingField("editorial_max_rounds", "Максимум раундов правки", "int"),
            SettingField("editorial_web_verify_enabled", "Веб-сверка спорных фактов", "bool"),
            SettingField("editorial_web_verify_max_claims", "Потолок веб-запросов на пост", "int"),
            SettingField("editorial_prompt_template", "Промпт редактора-фактчекера", "text"),
            SettingField("editorial_revise_prompt_template", "Промпт правки по замечаниям", "text"),
            # F50 «редакционная кухня» — трансляция хода редакции в чат.
            SettingField("editorial_newsroom_enabled", "Транслировать ход редакции в чат", "bool"),
            SettingField("editorial_newsroom_chat_id", "Чат «редакционной кухни» (id)", "int"),
            SettingField(
                "editorial_newsroom_verbosity", "Что транслировать", "str",
                choices=newsroom.VERBOSITY_CHOICES,
            ),
        ),
        "Профессиональный рерайт: журналист пишет черновик, редактор-фактчекер "
        "сверяет его с источниками и пишет замечания, журналист переписывает по "
        "ним. Дороже по токенам — 1 раунд правки это ТРИ вызова LLM на вариант "
        "вместо одного. 0 раундов = только черновик, без рецензии. Веб-сверка "
        "требует настроенного поиска (см. «Добор источников»).",
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
            SettingField("openai_embedding_model", "Модель эмбеддингов", "str", needs_resync=True),
            SettingField("semantic_similarity_threshold", "Порог сходства", "float"),
            SettingField("dedup_window_days", "Окно сравнения, дней", "int"),
            SettingField("cluster_grace_minutes", "Пауза на сбор сюжета, мин", "int"),
        ),
        "Ловит ПЕРЕФРАЗИРОВАННЫЕ повторы (не только точные дубли, как базовый "
        "хэш-дедуп) через эмбеддинги. Повтор из другого источника не "
        "выбрасывается, а цепляется к первому посту в «сюжет» и идёт в "
        "фактчек как подтверждение. Пауза на сбор — задержка перед рерайтом, "
        "чтобы источники успели подтянуться; 0 — без ожидания.",
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
        "rss", "RSS-ленты как источник",
        (
            SettingField("rss_enabled", "Опрос лент включён", "bool", needs_resync=True),
            SettingField("rss_poll_interval_minutes", "Интервал опроса, мин", "int", needs_resync=True),
            SettingField("rss_max_items_per_poll", "Записей за опрос, максимум", "int"),
            SettingField("rss_first_poll_items", "Записей при первом опросе ленты", "int"),
            SettingField("rss_max_queue_backlog", "Потолок очереди (пауза опроса)", "int"),
        ),
        "Ленты добавляются на странице «Источники». Записи попадают в ту же "
        "очередь, что и посты из каналов, и проходят весь тот же путь: "
        "фильтры, стиль-профиль, переход по ссылке за полным текстом статьи, "
        "формат публикации. Опрос не зависит от Telegram — при недоступном "
        "Telethon ленты продолжают наполнять очередь.",
    ),
    SettingsGroup(
        "telegraph", "Статьи на Telegraph (лонгриды)",
        (
            SettingField("telegraph_enabled", "Включены", "bool"),
            SettingField("telegraph_author_name", "Автор (подпись под статьёй)", "str"),
            SettingField("telegraph_author_url", "Ссылка автора (например, канал)", "str"),
            SettingField("article_teaser_max_chars", "Длина тизера в канале, символов", "int"),
            SettingField("article_prompt_template", "Промпт статьи", "text"),
        ),
        "Пост в канале ограничен 4096 символами, подпись к картинке — 1024, "
        "и код-блоки в них не отрендерить. Статья на telegra.ph — 64 КБ, с "
        "подсветкой кода и картинками между абзацами, Telegram открывает её "
        "через Instant View прямо в приложении. Ключ и регистрация не нужны: "
        "аккаунт заводится сам при первой публикации. Формат выбирается У "
        "КАЖДОГО ИСТОЧНИКА (страница источника → «Формат публикации»), эта "
        "галочка — общий рубильник.",
        secret_keys=("telegraph_access_token",),
    ),
    SettingsGroup(
        "enrichment", "Добор источников — F16",
        (
            SettingField("enable_source_enrichment", "Включён глобально", "bool"),
            SettingField(
                "search_provider", "Поисковик", "str",
                choices=("searxng", "brave", "ddgs"),
            ),
            SettingField("searxng_base_url", "SearXNG: адрес", "str"),
            SettingField("searxng_engines", "SearXNG: движки", "str"),
            SettingField("searxng_language", "SearXNG: язык выдачи", "str"),
            SettingField("brave_search_url", "Brave Search URL", "str"),
            SettingField("enrichment_max_results", "Макс. результатов поиска", "int"),
            SettingField("enrichment_max_sources", "Макс. источников в посте", "int"),
            SettingField(
                "version_comparison_enabled", "Сравнение версий источников — F24", "bool",
            ),
        ),
        "Ищет доп. ссылки по теме поста и добавляет блок «📚 Источники» — рост "
        "доверия к посту. Поисковик выбирается ниже: searxng — свой сервис в "
        "Docker, бесплатен без оговорок (ни ключа, ни аккаунта, ни квоты) и "
        "позволяет выбрать движки, что важно, если часть выдачи недоступна из "
        "сети сервера; brave — внешний API, бесплатный тир закрыт для новых "
        "регистраций с февраля 2026; ddgs — DuckDuckGo без ключа, но "
        "неофициально и с троттлингом.",
        secret_keys=("brave_api_key",),
    ),
    SettingsGroup(
        "covers", "Авто-обложки — F18",
        (
            SettingField("enable_auto_cover", "Включены", "bool"),
            SettingField(
                "cover_strategy", "Стратегия", "str", choices=("unsplash", "comfyui", "openai"),
            ),
            SettingField("cover_variant_count", "Вариантов обложки на пост", "int"),
            SettingField("cover_replace_source_media", "Своя обложка вместо картинки оригинала", "bool"),
            # Промпт подбора search-запроса (unsplash/comfyui) раньше жил
            # только в файле cover_prompt.txt и не редактировался из админки,
            # хотя именно он решает, что за картинка приедет.
            SettingField("cover_search_prompt_template", "Промпт подбора запроса (unsplash/comfyui)", "text"),
            SettingField("cover_openai_model", "Модель (openai-стратегия)", "str"),
            SettingField(
                "cover_openai_image_size", "Размер картинки (openai-стратегия)", "str",
                choices=("1792x1024", "1024x1024", "1024x1792", "1536x1024", "1024x1536"),
            ),
            SettingField("cover_image_prompt_template", "Промпт генерации (openai-стратегия)", "text"),
            SettingField("unsplash_api_url", "Unsplash API URL", "str"),
            SettingField("comfyui_base_url", "ComfyUI base URL", "str"),
            SettingField("comfyui_workflow_path", "Путь к workflow JSON", "str"),
            SettingField("comfyui_positive_node_id", "ID узла позитивного промпта", "str"),
            SettingField("comfyui_negative_node_id", "ID узла негативного промпта", "str"),
            SettingField("comfyui_negative_prompt", "Негативный промпт (ComfyUI)", "text"),
            SettingField("comfyui_poll_attempts", "Попыток опроса", "int"),
            SettingField("comfyui_poll_interval_seconds", "Интервал опроса, сек", "float"),
        ),
        "Если у поста нет своей картинки: unsplash — стоковое фото по "
        "ключевым словам (быстро, бесплатно, не уникально); comfyui — "
        "AI-генерация через твою локальную установку (нужны workflow JSON "
        "в API-формате и ID узла промпта — специфично для конкретной установки); "
        "openai — генерация через уже настроенный OpenAI-совместимый провайдер "
        "рерайта (см. группу «Рерайт» выше) — свой ключ не нужен, только "
        "модель и промпт ниже. Все промпты уже настроены на картинку БЕЗ "
        "текста и надписей и на ассоциативную сцену по теме, а не буквальную "
        "иллюстрацию заголовка.",
        secret_keys=("unsplash_access_key",),
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
        "utm", "UTM-метки на ссылках — F59",
        (
            SettingField("utm_enabled", "Включены", "bool"),
            SettingField("utm_source", "utm_source", "str"),
            SettingField("utm_medium", "utm_medium", "str"),
            SettingField("utm_campaign", "utm_campaign (можно {post_id})", "str"),
        ),
        "Дописывает метки к внешним ссылкам при публикации — так внешняя "
        "аналитика видит, какой пост принёс переходы. Ссылки на Telegram "
        "НЕ размечаются: метки там бессмысленны, а инвайт-ссылку лишний "
        "параметр может сломать. Ссылка, уже содержащая utm_source, "
        "остаётся как есть.",
    ),
    SettingsGroup(
        "paid_access", "Платный доступ (Stars) — F49",
        (
            SettingField("paid_access_enabled", "Включён", "bool"),
            SettingField("paid_access_chat_id", "chat_id закрытого канала", "int"),
            SettingField("paid_access_price_stars", "Цена в звёздах за 30 дней", "int"),
            SettingField("paid_access_title", "Название для счёта", "str"),
        ),
        "Продажа доступа к закрытому каналу за Telegram Stars — 0% комиссии, "
        "против 10–20% у Tribute, PaidSub и Paywall. Платёжный контур ведёт "
        "Telegram: он принимает звёзды, сам списывает следующий период и сам "
        "решает, когда подписка кончилась. Наша часть — выдать персональную "
        "ссылку с лимитом в одно использование, закрыть доступ после "
        "окончания и связать оплату с карточкой человека. Бот Engage должен "
        "быть администратором канала с правом приглашать. С 2024 года Stars "
        "ОБЯЗАТЕЛЬНЫ для цифровых товаров в ботах — обычный эквайринг здесь "
        "ведёт к бану бота.",
    ),
    SettingsGroup(
        "miniapp", "Личный кабинет (Mini App) — F74",
        (
            SettingField("miniapp_url", "Публичный адрес (https://…)", "str"),
        ),
        "Кабинет внутри Telegram: своя подписка, свои приглашённые, каталог и "
        "таблица лидеров. ПУСТО = кнопки в боте нет, и это правильное "
        "умолчание: мини-апп — единственная часть системы, которая обязана "
        "торчать наружу, вся остальная админка живёт за логином. Telegram "
        "принимает только https и не открывает localhost. Доступ проверяется "
        "подписью Telegram на КАЖДЫЙ запрос, не паролем; человек видит только "
        "своё, админских экранов там нет.",
    ),
    SettingsGroup(
        "affiliate", "Партнёрская программа — F67",
        (
            SettingField("affiliate_percent", "Процент партнёру, %", "int"),
        ),
        "Процент от каждой оплаты тому, кто привёл человека. НОЛЬ выключает "
        "программу — комиссия по умолчанию означала бы, что доля выручки "
        "раздаётся без вашего решения. Сложную часть уже сделал F42: "
        "комиссия начисляется только за ПОДТВЕРЖДЁННОГО реферала (вступил, "
        "написал, прожил N дней), самому себе не начисляется никогда, а "
        "возврат платежа снимает начисление обратно. Выплаты записываются "
        "вручную: Telegram не даёт боту переслать звёзды человеку, вывод "
        "идёт через Fragment на ваш кошелёк.",
    ),
    SettingsGroup(
        "shop", "Магазин — F69/F70",
        (
            SettingField("shop_enabled", "Включён", "bool"),
            SettingField("shop_currency", "Валюта каталога", "str"),
        ),
        "Продажа ФИЗИЧЕСКИХ товаров через Bot Payments API: провайдер "
        "подключается в @BotFather, его токен вводится на этой же странице "
        "как секрет. Цифровое, потребляемое внутри Telegram, сюда класть "
        "нельзя — оно продаётся только за Stars, иначе бан бота. Остаток "
        "списывается при оплате, а не при открытии счёта: иначе брошенные "
        "корзины съедают склад.",
        secret_keys=("shop_provider_token",),
    ),
    SettingsGroup(
        "ad_marking", "Маркировка рекламы — F62",
        (
            SettingField("ad_marking_enabled", "Включена", "bool"),
        ),
        "Дописывает в НАЧАЛО рекламного поста пометку «Реклама. <рекламодатель>. "
        "erid: <токен>». В начало, а не в конец: Telegram сворачивает длинный "
        "текст, и пометка под «показать полностью» формально есть, а "
        "фактически не видна. Пока включено, рекламный пост БЕЗ erid не "
        "публикуется — опубликовать с половиной маркировки хуже, чем не "
        "опубликовать, потому что ушедший пост не отозвать. Токен выдаёт ОРД "
        "на креатив, вставляется в бриф вручную: интеграции с API оператора "
        "нет, регистрация креатива требует договора и делается вне системы.",
    ),
    SettingsGroup(
        "approval", "Согласование постов — F72",
        (
            SettingField(
                "require_owner_approval", "Редактор одобрил → ждём владельца", "bool",
            ),
        ),
        "Пост, одобренный редактором, не публикуется, пока его не подтвердит "
        "владелец. По умолчанию выключено: там, где владелец работает один "
        "или полностью доверяет редактору, это только замедляет. Включать, "
        "когда редактор появился, а доверие ещё строится.",
    ),
    SettingsGroup(
        "task_queue", "Очередь задач — F64",
        (
            SettingField(
                "task_queue_interval_seconds", "Период проверки, сек", "int",
                needs_resync=True,
            ),
        ),
        "Воркер, который выполняет долгие операции: рассылки по сегменту и "
        "(в будущем) шаги воронок. Он всегда включён — выключателя нет "
        "намеренно, иначе можно было бы незаметно остановить доставку уже "
        "созданных рассылок. На холостом ходу проверка стоит один запрос.",
    ),
    SettingsGroup(
        "channel_stats", "Статистика канала (MTProto) — F56",
        (
            SettingField(
                "channel_stats_enabled", "Включена", "bool", needs_resync=True,
            ),
            SettingField(
                "channel_stats_interval_hours", "Период сбора, часов", "int",
                needs_resync=True,
            ),
            SettingField("channel_stats_window_days", "Окно динамики, дней", "int"),
        ),
        "Собирает данные, которых нет у ботов: доля подписчиков с ВКЛЮЧЁННЫМИ "
        "уведомлениями, средние просмотры/репосты/реакции от самого Telegram. "
        "Падение доли уведомлений — отток ДО отписки: люди ещё подписаны, но "
        "уже не читают. Требует прав АДМИНИСТРАТОРА в канале.",
    ),
    SettingsGroup(
        "media_cleanup", "Уборка старых данных",
        (
            SettingField("media_cleanup_enabled", "Убирать по расписанию", "bool",
                         needs_resync=True),
            SettingField("media_retention_days", "Хранить медиа, дней", "int",
                         needs_resync=True),
            SettingField("queue_retention_days",
                         "Хранить завершённые задачи, дней", "int",
                         needs_resync=True),
            SettingField("audit_retention_days",
                         "Хранить журнал действий, дней", "int",
                         needs_resync=True),
        ),
        "Обложки постов, которые уже отработаны — отклонённых, опубликованных "
        "и упавших, — удаляются вместе со ссылками в базе. Остальные не "
        "трогаются вовсе. У упавших срок двойной: их можно повторить из "
        "админки, и повтор без картинки был бы потерей, а не уборкой. Тем же "
        "проходом уходят завершённые задачи очереди (ждущие и работающие — "
        "никогда) и записи журнала действий старше своего срока. Ноль в любом "
        "поле — не убирать вовсе.",
    ),
    SettingsGroup(
        "backup", "Резервные копии",
        (
            SettingField("backup_enabled", "Делать копии по расписанию", "bool",
                         needs_resync=True),
            SettingField("backup_hour", "Час по UTC", "int", needs_resync=True),
            SettingField("backup_keep", "Сколько копий хранить", "int"),
        ),
        "Копия включает .env, обе базы и логи; складывается в data/backups на "
        "хосте и переживает пересоздание контейнера. Раньше копии делались "
        "только кнопкой и жили внутри контейнера — то есть исчезали при каждом "
        "обновлении системы. ВАЖНО: в копии лежит мастер-ключ вместе с "
        "зашифрованной базой, поэтому выгружать её наружу можно только "
        "зашифрованной.",
    ),
    SettingsGroup(
        "recycle", "Повтор выстреливших постов — F55",
        (
            SettingField("recycle_enabled", "Включён", "bool", needs_resync=True),
            SettingField(
                "recycle_interval_hours", "Как часто искать, часов", "int", needs_resync=True,
            ),
            SettingField("recycle_top_n", "Повторов за проход", "int"),
            SettingField("recycle_window_days", "Окно поиска, дней", "int"),
            SettingField("recycle_min_age_days", "Мин. возраст поста, дней", "int"),
            SettingField("recycle_min_views", "Порог просмотров (0=без порога)", "int"),
        ),
        "Удачный пост ставится в очередь ПОВТОРНО — почти бесплатный охват из "
        "уже проверенного контента. Повтор идёт в модерацию с пометкой "
        "«🔁 ПОВТОР», а не публикуется сам. Повторяются только оригиналы и "
        "только один раз. «Мин. возраст» должен быть меньше «окна поиска», "
        "иначе кандидатов не будет никогда.",
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
    SettingsGroup(
        "post_source_button", "Кнопка источника на посте — F34",
        (
            SettingField("post_source_button_enabled", "Показывать кнопку", "bool"),
            SettingField("post_source_button_label", "Текст кнопки", "str"),
        ),
        "Inline-кнопка со ссылкой на оригинал под опубликованным постом — "
        "только для постов из источников (у рекламы/дайджестов/опросов "
        "нет ссылки на первоисточник, кнопка на них не появится).",
    ),
    SettingsGroup(
        "guardian_bot", "Guardian — токен бота-модератора",
        (),
        "Guardian (капча, антиспам, антирейд) — ОТДЕЛЬНЫЙ бот и процесс от "
        "репост-бота выше. Список защищаемых групп и остальные настройки "
        "Guardian (стоп-слова, домены, пороги) — на странице «Guardian» в "
        "меню, здесь только его токен (секрет).",
        secret_keys=("guardian_bot_token",),
    ),
    SettingsGroup(
        "quiz", "Викторины по постам — F43",
        (
            SettingField("quiz_enabled", "Включить викторины", "bool"),
            SettingField("quiz_delay_minutes", "Пауза после поста, мин", "int"),
            SettingField("quiz_every_nth_post", "Из каждого N-го поста", "int"),
            SettingField("quiz_prompt_template", "Промпт составителя вопроса", "text"),
        ),
        "Бот выдаёт контент, а через паузу задаёт по нему вопрос — очки идут за "
        "ПРАВИЛЬНЫЙ ОТВЕТ, а не за количество сообщений (те превращаются в ферму "
        "флуда). Вопрос составляет LLM из уже проверенного редактором материала: "
        "+1 вызов на пост, из которого делаем квиз. Публикует бот Engage — без "
        "его токена викторины не заработают. РАБОТАЕТ ТОЛЬКО В ГРУППАХ: в канале "
        "у постов нет авторов-участников, и ответы оттуда не приходят (для "
        "канала — его discussion-группа).",
    ),
    SettingsGroup(
        "referrals", "Реферальная программа — F42",
        (
            SettingField("referrals_enabled", "Включить рефералы", "bool"),
            SettingField("referral_min_days", "Дней в группе до зачёта", "int"),
        ),
        "Участник берёт у бота Engage персональную ссылку (/invite) и получает "
        "очки за приведённых. АНТИНАКРУТКА обязательна и встроена: реферал "
        "засчитывается, только когда приглашённый прожил в группе указанное "
        "число дней И написал хотя бы одно сообщение. Без этого механика за "
        "день превращается в ферму мультиаккаунтов: завёл десять аккаунтов, "
        "прошёл по своей ссылке, собрал награды.",
    ),
    SettingsGroup(
        "contests", "Конкурсы и розыгрыши — F44",
        (SettingField("contests_enabled", "Включить конкурсы", "bool"),),
        "Розыгрыш ВОСПРОИЗВОДИМЫЙ: seed генерируется при создании конкурса "
        "(до того, как появился хоть один участник) и публикуется вместе с "
        "условиями, а после розыгрыша публикуется протокол — список участников "
        "и победители. Имея seed, список и алгоритм, результат перепроверяет "
        "любой желающий. Без этого аудитория не верит в честность, и конкурс "
        "не вовлекает, а раздражает. Условия проверяются ДВАЖДЫ: при записи и "
        "при розыгрыше — иначе можно подписаться, записаться и сразу "
        "отписаться. Проводит бот Engage.",
    ),
    SettingsGroup(
        "suggestions", "Предложка и онбординг — F46/F47",
        (
            SettingField("suggestions_enabled", "Принимать посты от подписчиков", "bool"),
            SettingField("onboarding_enabled", "Онбординг новичка в личку", "bool"),
        ),
        "Предложенный пост попадает в ТУ ЖЕ очередь модерации, что и рерайты, — "
        "ты решаешь, публиковать ли. Автор виден в карточке поста. Онбординг "
        "пишет новичку в личку короткую памятку (что тут есть, какие команды) — "
        "но ТОЛЬКО тем, кто уже стартовал бота: Telegram не даёт писать первым. "
        "Обе фичи работают через бота Engage.",
    ),
    SettingsGroup(
        "engage_bot", "Engage — токен бота вовлечения",
        (),
        "ОТДЕЛЬНЫЙ бот, который говорит с УЧАСТНИКАМИ: викторины по постам, "
        "конкурсы, реферальные приглашения, предложка. Не тот же бот, что "
        "публикует посты, и не Guardian. Получить: @BotFather → /newbot. "
        "Engage — отдельный процесс: после сохранения токена его нужно "
        "перезапустить (`docker compose restart engage`).",
        secret_keys=("engage_bot_token",),
    ),
)


# Пределы проставляются здесь, а не у каждого поля: так их видно списком,
# и добавить новый предел — одна строка в `_LIMITS`, а не правка описания.
SETTINGS_GROUPS: tuple[SettingsGroup, ...] = tuple(
    _with_limits(group) for group in _RAW_GROUPS
)

SECRET_LABELS: dict[str, str] = {
    "tg_api_hash": "Telegram API Hash",
    "tg_session_string": "Telethon Session String",
    "tg_bot_token": "Telegram Bot Token",
    "openai_api_key": "OpenAI API Key",
    "brave_api_key": "Brave Search API Key",
    "unsplash_access_key": "Unsplash Access Key",
    "proxy_mtproto_secret": "MTProto: секрет",
    "proxy_socks5_password": "SOCKS5: пароль",
    "proxy_http_password": "HTTP(S): пароль",
    "guardian_bot_token": "Guardian Bot Token",
    "engage_bot_token": "Engage Bot Token",
    "shop_provider_token": "Токен платёжного провайдера",
    "telegraph_access_token": "Telegraph Access Token",
}

# Что это и где взять — показывается на /secrets рядом с полем, чтобы не
# приходилось лезть в README/CLAUDE.md за расшифровкой техн. названия поля
# (найдено по реальной путанице пользователя: не с первого раза понятно,
# что TG_API_ID/HASH и TG_BOT_TOKEN — это два РАЗНЫХ места получения).
SECRET_HINTS: dict[str, str] = {
    "tg_api_hash": (
        "Пара с полем «API ID» выше, в этой же группе. "
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
    "proxy_mtproto_secret": (
        "Секрет-часть MTProto-прокси (вместо логина/пароля). Адрес — в поле "
        "«MTProto: адрес» выше, в этой же группе. Внимание: секреты с префиксом "
        "ee (fake-TLS) Telethon НЕ поддерживает — тогда бери SOCKS5 или HTTP(S)."
    ),
    "proxy_socks5_password": (
        "Пароль SOCKS5-прокси. Адрес и логин — в полях выше. Оставь пустым, "
        "если прокси без авторизации."
    ),
    "proxy_http_password": (
        "Пароль HTTP(S)-прокси. Адрес и логин — в полях выше. Оставь пустым, "
        "если прокси без авторизации."
    ),
    "shop_provider_token": (
        "Токен платёжного провайдера для ФИЗИЧЕСКИХ товаров магазина (F69). "
        "Получить: @BotFather → /mybots → бот Engage → Payments → выбрать "
        "провайдера. Для подписки (Stars) НЕ нужен — там провайдер не "
        "участвует вовсе. Список провайдеров менялся, часть российских "
        "отключалась из-за санкций: актуальность проверяйте при подключении. "
        "Читает его Engage — после сохранения нужен `docker compose restart "
        "engage`."
    ),
    "engage_bot_token": (
        "Токен ОТДЕЛЬНОГО бота вовлечения (викторины по постам, конкурсы, "
        "рефералы, предложка) — НЕ тот бот, что публикует посты, и не Guardian. "
        "Получить: @BotFather → /newbot. Engage — отдельный процесс: после "
        "сохранения нужно `docker compose restart engage`."
    ),
    "guardian_bot_token": (
        "Токен ОТДЕЛЬНОГО бота-модератора Guardian — НЕ тот же бот, что "
        "публикует посты выше. Получить: диалог с @BotFather → /newbot "
        "(либо переиспользуй уже существующего бота, если заводил его "
        "раньше вручную). Guardian — отдельный процесс/контейнер: после "
        "сохранения его нужно перезапустить (`docker compose restart "
        "guardian`), чтобы он подхватил токен — живого применения без "
        "рестарта для этого поля нет."
    ),
    "telegraph_access_token": (
        "Заполняется САМА при первой публикации статьи: Telegraph выдаёт "
        "токен без регистрации. Руками сюда что-то вписывают только чтобы "
        "перенести уже существующий аккаунт с другой инсталляции. Потеряв "
        "токен, теряешь возможность править уже опубликованные статьи — "
        "сами страницы остаются доступны по своим адресам."
    ),
}


def effective_value(field: SettingField) -> object:
    """Текущее эффективное значение поля (.env + оверлей из БД)."""
    return getattr(get_settings(), field.name)


def is_overridden(field: SettingField) -> bool:
    """Есть ли для поля сохранённое в админке значение (строка в
    `app_settings`), перекрывающее дефолт кода/`.env`.

    Для СПИСКА полей эту функцию звать нельзя — есть `overridden_keys()`.
    Замер 2026-08-19: страница настроек делала 155 запросов, из них 154 —
    вот этот, по одному на поле.
    """
    return field.name in overridden_keys()


def overridden_keys() -> set[str]:
    """Все ключи, у которых есть сохранённое в админке значение — ОДНИМ
    запросом.

    Полей в настройках 154, и раньше страница спрашивала базу про каждое
    отдельно. На SQLite это не падало, но 154 обращения к базе на один
    показ страницы — это 154 остановки общего цикла событий, в котором
    вместе с админкой живут все четыре бота.
    """
    with session_scope() as session:
        return {key for (key,) in session.query(AppSetting.key)}


def reset_setting(key: str) -> bool:
    """Убрать оверлей настройки — вернуться к дефолту кода/`.env`.

    Нужно прежде всего для промптов. Дефолты промптов живут в
    `rewriter/prompts/*.txt` и обновляются с новой версией кода, но
    СОХРАНЁННОЕ в админке значение перекрывает их навсегда: один раз нажав
    «Сохранить» в группе «Рерайт», владелец замораживал тогдашнюю редакцию
    всех промптов группы и больше не получал улучшений — и понять это из
    интерфейса было невозможно.

    Возвращает True, если оверлей действительно был (для честного сообщения
    в UI: «сброшено» против «и так было по умолчанию»).
    """
    if key not in Settings.model_fields:
        raise ValueError(f"Неизвестная настройка: {key}")
    with session_scope() as session:
        deleted = session.query(AppSetting).filter(AppSetting.key == key).delete()
    invalidate_settings_cache()
    if deleted:
        logger.info("Настройка '%s' сброшена к значению по умолчанию", key)
    return bool(deleted)


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


def clear_secret(key: str) -> bool:
    """Удалить сохранённый секрет — `/secrets` раньше не давал способа
    очистить поле (форма `POST /secrets/{key}` с пустым value молча ничего
    не делала), например отключить прокси после его настройки без замены на
    новый (реальная жалоба пользователя). Возвращает True, если запись в БД
    была и удалена.

    Если значение изначально пришло из `.env` (не из БД — см. source="env" в
    `list_secret_status`), этот вызов его не уберёт: `.env` — bootstrap-файл,
    веб-админка его не редактирует. В таком случае эффективное значение
    после очистки останется тем же, что в `.env`, и это ожидаемо, не баг.
    """
    if key not in SECRET_FIELD_NAMES:
        raise ValueError(f"Неизвестный секрет: {key}")
    with session_scope() as session:
        existing = session.query(Secret).filter(Secret.key == key).one_or_none()
        if existing is None:
            return False
        session.delete(existing)
    invalidate_settings_cache()
    logger.info("Секрет '%s' очищен через веб-админку", key)
    return True

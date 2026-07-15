"""Двуязычный (RU/EN) слой текста веб-админки.

Один источник истины для ВСЕХ строк UI — и статичного текста шаблонов
(`{{ t('nav.dashboard') }}`), и динамического текста, собираемого в Python
(заголовки/описания групп настроек, лейблы секретов и т.п. — резолвятся
через `t()` в `webui/app.py`/`webui/crud_routes.py`/`webui/guardian_routes.py`
ДО передачи в шаблон, а не в самом шаблоне, т.к. эти строки приходят как уже
собранный контекст, а не как статичная разметка).

Текущий язык — per-request: middleware в `app.py` читает
`request.session["lang"]` (по умолчанию `"ru"`) и на время обработки запроса
выставляет `ContextVar` — асинхронно-безопасно (каждый HTTP-запрос Starlette
обрабатывает в своей asyncio Task, `ContextVar` копируется per-task, гонки
между параллельными запросами разных админов исключены).
"""

from __future__ import annotations

from contextvars import ContextVar

SUPPORTED_LANGS: tuple[str, ...] = ("ru", "en")
DEFAULT_LANG = "ru"

_current_lang: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)


def set_current_lang(lang: str) -> None:
    """Выставить текущий язык для этого request/task (вызывается middleware)."""
    _current_lang.set(lang if lang in SUPPORTED_LANGS else DEFAULT_LANG)


def get_current_lang() -> str:
    return _current_lang.get()


def normalize_lang(lang: str | None) -> str:
    """Привести произвольную строку к поддерживаемому коду языка —
    используется и middleware (значение из сессии), и роутом `/lang/{code}`
    (значение из URL, ещё не провалидированное)."""
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def humanize_action(action: str, namespace: str = "audit.action") -> str:
    """Человекочитаемый лейбл для сырого ключа действия из `audit_log`/
    `guardian.ModerationLog` (например `source_add` → «Добавлен источник»).
    Такие ключи — внутренние snake_case-идентификаторы, читаемые
    разработчику, но не конечному пользователю (найдено при аудите UI).
    В отличие от `t()`, при отсутствии перевода возвращает САМ `action`
    (не `[key]`-заглушку) — это runtime-значение из БД, а не забытый ключ
    каталога, ломать вид таблицы плейсхолдером не нужно.

    `namespace` переключает каталог между `audit.action.*` (tg_repost
    audit_log) и `guardian_dashboard.action.*` (Guardian ModerationLog) —
    разные наборы событий, разные префиксы ключей."""
    entry = STRINGS.get(f"{namespace}.{action}")
    if entry is None:
        return action
    return entry.get(get_current_lang(), entry.get(DEFAULT_LANG, action))


def t(key: str, **kwargs: object) -> str:
    """Перевести строку по ключу на текущий язык (см. `get_current_lang()`).

    Отсутствующий ключ — не 500-я и не пустая строка (это ломало бы UI молча
    и было бы незаметно при рерайте копирайтинга), а сам ключ в квадратных
    скобках — сразу видно на странице/в тесте, что перевод забыли добавить.
    `**kwargs` — простая `.format()`-подстановка для строк со счётчиками
    (например `t("audit.footer", total=42, page=1, pages=3)`).
    """
    entry = STRINGS.get(key)
    if entry is None:
        return f"[{key}]"
    text = entry.get(get_current_lang(), entry.get(DEFAULT_LANG, f"[{key}]"))
    return text.format(**kwargs) if kwargs else text


# ---------------------------------------------------------------------------
# Каталог строк. Организован по разделам приложения, не по языку — так легко
# видеть RU/EN пару рядом и не разойтись в смысле при правке одного языка.
# ---------------------------------------------------------------------------
STRINGS: dict[str, dict[str, str]] = {
    # --- Общее: навигация, бренд ---
    "app.brand": {"ru": "tg_repost", "en": "tg_repost"},
    "app.brand.guardian": {"ru": "Guardian", "en": "Guardian"},
    "nav.dashboard": {"ru": "Дашборд", "en": "Dashboard"},
    "nav.sources": {"ru": "Источники", "en": "Sources"},
    "nav.targets": {"ru": "Цели", "en": "Targets"},
    "nav.moderation": {"ru": "Модерация", "en": "Moderation"},
    "nav.ads": {"ru": "Реклама", "en": "Ads"},
    "nav.telethon_sessions": {"ru": "Telethon-сессии", "en": "Telethon sessions"},
    "nav.stats": {"ru": "Статистика", "en": "Stats"},
    "nav.components": {"ru": "Компоненты", "en": "Components"},
    "nav.settings": {"ru": "Настройки и секреты", "en": "Settings & secrets"},
    "nav.audit": {"ru": "Журнал изменений", "en": "Audit log"},
    "nav.logs": {"ru": "Логи", "en": "Logs"},
    "nav.guardian_dashboard": {"ru": "Дашборд", "en": "Dashboard"},
    "nav.guardian_settings": {"ru": "Настройки", "en": "Settings"},
    "nav.guardian_stopwords": {"ru": "Стоп-слова", "en": "Stop words"},
    "nav.guardian_domains": {"ru": "Whitelist доменов", "en": "Domain whitelist"},
    "nav.guardian_trusted": {"ru": "Исключения", "en": "Trusted users"},
    "nav.logout": {"ru": "Выйти", "en": "Log out"},
    "nav.lang_switch": {"ru": "Язык", "en": "Language"},

    # --- Общие слова действий (унифицированы по всему приложению) ---
    "common.save": {"ru": "Сохранить", "en": "Save"},
    "common.save_group": {"ru": "Сохранить группу", "en": "Save group"},
    "common.add": {"ru": "Добавить", "en": "Add"},
    "common.delete": {"ru": "Удалить", "en": "Delete"},
    "common.clear": {"ru": "Очистить", "en": "Clear"},
    "common.show": {"ru": "Показать", "en": "Reveal"},
    "common.activate": {"ru": "Активировать", "en": "Activate"},
    "common.deactivate": {"ru": "Деактивировать", "en": "Deactivate"},
    "common.cancel": {"ru": "Отмена", "en": "Cancel"},
    "common.open": {"ru": "Открыть", "en": "Open"},
    "common.apply_now": {"ru": "Применить сейчас", "en": "Apply now"},
    "common.restart": {"ru": "Перезапустить", "en": "Restart"},
    "common.yes": {"ru": "Да", "en": "Yes"},
    "common.no": {"ru": "Нет", "en": "No"},
    "common.status": {"ru": "Статус", "en": "Status"},
    "common.source": {"ru": "Источник", "en": "Source"},
    "common.not_set": {"ru": "не задан", "en": "not set"},
    "common.unlimited": {"ru": "без лимита", "en": "unlimited"},
    "common.all": {"ru": "все", "en": "all"},
    "common.new_value": {"ru": "новое значение", "en": "new value"},
    "common.source.db": {"ru": "веб-админка", "en": "web admin"},
    "common.source.env": {"ru": ".env", "en": ".env"},
    "common.source.unset": {"ru": "—", "en": "—"},
    # ВНИМАНИЕ: строки confirm_* подставляются в JS `confirm('...')` внутри
    # HTML-атрибута `onsubmit` в шаблонах (см. `_macros.html::confirm_form`)
    # — НЕ добавляй в них апострофы/одинарные кавычки. Jinja-автоэкранирование
    # HTML-кодирует `'` в `&#39;`, браузер декодирует его обратно в `'` ДО
    # передачи JS-парсеру — получится преждевременно оборванная строка и
    # синтаксическая ошибка, а не безопасное экранирование.
    "common.confirm_delete": {
        "ru": "Удалить эту запись? Действие необратимо.",
        "en": "Delete this record? This cannot be undone.",
    },
    "common.confirm_deactivate": {
        "ru": "Деактивировать эту запись?",
        "en": "Deactivate this record?",
    },
    "common.confirm_clear_secret": {
        "ru": "Очистить этот секрет? Значение нельзя будет восстановить, потребуется ввести заново.",
        "en": "Clear this secret? The value cannot be recovered — you will need to re-enter it.",
    },
    "common.empty_list": {"ru": "Записей нет.", "en": "No records."},
    "common.enrich_global": {"ru": "по умолч.", "en": "default"},
    "common.list_truncated": {
        "ru": "Показаны первые {limit} записей — уточните список, если их больше.",
        "en": "Showing the first {limit} records — narrow the list if there are more.",
    },
    "common.resync_badge": {"ru": "resync", "en": "resync"},

    # --- Логин ---
    "login.title": {"ru": "Вход", "en": "Log in"},
    "login.password_placeholder": {"ru": "Пароль", "en": "Password"},
    "login.submit": {"ru": "Войти", "en": "Log in"},
    "login.error_wrong_password": {"ru": "Неверный пароль", "en": "Wrong password"},
    "login.error_locked": {
        "ru": "Слишком много неудачных попыток — подожди немного и попробуй снова.",
        "en": "Too many failed attempts — wait a bit and try again.",
    },

    # --- Первый запуск ---
    "setup.title": {"ru": "Первый запуск", "en": "First-time setup"},
    "setup.intro": {
        "ru": "Создай пароль администратора и (опционально) сразу укажи "
        "минимум секретов — всё, что оставишь пустым, можно будет заполнить "
        "позже на «<a href=\"/settings\">Настройки и секреты</a>».",
        "en": "Create an admin password and (optionally) fill in a minimum "
        "of secrets right away — anything left blank can be filled in "
        "later on “<a href=\"/settings\">Settings &amp; secrets</a>”.",
    },
    "setup.telethon_not_connected": {
        "ru": "Telethon-аккаунт ещё не подключён.", "en": "No Telethon account linked yet.",
    },
    "setup.password_section_title": {
        "ru": "Пароль администратора", "en": "Admin password",
    },
    "setup.password_placeholder": {
        "ru": "Пароль (мин. 8 символов)", "en": "Password (min. 8 characters)",
    },
    "setup.password_confirm_placeholder": {
        "ru": "Повтори пароль", "en": "Confirm password",
    },
    "setup.telegram_section_title": {
        "ru": "Telegram (опционально сейчас)", "en": "Telegram (optional for now)",
    },
    "setup.telegram_section_desc": {
        "ru": "TG_API_ID и TG_API_HASH — с <a href=\"https://my.telegram.org\" "
        "target=\"_blank\" rel=\"noopener\">my.telegram.org</a>, раздел «API "
        "development tools». TG_BOT_TOKEN — от @BotFather (/newbot). Можно "
        "оставить пустым и заполнить позже здесь же, на «Настройки и секреты».",
        "en": "TG_API_ID and TG_API_HASH — from <a href=\"https://my.telegram.org\" "
        "target=\"_blank\" rel=\"noopener\">my.telegram.org</a>, “API "
        "development tools”. TG_BOT_TOKEN — from @BotFather (/newbot). You "
        "can leave this blank and fill it in later on “Settings &amp; secrets”.",
    },
    "setup.rewrite_section_title": {
        "ru": "Рерайт (опционально)", "en": "Rewrite (optional)",
    },
    "setup.rewrite_section_desc": {
        "ru": "Ключ OpenAI-совместимого API — без него посты не будут "
        "переписываться. Можно добавить позже.",
        "en": "OpenAI-compatible API key — without it posts won't be "
        "rewritten. Can be added later.",
    },
    "setup.telethon_connected": {
        "ru": "✅ Telegram-сессия уже привязана", "en": "✅ Telegram session already linked",
    },
    "setup.telethon_connect_cta": {
        "ru": "Войти через Telegram →", "en": "Sign in with Telegram →",
    },
    "setup.submit": {
        "ru": "Создать администратора и продолжить", "en": "Create admin and continue",
    },
    "setup.error_password_mismatch": {
        "ru": "Пароли не совпадают или короче 8 символов",
        "en": "Passwords don't match or are shorter than 8 characters",
    },
    "setup_locked.title": {"ru": "Нужен токен установки", "en": "Setup token required"},
    "setup_locked.body": {
        "ru": "Первичная настройка (<code>/setup</code>) требует одноразовый "
        "токен — он не выводится на этой странице, а только в консоль/файл "
        "лога первого запуска сервера (например <code>docker compose logs "
        "tg_repost</code> или файл <code>logs/tg_repost.log</code>). Открой "
        "ссылку вида <code>/setup?token=...</code> оттуда.",
        "en": "First-time setup (<code>/setup</code>) requires a one-time "
        "token — it isn't shown on this page, only in the console/log of "
        "the server's first start (e.g. <code>docker compose logs "
        "tg_repost</code> or <code>logs/tg_repost.log</code>). Open the "
        "<code>/setup?token=...</code> link from there.",
    },

    # --- Telethon-визард ---
    "telethon_login.page_title": {"ru": "Подключение Telegram-аккаунта", "en": "Connecting a Telegram account"},
    "telethon.step_phone.desc": {
        "ru": "Нужны TG_API_ID/TG_API_HASH с <a href=\"https://my.telegram.org\" "
        "target=\"_blank\" rel=\"noopener\">my.telegram.org</a> (если ещё не "
        "заданы) и номер телефона аккаунта, который будет читать каналы.",
        "en": "Needs TG_API_ID/TG_API_HASH from <a href=\"https://my.telegram.org\" "
        "target=\"_blank\" rel=\"noopener\">my.telegram.org</a> (if not set "
        "yet) and the phone number of the account that will read channels.",
    },
    "telethon.step_code.desc": {
        "ru": "Код отправлен в Telegram — введи его ниже.",
        "en": "The code was sent via Telegram — enter it below.",
    },
    "telethon.step_password.desc": {
        "ru": "Аккаунт защищён облачным паролем (2FA) — введи его.",
        "en": "The account is protected by a cloud password (2FA) — enter it.",
    },
    "telethon.step_phone.title": {"ru": "Номер телефона", "en": "Phone number"},
    "telethon.step_phone.placeholder": {"ru": "+79991234567", "en": "+15551234567"},
    "telethon.step_phone.api_id_placeholder": {
        "ru": "TG_API_ID (если ещё не задан)", "en": "TG_API_ID (if not set yet)",
    },
    "telethon.step_phone.api_hash_placeholder": {
        "ru": "TG_API_HASH (если ещё не задан)", "en": "TG_API_HASH (if not set yet)",
    },
    "telethon.step_phone.submit": {"ru": "Отправить код", "en": "Send code"},
    "telethon.step_phone.missing_creds": {
        "ru": "Укажи TG_API_ID и TG_API_HASH.", "en": "Enter TG_API_ID and TG_API_HASH.",
    },
    "telethon.step_code.title": {"ru": "Код из Telegram", "en": "Code from Telegram"},
    "telethon.step_code.placeholder": {"ru": "12345", "en": "12345"},
    "telethon.step_code.submit": {"ru": "Подтвердить", "en": "Confirm"},
    "telethon.step_password.title": {
        "ru": "Пароль двухфакторки (2FA)", "en": "Two-factor password (2FA)",
    },
    "telethon.step_password.placeholder": {"ru": "Пароль 2FA", "en": "2FA password"},
    "telethon.step_password.submit": {"ru": "Войти", "en": "Sign in"},
    "telethon.step_done.title": {"ru": "Готово", "en": "Done"},
    "telethon.step_done.body": {
        "ru": "Telegram-сессия привязана и сохранена.",
        "en": "Telegram session linked and saved.",
    },
    "telethon.step_done.continue": {"ru": "Продолжить →", "en": "Continue →"},
    "telethon.cancel": {"ru": "← Отменить и назад", "en": "← Cancel and go back"},

    # --- Дашборд ---
    "dashboard.title": {"ru": "Дашборд", "en": "Dashboard"},
    "dashboard.desc": {
        "ru": "Сводка системы: статус компонентов, воронка постов, расход "
        "токенов рерайта, последние посты.",
        "en": "System overview: component status, post funnel, rewrite "
        "token spend, recent posts.",
    },
    "dashboard.not_configured_warning": {
        "ru": "⚠️ Минимальная конфигурация не завершена — Telethon/бот/"
        "планировщик не запущены. Заполни секреты на "
        "<a href=\"/settings\">«Настройки и секреты»</a>.",
        "en": "⚠️ Minimal configuration isn't complete — Telethon/bot/"
        "scheduler aren't running. Fill in the secrets on "
        "<a href=\"/settings\">“Settings &amp; secrets”</a>.",
    },
    "dashboard.components_title": {"ru": "Компоненты", "en": "Components"},
    "dashboard.funnel_title": {"ru": "Посты по статусам", "en": "Posts by status"},
    "dashboard.funnel_empty": {"ru": "Постов ещё нет", "en": "No posts yet"},
    "dashboard.metrics_title": {"ru": "Метрики", "en": "Metrics"},
    "dashboard.tokens_today": {"ru": "Токенов рерайта сегодня", "en": "Rewrite tokens today"},
    "dashboard.error_rate": {"ru": "Доля ошибок за 24ч", "en": "Error rate, 24h"},
    "dashboard.recent_posts_title": {"ru": "Последние посты", "en": "Recent posts"},
    "dashboard.col_id": {"ru": "ID", "en": "ID"},
    "dashboard.col_kind": {"ru": "Вид", "en": "Kind"},
    "dashboard.col_status": {"ru": "Статус", "en": "Status"},
    "dashboard.col_created": {"ru": "Создан", "en": "Created"},
    "dashboard.col_text": {"ru": "Текст", "en": "Text"},

    # --- Источники ---
    "sources.title": {"ru": "Источники", "en": "Sources"},
    "sources.desc": {
        "ru": "Каналы, которые Telethon читает и парсит на новые посты.",
        "en": "Channels that Telethon reads and parses for new posts.",
    },
    "sources.add_placeholder": {"ru": "@channel или ссылка", "en": "@channel or link"},
    "sources.col_active": {"ru": "Активен", "en": "Active"},
    "sources.col_username": {"ru": "Username", "en": "Username"},
    "sources.col_style": {"ru": "Стиль", "en": "Style"},
    "sources.col_enrich": {"ru": "Добор", "en": "Enrichment"},
    "sources.col_targets": {"ru": "Цели", "en": "Targets"},
    "sources.targets_count": {"ru": "{n} груп.", "en": "{n} groups"},
    "sources.add_hint": {
        "ru": "Клик по строке открывает настройки источника (стиль, добор, цели).",
        "en": "Click a row to open the source's settings (style, enrichment, targets).",
    },

    "source_detail.style_label": {"ru": "Стиль рерайта", "en": "Rewrite style"},
    "source_detail.enrich_label": {"ru": "Добор источников", "en": "Source enrichment"},
    "source_detail.enrich_default": {"ru": "по глобальной настройке", "en": "use global setting"},
    "source_detail.enrich_on": {"ru": "включён", "en": "on"},
    "source_detail.enrich_off": {"ru": "выключен", "en": "off"},
    "source_detail.targets_label": {"ru": "Куда публиковать", "en": "Where to publish"},
    "source_detail.targets_hint": {
        "ru": "Отметь целевые группы для этого источника. Ничего не "
        "отмечено — публикуется во все активные цели.",
        "en": "Check the target groups for this source. Nothing checked — "
        "publishes to all active targets.",
    },
    "source_detail.targets_empty_hint": {
        "ru": "Целевых групп пока нет — <a href=\"/targets\">добавь хотя бы "
        "одну</a>, чтобы выбрать, куда публиковать. Сейчас посты идут во "
        "все активные цели.",
        "en": "No target groups yet — <a href=\"/targets\">add at least "
        "one</a> to choose where to publish. Posts currently go to all "
        "active targets.",
    },
    "source_detail.orphan_badge": {
        "ru": "нет в списке целей", "en": "not in target list",
    },
    "source_detail.inactive_badge": {"ru": "неактивна", "en": "inactive"},
    "source_detail.back_link": {"ru": "← К списку источников", "en": "← Back to sources"},
    "source_detail.backfill_title": {"ru": "Сбор истории", "en": "Collect history"},
    "source_detail.backfill_desc": {
        "ru": "Live-поток ловит только новые сообщения. Чтобы забрать уже "
        "вышедшие посты — укажи сколько последних сообщений собрать (через "
        "тот же фильтр/дедуп, что и обычно). Для больших чисел (сотни +) "
        "быстрее из терминала: <code>docker exec -it &lt;контейнер&gt; "
        "python -m tg_repost.cli backfill-source @{channel} --limit N</code>.",
        "en": "The live stream only catches new messages. To pull posts "
        "that already went out — set how many recent messages to collect "
        "(through the same filter/dedup as usual). For large numbers "
        "(hundreds+), it's faster from a terminal: <code>docker exec -it "
        "&lt;container&gt; python -m tg_repost.cli backfill-source "
        "@{channel} --limit N</code>.",
    },
    "source_detail.backfill_limit_placeholder": {"ru": "Сколько сообщений", "en": "How many messages"},
    "source_detail.backfill_submit": {"ru": "Собрать", "en": "Collect"},
    "source_detail.backfill_success": {
        "ru": "✅ Обработано сообщений: {count} (часть могла отфильтроваться/"
        "задвоиться — это штатно, см. очередь модерации).",
        "en": "✅ Processed {count} messages (some may have been filtered "
        "out/deduped — that's expected, see the moderation queue).",
    },
    "source_detail.error_invalid_backfill_limit": {
        "ru": "Количество должно быть целым числом от 1 до {max}.",
        "en": "The count must be an integer from 1 to {max}.",
    },
    "source_detail.error_backfill_not_running": {
        "ru": "Компоненты не запущены — сначала запусти их на странице «Компоненты».",
        "en": "Components aren't running — start them on the “Components” page first.",
    },
    "source_detail.error_invalid_enrich_mode": {
        "ru": "Недопустимый режим добора источников.", "en": "Invalid enrichment mode.",
    },
    "source_detail.error_invalid_targets": {
        "ru": "Цели должны быть числами (chat_id).", "en": "Targets must be numbers (chat_id).",
    },

    # --- Цели ---
    "targets.title": {"ru": "Цели публикации", "en": "Publish targets"},
    "targets.desc": {
        "ru": "Группы/каналы, куда публикуются одобренные посты.",
        "en": "Groups/channels that approved posts get published to.",
    },
    "targets.chat_id_placeholder": {"ru": "chat_id (отрицательный)", "en": "chat_id (negative)"},
    "targets.title_placeholder": {"ru": "Название (опционально)", "en": "Title (optional)"},
    "targets.col_active": {"ru": "Активна", "en": "Active"},
    "targets.col_chat_id": {"ru": "chat_id", "en": "chat_id"},
    "targets.col_title": {"ru": "Название", "en": "Title"},
    "targets.add_hint": {
        "ru": "Активных целей должно быть минимум одна — иначе публикация невозможна.",
        "en": "There must be at least one active target, otherwise publishing is impossible.",
    },
    "targets.error_invalid_chat_id": {
        "ru": "chat_id должен быть целым числом.", "en": "chat_id must be an integer.",
    },
    "targets.discovered_title": {"ru": "Обнаруженные чаты", "en": "Discovered chats"},
    "targets.discovered_desc": {
        "ru": "Бот уже состоит в этих чатах, но они ещё не добавлены как цели "
        "публикации — просто добавь бота в нужную группу/канал, chat_id "
        "определится сам.",
        "en": "The bot is already a member of these chats, but they aren't "
        "publish targets yet — just add the bot to the group/channel you "
        "want, and chat_id is picked up automatically.",
    },
    "targets.discovered_add": {"ru": "Добавить как цель", "en": "Add as target"},

    # --- Модерация ---
    "moderation.title": {"ru": "Очередь модерации", "en": "Moderation queue"},
    "moderation.desc": {
        "ru": "Посты, ожидающие ручного решения — те же, что приходят в "
        "Telegram владельцу с кнопками ✅/❌/✏️.",
        "en": "Posts awaiting a manual decision — the same ones sent to "
        "the owner in Telegram with ✅/❌/✏️ buttons.",
    },
    "moderation.empty": {"ru": "Очередь пуста", "en": "Queue is empty"},
    "moderation.col_kind": {"ru": "Тип", "en": "Kind"},
    "moderation.col_text": {"ru": "Текст", "en": "Text"},
    "moderation.col_created": {"ru": "Создан", "en": "Created"},
    "moderation_detail.title": {"ru": "Пост на модерации", "en": "Post under review"},
    "moderation_detail.source_link": {"ru": "Источник", "en": "Source"},
    "moderation_detail.has_media": {"ru": "🖼 Есть медиа", "en": "🖼 Has media"},
    "moderation_detail.save_text": {"ru": "Сохранить текст", "en": "Save text"},
    "moderation_detail.approve": {"ru": "✅ Одобрить", "en": "✅ Approve"},
    "moderation_detail.reject": {"ru": "❌ Отклонить", "en": "❌ Reject"},
    "moderation_detail.back_link": {"ru": "← К очереди модерации", "en": "← Back to moderation queue"},
    "moderation_detail.confirm_reject": {
        "ru": "Отклонить пост? Действие необратимо.",
        "en": "Reject this post? This cannot be undone.",
    },
    "moderation_detail.error_bot_not_running": {
        "ru": "Бот модерации не запущен — публикация невозможна. Запусти "
        "компоненты на странице «Компоненты».",
        "en": "The moderation bot isn't running — publishing isn't "
        "possible. Start the components on the “Components” page.",
    },

    # --- Реклама ---
    "ads.title": {"ru": "Нативная реклама", "en": "Native ads"},
    "ads.desc": {
        "ru": "Брифы, которые ИИ вплетает в каждый N-й пост (см. настройку "
        "«Нативная реклама» в /settings).",
        "en": "Briefs the AI weaves into every Nth post (see the “Native "
        "ads” setting on /settings).",
    },
    "ads.add_placeholder": {"ru": "Текст брифа", "en": "Brief text"},
    "ads.max_uses_placeholder": {"ru": "Лимит показов, пусто = без лимита", "en": "Usage cap, blank = unlimited"},
    "ads.col_active": {"ru": "Активен", "en": "Active"},
    "ads.col_used": {"ru": "Использован", "en": "Used"},
    "ads.col_limit": {"ru": "Лимит", "en": "Limit"},
    "ads.col_text": {"ru": "Текст", "en": "Text"},
    "ads.error_invalid_max_uses": {
        "ru": "Лимит показов должен быть целым неотрицательным числом или пустым.",
        "en": "The usage cap must be a non-negative integer or blank.",
    },

    # --- Telethon-сессии ---
    "telethon_sessions.title": {"ru": "Дополнительные Telethon-сессии", "en": "Additional Telethon sessions"},
    "telethon_sessions.desc": {
        "ru": "Доп. аккаунты для распределения нагрузки чтения источников "
        "между несколькими сессиями. Сессию нужно получить отдельно: "
        "{cmd} на сервере, скопировать вывод сюда.",
        "en": "Extra accounts to spread source-reading load across several "
        "sessions. Get the session string separately: run {cmd} on the "
        "server and paste the output here.",
    },
    "telethon_sessions.label_placeholder": {"ru": "Метка (например, «второй аккаунт»)", "en": "Label (e.g. “second account”)"},
    "telethon_sessions.session_placeholder": {"ru": "session string", "en": "session string"},
    "telethon_sessions.col_active": {"ru": "Активна", "en": "Active"},
    "telethon_sessions.col_label": {"ru": "Метка", "en": "Label"},
    "telethon_sessions.col_mask": {"ru": "Маска", "en": "Masked value"},
    "telethon_sessions.session_hint": {
        "ru": "Session string даёт полный доступ к аккаунту — вводи только "
        "уже сгенерированную через {cmd} (визарда для доп. аккаунтов пока "
        "нет). Значение никогда не показывается повторно, только маска.",
        "en": "The session string grants full account access — only enter "
        "one already generated via {cmd} (no guided wizard for extra "
        "accounts yet). The value is never shown again, only the mask.",
    },
    "telethon_sessions.empty": {
        "ru": "Дополнительных сессий нет — используется только основная.",
        "en": "No additional sessions — only the primary one is used.",
    },

    # --- Guardian: стоп-слова / домены / доверенные ---
    "guardian_stopwords.title": {"ru": "Стоп-слова Guardian", "en": "Guardian stop words"},
    "guardian_stopwords.desc": {
        "ru": "Сообщение с любым из этих слов ловится фильтром спама.",
        "en": "A message containing any of these words is caught by the spam filter.",
    },
    "guardian_stopwords.add_placeholder": {"ru": "Слово", "en": "Word"},
    "guardian_stopwords.col_word": {"ru": "Слово", "en": "Word"},

    "guardian_domains.title": {"ru": "Whitelist доменов Guardian", "en": "Guardian domain whitelist"},
    "guardian_domains.desc": {
        "ru": "Ссылки на эти домены не считаются спамом — остальные "
        "ссылки в сообщениях новичков ловятся фильтром.",
        "en": "Links to these domains aren't flagged as spam — other "
        "links in newcomers' messages are caught by the filter.",
    },
    "guardian_domains.add_placeholder": {"ru": "Домен (example.com)", "en": "Domain (example.com)"},
    "guardian_domains.col_domain": {"ru": "Домен", "en": "Domain"},
    "guardian_domains.empty": {
        "ru": "Whitelist пуст — любая ссылка считается нарушением.",
        "en": "The whitelist is empty — any link is treated as a violation.",
    },

    "guardian_trusted.title": {"ru": "Доверенные пользователи Guardian", "en": "Guardian trusted users"},
    "guardian_trusted.desc": {
        "ru": "Полностью обходят все фильтры Guardian.",
        "en": "Fully bypass all Guardian filters.",
    },
    "guardian_trusted.no_group_warning": {
        "ru": "⚠️ GUARDIAN_GROUP_ID не задан — прикреплять доверие не к чему.",
        "en": "⚠️ GUARDIAN_GROUP_ID isn't set — nothing to attach trust records to.",
    },
    "guardian_trusted.user_id_placeholder": {"ru": "user_id", "en": "user_id"},
    "guardian_trusted.user_id_hint": {
        "ru": "Числовой Telegram id, не @username — узнать можно переслав "
        "сообщение этого человека боту @userinfobot.",
        "en": "A numeric Telegram id, not @username — find it by "
        "forwarding a message from this person to @userinfobot.",
    },
    "guardian_trusted.no_group_missing_warning": {
        "ru": "⚠️ GUARDIAN_GROUP_ID не задан — добавлять доверенных пока "
        "некуда. Настрой Guardian в <code>.env</code> сначала.",
        "en": "⚠️ GUARDIAN_GROUP_ID isn't set — nothing to attach trust "
        "records to yet. Configure Guardian in <code>.env</code> first.",
    },
    "guardian_trusted.reason_placeholder": {"ru": "Причина (опционально)", "en": "Reason (optional)"},
    "guardian_trusted.col_user_id": {"ru": "user_id", "en": "user_id"},
    "guardian_trusted.col_added_at": {"ru": "Добавлен", "en": "Added"},
    "guardian_trusted.col_added_by": {"ru": "Кем", "en": "By"},
    "guardian_trusted.col_reason": {"ru": "Причина", "en": "Reason"},
    "guardian_trusted.error_no_group": {
        "ru": "GUARDIAN_GROUP_ID не задан — сначала настрой Guardian в .env.",
        "en": "GUARDIAN_GROUP_ID isn't set — configure Guardian in .env first.",
    },
    "guardian_trusted.error_invalid_user_id": {
        "ru": "user_id должен быть целым числом.", "en": "user_id must be an integer.",
    },
    "guardian_trusted.remove": {"ru": "Удалить", "en": "Delete"},

    # --- Статистика ---
    "stats.title": {"ru": "Статистика", "en": "Stats"},
    "stats.desc": {
        "ru": "Просмотры опубликованных постов за последние {days} дн. "
        "Собирается периодически, если включён сбор статистики.",
        "en": "Views of published posts over the last {days} days. "
        "Collected periodically when stats collection is enabled.",
    },
    "stats.top_post_prefix": {"ru": "🏆 Топ пост:", "en": "🏆 Top post:"},
    "stats.views_suffix": {"ru": "просмотров", "en": "views"},
    "stats.tab_overview": {"ru": "Обзор", "en": "Overview"},
    "stats.tab_best_times": {"ru": "Лучшее время", "en": "Best times"},
    "stats.tab_growth": {"ru": "Рост подписчиков", "en": "Growth"},
    "stats.published": {"ru": "Опубликовано", "en": "Published"},
    "stats.tracked": {"ru": "Учтено в статистике", "en": "Tracked"},
    "stats.views_total": {"ru": "Суммарно просмотров", "en": "Total views"},
    "stats.views_avg": {"ru": "Среднее просмотров/пост", "en": "Avg. views/post"},
    "stats.top_post": {"ru": "🏆 Топ-пост", "en": "🏆 Top post"},
    "stats.top_post_empty": {"ru": "Пока недостаточно данных", "en": "Not enough data yet"},

    "best_times.title": {"ru": "Лучшее время публикации", "en": "Best posting times"},
    "best_times.desc": {
        "ru": "Анализирует, в какие часы прошлые посты собирали больше "
        "просмотров, и предлагает слоты автопубликации под пик активности.",
        "en": "Analyzes which hours past posts got the most views, and "
        "suggests auto-posting slots for peak audience activity.",
    },
    "best_times.auto_apply_hint": {
        "ru": "Можно также включить автоприменение раз в сутки — группа "
        "«Умное расписание» в настройках.",
        "en": "You can also enable daily auto-apply — the “Smart "
        "schedule” group in settings.",
    },
    "best_times.back_link": {"ru": "← К статистике", "en": "← Back to stats"},
    "best_times.not_enough_data": {
        "ru": "Недостаточно данных: проанализировано {analyzed}, нужно минимум {need}.",
        "en": "Not enough data: analyzed {analyzed}, need at least {need}.",
    },
    "best_times.analyzed": {"ru": "Проанализировано постов: {n}", "en": "Posts analyzed: {n}"},
    "best_times.recommended_hours": {"ru": "Рекомендованные часы (UTC)", "en": "Recommended hours (UTC)"},
    "best_times.applied": {"ru": "✅ Применено", "en": "✅ Applied"},

    "growth.title": {"ru": "Отчёт о росте", "en": "Growth report"},
    "growth.window_desc": {"ru": "За последние {days} дн.", "en": "Over the last {days} days."},
    "growth.auto_track_hint": {
        "ru": "Включи отслеживание роста в настройках и подожди накопления данных.",
        "en": "Enable growth tracking in settings and wait for data to accumulate.",
    },
    "growth.na": {"ru": "н/д", "en": "n/a"},
    "growth.back_link": {"ru": "← К статистике", "en": "← Back to stats"},
    "growth.not_enough_data": {
        "ru": "Недостаточно снимков: есть {have}, нужно минимум {need}.",
        "en": "Not enough snapshots: have {have}, need at least {need}.",
    },
    "growth.before": {"ru": "Было", "en": "Before"},
    "growth.after": {"ru": "Стало", "en": "After"},
    "growth.delta": {"ru": "Изменение", "en": "Change"},
    "growth.by_style_title": {"ru": "По стилям", "en": "By style"},
    "growth.col_style": {"ru": "Стиль", "en": "Style"},
    "growth.col_posts": {"ru": "Постов", "en": "Posts"},
    "growth.footnote": {
        "ru": "Это счётчики, не статистическая корреляция — не делай "
        "выводов о причинно-следственной связи только по ним.",
        "en": "These are counts, not a statistical correlation — don't "
        "draw cause-and-effect conclusions from them alone.",
    },

    # --- Настройки (общие для страницы) ---
    "settings.title": {"ru": "Настройки и секреты", "en": "Settings & secrets"},
    "settings.intro": {
        "ru": "Каждая группа сохраняется независимо. Поля {resync} "
        "дополнительно синхронизируют задачи планировщика (см. "
        "«Компоненты»). Секреты — write-only: показать значение можно "
        "кнопкой «Показать» после повторного ввода пароля.",
        "en": "Each group saves independently. Fields marked {resync} "
        "also sync scheduler jobs (see “Components”). Secrets are "
        "write-only: reveal a value with the “Show” button after "
        "re-entering your password.",
    },
    "settings.secrets_subtitle": {"ru": "Секреты группы", "en": "Group secrets"},
    "settings.env_source_note": {
        "ru": "задан в .env — «Очистить» тут не поможет, редактируй файл на сервере",
        "en": "set in .env — “Clear” won't remove it, edit the file on the server",
    },
    "settings.revealed_once_note": {
        "ru": "Показано один раз — обнови страницу, чтобы скрыть:",
        "en": "Shown once — refresh the page to hide it:",
    },
    "settings.password_placeholder": {"ru": "пароль администратора", "en": "admin password"},
    "settings.telethon_manual_toggle": {
        "ru": "…или вставить готовую session string вручную",
        "en": "…or paste an existing session string manually",
    },
    "settings.telethon_login_cta": {"ru": "Войти через Telegram →", "en": "Sign in with Telegram →"},
    "settings.jump_to": {"ru": "Перейти к разделу", "en": "Jump to section"},
    "settings.error_invalid_number": {
        "ru": "Некорректное значение в группе «{group}» — числовое поле должно содержать число.",
        "en": "Invalid value in group “{group}” — a numeric field must contain a number.",
    },
    "settings.error_invalid_choice": {
        "ru": "«{field}» должно быть одним из: {choices}.",
        "en": "“{field}” must be one of: {choices}.",
    },

    # --- Компоненты ---
    "components.title": {"ru": "Компоненты", "en": "Components"},
    "components.desc": {
        "ru": "Рестарт каждого компонента живой — без перезапуска процесса. "
        "Настройки с пометкой {resync} применяются автоматически при "
        "сохранении, ручной рестарт нужен только после смены "
        "session/token в секретах.",
        "en": "Each component restarts live — no process restart needed. "
        "Settings marked {resync} apply automatically on save; a manual "
        "restart is only needed after changing a session/token secret.",
    },
    "components.not_running_warning": {
        "ru": "⚠️ Компоненты не запущены.", "en": "⚠️ Components aren't running.",
    },
    "components.not_configured_note": {
        "ru": "Не хватает обязательных секретов — заполни их на "
        "<a href=\"/settings\">«Настройках»</a>.",
        "en": "Missing required secrets — fill them in on "
        "<a href=\"/settings\">“Settings”</a>.",
    },
    "components.start_now": {"ru": "Запустить сейчас", "en": "Start now"},
    "components.listener_title": {"ru": "Listener", "en": "Listener"},
    "components.bot_title": {"ru": "Бот модерации", "en": "Moderation bot"},
    "components.scheduler_title": {"ru": "Планировщик", "en": "Scheduler"},
    "components.restart_listener": {"ru": "Перезапустить listener", "en": "Restart listener"},
    "components.restart_bot": {"ru": "Перезапустить бота", "en": "Restart bot"},
    "components.resync_scheduler": {"ru": "Применить настройки джобов", "en": "Apply job settings"},
    "components.switch_account": {"ru": "Сменить Telegram-аккаунт →", "en": "Switch Telegram account →"},
    "components.status_running": {"ru": "работает", "en": "running"},
    "components.status_stopped": {"ru": "остановлен", "en": "stopped"},

    # --- Журнал изменений ---
    "audit.title": {"ru": "Журнал изменений", "en": "Audit log"},
    "audit.desc": {
        "ru": "Кто и когда менял настройки/секреты, одобрял посты, "
        "перезапускал компоненты — журнал мутирующих действий из "
        "админки (не общий вывод процесса, см. «Логи»).",
        "en": "Who changed settings/secrets, approved posts, restarted "
        "components, and when — a log of mutating admin actions (not "
        "the process's raw output, see “Logs”).",
    },
    "audit.col_time": {"ru": "Время", "en": "Time"},
    "audit.col_action": {"ru": "Действие", "en": "Action"},
    "audit.col_target": {"ru": "Объект", "en": "Target"},
    "audit.col_detail": {"ru": "Детали", "en": "Detail"},
    "audit.footer": {
        "ru": "Всего записей: {total} · страница {page} из {pages}",
        "en": "Total entries: {total} · page {page} of {pages}",
    },
    "audit.newer": {"ru": "← Новее", "en": "← Newer"},
    "audit.older": {"ru": "Старее →", "en": "Older →"},
    "audit.empty": {"ru": "Записей пока нет", "en": "No entries yet"},

    # --- Логи ---
    "logs.title": {"ru": "Логи", "en": "Logs"},
    "logs.desc": {
        "ru": "Живой поток логов процесса — обновляется само по себе. При "
        "обрыве браузер переподключится сам.",
        "en": "A live stream of the process's logs — updates on its own. "
        "The browser reconnects automatically if the connection drops.",
    },
    "logs.status_connecting": {"ru": "подключение…", "en": "connecting…"},
    "logs.status_live": {"ru": "живо", "en": "live"},
    "logs.status_reconnecting": {"ru": "переподключение…", "en": "reconnecting…"},

    # --- Guardian: дашборд ---
    "guardian_dashboard.title": {"ru": "Guardian", "en": "Guardian"},
    "guardian_dashboard.desc": {
        "ru": "Отдельный бот-модератор группового чата — свой процесс, "
        "своя БД, читается и пишется напрямую отсюда.",
        "en": "A separate group-chat moderation bot — its own process, "
        "its own database, read and written directly from here.",
    },
    "guardian_dashboard.recent_actions_empty": {
        "ru": "Действий ещё не было.", "en": "No actions yet.",
    },
    "guardian_dashboard.not_configured_warning": {
        "ru": "⚠️ GUARDIAN_BOT_TOKEN/GUARDIAN_GROUP_ID не заданы — правь "
        "`.env` на сервере, отсюда не редактируются.",
        "en": "⚠️ GUARDIAN_BOT_TOKEN/GUARDIAN_GROUP_ID aren't set — edit "
        "`.env` on the server, they can't be edited from here.",
    },
    "guardian_dashboard.config_title": {"ru": "Текущий конфиг", "en": "Current config"},
    "guardian_dashboard.spam_mode": {"ru": "Режим спам-фильтра", "en": "Spam filter mode"},
    "guardian_dashboard.captcha_type": {"ru": "Тип капчи", "en": "Captcha type"},
    "guardian_dashboard.warn_thresholds": {"ru": "Пороги мут / кик / бан", "en": "Mute / kick / ban thresholds"},
    "guardian_dashboard.counters_title": {"ru": "Счётчики", "en": "Counters"},
    "guardian_dashboard.stopwords_count": {"ru": "Стоп-слова", "en": "Stop words"},
    "guardian_dashboard.domains_count": {"ru": "Домены whitelist", "en": "Whitelisted domains"},
    "guardian_dashboard.trusted_count": {"ru": "Доверенные", "en": "Trusted users"},
    "guardian_dashboard.members_count": {"ru": "Участников", "en": "Members"},
    "guardian_dashboard.banned_count": {"ru": "Забанено", "en": "Banned"},
    "guardian_dashboard.recent_actions_title": {"ru": "Последние действия модерации", "en": "Recent moderation actions"},
    "guardian_dashboard.col_when": {"ru": "Когда", "en": "When"},
    "guardian_dashboard.col_action": {"ru": "Действие", "en": "Action"},
    "guardian_dashboard.col_user": {"ru": "Пользователь", "en": "User"},
    "guardian_dashboard.col_reason": {"ru": "Причина", "en": "Reason"},
    "guardian_dashboard.col_by": {"ru": "Кто", "en": "By"},

    "guardian_settings.title": {"ru": "Настройки Guardian", "en": "Guardian settings"},
    # --- Журнал изменений: человекочитаемые лейблы сырых action-ключей ---
    "audit.action.setup_completed": {"ru": "Первичная настройка", "en": "Initial setup"},
    "audit.action.setting_set": {"ru": "Изменена настройка", "en": "Setting changed"},
    "audit.action.secret_set": {"ru": "Сохранён секрет", "en": "Secret saved"},
    "audit.action.secret_clear": {"ru": "Очищен секрет", "en": "Secret cleared"},
    "audit.action.secret_reveal": {"ru": "Показан секрет", "en": "Secret revealed"},
    "audit.action.telethon_session_set": {"ru": "Привязана Telegram-сессия", "en": "Telegram session linked"},
    "audit.action.component_start": {"ru": "Компоненты запущены", "en": "Components started"},
    "audit.action.component_restart": {"ru": "Компонент перезапущен", "en": "Component restarted"},
    "audit.action.component_resync": {"ru": "Джобы синхронизированы", "en": "Jobs synced"},
    "audit.action.source_add": {"ru": "Добавлен источник", "en": "Source added"},
    "audit.action.source_reactivate": {"ru": "Источник реактивирован", "en": "Source reactivated"},
    "audit.action.source_update": {"ru": "Источник изменён", "en": "Source updated"},
    "audit.action.source_deactivate": {"ru": "Источник деактивирован", "en": "Source deactivated"},
    "audit.action.source_backfill": {"ru": "Собрана история источника", "en": "Source history collected"},
    "audit.action.target_add": {"ru": "Добавлена цель", "en": "Target added"},
    "audit.action.target_toggle": {"ru": "Цель переключена", "en": "Target toggled"},
    "audit.action.telethon_session_add": {"ru": "Добавлена доп. сессия", "en": "Extra session added"},
    "audit.action.telethon_session_disable": {"ru": "Доп. сессия отключена", "en": "Extra session disabled"},
    "audit.action.post_approve": {"ru": "Пост одобрен", "en": "Post approved"},
    "audit.action.post_reject": {"ru": "Пост отклонён", "en": "Post rejected"},
    "audit.action.post_edit": {"ru": "Пост отредактирован", "en": "Post edited"},
    "audit.action.ad_brief_add": {"ru": "Добавлен рекламный бриф", "en": "Ad brief added"},
    "audit.action.ad_brief_disable": {"ru": "Рекламный бриф отключён", "en": "Ad brief disabled"},
    "audit.action.guardian_setting_set": {"ru": "Изменена настройка Guardian", "en": "Guardian setting changed"},
    "audit.action.guardian_stopword_add": {"ru": "Добавлено стоп-слово", "en": "Stop word added"},
    "audit.action.guardian_stopword_remove": {"ru": "Удалено стоп-слово", "en": "Stop word removed"},
    "audit.action.guardian_domain_add": {"ru": "Добавлен домен в whitelist", "en": "Domain whitelisted"},
    "audit.action.guardian_domain_remove": {"ru": "Домен убран из whitelist", "en": "Domain removed from whitelist"},
    "audit.action.guardian_trust_add": {"ru": "Добавлен доверенный пользователь", "en": "Trusted user added"},
    "audit.action.guardian_trust_remove": {"ru": "Убран доверенный пользователь", "en": "Trusted user removed"},

    # --- Guardian ModerationLog: человекочитаемые лейблы (см. namespace
    # "guardian_dashboard.action" в humanize_action) ---
    "guardian_dashboard.action.warn": {"ru": "Предупреждение", "en": "Warning"},
    "guardian_dashboard.action.mute": {"ru": "Мут", "en": "Mute"},
    "guardian_dashboard.action.unmute": {"ru": "Снят мут", "en": "Unmute"},
    "guardian_dashboard.action.kick": {"ru": "Кик", "en": "Kick"},
    "guardian_dashboard.action.ban": {"ru": "Бан", "en": "Ban"},
    "guardian_dashboard.action.unban": {"ru": "Снят бан", "en": "Unban"},
    "guardian_dashboard.action.verify": {"ru": "Прошёл капчу", "en": "Passed captcha"},
    "guardian_dashboard.action.trust": {"ru": "Добавлен в доверенные", "en": "Trusted"},
    "guardian_dashboard.action.untrust": {"ru": "Убран из доверенных", "en": "Untrusted"},
    "guardian_dashboard.action.delete_msg": {"ru": "Удалено сообщение", "en": "Message deleted"},
    "guardian_dashboard.action.link_flagged": {"ru": "Помечена ссылка", "en": "Link flagged"},
    "guardian_dashboard.action.raid_end": {"ru": "Антирейд снят", "en": "Anti-raid lifted"},
    "guardian_dashboard.action.raid_detected": {"ru": "Обнаружен рейд", "en": "Raid detected"},

    "guardian_settings.intro": {
        "ru": "Применяются сразу, без перезапуска — Guardian перечитывает их "
        "из БД. Токен бота, id группы и OpenAI-ключ — не здесь: токен/группа "
        "в `.env` на сервере, OpenAI-ключ общий с репост-ботом ({link}).",
        "en": "Applied immediately, no restart needed — Guardian re-reads "
        "them from the DB. Bot token, group id, and the OpenAI key aren't "
        "here: token/group live in `.env` on the server, the OpenAI key is "
        "shared with the repost bot ({link}).",
    },

    # --- Настройки tg_repost: заголовки/описания групп (settings_store.py) ---
    "settings.group.telegram.title": {"ru": "Telegram (идентичность)", "en": "Telegram (identity)"},
    "settings.group.telegram.desc": {
        "ru": "Данные приложения с my.telegram.org — не токен бота, другой "
        "тип credentials.",
        "en": "Application credentials from my.telegram.org — not the bot "
        "token, a different kind of credential.",
    },
    "settings.group.proxy.title": {"ru": "Прокси — MTProto для Telethon", "en": "Proxy — MTProto for Telethon"},
    "settings.group.proxy.desc": {
        "ru": "Если Telegram зарезан — сначала попробуй секрет «Telethon "
        "SOCKS5» ниже, он проще и без ограничения fake-TLS. Эта пара "
        "host/port — альтернативный MTProto-путь, не работает с секретами "
        "формата ee.",
        "en": "If Telegram is blocked — try the “Telethon SOCKS5” secret "
        "below first, it's simpler and has no fake-TLS limitation. This "
        "host/port pair is the alternative MTProto path — doesn't work "
        "with ee-format secrets.",
    },
    "settings.group.rewrite.title": {"ru": "Рерайт", "en": "Rewrite"},
    "settings.group.rewrite.desc": {
        "ru": "Любой OpenAI-совместимый провайдер — необязательно сам OpenAI. "
        "Если в посте есть ссылка — бот переходит по ней и рерайтит по "
        "полному тексту статьи, а не только по короткому анонсу.",
        "en": "Any OpenAI-compatible provider — not necessarily OpenAI itself. "
        "If the post contains a link, the bot follows it and rewrites from "
        "the full article text, not just the short teaser.",
    },
    "settings.group.filtering.title": {"ru": "Фильтрация по словам", "en": "Word filtering"},
    "settings.group.filtering.desc": {
        "ru": "Через запятую. Стоп-слово — пост отфильтровывается; "
        "обязательные слова — пост без ни одного из них тоже отфильтровывается.",
        "en": "Comma-separated. A stop word filters the post out; if any "
        "required words are set, a post with none of them is also filtered out.",
    },
    "settings.group.pipeline.title": {"ru": "Пайплайн", "en": "Pipeline"},
    "settings.group.pipeline.desc": {
        "ru": "Авто-постинг без модерации публикует посты сразу, без кнопок "
        "одобрения — включай осознанно.",
        "en": "Auto-post without moderation publishes posts immediately, "
        "no approval buttons — enable deliberately.",
    },
    "settings.group.antiban.title": {"ru": "Антибан", "en": "Anti-ban"},
    "settings.group.antiban.desc": {
        "ru": "Джиттер и почасовой лимит снижают риск ограничений "
        "юзер-сессии Telegram.",
        "en": "Jitter and an hourly cap reduce the risk of Telegram "
        "restricting the user session.",
    },
    "settings.group.posting_schedule.title": {"ru": "Расписание публикации", "en": "Posting schedule"},
    "settings.group.posting_schedule.desc": {
        "ru": "Если включено — одобренные посты выходят по расписанию, не "
        "мгновенно. Время — UTC.",
        "en": "If enabled, approved posts go out on a schedule instead of "
        "instantly. Time is UTC.",
    },
    "settings.group.semantic_dedup.title": {"ru": "Семантический дубль-чек", "en": "Semantic dedup"},
    "settings.group.semantic_dedup.desc": {
        "ru": "Ловит перефразированные повторы через эмбеддинги — тратит "
        "токены на каждый пост, поэтому выключено по умолчанию.",
        "en": "Catches paraphrased duplicates via embeddings — costs "
        "tokens per post, off by default.",
    },
    "settings.group.stats.title": {"ru": "Статистика", "en": "Stats"},
    "settings.group.stats.desc": {
        "ru": "Сбор просмотров/пересылок/реакций через Telethon.",
        "en": "Collects views/forwards/reactions via Telethon.",
    },
    "settings.group.negative_reactions.title": {"ru": "Реакция на негатив", "en": "Negative reaction response"},
    "settings.group.negative_reactions.desc": {
        "ru": "При превышении порога негативных реакций шлёт уведомление "
        "владельцу; авто-удаление — отдельная опция, с потолком в час.",
        "en": "Notifies the owner past the negative-reaction threshold; "
        "auto-delete is a separate option, capped per hour.",
    },
    "settings.group.style_profiles.title": {"ru": "Стиль-профили", "en": "Style profiles"},
    "settings.group.style_profiles.desc": {
        "ru": "Промпт рерайта по умолчанию, если у источника нет своего.",
        "en": "Default rewrite prompt when a source doesn't set its own.",
    },
    "settings.group.enrichment.title": {"ru": "Добор источников", "en": "Source enrichment"},
    "settings.group.enrichment.desc": {
        "ru": "Ищет через Brave Search доп. ссылки по теме поста. Нужен "
        "ключ Brave ниже, иначе блок не добавляется.",
        "en": "Finds extra links on the post's topic via Brave Search. "
        "Needs the Brave key below, otherwise the block isn't added.",
    },
    "settings.group.covers.title": {"ru": "Авто-обложки", "en": "Auto covers"},
    "settings.group.covers.desc": {
        "ru": "unsplash — стоковое фото по ключевым словам; comfyui — "
        "AI-генерация через локальную установку.",
        "en": "unsplash — stock photo by keywords; comfyui — AI generation "
        "via your local install.",
    },
    "settings.group.smart_schedule.title": {"ru": "Умное расписание", "en": "Smart schedule"},
    "settings.group.smart_schedule.desc": {
        "ru": "Рекомендует часы публикации по истории просмотров (см. "
        "«Лучшее время»); без автоприменения только советует.",
        "en": "Recommends posting hours from view history (see “Best "
        "times”); without auto-apply it only suggests.",
    },
    "settings.group.digest.title": {"ru": "Авто-дайджест", "en": "Auto digest"},
    "settings.group.digest.desc": {
        "ru": "Раз в неделю ИИ собирает топ постов в сводный обзор и "
        "публикует его как обычный пост.",
        "en": "Once a week the AI compiles top posts into a digest and "
        "publishes it like a regular post.",
    },
    "settings.group.ads.title": {"ru": "Нативная реклама", "en": "Native ads"},
    "settings.group.ads.desc": {
        "ru": "Каждый N-й опубликованный пост сопровождается рекламным из "
        "брифов (страница «Реклама»).",
        "en": "Every Nth published post is paired with an ad from a brief "
        "(the “Ads” page).",
    },
    "settings.group.growth.title": {"ru": "Growth-трекер", "en": "Growth tracker"},
    "settings.group.growth.desc": {
        "ru": "Снимает число подписчиков целевых каналов через Telethon.",
        "en": "Snapshots target channel subscriber counts via Telethon.",
    },

    # --- Настройки tg_repost: лейблы полей ---
    "settings.field.tg_api_id.label": {"ru": "API ID", "en": "API ID"},
    "settings.field.tg_owner_user_id.label": {"ru": "Owner user ID", "en": "Owner user ID"},
    "settings.field.mtproto_proxy_host.label": {"ru": "MTProto host", "en": "MTProto host"},
    "settings.field.mtproto_proxy_port.label": {"ru": "MTProto port", "en": "MTProto port"},
    "settings.field.openai_base_url.label": {"ru": "Base URL", "en": "Base URL"},
    "settings.field.openai_model.label": {"ru": "Модель", "en": "Model"},
    "settings.field.fetch_link_content_enabled.label": {
        "ru": "Переходить по ссылке в посте", "en": "Follow link in post",
    },
    "settings.field.rewrite_prompt_template.label": {"ru": "Промпт рерайта", "en": "Rewrite prompt"},
    "settings.field.filter_stop_words.label": {"ru": "Стоп-слова", "en": "Stop words"},
    "settings.field.filter_required_words.label": {"ru": "Обязательные слова", "en": "Required words"},
    "settings.field.pipeline_interval_seconds.label": {"ru": "Интервал тика, сек", "en": "Tick interval, sec"},
    "settings.field.auto_post_enabled.label": {"ru": "Авто-постинг без модерации", "en": "Auto-post without moderation"},
    "settings.field.log_level.label": {"ru": "Уровень логирования", "en": "Log level"},
    "settings.field.listener_min_delay_seconds.label": {"ru": "Мин. задержка, сек", "en": "Min delay, sec"},
    "settings.field.listener_max_delay_seconds.label": {"ru": "Макс. задержка, сек", "en": "Max delay, sec"},
    "settings.field.max_reads_per_hour.label": {"ru": "Лимит чтений в час", "en": "Reads/hour cap"},
    "settings.field.scheduled_posting_enabled.label": {"ru": "Публикация по слотам", "en": "Slot-based posting"},
    "settings.field.posting_slots.label": {"ru": "Слоты (HH:MM)", "en": "Slots (HH:MM)"},
    "settings.field.posting_batch_per_slot.label": {"ru": "Постов за слот", "en": "Posts per slot"},
    "settings.field.semantic_dedup_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.openai_embedding_model.label": {"ru": "Модель эмбеддингов", "en": "Embedding model"},
    "settings.field.semantic_similarity_threshold.label": {"ru": "Порог сходства", "en": "Similarity threshold"},
    "settings.field.dedup_window_days.label": {"ru": "Окно сравнения, дней", "en": "Comparison window, days"},
    "settings.field.stats_enabled.label": {"ru": "Сбор статистики включён", "en": "Stats collection enabled"},
    "settings.field.stats_interval_minutes.label": {"ru": "Период опроса, мин", "en": "Poll interval, min"},
    "settings.field.stats_window_days.label": {"ru": "Окно для /stats, дней", "en": "/stats window, days"},
    "settings.field.negative_reaction_threshold.label": {"ru": "Порог негативных реакций (0=выкл)", "en": "Negative reaction threshold (0=off)"},
    "settings.field.auto_delete_on_negative.label": {"ru": "Авто-удалять при превышении", "en": "Auto-delete when exceeded"},
    "settings.field.max_auto_deletes_per_hour.label": {"ru": "Потолок авто-удалений в час", "en": "Auto-delete cap/hour"},
    "settings.field.default_style_profile.label": {"ru": "Профиль по умолчанию", "en": "Default profile"},
    "settings.field.enable_source_enrichment.label": {"ru": "Включён глобально", "en": "Enabled globally"},
    "settings.field.brave_search_url.label": {"ru": "Brave Search URL", "en": "Brave Search URL"},
    "settings.field.enrichment_max_results.label": {"ru": "Макс. результатов поиска", "en": "Max search results"},
    "settings.field.enrichment_max_sources.label": {"ru": "Макс. источников в посте", "en": "Max sources per post"},
    "settings.field.version_comparison_enabled.label": {"ru": "Сравнение версий источников", "en": "Compare source versions"},
    "settings.field.enable_auto_cover.label": {"ru": "Включены", "en": "Enabled"},
    "settings.field.cover_strategy.label": {"ru": "Стратегия", "en": "Strategy"},
    "settings.field.unsplash_api_url.label": {"ru": "Unsplash API URL", "en": "Unsplash API URL"},
    "settings.field.comfyui_base_url.label": {"ru": "ComfyUI base URL", "en": "ComfyUI base URL"},
    "settings.field.comfyui_workflow_path.label": {"ru": "Путь к workflow JSON", "en": "Workflow JSON path"},
    "settings.field.comfyui_positive_node_id.label": {"ru": "ID узла промпта", "en": "Prompt node ID"},
    "settings.field.comfyui_poll_attempts.label": {"ru": "Попыток опроса", "en": "Poll attempts"},
    "settings.field.comfyui_poll_interval_seconds.label": {"ru": "Интервал опроса, сек", "en": "Poll interval, sec"},
    "settings.field.smart_schedule_min_posts.label": {"ru": "Мин. постов для рекомендации", "en": "Min posts for a recommendation"},
    "settings.field.smart_schedule_top_n.label": {"ru": "Топ-N часов", "en": "Top-N hours"},
    "settings.field.smart_schedule_window_days.label": {"ru": "Окно анализа, дней", "en": "Analysis window, days"},
    "settings.field.smart_schedule_auto_apply.label": {"ru": "Автоприменение раз в сутки", "en": "Auto-apply daily"},
    "settings.field.digest_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.digest_day_of_week.label": {"ru": "День недели (mon..sun)", "en": "Day of week (mon..sun)"},
    "settings.field.digest_hour.label": {"ru": "Час", "en": "Hour"},
    "settings.field.digest_minute.label": {"ru": "Минута", "en": "Minute"},
    "settings.field.digest_top_n.label": {"ru": "Постов в дайджест", "en": "Posts in digest"},
    "settings.field.digest_window_days.label": {"ru": "Окно отбора, дней", "en": "Selection window, days"},
    "settings.field.ad_every_nth_post.label": {"ru": "Каждый N-й пост (0=выкл)", "en": "Every Nth post (0=off)"},
    "settings.field.growth_tracking_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.growth_snapshot_interval_minutes.label": {"ru": "Период снимков, мин", "en": "Snapshot period, min"},
    "settings.field.growth_min_snapshots.label": {"ru": "Мин. снимков для отчёта", "en": "Min snapshots for a report"},
    "settings.field.growth_report_window_days.label": {"ru": "Окно отчёта, дней", "en": "Report window, days"},

    # --- Секреты tg_repost: лейблы + подсказки ---
    "secrets.field.tg_api_hash.label": {"ru": "Telegram API Hash", "en": "Telegram API Hash"},
    "secrets.field.tg_api_hash.hint": {
        "ru": "Пара с полем «API ID» выше. Получить: my.telegram.org → "
        "API development tools → создать приложение.",
        "en": "Pairs with the “API ID” field above. Get it from "
        "my.telegram.org → API development tools → create an app.",
    },
    "secrets.field.tg_bot_token.label": {"ru": "Telegram Bot Token", "en": "Telegram Bot Token"},
    "secrets.field.tg_bot_token.hint": {
        "ru": "Токен бота для публикации/модерации — не то же самое, что "
        "API ID/Hash. Получить: @BotFather → /newbot.",
        "en": "Bot token for publishing/moderation — not the same as API "
        "ID/Hash. Get it from @BotFather → /newbot.",
    },
    "secrets.field.tg_session_string.label": {"ru": "Telethon Session String", "en": "Telethon Session String"},
    "secrets.field.tg_session_string.hint": {
        "ru": "Привязка твоего аккаунта к Telethon (читает источники). "
        "Проще — кнопка «Войти через Telegram» справа.",
        "en": "Links your account to Telethon (reads sources). Easier — "
        "the “Sign in with Telegram” button on the right.",
    },
    "secrets.field.mtproto_proxy_secret.label": {"ru": "MTProto Proxy Secret", "en": "MTProto Proxy Secret"},
    "secrets.field.mtproto_proxy_secret.hint": {
        "ru": "Секрет-часть MTProto-прокси. Секреты с префиксом ee "
        "(fake-TLS) Telethon НЕ поддерживает — используй SOCKS5 ниже.",
        "en": "Secret part of the MTProto proxy. Telethon does NOT "
        "support ee-prefixed (fake-TLS) secrets — use SOCKS5 below instead.",
    },
    "secrets.field.telethon_proxy_url.label": {
        "ru": "Telethon SOCKS5 Proxy URL (socks5://[user:pass@]host:port)",
        "en": "Telethon SOCKS5 Proxy URL (socks5://[user:pass@]host:port)",
    },
    "secrets.field.telethon_proxy_url.hint": {
        "ru": "SOCKS5-туннель для Telethon — рекомендуемая замена "
        "MTProto-прокси, без ограничения fake-TLS. Имеет приоритет, если заданы оба.",
        "en": "SOCKS5 tunnel for Telethon — the recommended replacement "
        "for the MTProto proxy, no fake-TLS limitation. Takes priority if both are set.",
    },
    "secrets.field.bot_api_proxy_url.label": {
        "ru": "Bot API Proxy URL (socks5://[user:pass@]host:port)",
        "en": "Bot API Proxy URL (socks5://[user:pass@]host:port)",
    },
    "secrets.field.bot_api_proxy_url.hint": {
        "ru": "SOCKS5-прокси для Bot API репост-бота — не MTProto, другой протокол.",
        "en": "SOCKS5 proxy for the repost bot's Bot API — not MTProto, a different protocol.",
    },
    "secrets.field.openai_api_key.label": {"ru": "OpenAI API Key", "en": "OpenAI API Key"},
    "secrets.field.openai_api_key.hint": {
        "ru": "Ключ для рерайта постов через LLM. Подходит любой "
        "OpenAI-совместимый провайдер (см. Base URL выше).",
        "en": "Key for rewriting posts via LLM. Any OpenAI-compatible "
        "provider works (see Base URL above).",
    },
    "secrets.field.brave_api_key.label": {"ru": "Brave Search API Key", "en": "Brave Search API Key"},
    "secrets.field.brave_api_key.hint": {
        "ru": "Для добора источников — поиск по теме поста через Brave "
        "Search API. Без ключа блок просто не добавляется.",
        "en": "For source enrichment — searches the post's topic via Brave "
        "Search API. Without a key the block is simply not added.",
    },
    "secrets.field.unsplash_access_key.label": {"ru": "Unsplash Access Key", "en": "Unsplash Access Key"},
    "secrets.field.unsplash_access_key.hint": {
        "ru": "Для авто-обложек, если выбрана стратегия unsplash. Без "
        "ключа обложка не генерируется.",
        "en": "For auto covers when the unsplash strategy is selected. "
        "Without a key, no cover is generated.",
    },

    # --- Guardian: заголовки/описания групп (guardian/settings_store.py) ---
    "guardian.settings.group.identity.title": {"ru": "Идентичность", "en": "Identity"},
    "guardian.settings.group.identity.desc": {
        "ru": "Отрицательные числа (chat_id групп/каналов). Узнать id — "
        "переслать сообщение боту @getidsbot. Guardian должен быть "
        "администратором в обоих чатах.",
        "en": "Negative numbers (group/channel chat_id). To find an id — "
        "forward a message to @getidsbot. Guardian must be an admin in both chats.",
    },
    "guardian.settings.group.spam_filter.title": {"ru": "Спам-фильтр", "en": "Spam filter"},
    "guardian.settings.group.spam_filter.desc": {
        "ru": "keywords — бесплатно, только стоп-слова. ai — каждое "
        "сообщение через LLM (дороже всего). hybrid (рекомендуется) — "
        "эвристики отбирают подозрительные, только они идут в AI.",
        "en": "keywords — free, stop words only. ai — every message "
        "through an LLM (most expensive). hybrid (recommended) — "
        "heuristics flag suspicious messages, only those go to AI.",
    },
    "guardian.settings.group.captcha.title": {"ru": "Капча", "en": "Captcha"},
    "guardian.settings.group.captcha.desc": {
        "ru": "Что видит новый участник до ответа: math (пример), button "
        "(«я не робот»), question (про канал). Не ответил вовремя — кик.",
        "en": "What a newcomer sees until they answer: math (arithmetic), "
        "button (“I'm not a robot”), question (about the channel). No "
        "answer in time — kicked.",
    },
    "guardian.settings.group.warns.title": {"ru": "Варны и эскалация", "en": "Warnings & escalation"},
    "guardian.settings.group.warns.desc": {
        "ru": "Каждое нарушение — варн. При достижении порога — "
        "автоматический мут/кик/бан. Пороги должны идти по возрастанию.",
        "en": "Every violation is a warning. Hitting a threshold triggers "
        "an automatic mute/kick/ban. Thresholds must increase in order.",
    },
    "guardian.settings.group.flood.title": {"ru": "Антифлуд", "en": "Anti-flood"},
    "guardian.settings.group.flood.desc": {
        "ru": "Слишком много сообщений за короткое окно — варн. "
        "Одинаковый текст подряд ловится отдельно, всегда.",
        "en": "Too many messages in a short window — a warning. "
        "Identical repeated text is always caught separately.",
    },
    "guardian.settings.group.raid.title": {"ru": "Антирейд", "en": "Anti-raid"},
    "guardian.settings.group.raid.desc": {
        "ru": "Всплеск вступлений замораживает права всей группы. "
        "Снимается автоматически после тишины или вручную из лог-канала.",
        "en": "A join spike freezes the whole group's permissions. Lifts "
        "automatically after quiet time, or manually from the log channel.",
    },
    "guardian.settings.group.trust.title": {"ru": "Доверенные", "en": "Trust"},
    "guardian.settings.group.trust.desc": {
        "ru": "Участники без нарушений N дней автоматически обходят все фильтры.",
        "en": "Members with no violations for N days automatically bypass all filters.",
    },
    "guardian.settings.group.profile.title": {"ru": "Анализ профиля", "en": "Profile analysis"},
    "guardian.settings.group.profile.desc": {
        "ru": "Подозрительные признаки нового аккаунта усиливают капчу до "
        "math — не банят и не отклоняют автоматически.",
        "en": "Suspicious signals on a new account escalate the captcha "
        "to math — never auto-bans or auto-rejects.",
    },
    "guardian.settings.group.quiet_hours.title": {"ru": "Тихие часы / строгость", "en": "Quiet hours / strictness"},
    "guardian.settings.group.quiet_hours.desc": {
        "ru": "Строгий режим — варн за любое нарушение. Мягкий — ссылки "
        "вне whitelist только логируются. Время — UTC.",
        "en": "Strict mode warns for any violation. Soft mode only logs "
        "off-whitelist links. Time is UTC.",
    },

    # --- Guardian: лейблы полей ---
    "guardian.settings.field.guardian_group_id.label": {"ru": "id защищаемой группы", "en": "Protected group id"},
    "guardian.settings.field.guardian_log_channel_id.label": {"ru": "id канала для лога модерации", "en": "Moderation log channel id"},
    "guardian.settings.field.spam_mode.label": {"ru": "Режим", "en": "Mode"},
    "guardian.settings.field.ai_spam_confidence_threshold.label": {"ru": "Порог уверенности AI", "en": "AI confidence threshold"},
    "guardian.settings.field.captcha_type.label": {"ru": "Тип", "en": "Type"},
    "guardian.settings.field.captcha_timeout_minutes.label": {"ru": "Тайм-аут, мин", "en": "Timeout, min"},
    "guardian.settings.field.warn_threshold_mute.label": {"ru": "Варнов до мута", "en": "Warnings until mute"},
    "guardian.settings.field.warn_threshold_kick.label": {"ru": "Варнов до кика", "en": "Warnings until kick"},
    "guardian.settings.field.warn_threshold_ban.label": {"ru": "Варнов до бана", "en": "Warnings until ban"},
    "guardian.settings.field.warn_ttl_days.label": {"ru": "Сброс варнов через, дней", "en": "Warnings reset after, days"},
    "guardian.settings.field.mute_duration_hours.label": {"ru": "Длительность мута по умолчанию, ч", "en": "Default mute duration, h"},
    "guardian.settings.field.flood_max_messages.label": {"ru": "Сообщений за окно", "en": "Messages per window"},
    "guardian.settings.field.flood_window_seconds.label": {"ru": "Окно, сек", "en": "Window, sec"},
    "guardian.settings.field.allow_forwards.label": {"ru": "Разрешить форварды", "en": "Allow forwards"},
    "guardian.settings.field.raid_join_threshold.label": {"ru": "Участников за период", "en": "Joins per period"},
    "guardian.settings.field.raid_join_window_minutes.label": {"ru": "Период наблюдения, мин", "en": "Observation period, min"},
    "guardian.settings.field.raid_cooldown_minutes.label": {"ru": "Тишина для снятия режима, мин", "en": "Quiet time to lift, min"},
    "guardian.settings.field.auto_trust_after_days.label": {"ru": "Автодоверие через, дней", "en": "Auto-trust after, days"},
    "guardian.settings.field.profile_suspicion_threshold.label": {"ru": "Порог для усиленной капчи", "en": "Threshold for stricter captcha"},
    "guardian.settings.field.strict_mode.label": {"ru": "Строгий режим сейчас", "en": "Strict mode active now"},
    "guardian.settings.field.quiet_hours_enabled.label": {"ru": "Расписание тихих часов включено", "en": "Quiet hours schedule enabled"},
    "guardian.settings.field.quiet_hours_start_hour.label": {"ru": "Начало строгого режима, час UTC", "en": "Strict mode start, UTC hour"},
    "guardian.settings.field.quiet_hours_end_hour.label": {"ru": "Конец строгого режима, час UTC", "en": "Strict mode end, UTC hour"},
}

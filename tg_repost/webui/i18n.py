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


def opt(key: str, **kwargs: object) -> str:
    """Как `t()`, но для НЕОБЯЗАТЕЛЬНЫХ строк: отсутствующий ключ даёт пустую
    строку, а не `[ключ]`.

    Нужно для подсказок к полям настроек: их около сотни, подсказка осмысленна
    далеко не у каждого поля (у `stats_window_days` название говорит само за
    себя), а `t()` вывалил бы в интерфейс `[settings.field.x.hint]` для всех
    полей без подсказки. Шаблон рендерит блок подсказки только при непустом
    результате.

    Для ОБЯЗАТЕЛЬНЫХ строк по-прежнему `t()` — там молчаливое исчезновение
    текста как раз то, чего мы избегаем.
    """
    entry = STRINGS.get(key)
    if entry is None:
        return ""
    text = entry.get(get_current_lang(), entry.get(DEFAULT_LANG, ""))
    return text.format(**kwargs) if (text and kwargs) else text


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
    "nav.invites": {"ru": "Инвайты", "en": "Invites"},
    "nav.polls": {"ru": "Опросы", "en": "Polls"},
    "nav.export": {"ru": "Экспорт / Импорт", "en": "Export / Import"},
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
    "sources.list_title": {"ru": "Все источники", "en": "All sources"},
    "sources.rss_title": {"ru": "RSS-ленты", "en": "RSS feeds"},
    "sources.rss_desc": {
        "ru": "Записи ленты попадают в ту же очередь, что и посты из каналов: "
              "работают фильтры, стиль-профиль источника, переход по ссылке за "
              "полным текстом статьи и формат публикации. Настраивается всё там "
              "же — на странице источника.",
        "en": "Feed entries land in the same queue as channel posts: filters, "
              "the source style profile, following the link for the full "
              "article text and the publication format all apply. Everything is "
              "configured on the same source page.",
    },
    "sources.rss_placeholder": {
        "ru": "https://example.com/feed/\nhttps://another.site/rss.xml",
        "en": "https://example.com/feed/\nhttps://another.site/rss.xml",
    },
    "sources.rss_hint": {
        "ru": "Можно несколько сразу — по одной на строку или через запятую. "
              "Повторное добавление той же ленты дубля не создаст. При первом "
              "опросе берутся только несколько свежих записей, архив не "
              "выгружается — иначе лента с тысячей записей забьёт очередь.",
        "en": "Several at once are fine — one per line or comma-separated. "
              "Adding the same feed twice creates no duplicate. The first poll "
              "takes only a few recent entries and skips the archive, otherwise "
              "a feed with a thousand items would flood the queue.",
    },
    "sources.rss_add": {"ru": "Добавить ленты", "en": "Add feeds"},
    "sources.rss_presets_title": {
        "ru": "Готовые наборы (адреса проверены, дубли не создаются):",
        "en": "Ready-made sets (URLs verified, no duplicates created):",
    },
    "sources.rss_preset.security_vulns": {
        "ru": "Уязвимости и эксплойты", "en": "Vulnerabilities and exploits",
    },
    "sources.rss_preset.security_news_en": {
        "ru": "ИБ-новости (EN)", "en": "Security news (EN)",
    },
    "sources.rss_preset.security_news_ru": {
        "ru": "ИБ-новости (RU)", "en": "Security news (RU)",
    },
    "sources.error_bad_feed_url": {
        "ru": "Адрес ленты должен начинаться с http:// или https:// — не подошло: {urls}",
        "en": "A feed URL must start with http:// or https:// — rejected: {urls}",
    },
    "sources.add_bulk_hint": {
        "ru": "Можно вставить сразу несколько — через запятую и/или по одному "
        "на строку. Подключение к Telegram после добавления может занять "
        "пару секунд.",
        "en": "You can paste several at once — comma-separated and/or one "
        "per line. Connecting to Telegram after adding may take a couple "
        "of seconds.",
    },
    "sources.error_too_many": {
        "ru": "Слишком много каналов за раз (максимум {max}) — раздели на "
        "несколько отправок.",
        "en": "Too many channels at once (max {max}) — split into several "
        "submissions.",
    },
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
    # Пункт «наследовать» назывался ровно так же, как явный профиль default —
    # в списке было два визуально одинаковых «default» с разным поведением
    # (пустое значение тянет ГЛОБАЛЬНЫЙ профиль, который может быть каким
    # угодно; явный «default» всегда базовый). Теперь разница видна.
    "source_detail.style_inherit": {
        "ru": "по глобальной настройке ({profile})",
        "en": "use global setting ({profile})",
    },
    "source_detail.style_hint": {
        "ru": "Текст промпта для каждого стиля правится в "
              "<a href=\"/settings#rewrite\">Настройках → Рерайт</a>.",
        "en": "The prompt text for each style is edited in "
              "<a href=\"/settings#rewrite\">Settings → Rewrite</a>.",
    },
    "source_detail.format_label": {"ru": "Формат публикации", "en": "Publication format"},
    "source_detail.format_post": {
        "ru": "пост в ленте (до 4096 символов)", "en": "feed post (up to 4096 chars)",
    },
    "source_detail.format_article": {
        "ru": "статья на Telegraph + тизер со ссылкой",
        "en": "Telegraph article + teaser with a link",
    },
    "source_detail.format_hint": {
        "ru": "Статья снимает потолок в 900 символов: лонгрид до 64 КБ с "
              "код-блоками и картинками между абзацами уходит на telegra.ph, "
              "в канал — короткий тизер, Telegram открывает статью через "
              "Instant View. Требует общей галочки в "
              "<a href=\"/settings#telegraph\">Настройках → Статьи на Telegraph</a>.",
        "en": "Article mode lifts the 900-character ceiling: a longread of up "
              "to 64 KB with code blocks and inline images goes to telegra.ph "
              "and the channel gets a short teaser, which Telegram opens via "
              "Instant View. Requires the global switch in "
              "<a href=\"/settings#telegraph\">Settings → Telegraph articles</a>.",
    },
    "source_detail.error_invalid_format": {
        "ru": "Формат публикации должен быть «пост» или «статья».",
        "en": "Publication format must be either post or article.",
    },
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
    "source_detail.backfill_title_rss": {"ru": "Опросить ленту", "en": "Poll the feed"},
    "source_detail.backfill_desc_rss": {
        "ru": "Лента опрашивается по расписанию (Настройки → RSS). Кнопка "
        "делает внеочередной опрос прямо сейчас и заводит новые записи в "
        "очередь модерации — уже виденные записи не задваиваются. Работает "
        "независимо от галочки «Опрос лент включён».",
        "en": "The feed is polled on a schedule (Settings → RSS). This button "
        "runs an extra poll right now and queues new entries for moderation — "
        "entries already seen are not duplicated. Works regardless of the "
        "\"feed polling enabled\" checkbox.",
    },
    "source_detail.backfill_limit_placeholder": {"ru": "Сколько сообщений", "en": "How many messages"},
    "source_detail.backfill_limit_placeholder_rss": {"ru": "Сколько записей", "en": "How many entries"},
    "source_detail.backfill_success_rss": {
        "ru": "✅ Новых записей в очередь: {count} (уже виденные пропущены — "
        "это штатно, см. очередь модерации).",
        "en": "✅ Queued {count} new entries (already-seen ones were skipped — "
        "that's expected, see the moderation queue).",
    },
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
    "targets.discovered_cannot_post": {
        "ru": "Бот без прав администратора с публикацией сообщений — "
        "постить сюда не сможет, пока не выдашь права в настройках канала",
        "en": "The bot isn't an admin with posting rights here — it won't "
        "be able to post until you grant that in the channel's settings",
    },
    "targets.col_guardian": {"ru": "Guardian", "en": "Guardian"},
    "targets.col_language": {"ru": "Язык", "en": "Language"},
    "targets.language_hint": {
        "ru": "Язык публикации выбирается у КАЖДОЙ группы: по нему делается "
              "рерайт, а не по языку исходника. Если один источник направлен "
              "в группы с разными языками, на каждый пост делается по рерайту "
              "на каждый язык, и в группу уходит текст её языка. Смена языка "
              "действует на будущие посты; уже отрерайченные можно вернуть в "
              "очередь кнопкой «Повторить» на странице поста.",
        "en": "Publication language is chosen per group: the rewrite follows "
              "it, not the source's language. If one source feeds groups with "
              "different languages, each post is rewritten once per language, "
              "and every group receives the text in its own. Changing the "
              "language affects future posts; already-rewritten ones can be "
              "sent back to the queue with the \"Retry\" button on the post page.",
    },
    "targets.guardian_enable": {"ru": "Включить Guardian", "en": "Enable Guardian"},
    "targets.guardian_disable": {"ru": "Выключить Guardian", "en": "Disable Guardian"},
    "targets.guardian_cannot_moderate": {
        "ru": "Guardian включён, но не добавлен администратором в этот чат — "
        "капча/антиспам/антирейд здесь не работают",
        "en": "Guardian is enabled but not added as admin to this chat — "
        "captcha/anti-spam/anti-raid don't work here",
    },

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
    "moderation_detail.link_read": {
        "ru": "статья по ссылке прочитана: {chars} символов",
        "en": "linked article read: {chars} characters",
    },
    "moderation_detail.link_not_read": {
        "ru": "статья по ссылке не прочитана",
        "en": "linked article not read",
    },
    "moderation_detail.link_not_read_hint": {
        "ru": "Рерайт сделан по одному тексту поста. Если он выглядит слабо — "
              "причина скорее здесь, а не в промпте: в посте не было ссылки, "
              "либо сайт не отдал текст (пейвол, JS-рендеринг, таймаут).",
        "en": "The rewrite used only the post text. If it looks weak, the cause "
              "is likely here rather than in the prompt: the post had no link, "
              "or the site returned no text (paywall, JS rendering, timeout).",
    },
    "moderation_detail.source_link": {"ru": "Источник", "en": "Source"},
    "moderation_detail.save_text": {"ru": "Сохранить текст", "en": "Save text"},
    "moderation_detail.approve": {"ru": "✅ Одобрить", "en": "✅ Approve"},
    "moderation_detail.retry": {"ru": "↻ Повторить рерайт", "en": "↻ Retry rewrite"},
    "moderation_detail.retry_desc": {
        "ru": "Пост застрял и сам из этого состояния не выйдет. Кнопка вернёт "
              "его в начало очереди — рерайт и обложка сделаются заново.",
        "en": "The post is stuck and will not leave this state on its own. This "
              "button sends it back to the start of the queue — the rewrite and "
              "cover are redone from scratch.",
    },
    "moderation_detail.reject": {"ru": "❌ Отклонить", "en": "❌ Reject"},
    "moderation_detail.back_link": {"ru": "← К очереди модерации", "en": "← Back to moderation queue"},
    "moderation_detail.rewrite_variants_title": {
        "ru": "Варианты текста", "en": "Text variants",
    },
    "moderation_detail.cover_variants_title": {
        "ru": "Варианты обложки", "en": "Cover variants",
    },
    "moderation_detail.variant_n": {"ru": "Вариант {n}", "en": "Variant {n}"},
    "moderation_detail.active": {"ru": "Активен", "en": "Active"},
    "moderation_detail.select": {"ru": "Выбрать", "en": "Select"},
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
    "moderation_detail.will_post_to": {"ru": "Опубликуется в", "en": "Will post to"},
    "moderation_detail.no_targets_warning": {
        "ru": "Публиковать некуда — нет активных целевых групп (или "
        "персональные цели источника все неактивны). Одобрение сейчас "
        "переведёт пост в статус «ошибка».",
        "en": "Nowhere to publish — no active target groups (or the "
        "source's personal targets are all inactive). Approving now "
        "will send this post straight to “failed”.",
    },

    # --- F29: управление уже опубликованным постом ---
    "moderation_detail.published_targets_title": {
        "ru": "Опубликовано в", "en": "Published to",
    },
    "moderation_detail.col_chat": {"ru": "Группа", "en": "Group"},
    "moderation_detail.col_target_status": {"ru": "Статус", "en": "Status"},
    "moderation_detail.target_ok": {"ru": "опубликовано", "en": "published"},
    "moderation_detail.target_deleted": {"ru": "удалено", "en": "deleted"},
    "moderation_detail.target_failed": {"ru": "ошибка публикации", "en": "publish failed"},
    "moderation_detail.edit_published_placeholder": {
        "ru": "Новый текст", "en": "New text",
    },
    "moderation_detail.pin": {"ru": "📌 Закрепить", "en": "📌 Pin"},
    "moderation_detail.unpin": {"ru": "Открепить", "en": "Unpin"},

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

    # --- F35: ручной учёт рекламного дохода ---
    "ads.revenue_title": {"ru": "Доход от рекламы", "en": "Ad revenue"},
    "ads.revenue_desc": {
        "ru": "Ручной журнал поступлений — не интеграция с рекламной "
        "биржей, просто учёт кто/сколько/когда заплатил.",
        "en": "A manual revenue log — not an integration with an ad "
        "exchange, just a record of who paid how much and when.",
    },
    "ads.revenue_source_label": {"ru": "Биржа/заказчик", "en": "Exchange/customer"},
    "ads.revenue_source_placeholder": {"ru": "Например, Telega.in", "en": "e.g. Telega.in"},
    "ads.revenue_amount_label": {"ru": "Сумма", "en": "Amount"},
    "ads.revenue_currency_label": {"ru": "Валюта", "en": "Currency"},
    "ads.revenue_date_label": {"ru": "Дата", "en": "Date"},
    "ads.revenue_brief_label": {"ru": "Бриф (опционально)", "en": "Brief (optional)"},
    "ads.revenue_brief_none": {"ru": "— без привязки —", "en": "— unlinked —"},
    "ads.revenue_note_label": {"ru": "Примечание", "en": "Note"},
    "ads.revenue_note_placeholder": {"ru": "Опционально", "en": "Optional"},
    "ads.revenue_add": {"ru": "Добавить запись", "en": "Add entry"},
    "ads.revenue_col_date": {"ru": "Дата", "en": "Date"},
    "ads.revenue_col_source": {"ru": "Биржа/заказчик", "en": "Exchange/customer"},
    "ads.revenue_col_amount": {"ru": "Сумма", "en": "Amount"},
    "ads.revenue_col_note": {"ru": "Примечание", "en": "Note"},
    "ads.error_invalid_amount": {
        "ru": "Сумма должна быть числом.", "en": "The amount must be a number.",
    },
    "ads.error_invalid_date": {
        "ru": "Дата должна быть в формате ГГГГ-ММ-ДД.", "en": "The date must be in YYYY-MM-DD format.",
    },

    # --- F33: опросы ---
    "polls.title": {"ru": "Опросы", "en": "Polls"},
    "polls.desc": {
        "ru": "Создать опрос — он появится в очереди модерации (/moderation), "
        "как обычный пост, и опубликуется тем же способом.",
        "en": "Create a poll — it appears in the moderation queue "
        "(/moderation) like a regular post and publishes the same way.",
    },
    "polls.question_label": {"ru": "Вопрос", "en": "Question"},
    "polls.options_label": {"ru": "Варианты ответа", "en": "Answer options"},
    "polls.options_placeholder": {"ru": "По одному варианту на строку", "en": "One option per line"},
    "polls.options_hint": {"ru": "От 2 до 10 вариантов, до 100 символов каждый.", "en": "2 to 10 options, up to 100 characters each."},
    "polls.is_anonymous_label": {"ru": "Анонимный опрос", "en": "Anonymous poll"},
    "polls.allows_multiple_label": {"ru": "Разрешить несколько вариантов", "en": "Allow multiple answers"},
    "polls.create": {"ru": "Создать опрос", "en": "Create poll"},
    "polls.after_create_hint": {
        "ru": "После создания опрос нужно одобрить в очереди модерации, как и обычный пост.",
        "en": "After creating, approve the poll in the moderation queue like any other post.",
    },
    "polls.error_invalid_question": {
        "ru": "Вопрос обязателен и не должен превышать 300 символов.",
        "en": "The question is required and must be under 300 characters.",
    },
    "polls.error_option_count": {
        "ru": "Нужно от 2 до 10 вариантов ответа.",
        "en": "There must be between 2 and 10 answer options.",
    },
    "polls.error_option_too_long": {
        "ru": "Каждый вариант ответа — не более 100 символов.",
        "en": "Each answer option must be under 100 characters.",
    },

    # --- F32: инвайт-ссылки и заявки на вступление ---
    "invites.title": {"ru": "Инвайты и заявки", "en": "Invites and requests"},
    "invites.desc": {
        "ru": "Инвайт-ссылки целевых групп и заявки на вступление "
        "(если у группы включено подтверждение админом).",
        "en": "Invite links for target groups and join requests "
        "(if the group has admin approval enabled).",
    },
    "invites.col_chat": {"ru": "Группа", "en": "Group"},
    "invites.col_link": {"ru": "Ссылка", "en": "Link"},
    "invites.col_name": {"ru": "Название", "en": "Name"},
    "invites.col_status": {"ru": "Статус", "en": "Status"},
    "invites.col_user": {"ru": "Пользователь", "en": "User"},
    "invites.col_requested_at": {"ru": "Когда", "en": "When"},
    "invites.name_label": {"ru": "Название ссылки", "en": "Link name"},
    "invites.name_placeholder": {"ru": "Например, «из Instagram»", "en": "e.g. \"from Instagram\""},
    "invites.member_limit_label": {"ru": "Лимит участников", "en": "Member limit"},
    "invites.member_limit_placeholder": {"ru": "Пусто = без лимита", "en": "Blank = unlimited"},
    "invites.creates_join_request_label": {
        "ru": "Требовать подтверждение админа", "en": "Require admin approval",
    },
    "invites.creates_join_request_hint": {
        "ru": "Вступающие по этой ссылке попадут в «Заявки на вступление» "
        "ниже вместо мгновенного добавления в группу.",
        "en": "People joining via this link will appear under \"Join "
        "requests\" below instead of joining instantly.",
    },
    "invites.create": {"ru": "Создать ссылку", "en": "Create link"},
    "invites.error_invalid_member_limit": {
        "ru": "Лимит участников должен быть целым положительным числом или пустым.",
        "en": "The member limit must be a positive integer or blank.",
    },
    "invites.links_title": {"ru": "Инвайт-ссылки", "en": "Invite links"},
    "invites.active": {"ru": "активна", "en": "active"},
    "invites.revoked": {"ru": "отозвана", "en": "revoked"},
    "invites.revoke": {"ru": "Отозвать", "en": "Revoke"},
    "invites.join_requests_title": {"ru": "Заявки на вступление", "en": "Join requests"},
    "invites.no_pending_requests": {"ru": "Заявок нет.", "en": "No pending requests."},
    "invites.approve": {"ru": "✅ Одобрить", "en": "✅ Approve"},
    "invites.decline": {"ru": "❌ Отклонить", "en": "❌ Decline"},

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

    # --- Guardian: общий селектор группы (F28 — стоп-слова/домены/
    # доверенные/дашборд раздельны по каждой защищаемой группе) ---
    "guardian.select_chat_label": {"ru": "Группа", "en": "Group"},
    "guardian.no_protected_chats_warning": {
        "ru": "⚠️ Ни одна цель не отмечена галочкой «Guardian» — включи "
        "защиту хотя бы для одной группы на странице <a href=\"/targets\">Целей</a>.",
        "en": "⚠️ No target has the Guardian checkbox enabled — turn on "
        "protection for at least one group on the <a href=\"/targets\">Targets</a> page.",
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
    "guardian_trusted.user_id_placeholder": {"ru": "user_id", "en": "user_id"},
    "guardian_trusted.user_id_hint": {
        "ru": "Числовой Telegram id, не @username — узнать можно переслав "
        "сообщение этого человека боту @userinfobot.",
        "en": "A numeric Telegram id, not @username — find it by "
        "forwarding a message from this person to @userinfobot.",
    },
    "guardian_trusted.reason_placeholder": {"ru": "Причина (опционально)", "en": "Reason (optional)"},
    "guardian_trusted.col_user_id": {"ru": "user_id", "en": "user_id"},
    "guardian_trusted.col_added_at": {"ru": "Добавлен", "en": "Added"},
    "guardian_trusted.col_added_by": {"ru": "Кем", "en": "By"},
    "guardian_trusted.col_reason": {"ru": "Причина", "en": "Reason"},
    "guardian_trusted.error_no_group": {
        "ru": "Выбранная группа больше не защищается Guardian — обнови страницу.",
        "en": "The selected group is no longer protected by Guardian — refresh the page.",
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
    "settings.expand_text_field": {
        "ru": "Показать и отредактировать текст", "en": "Show and edit text",
    },
    "settings.reset_field": {"ru": "↺ по умолчанию", "en": "↺ default"},
    "settings.reset_field_title": {
        "ru": "Убрать сохранённое значение и вернуться к тому, что идёт с "
              "версией системы. Показывается только у изменённых полей.",
        "en": "Drop the saved value and go back to what ships with this "
              "version. Shown only for fields you have changed.",
    },
    # Без апострофов: строка уходит в JS confirm() внутри HTML-атрибута
    # (см. предупреждение над common.confirm_delete и тест на это).
    "settings.confirm_reset_field": {
        "ru": "Вернуть поле к значению по умолчанию? Ваша версия будет потеряна.",
        "en": "Reset this field to its default? Your version will be lost.",
    },
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

    # --- F38: экспорт содержимого канала + полный бэкап/восстановление ---
    "export.title": {"ru": "Экспорт / Импорт", "en": "Export / Import"},
    "export.desc": {
        "ru": "Содержимое канала отдельно, полный бэкап системы (токены, "
        "настройки, БД целиком) отдельно — см. секции ниже.",
        "en": "Channel content separately, a full system backup (tokens, "
        "settings, the whole database) separately — see the sections below.",
    },
    "export.posts_section_title": {"ru": "Посты", "en": "Posts"},
    "export.since_label": {"ru": "С даты", "en": "From date"},
    "export.until_label": {"ru": "По дату", "en": "To date"},
    "export.date_range_hint": {
        "ru": "Оба поля необязательны — пусто значит «весь архив».",
        "en": "Both fields are optional — blank means \"the whole archive\".",
    },
    "export.download_json": {"ru": "Скачать JSON", "en": "Download JSON"},
    "export.download_csv": {"ru": "Скачать CSV", "en": "Download CSV"},
    "export.error_invalid_date": {
        "ru": "Дата должна быть в формате ГГГГ-ММ-ДД.", "en": "The date must be in YYYY-MM-DD format.",
    },
    "export.backup_section_title": {
        "ru": "Полный бэкап (токены, настройки, БД целиком)",
        "en": "Full backup (tokens, settings, the whole database)",
    },
    "export.backup_section_desc": {
        "ru": "Архив `.env` + обеих БД (tg_repost и Guardian) + логов — "
        "буквально всё: посты, источники, цели, настройки, зашифрованные "
        "секреты/токены. То же самое, что делает `python -m "
        "tg_repost.tools.backup` по cron, но по кнопке и из браузера.",
        "en": "An archive of `.env` + both databases (tg_repost and "
        "Guardian) + logs — literally everything: posts, sources, targets, "
        "settings, encrypted secrets/tokens. The same thing `python -m "
        "tg_repost.tools.backup` does via cron, just a button in the browser.",
    },
    "export.backup_download": {"ru": "Скачать бэкап сейчас", "en": "Download backup now"},
    "export.backup_restore_label": {"ru": "Файл бэкапа (.zip)", "en": "Backup file (.zip)"},
    "export.backup_restore_hint": {
        "ru": "⚠️ Перезаписывает .env и ОБЕ БД поверх текущих — перед этим "
        "автоматически снимается снимок текущего состояния. После "
        "восстановления нужен перезапуск контейнеров (docker compose "
        "restart), живого применения без рестарта нет.",
        "en": "⚠️ Overwrites .env and BOTH databases in place — a snapshot "
        "of the current state is taken automatically first. Restart the "
        "containers (docker compose restart) after restoring — this has "
        "no live effect without a restart.",
    },
    "export.backup_restore_button": {"ru": "Восстановить из бэкапа", "en": "Restore from backup"},
    "export.confirm_restore": {
        "ru": "Перезаписать .env и обе БД содержимым загруженного архива? "
        "Текущее состояние будет автоматически сохранено перед этим.",
        "en": "Overwrite .env and both databases with the uploaded archive? "
        "The current state will be saved automatically first.",
    },
    "export.restore_success": {
        "ru": "Восстановлено {count} файлов. Перезапусти контейнеры (docker "
        "compose restart), чтобы применить.",
        "en": "Restored {count} files. Restart the containers (docker "
        "compose restart) to apply.",
    },
    "export.error_empty_backup_file": {
        "ru": "Файл бэкапа пуст или не выбран.", "en": "The backup file is empty or wasn't selected.",
    },
    "export.error_restore_failed": {
        "ru": "Не удалось восстановить: {detail}", "en": "Restore failed: {detail}",
    },

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
        "ru": "⚠️ Токен бота Guardian не задан — впиши его в "
        "<a href=\"/settings#guardian_bot\">Настройках</a> (группа "
        "«Guardian»), затем перезапусти контейнер guardian, чтобы он его "
        "подхватил. GUARDIAN_GROUP_ID больше не нужен — какие группы "
        "защищать, выбирается галочкой на странице «Цели».",
        "en": "⚠️ The Guardian bot token isn't set — enter it in "
        "<a href=\"/settings#guardian_bot\">Settings</a> (the «Guardian» "
        "group), then restart the guardian container to pick it up. "
        "GUARDIAN_GROUP_ID is no longer needed — which groups are "
        "protected is chosen via the checkbox on the «Targets» page.",
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
        "AI-генерация через локальную установку; openai — генерация через "
        "уже настроенный OpenAI-совместимый провайдер рерайта, свой ключ не нужен.",
        "en": "unsplash — stock photo by keywords; comfyui — AI generation "
        "via your local install; openai — generation via the already "
        "configured OpenAI-compatible rewrite provider, no separate key needed.",
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
    "settings.group.post_source_button.title": {
        "ru": "Кнопка источника на посте", "en": "Source button on posts",
    },
    "settings.group.post_source_button.desc": {
        "ru": "Inline-кнопка со ссылкой на оригинал — только для постов из "
        "источников (у рекламы/дайджестов/опросов нет ссылки на первоисточник).",
        "en": "Inline button linking to the original — only for posts "
        "from sources (ads/digests/polls have no original to link to).",
    },
    "settings.group.guardian_bot.title": {
        "ru": "Guardian — токен бота-модератора", "en": "Guardian — moderator bot token",
    },
    "settings.group.guardian_bot.desc": {
        "ru": "Guardian — отдельный бот и процесс от репост-бота выше. "
        "Список защищаемых групп и остальные настройки — на странице "
        "«Guardian» в меню, здесь только его токен.",
        "en": "Guardian is a separate bot and process from the repost bot "
        "above. Protected groups and the rest of its settings live on the "
        "«Guardian» page in the menu — only its token lives here.",
    },

    # --- Настройки tg_repost: лейблы полей ---
    "settings.field.tg_api_id.label": {"ru": "API ID", "en": "API ID"},
    "settings.field.tg_owner_user_id.label": {"ru": "Owner user ID", "en": "Owner user ID"},
    "settings.field.mtproto_proxy_host.label": {"ru": "MTProto host", "en": "MTProto host"},
    "settings.field.mtproto_proxy_port.label": {"ru": "MTProto port", "en": "MTProto port"},
    "settings.field.openai_base_url.label": {"ru": "Base URL", "en": "Base URL"},
    "settings.field.openai_model.label": {"ru": "Модель", "en": "Model"},
    "settings.field.openai_timeout_seconds.label": {
        "ru": "Таймаут запроса, сек", "en": "Request timeout, sec",
    },
    "settings.field.openai_timeout_seconds.hint": {
        "ru": "Рерайт по полной статье — длинный запрос. Если посты уходят в "
              "«ошибка рерайта: Request timed out» — поднимай.",
        "en": "Rewriting from a full article is a long request. If posts end up "
              "as \"rewrite error: Request timed out\", raise this.",
    },
    "settings.field.openai_max_retries.label": {
        "ru": "Повторов запроса при сбое", "en": "Request retries on failure",
    },
    "settings.field.fetch_link_content_enabled.label": {
        "ru": "Переходить по ссылке в посте", "en": "Follow link in post",
    },
    "settings.field.rewrite_variant_count.label": {
        "ru": "Вариантов текста на пост", "en": "Text variants per post",
    },
    "settings.field.rewrite_temperature.label": {"ru": "Температура", "en": "Temperature"},
    "settings.field.rewrite_temperature.hint": {
        "ru": "Насколько свободно модель формулирует. Ниже 0.7 текст сушится и "
              "становится шаблонным, выше 1.0 растёт риск искажения фактов. "
              "Разумный коридор — 0.7–1.0.",
        "en": "How freely the model phrases things. Below 0.7 the text dries out "
              "and turns formulaic; above 1.0 the risk of distorting facts grows. "
              "Sensible range: 0.7–1.0.",
    },
    "settings.field.link_content_max_chars.label": {
        "ru": "Лимит текста статьи, символов", "en": "Article text cap, chars",
    },
    "settings.field.link_content_max_chars.hint": {
        "ru": "Сколько символов статьи по ссылке уходит в модель. Именно этот "
              "лимит решает, увидит ли она материал целиком или только начало — "
              "если рерайт пересказывает лишь первые абзацы, поднимай здесь. "
              "Больше символов = дороже токены.",
        "en": "How many characters of the linked article are passed to the model. "
              "This cap decides whether it sees the whole piece or only the "
              "beginning — raise it if rewrites only retell the opening "
              "paragraphs. More characters = more tokens = higher cost.",
    },
    "settings.field.link_fetch_timeout_seconds.label": {
        "ru": "Таймаут загрузки статьи, сек", "en": "Article fetch timeout, sec",
    },
    "settings.field.link_fetch_timeout_seconds.hint": {
        "ru": "Сколько ждать ответа сайта. По истечении рерайт идёт по одному "
              "посту, без текста статьи — молча, без ошибки.",
        "en": "How long to wait for the site. On timeout the rewrite proceeds "
              "from the post alone, without the article text — silently, no error.",
    },
    "settings.field.rewrite_humanize_enabled.label": {
        "ru": "Убирать признаки ИИ-текста", "en": "Strip AI-text tells",
    },
    "settings.field.rewrite_humanize_enabled.hint": {
        "ru": "Добавляет к КАЖДОМУ промпту рерайта (любого стиля) блок правил "
              "ниже: рваный ритм фраз, без дежурных связок и шаблонных "
              "конструкций, по которым текст обычно и опознаётся как машинный.",
        "en": "Appends the rule block below to EVERY rewrite prompt (any style): "
              "varied sentence rhythm, no filler connectives or boilerplate "
              "constructions that usually give machine text away.",
    },
    "settings.field.rewrite_humanize_instructions.label": {
        "ru": "Правила «не как нейросеть»", "en": "\"Not like an AI\" rules",
    },
    "settings.field.rewrite_humanize_instructions.hint": {
        "ru": "Приклеивается в КОНЕЦ промпта — там модель соблюдает инструкции "
              "охотнее. Действует только при включённой галочке выше. Один "
              "список на все пять стилей.",
        "en": "Appended to the END of the prompt — models follow instructions "
              "placed there more reliably. Active only when the checkbox above "
              "is on. One list shared by all five styles.",
    },
    "settings.field.rewrite_prompt_template.label": {
        "ru": "Промпт: базовый (default)", "en": "Prompt: base (default)",
    },
    "settings.field.rewrite_prompt_template.hint": {
        "ru": "Плейсхолдеры: {post_text} — исходный пост, {link_content} — текст "
              "статьи по ссылке (пусто, если ссылки не было). Пустое поле = "
              "откат на файл prompts/default.txt.",
        "en": "Placeholders: {post_text} — the source post, {link_content} — the "
              "linked article text (empty if there was no link). Blank field = "
              "falls back to prompts/default.txt.",
    },
    "settings.field.rewrite_prompt_news.label": {
        "ru": "Промпт: новость (news)", "en": "Prompt: news",
    },
    "settings.field.rewrite_prompt_news.hint": {
        "ru": "Применяется к источникам со стиль-профилем «news». Те же "
              "плейсхолдеры. Пустое поле = откат на файл prompts/news.txt.",
        "en": "Applied to sources with the \"news\" style profile. Same "
              "placeholders. Blank field = falls back to prompts/news.txt.",
    },
    "settings.field.rewrite_prompt_opinion.label": {
        "ru": "Промпт: мнение (opinion)", "en": "Prompt: opinion",
    },
    "settings.field.rewrite_prompt_opinion.hint": {
        "ru": "Применяется к источникам со стиль-профилем «opinion». Пустое "
              "поле = откат на файл prompts/opinion.txt.",
        "en": "Applied to sources with the \"opinion\" style profile. Blank "
              "field = falls back to prompts/opinion.txt.",
    },
    "settings.field.rewrite_prompt_instruction.label": {
        "ru": "Промпт: инструкция (instruction)", "en": "Prompt: instruction",
    },
    "settings.field.rewrite_prompt_instruction.hint": {
        "ru": "Применяется к источникам со стиль-профилем «instruction». Пустое "
              "поле = откат на файл prompts/instruction.txt.",
        "en": "Applied to sources with the \"instruction\" style profile. Blank "
              "field = falls back to prompts/instruction.txt.",
    },
    "settings.field.rewrite_prompt_humor.label": {
        "ru": "Промпт: юмор (humor)", "en": "Prompt: humor",
    },
    "settings.field.rewrite_prompt_humor.hint": {
        "ru": "Применяется к источникам со стиль-профилем «humor». Пустое поле "
              "= откат на файл prompts/humor.txt.",
        "en": "Applied to sources with the \"humor\" style profile. Blank field "
              "= falls back to prompts/humor.txt.",
    },
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
    "settings.group.rss.title": {
        "ru": "RSS-ленты как источник", "en": "RSS feeds as a source",
    },
    "settings.group.rss.desc": {
        "ru": "Ленты добавляются на странице «Источники». Записи попадают в ту "
              "же очередь, что и посты из каналов, и проходят весь тот же путь: "
              "фильтры, стиль-профиль, переход по ссылке за полным текстом "
              "статьи, формат публикации. Опрос не зависит от Telegram — при "
              "недоступном Telethon ленты продолжают наполнять очередь.",
        "en": "Feeds are added on the Sources page. Entries land in the same "
              "queue as channel posts and follow the same path: filters, style "
              "profile, following the link for the full article, publication "
              "format. Polling does not depend on Telegram — if Telethon is "
              "down, feeds keep filling the queue.",
    },
    "settings.field.rss_enabled.label": {
        "ru": "Опрос лент включён", "en": "Feed polling enabled",
    },
    "settings.field.rss_poll_interval_minutes.label": {
        "ru": "Интервал опроса, мин", "en": "Poll interval, min",
    },
    "settings.field.rss_max_items_per_poll.label": {
        "ru": "Записей за опрос, максимум", "en": "Max items per poll",
    },
    "settings.field.rss_max_items_per_poll.hint": {
        "ru": "Потолок на ОДНУ ленту за один опрос — страховка от ленты, которая "
              "разом выкатила сотню записей или сломалась и отдаёт всё подряд.",
        "en": "A cap per feed per poll — insurance against a feed that dumps a "
              "hundred entries at once or breaks and returns everything.",
    },
    "settings.field.rss_max_queue_backlog.label": {
        "ru": "Потолок очереди (пауза опроса)", "en": "Queue cap (pauses polling)",
    },
    "settings.field.rss_max_queue_backlog.hint": {
        "ru": "Опрос лент приостанавливается, пока необработанных постов "
              "больше этого числа. Лент бывает два десятка, и приток легко "
              "обгоняет обработку (пост = вызовы модели и генерация обложек) "
              "— без потолка очередь и счёт за API растут бесконечно. "
              "Записи не теряются: ленты отдадут их на следующем опросе. "
              "0 — выключить предохранитель.",
        "en": "Feed polling pauses while more than this many posts are still "
              "unprocessed. With a couple of dozen feeds the intake easily "
              "outruns processing (each post means model calls plus cover "
              "generation) — without a cap the queue and the API bill grow "
              "without bound. Nothing is lost: feeds serve those entries again "
              "on the next poll. 0 disables the cap.",
    },
    "settings.field.rss_first_poll_items.label": {
        "ru": "Записей при первом опросе ленты", "en": "Items on a feed's first poll",
    },
    "settings.field.rss_first_poll_items.hint": {
        "ru": "В архиве ленты бывают тысячи записей (у MSRC — больше пяти тысяч). "
              "Завести их все постами значит забить очередь модерации и счёт за "
              "рерайт, поэтому при первом опросе берутся только свежие, "
              "остальное считается историей.",
        "en": "A feed archive can hold thousands of entries (MSRC has over five "
              "thousand). Turning them all into posts would flood the moderation "
              "queue and the rewrite bill, so the first poll takes only recent "
              "ones and treats the rest as history.",
    },
    "settings.group.telegraph.title": {
        "ru": "Статьи на Telegraph (лонгриды)", "en": "Telegraph articles (longreads)",
    },
    "settings.group.telegraph.desc": {
        "ru": "Пост в канале ограничен 4096 символами, подпись к картинке — "
              "1024, и код-блоки в них не отрендерить. Статья на telegra.ph — "
              "64 КБ, с подсветкой кода и картинками между абзацами, Telegram "
              "открывает её через Instant View прямо в приложении. Ключ и "
              "регистрация не нужны: аккаунт заводится сам при первой "
              "публикации. Формат выбирается У КАЖДОГО ИСТОЧНИКА (страница "
              "источника → «Формат публикации»), эта галочка — общий рубильник.",
        "en": "A channel post is capped at 4096 characters, a media caption at "
              "1024, and neither renders code blocks. A telegra.ph article "
              "holds 64 KB with code highlighting and inline images, and "
              "Telegram opens it via Instant View inside the app. No key or "
              "signup needed: the account is created on first publish. The "
              "format is chosen PER SOURCE (source page → Publication format); "
              "this checkbox is the global switch.",
    },
    "settings.field.telegraph_enabled.label": {"ru": "Включены", "en": "Enabled"},
    "settings.field.telegraph_author_name.label": {
        "ru": "Автор (подпись под статьёй)", "en": "Author (byline)",
    },
    "settings.field.telegraph_author_url.label": {
        "ru": "Ссылка автора (например, канал)", "en": "Author link (e.g. your channel)",
    },
    "settings.field.telegraph_author_url.hint": {
        "ru": "Кликабельна под заголовком статьи — единственное легальное "
              "место, где можно привести читателя обратно в канал.",
        "en": "Clickable under the article title — the one legitimate spot to "
              "lead a reader back to your channel.",
    },
    "settings.field.article_teaser_max_chars.label": {
        "ru": "Длина тизера в канале, символов", "en": "Teaser length in channel, chars",
    },
    "settings.field.article_teaser_max_chars.hint": {
        "ru": "Тизер — то, что видно в ленте под ссылкой на статью. 900 — с "
              "запасом под лимит подписи к картинке (1024), чтобы тизер с "
              "обложкой уехал одним сообщением. Ссылка в этот лимит входит и "
              "режется последней.",
        "en": "The teaser is what shows in the feed above the article link. "
              "900 leaves room under the 1024 caption cap so a teaser with a "
              "cover goes out as a single message. The link counts toward this "
              "limit and is never the part that gets cut.",
    },
    "settings.field.article_prompt_template.label": {
        "ru": "Промпт статьи", "en": "Article prompt",
    },
    "settings.field.article_prompt_template.hint": {
        "ru": "Отдельный от пяти «постовых» стилей: у статьи нет потолка в 900 "
              "символов и своя разметка (## подзаголовки, ``` для кода). "
              "Плейсхолдеры те же: {post_text}, {link_content}. Пустое поле = "
              "откат на файл prompts/article.txt.",
        "en": "Separate from the five post styles: an article has no 900-char "
              "ceiling and its own markup (## subheadings, ``` for code). Same "
              "placeholders: {post_text}, {link_content}. Blank field = falls "
              "back to prompts/article.txt.",
    },
    "secrets.field.telegraph_access_token.label": {
        "ru": "Telegraph access token", "en": "Telegraph access token",
    },
    "secrets.field.telegraph_access_token.hint": {
        "ru": "Руками вводить не нужно: выдаётся автоматически при первой "
              "публикации статьи (регистрация в Telegraph не требуется). "
              "Нужен, чтобы уже опубликованные статьи можно было ПРАВИТЬ — "
              "потеряв его, страницы не теряешь, но редактировать их больше "
              "не сможешь.",
        "en": "No need to enter it by hand: issued automatically on the first "
              "article publish (Telegraph needs no signup). It exists so that "
              "already published articles stay EDITABLE — lose it and the "
              "pages remain online but can no longer be changed.",
    },
    "settings.field.search_provider.label": {"ru": "Поисковик", "en": "Search provider"},
    "settings.field.search_provider.hint": {
        "ru": "searxng — свой сервис в Docker: бесплатен без оговорок (ни ключа, "
              "ни аккаунта, ни квоты) и позволяет выбрать движки. brave — "
              "внешний API, бесплатный тир закрыт для новых регистраций с "
              "февраля 2026, ключ работает только у подписавшихся раньше. "
              "ddgs — DuckDuckGo без ключа, но библиотека неофициальная и "
              "ловит троттлинг; нужен отдельный pip install ddgs.",
        "en": "searxng — your own service in Docker: free with no strings (no "
              "key, no account, no quota) and lets you pick the engines. "
              "brave — external API; its free tier closed to new signups in "
              "February 2026, keys still work only for earlier subscribers. "
              "ddgs — DuckDuckGo without a key, but the library is unofficial "
              "and gets throttled; needs a separate pip install ddgs.",
    },
    "settings.field.searxng_base_url.label": {"ru": "SearXNG: адрес", "en": "SearXNG: base URL"},
    "settings.field.searxng_base_url.hint": {
        "ru": "Внутри docker-compose — http://searxng:8080 (имя сервиса). Без "
              "Docker — http://127.0.0.1:8080. В settings.yml самого SearXNG "
              "должен быть включён формат json, иначе на запрос придёт 403: "
              "по умолчанию активен только html.",
        "en": "Inside docker-compose it is http://searxng:8080 (the service "
              "name). Without Docker: http://127.0.0.1:8080. SearXNG's own "
              "settings.yml must enable the json format or requests get a 403 "
              "— only html is active by default.",
    },
    "settings.field.searxng_engines.label": {"ru": "SearXNG: движки", "en": "SearXNG: engines"},
    "settings.field.searxng_engines.hint": {
        "ru": "Через запятую без пробелов: google,bing,duckduckgo,yandex. "
              "Пусто — движки по умолчанию из settings.yml. Смысл ограничивать: "
              "если часть выдачи недоступна из сети сервера, молчащие движки "
              "съедают таймаут на каждом запросе.",
        "en": "Comma-separated, no spaces: google,bing,duckduckgo,yandex. Empty "
              "means the defaults from settings.yml. Worth narrowing: if some "
              "engines are unreachable from the server's network, they burn a "
              "timeout on every query.",
    },
    "settings.field.searxng_language.label": {
        "ru": "SearXNG: язык выдачи", "en": "SearXNG: results language",
    },
    "settings.field.searxng_language.hint": {
        "ru": "ru, en или all. Пусто — как настроено в самом SearXNG.",
        "en": "ru, en or all. Empty means whatever SearXNG itself is set to.",
    },
    "settings.field.brave_search_url.label": {"ru": "Brave Search URL", "en": "Brave Search URL"},
    "settings.field.enrichment_max_results.label": {"ru": "Макс. результатов поиска", "en": "Max search results"},
    "settings.field.enrichment_max_sources.label": {"ru": "Макс. источников в посте", "en": "Max sources per post"},
    "settings.field.version_comparison_enabled.label": {"ru": "Сравнение версий источников", "en": "Compare source versions"},
    "settings.field.enable_auto_cover.label": {"ru": "Включены", "en": "Enabled"},
    "settings.field.cover_strategy.label": {"ru": "Стратегия", "en": "Strategy"},
    "settings.field.cover_variant_count.label": {
        "ru": "Вариантов обложки на пост", "en": "Cover variants per post",
    },
    "settings.field.cover_replace_source_media.label": {
        "ru": "Своя обложка вместо картинки оригинала",
        "en": "Own cover instead of the source image",
    },
    "settings.field.cover_replace_source_media.hint": {
        "ru": "Выключено — если у исходного поста была своя картинка, она и "
              "уйдёт на модерацию (обычно с текстом и watermark'ами). "
              "Включено — генерируем свою обложку и для таких постов, а "
              "оригинал остаётся последним вариантом: вернуться к нему можно "
              "кнопками ◀▶ при модерации.",
        "en": "Off — if the source post had its own image, that image goes to "
              "moderation (usually with text and watermarks). On — we generate "
              "our own cover for those posts too, and the original stays as the "
              "last variant, reachable with the ◀▶ buttons during moderation.",
    },
    "settings.field.cover_openai_model.label": {
        "ru": "Модель (openai-стратегия)", "en": "Model (openai strategy)",
    },
    "settings.field.cover_image_prompt_template.label": {
        "ru": "Промпт генерации (openai-стратегия)", "en": "Generation prompt (openai strategy)",
    },
    "settings.field.cover_image_prompt_template.hint": {
        "ru": "Уходит прямо в генератор картинок. Плейсхолдер {post_text}. "
              "Дефолт настроен на картинку БЕЗ текста и надписей и на "
              "ассоциативную сцену по теме, а не буквальную иллюстрацию "
              "заголовка — запрет текста повторён и в начале, и в конце "
              "намеренно: одного упоминания модели стабильно не хватает.",
        "en": "Goes straight to the image generator. Placeholder: {post_text}. "
              "The default asks for an image with NO text or lettering and an "
              "associative scene rather than a literal illustration of the "
              "headline — the no-text rule is repeated at both the start and "
              "the end on purpose: one mention is reliably not enough.",
    },
    "settings.field.cover_openai_image_size.label": {
        "ru": "Размер картинки (openai-стратегия)", "en": "Image size (openai strategy)",
    },
    "settings.field.cover_openai_image_size.hint": {
        "ru": "1792x1024 — широкая, как Telegram и показывает обложку поста. "
              "Квадрат 1024x1024 обрезается по краям, из кадра уезжает как раз "
              "композиционно важное. Провайдер может поддерживать не все размеры.",
        "en": "1792x1024 is wide — the way Telegram actually displays a post "
              "cover. A 1024x1024 square gets cropped at the edges, cutting off "
              "exactly what matters compositionally. Not every provider "
              "supports every size.",
    },
    "settings.field.cover_search_prompt_template.label": {
        "ru": "Промпт подбора запроса (unsplash/comfyui)", "en": "Query-picking prompt (unsplash/comfyui)",
    },
    "settings.field.cover_search_prompt_template.hint": {
        "ru": "Это промпт для ТЕКСТОВОЙ модели: она выдаёт короткий запрос, по "
              "которому Unsplash ищет фото, а ComfyUI генерирует картинку. "
              "Плейсхолдер {post_text}. Пустое поле = откат на файл "
              "prompts/cover_prompt.txt.",
        "en": "This is a prompt for the TEXT model: it produces the short query "
              "Unsplash searches by and ComfyUI generates from. Placeholder: "
              "{post_text}. Blank field = falls back to prompts/cover_prompt.txt.",
    },
    "settings.field.unsplash_api_url.label": {"ru": "Unsplash API URL", "en": "Unsplash API URL"},
    "settings.field.comfyui_base_url.label": {"ru": "ComfyUI base URL", "en": "ComfyUI base URL"},
    "settings.field.comfyui_workflow_path.label": {"ru": "Путь к workflow JSON", "en": "Workflow JSON path"},
    "settings.field.comfyui_positive_node_id.label": {
        "ru": "ID узла позитивного промпта", "en": "Positive prompt node ID",
    },
    "settings.field.comfyui_negative_node_id.label": {
        "ru": "ID узла негативного промпта", "en": "Negative prompt node ID",
    },
    "settings.field.comfyui_negative_node_id.hint": {
        "ru": "Ключ узла негативного CLIPTextEncode в твоём workflow JSON. "
              "Пусто — негатив из workflow не трогается. Заполнить стоит: без "
              "явного запрета модели упорно дорисовывают на «новостных» "
              "картинках надписи и псевдологотипы.",
        "en": "The key of the negative CLIPTextEncode node in your workflow "
              "JSON. Blank leaves the workflow's own negative untouched. Worth "
              "filling in: without an explicit ban, models keep painting "
              "captions and pseudo-logos onto \"news\" images.",
    },
    "settings.field.comfyui_negative_prompt.label": {
        "ru": "Негативный промпт (ComfyUI)", "en": "Negative prompt (ComfyUI)",
    },
    "settings.field.comfyui_negative_prompt.hint": {
        "ru": "Подставляется в узел выше. Дефолт уже перечисляет всё, что даёт "
              "текст в кадре: text, letters, caption, watermark, logo, poster, "
              "infographic и т.д.",
        "en": "Injected into the node above. The default already lists "
              "everything that yields text in frame: text, letters, caption, "
              "watermark, logo, poster, infographic and so on.",
    },
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
    "settings.field.post_source_button_enabled.label": {"ru": "Показывать кнопку", "en": "Show button"},
    "settings.field.post_source_button_label.label": {"ru": "Текст кнопки", "en": "Button text"},

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
    "secrets.field.guardian_bot_token.label": {
        "ru": "Guardian Bot Token", "en": "Guardian Bot Token",
    },
    "secrets.field.guardian_bot_token.hint": {
        "ru": "Токен ОТДЕЛЬНОГО бота-модератора Guardian — не тот же бот, "
        "что публикует посты. Получить: @BotFather → /newbot. Guardian — "
        "отдельный процесс/контейнер: после сохранения перезапусти его "
        "(`docker compose restart guardian`), живого применения без "
        "рестарта для этого поля нет.",
        "en": "Token for the SEPARATE Guardian moderator bot — not the "
        "same bot that publishes posts. Get one via @BotFather → /newbot. "
        "Guardian is a separate process/container: restart it after "
        "saving (`docker compose restart guardian`) — this field has no "
        "live effect without a restart.",
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

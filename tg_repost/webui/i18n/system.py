"""Система: компоненты, логи, доступ, интеграции.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "users.title": {"ru": "Пользователи", "en": "Users"},
    "users.intro": {
        "ru": "Роли вложены: владелец может всё, редактор — контент и "
              "модерацию, аналитик — только смотреть статистику. Страница, "
              "не описанная в политике доступа, открыта ТОЛЬКО владельцу — "
              "так забытая настройка не превращается в дыру.",
        "en": "Roles are nested: the owner can do everything, the editor "
              "handles content and moderation, the analyst only views stats. "
              "A page not listed in the access policy is open to the OWNER "
              "ONLY — so a forgotten entry never becomes a hole.",
    },
    "users.name": {"ru": "Имя", "en": "Name"},
    "users.role": {"ru": "Роль", "en": "Role"},
    "users.created": {"ru": "Создан", "en": "Created"},
    "users.role_owner": {"ru": "владелец — всё, включая секреты", "en": "owner — everything, including secrets"},
    "users.role_editor": {"ru": "редактор — контент и модерация", "en": "editor — content and moderation"},
    "users.role_analyst": {"ru": "аналитик — только чтение статистики", "en": "analyst — read-only stats"},
    "users.new": {"ru": "Новый пользователь", "en": "New user"},
    "users.password": {"ru": "Пароль", "en": "Password"},
    "users.add": {"ru": "Добавить", "en": "Add"},
    "users.delete": {"ru": "Удалить", "en": "Delete"},
    "users.confirm_delete": {
        "ru": "Удалить пользователя? Он потеряет доступ немедленно.",
        "en": "Delete this user? Access is lost immediately.",
    },
    "users.error_exists": {
        "ru": "Такое имя уже занято.", "en": "That name is already taken.",
    },
    "users.error_short_password": {
        "ru": "Пароль слишком короткий — минимум 12 символов.",
        "en": "Password is too short — 12 characters minimum.",
    },
    "users.error_need_fields": {
        "ru": "Нужны имя и пароль.", "en": "Name and password are required.",
    },
    "users.error_last_owner": {
        "ru": "Это последний владелец. Удалить его — значит остаться без "
              "доступа к настройкам и секретам, откуда уже не выбраться.",
        "en": "This is the last owner. Deleting them means losing access to "
              "settings and secrets with no way back.",
    },
    "users.you": {"ru": "это вы", "en": "that's you"},

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
    "growth.by_style_empty": {
        "ru": "Постов за период не было.", "en": "No posts in this period.",
    },

    # --- Первые шаги на главной ---
    "onboarding.title": {"ru": "Первые шаги", "en": "Getting started"},
    "onboarding.intro": {
        "ru": "Пока не сделано обязательное, сбор и публикация не запускаются. "
        "Шаги идут по зависимостям: каждый следующий имеет смысл только после "
        "предыдущего.",
        "en": "Until the required steps are done, collection and publishing do "
        "not start. The steps follow dependencies: each one only makes sense "
        "after the previous.",
    },
    "onboarding.progress": {
        "ru": "Сделано {done} из {total}", "en": "{done} of {total} done",
    },
    "onboarding.go_next": {"ru": "Перейти к следующему шагу", "en": "Go to the next step"},
    "onboarding.optional_note": {
        "ru": "Необязательное. Ядро — сбор, рерайт, модерация, публикация — "
        "работает и без этого. Guardian и Engage это ОТДЕЛЬНЫЕ боты со своими "
        "токенами у @BotFather; без них система не хуже, просто уже.",
        "en": "Optional. The core — collect, rewrite, moderate, publish — works "
        "without these. Guardian and Engage are SEPARATE bots with their own "
        "@BotFather tokens; without them the system is not worse, just "
        "narrower.",
    },
    "onboarding.step.telegram_api": {
        "ru": "Ключи Telegram API (api_id и api_hash)",
        "en": "Telegram API keys (api_id and api_hash)",
    },
    "onboarding.why.telegram_api": {
        "ru": "Берутся на my.telegram.org. Без них нечем читать каналы: "
        "обычный бот чужие каналы не видит.",
        "en": "Get them at my.telegram.org. Without them there is no way to "
        "read channels: a plain bot cannot see other people's channels.",
    },
    "onboarding.step.telethon_session": {
        "ru": "Вход в Telegram по номеру телефона",
        "en": "Sign in to Telegram with your phone number",
    },
    "onboarding.why.telethon_session": {
        "ru": "Разовый вход прямо в админке. Пароль и код никуда не уходят — "
        "результатом становится строка сессии в шифрованной базе.",
        "en": "A one-off sign-in right in the admin panel. The password and "
        "code go nowhere — the result is a session string in the encrypted "
        "database.",
    },
    "onboarding.step.bot_token": {
        "ru": "Токен бота, который будет публиковать",
        "en": "Token of the bot that will publish",
    },
    "onboarding.why.bot_token": {
        "ru": "Заводится у @BotFather. Этот же бот присылает вам посты на "
        "одобрение и сообщает о сбоях.",
        "en": "Created via @BotFather. The same bot sends you posts for "
        "approval and reports failures.",
    },
    "onboarding.step.owner_id": {
        "ru": "Ваш Telegram ID", "en": "Your Telegram ID",
    },
    "onboarding.why.owner_id": {
        "ru": "Чтобы бот знал, кому слать посты на одобрение. Узнать можно у "
        "@userinfobot.",
        "en": "So the bot knows whom to send posts to for approval. "
        "@userinfobot will tell you.",
    },
    "onboarding.step.ai_key": {
        "ru": "Ключ ИИ для рерайта", "en": "AI key for rewriting"
    },
    "onboarding.why.ai_key": {
        "ru": "Любой OpenAI-совместимый: OpenAI, прокси к Claude, локальная "
        "модель через Ollama. Провайдер меняется в настройках, а не в коде.",
        "en": "Any OpenAI-compatible one: OpenAI, a Claude proxy, a local "
        "model via Ollama. The provider is changed in settings, not in code.",
    },
    "onboarding.step.sources": {
        "ru": "Хотя бы один источник", "en": "At least one source",
    },
    "onboarding.why.sources": {
        "ru": "Каналы или RSS-ленты, откуда брать посты.",
        "en": "Channels or RSS feeds to take posts from.",
    },
    "onboarding.step.targets": {
        "ru": "Хотя бы одна целевая группа", "en": "At least one target group",
    },
    "onboarding.why.targets": {
        "ru": "Куда публиковать. Бот должен быть в ней администратором.",
        "en": "Where to publish. The bot has to be an administrator there.",
    },
    "onboarding.step.guardian": {
        "ru": "Токен Guardian — защита группы", "en": "Guardian token — group defence",
    },
    "onboarding.why.guardian": {
        "ru": "Капча, антиспам, антирейд. Без токена процесс не стартует — он "
        "отказывается работать наполовину настроенным.",
        "en": "CAPTCHA, anti-spam, anti-raid. Without a token the process does "
        "not start — it refuses to run half-configured.",
    },
    "onboarding.step.engage": {
        "ru": "Токен Engage — вовлечение участников",
        "en": "Engage token — audience engagement",
    },
    "onboarding.why.engage": {
        "ru": "Викторины, рефералы, конкурсы, подписки и магазин. Тоже "
        "отдельный бот.",
        "en": "Quizzes, referrals, contests, subscriptions and the shop. Also "
        "a separate bot.",
    },
    "integrations.title": {"ru": "Интеграции", "en": "Integrations"},
    "integrations.intro": {
        "ru": "Ключи для чужих программ и вебхуки на события. Всё это "
        "публичная поверхность системы, поэтому доступ только у владельца.",
        "en": "Keys for other programs and webhooks for events. All of this "
        "is the system's public surface, so only the owner has access.",
    },
    "integrations.keys": {"ru": "Ключи API", "en": "API keys"},
    "integrations.key_name": {"ru": "Название", "en": "Name"},
    "integrations.key_name_placeholder": {
        "ru": "Дашборд на сайте", "en": "Website dashboard",
    },
    "integrations.key_prefix": {"ru": "Префикс", "en": "Prefix"},
    "integrations.key_scope": {"ru": "Права", "en": "Scope"},
    "integrations.scope_read": {"ru": "только чтение", "en": "read only"},
    "integrations.scope_write": {"ru": "чтение и запись", "en": "read and write"},
    "integrations.key_rate": {"ru": "Запросов в минуту", "en": "Requests per minute"},
    "integrations.per_minute": {"ru": "мин", "en": "min"},
    "integrations.key_last_used": {"ru": "Последний раз", "en": "Last used"},
    "integrations.never_used": {"ru": "ни разу", "en": "never"},
    "integrations.key_create": {"ru": "Создать ключ", "en": "Create key"},
    "integrations.key_shown_once": {
        "ru": "Ключ создан — скопируйте его сейчас",
        "en": "Key created — copy it now",
    },
    "integrations.key_shown_once_hint": {
        "ru": "Показать его повторно невозможно: в базе лежит только хэш, "
        "как у пароля. Потеряете — создайте новый и отзовите этот.",
        "en": "It cannot be shown again: only a hash is stored, like for a "
        "password. If you lose it, create a new one and revoke this.",
    },
    "integrations.revoke": {"ru": "Отозвать", "en": "Revoke"},
    "integrations.revoked": {"ru": "отозван", "en": "revoked"},
    "integrations.confirm_revoke": {
        "ru": "Отозвать ключ? Программы, которые им ходят, сразу перестанут "
        "работать.",
        "en": "Revoke the key? Programs using it will stop working "
        "immediately.",
    },
    "integrations.no_keys": {"ru": "Ключей пока нет.", "en": "No keys yet."},
    "integrations.webhooks": {"ru": "Вебхуки", "en": "Webhooks"},
    "integrations.webhooks_intro": {
        "ru": "Система сама постучится по адресу, когда случится событие. "
        "Каждый запрос подписан — получатель может проверить, что это мы. "
        "Доставка «хотя бы один раз»: в теле есть event_id, повторы надо "
        "отбрасывать по нему.",
        "en": "The system will call the address itself when an event "
        "happens. Every request is signed, so the receiver can verify it is "
        "us. Delivery is at-least-once: the body carries an event_id, and "
        "repeats must be discarded by it.",
    },
    "integrations.hook_url": {"ru": "Адрес", "en": "URL"},
    "integrations.hook_events": {"ru": "События", "en": "Events"},
    "integrations.hook_events_hint": {
        "ru": "Ничего не выбрано — присылаем все.",
        "en": "Nothing selected means all of them.",
    },
    "integrations.all_events": {"ru": "все", "en": "all"},
    "integrations.hook_create": {"ru": "Добавить вебхук", "en": "Add webhook"},
    "integrations.hook_state": {"ru": "Состояние", "en": "State"},
    "integrations.hook_active": {"ru": "работает", "en": "active"},
    "integrations.hook_off": {"ru": "отключён", "en": "off"},
    "integrations.no_hooks": {"ru": "Вебхуков пока нет.", "en": "No webhooks yet."},
    "integrations.security_note": {
        "ru": "Внутренние адреса (localhost, 10.*, 192.168.*, метаданные "
        "облака) отклоняются: запрос уходит с сервера системы, и такой адрес "
        "отдал бы наружу её собственное окружение. Вебхук отключается сам "
        "после серии отказов — правка адреса включает его обратно.",
        "en": "Internal addresses (localhost, 10.*, 192.168.*, cloud "
        "metadata) are refused: the request leaves from the system's own "
        "server, and such an address would expose its own environment. A "
        "webhook switches itself off after repeated failures — editing the "
        "address turns it back on.",
    },

    # --- F74: Mini App ---
    "miniapp.title": {"ru": "Личный кабинет", "en": "Your dashboard"},
    "miniapp.loading": {"ru": "Загружаю…", "en": "Loading…"},
    "miniapp.error": {
        "ru": "Не удалось загрузить. Откройте ещё раз из бота.",
        "en": "Could not load. Open it again from the bot.",
    },
    "miniapp.hello": {"ru": "Привет, {name}", "en": "Hi, {name}"},
    "miniapp.intro": {
        "ru": "Здесь видно только ваше: подписка, приглашённые вами люди и "
              "текущий каталог.",
        "en": "You only see your own: subscription, people you invited and "
              "the current catalogue.",
    },
    "miniapp.subscription": {"ru": "Подписка", "en": "Subscription"},
    "miniapp.sub_active": {"ru": "Активна до", "en": "Active until"},
    "miniapp.sub_inactive": {"ru": "Не активна", "en": "Not active"},
    "miniapp.sub_hint": {
        "ru": "Оформить можно командой /subscribe в боте.",
        "en": "Use /subscribe in the bot to get one.",
    },
    "miniapp.referrals": {"ru": "Приглашения", "en": "Invites"},
    "miniapp.ref_invited": {"ru": "перешли", "en": "clicked"},
    "miniapp.ref_confirmed": {"ru": "засчитаны", "en": "counted"},
    "miniapp.ref_owed": {"ru": "к выплате", "en": "owed"},
    "miniapp.ref_hint": {
        "ru": "Приглашение засчитывается, когда человек вступил, написал и "
              "прожил в группе заданное число дней — иначе это была бы ферма "
              "мультиаккаунтов.",
        "en": "An invite counts once the person has joined, posted and stayed "
              "for the configured number of days — otherwise it would be a "
              "multi-account farm.",
    },
    "miniapp.leaderboard": {"ru": "Таблица лидеров", "en": "Leaderboard"},
    "miniapp.top_inviters": {
        "ru": "Кто привёл больше всех", "en": "Top inviters",
    },
    "miniapp.shop": {"ru": "Каталог", "en": "Catalogue"},
    "miniapp.shop_hint": {
        "ru": "Купить — командой /shop в боте: оплата идёт через Telegram.",
        "en": "Buy with /shop in the bot: payment goes through Telegram.",
    },
    "miniapp.denied_title": {"ru": "Не получилось", "en": "Something went wrong"},
    "miniapp.denied_hint": {
        "ru": "Откройте кабинет заново из бота — данные для входа устарели.",
        "en": "Open the dashboard again from the bot — the sign-in data is "
              "out of date.",
    },

    # --- F60: детектор накрутки ---
    "fraud.title": {"ru": "Признаки накрутки", "en": "Signs of inflated growth"},
    "fraud.desc": {
        "ru": "Накрутка видна не в точке, а в ФОРМЕ кривой — поэтому считается "
        "по накопленной истории снимков, а не по сегодняшним цифрам. Разовые "
        "чекеры этого не умеют: у них истории нет.",
        "en": "Inflated growth shows up in the SHAPE of the curve, not in a "
        "single point — so it is computed from the accumulated snapshot "
        "history rather than today's numbers. One-shot checkers cannot do "
        "this: they have no history.",
    },
    "fraud.col_channel": {"ru": "Канал", "en": "Channel"},
    "fraud.col_verdict": {"ru": "Что видно", "en": "What is visible"},
    "fraud.not_enough_data": {
        "ru": "мало данных: снимков {have}, нужно {need}",
        "en": "not enough data: {have} snapshots, {need} needed",
    },
    "fraud.suspicious": {"ru": "есть признаки", "en": "signs present"},
    "fraud.clean": {"ru": "ничего подозрительного", "en": "nothing suspicious"},
    "fraud.code_sawtooth": {
        "ru": "«пила»: резкий приход и такой же уход",
        "en": "«sawtooth»: a sharp inflow followed by the same outflow",
    },
    "fraud.code_growth_without_reach": {
        "ru": "подписчиков прибыло, а охват не вырос",
        "en": "subscribers grew while reach did not",
    },
    "fraud.caution": {
        "ru": "Формулировки осторожные намеренно: видна форма кривой, а не "
        "намерение. Резкий приход и уход бывает и у честного канала — "
        "например, после виральной публикации.",
        "en": "The wording is deliberately careful: what is visible is the "
        "shape of the curve, not intent. A sharp rise and fall also happens "
        "to an honest channel — after a viral post, for instance.",
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
    "secrets.field.shop_provider_token.label": {
        "ru": "Токен платёжного провайдера", "en": "Payment provider token",
    },
    "secrets.field.shop_provider_token.hint": {
        "ru": "Только для ФИЗИЧЕСКИХ товаров магазина. Получить: @BotFather → "
        "/mybots → бот Engage → Payments → выбрать провайдера. Для подписки "
        "(Stars) не нужен — там провайдер не участвует вовсе. Список "
        "провайдеров менялся, часть российских отключалась из-за санкций: "
        "актуальность проверяйте при подключении. Читает его Engage — после "
        "сохранения нужен `docker compose restart engage`.",
        "en": "For PHYSICAL shop goods only. Get it via @BotFather → /mybots "
        "→ the Engage bot → Payments → pick a provider. Not needed for the "
        "Stars subscription — no provider is involved there. The provider "
        "list has changed over time: verify availability when connecting. "
        "Engage reads it — restart it after saving.",
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
    "secrets.field.proxy_mtproto_secret.label": {"ru": "MTProto: секрет", "en": "MTProto: secret"},
    "secrets.field.proxy_mtproto_secret.hint": {
        "ru": "Секрет-часть MTProto-прокси (вместо логина/пароля). Секреты с "
        "префиксом ee (fake-TLS) Telethon НЕ поддерживает — тогда используй "
        "SOCKS5 или HTTP(S).",
        "en": "Secret part of the MTProto proxy (instead of login/password). "
        "Telethon does NOT support ee-prefixed (fake-TLS) secrets — use SOCKS5 "
        "or HTTP(S) then.",
    },
    "secrets.field.proxy_socks5_password.label": {"ru": "SOCKS5: пароль", "en": "SOCKS5: password"},
    "secrets.field.proxy_socks5_password.hint": {
        "ru": "Пароль SOCKS5-прокси. Оставь пустым, если прокси без авторизации.",
        "en": "SOCKS5 proxy password. Leave blank if the proxy needs no authentication.",
    },
    "secrets.field.proxy_http_password.label": {"ru": "HTTP(S): пароль", "en": "HTTP(S): password"},
    "secrets.field.proxy_http_password.hint": {
        "ru": "Пароль HTTP(S)-прокси. Оставь пустым, если прокси без авторизации.",
        "en": "HTTP(S) proxy password. Leave blank if the proxy needs no authentication.",
    },
    "secrets.field.engage_bot_token.label": {
        "ru": "Engage Bot Token", "en": "Engage Bot Token",
    },
    "secrets.field.engage_bot_token.hint": {
        "ru": "Токен ОТДЕЛЬНОГО бота вовлечения — не тот, что публикует посты, "
        "и не Guardian. @BotFather → /newbot. Отдельный процесс: после "
        "сохранения нужен `docker compose restart engage`.",
        "en": "Token of the SEPARATE engagement bot — not the one publishing "
        "posts, and not Guardian. @BotFather → /newbot. Separate process: after "
        "saving run `docker compose restart engage`.",
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
}

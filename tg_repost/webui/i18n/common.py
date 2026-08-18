"""Общее: меню, дашборд, вход, ошибки.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

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
    "nav.contacts": {"ru": "Участники", "en": "Contacts"},
    "nav.segments": {"ru": "Сегменты", "en": "Segments"},
    "nav.broadcasts": {"ru": "Рассылки", "en": "Broadcasts"},
    "nav.mediakit": {"ru": "Медиакит", "en": "Media kit"},
    "nav.ad_requests": {"ru": "Заявки на рекламу", "en": "Ad requests"},
    "nav.users": {"ru": "Пользователи", "en": "Users"},
    "nav.calendar": {"ru": "Календарь", "en": "Calendar"},
    "nav.support": {"ru": "Поддержка", "en": "Support"},

    # --- F37: роли и доступ ---
    "access.denied": {
        "ru": "Недостаточно прав для этой страницы.",
        "en": "Not enough permissions for this page.",
    },
    "login.username_placeholder": {"ru": "Имя", "en": "Username"},
    "login.username_hint": {
        "ru": "Если пользователь в системе один, имя можно не вводить. "
              "У учётки, созданной до появления ролей, имя — owner.",
        "en": "If there is only one user, the name can be left empty. An "
              "account created before roles existed is named owner.",
    },

    # --- F75: боты реестра и конструктор сценариев ---
    "nav.bots": {"ru": "Конструктор ботов", "en": "Bot builder"},
    "broadcast_preview.title": {
        "ru": "Проверьте перед отправкой", "en": "Check before sending",
    },
    "broadcast_preview.who": {"ru": "Кому уйдёт", "en": "Who will receive it"},
    "broadcast_preview.in_segment": {"ru": "В сегменте", "en": "In the segment"},
    "broadcast_preview.will_receive": {"ru": "Получат сообщение", "en": "Will receive"},
    "broadcast_preview.why_fewer": {"ru": "Почему меньше", "en": "Why fewer"},
    "broadcast_preview.why_fewer_hint": {
        "ru": "Это ограничение Telegram, а не сбой системы.",
        "en": "This is a Telegram restriction, not a system failure.",
    },
    "broadcast_preview.never_started": {
        "ru": "не запускали бота", "en": "never started the bot",
    },
    "broadcast_preview.blocked": {"ru": "заблокировали бота", "en": "blocked the bot"},
    "broadcast_preview.unsubscribed": {
        "ru": "отписались от рассылок", "en": "unsubscribed from broadcasts",
    },
    "broadcast_preview.what": {"ru": "Что уйдёт", "en": "What will be sent"},
    "broadcast_preview.send": {
        "ru": "Отправить {n} получателям", "en": "Send to {n} recipients",
    },
    "broadcast_preview.confirm": {
        "ru": "Отправить сообщение {n} получателям? Отозвать его будет нельзя.",
        "en": "Send the message to {n} recipients? It cannot be recalled.",
    },
    "broadcast_preview.irreversible": {
        "ru": "Отправку можно остановить, но уже доставленные сообщения "
              "вернуть нельзя.",
        "en": "Sending can be stopped, but already delivered messages cannot "
              "be recalled.",
    },
    "broadcast_preview.nobody": {
        "ru": "Отправлять некому: в сегменте нет ни одного человека, "
              "запускавшего бота.",
        "en": "Nobody to send to: no one in this segment has started the bot.",
    },
    "broadcast_preview.changed": {
        "ru": "Состав сегмента изменился, пока вы читали: было {was}, стало "
              "{now}. Проверьте числа заново.",
        "en": "The segment changed while you were reading: it was {was}, now "
              "{now}. Please check the numbers again.",
    },
    "contact_detail.facts": {"ru": "Что о нём известно", "en": "What we know"},
    "contact_detail.origin": {"ru": "Откуда пришёл", "en": "Came from"},
    "contact_detail.organic_hint": {
        "ru": "Пришёл не по нашей ссылке: поиск, добавлен админом или ссылка "
              "создана вручную в Telegram. Это ответ, а не отсутствие данных.",
        "en": "Did not arrive through our link: search, added by an admin, or "
              "a link created manually in Telegram. That is an answer, not "
              "missing data.",
    },
    "contact_detail.first_seen": {"ru": "Впервые замечен", "en": "First seen"},
    "contact_detail.membership": {"ru": "Участие", "en": "Membership"},
    "contact_detail.still_in": {"ru": "в чате", "en": "still in chat"},
    "contact_detail.invited_by": {"ru": "Кто привёл", "en": "Invited by"},
    "contact_detail.confirmed_invites": {"ru": "Привёл сам", "en": "Invited by them"},
    "contact_detail.confirmed_hint": {
        "ru": "Только подтверждённые: приглашённый вступил, написал и прожил "
              "в группе положенный срок.",
        "en": "Confirmed only: the invitee joined, wrote a message and stayed "
              "for the required period.",
    },
    "contact_detail.activity": {"ru": "Активность", "en": "Activity"},
    "contact_detail.activity_value": {
        "ru": "{points} очков · уровень {level} · серия {streak} дн. · "
              "{correct} верных ответов",
        "en": "{points} points · level {level} · {streak}-day streak · "
              "{correct} correct answers",
    },
    "contact_detail.moderation": {"ru": "Модерация", "en": "Moderation"},
    "contact_detail.no_guardian_data": {
        "ru": "Guardian о нём ничего не знает (или сейчас недоступен)",
        "en": "Guardian knows nothing about them (or is unavailable now)",
    },
    "contact_detail.warns": {"ru": "варнов: {n}", "en": "warnings: {n}"},
    "contact_detail.verified": {"ru": "прошёл капчу", "en": "passed captcha"},
    "contact_detail.no_tags": {"ru": "Тегов пока нет.", "en": "No tags yet."},
    "contact_detail.tag_placeholder": {"ru": "например, покупатель", "en": "e.g. customer"},
    "contact_detail.tag_hint": {
        "ru": "Тег вешается на человека, а не на чат: «постоянный покупатель» "
              "останется таковым во всех ваших группах. Регистр и лишние "
              "пробелы не важны.",
        "en": "A tag belongs to the person, not the chat: «regular customer» "
              "stays true across all your groups. Case and extra spaces do "
              "not matter.",
    },
    "contact_detail.note": {"ru": "Заметка", "en": "Note"},
    "contact_detail.note_hint": {
        "ru": "Видна только вам. Пустая заметка удаляется.",
        "en": "Visible only to you. An empty note is deleted.",
    },
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
    # F54 — фильтр слов на уровне источника.
    "source_detail.stop_words_label": {"ru": "Стоп-слова источника", "en": "Source stop-words"},
    "source_detail.stop_words_hint": {
        "ru": "Через запятую. ДОБАВЛЯЮТСЯ к глобальным, а не заменяют их — "
              "источник не может молча отключить общую защиту. "
              "Пусто — только глобальные.",
        "en": "Comma-separated. ADDED to the global list, not replacing it — "
              "a source cannot silently disable shared protection. "
              "Empty means global only.",
    },
    "source_detail.required_words_label": {
        "ru": "Обязательные слова источника", "en": "Source required words",
    },
    "source_detail.required_override_label": {
        "ru": "Переопределить глобальный список",
        "en": "Override the global list",
    },
    "source_detail.required_words_hint": {
        "ru": "Через запятую. ЗАМЕЩАЮТ глобальные: срабатывает «хотя бы одно», "
              "поэтому объединение списков не ужесточило бы фильтр, а ослабило. "
              "Галочка снята — берутся глобальные. Галочка стоит, поле пустое — "
              "требования нет совсем (берём из ленты всё подряд).",
        "en": "Comma-separated. REPLACES the global list: the rule is "
              "«at least one match», so merging lists would loosen the filter, "
              "not tighten it. Unchecked means global. Checked with an empty "
              "field means no topic requirement at all.",
    },
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
    # --- F62: маркировка рекламы в предпросмотре ---
    "moderation_detail.ad_marking_missing": {
        "ru": "Маркировка не заполнена — пост не опубликуется",
        "en": "Marking is incomplete — the post will not be published",
    },
    "moderation_detail.ad_marking_hint": {
        "ru": "Эта строка будет добавлена в НАЧАЛО поста при публикации. "
              "Рекламодатель и erid заполняются в брифе на странице «Реклама»; "
              "токен выдаёт ОРД, интеграции с ним у системы нет.",
        "en": "This line will be prepended to the post when published. The "
              "advertiser and erid are filled in on the brief at the «Ads» "
              "page; the token is issued by the ad-data operator, the system "
              "has no integration with it.",
    },
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
    "moderation_detail.editorial_notes": {
        "ru": "Замечания редактора", "en": "Editor's notes",
    },
    "moderation_detail.story_sources": {
        "ru": "Источников по сюжету", "en": "Sources for this story",
    },
    "moderation_detail.story_hint": {
        "ru": "Эту новость подтвердили несколько независимых источников — "
        "они же были у редактора-фактчекера при проверке текста.",
        "en": "Several independent sources reported this story — the same "
        "ones the fact-checking editor had when verifying the text.",
    },
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

    # --- F49: подписчики платного канала ---
    "nav.subscriptions": {"ru": "Подписки", "en": "Subscriptions"},

    # --- F70: приём криптовалюты ---
    "nav.crypto": {"ru": "Крипта", "en": "Crypto"},

    "nav.menu": {"ru": "Меню", "en": "Menu"},
    "nav.group.content": {"ru": "Контент", "en": "Content"},
    "nav.group.audience": {"ru": "Аудитория", "en": "Audience"},
    "nav.group.money": {"ru": "Деньги", "en": "Money"},
    "nav.group.guardian": {"ru": "Guardian — защита группы", "en": "Guardian — group defence"},
    "nav.group.system": {"ru": "Система", "en": "System"},

    # --- F44: конкурсы ---
    "nav.contests": {"ru": "Конкурсы", "en": "Contests"},

    # --- F73: интеграции ---
    "nav.integrations": {"ru": "Интеграции", "en": "Integrations"},

    # --- F69/F70: магазин ---
    "nav.shop": {"ru": "Магазин", "en": "Shop"},

    # --- F67: партнёрская программа ---
    "nav.affiliate": {"ru": "Партнёры", "en": "Partners"},

    "guardian_settings.title": {"ru": "Настройки Guardian", "en": "Guardian settings"},

    "guardian_settings.intro": {
        "ru": "Применяются сразу, без перезапуска — Guardian перечитывает их "
        "из БД. Токен бота, id группы и OpenAI-ключ — не здесь: токен/группа "
        "в `.env` на сервере, OpenAI-ключ общий с репост-ботом ({link}).",
        "en": "Applied immediately, no restart needed — Guardian re-reads "
        "them from the DB. Bot token, group id, and the OpenAI key aren't "
        "here: token/group live in `.env` on the server, the OpenAI key is "
        "shared with the repost bot ({link}).",
    },
}

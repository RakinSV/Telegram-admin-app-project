"""Контент: источники, модерация, публикация, календарь.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # --- F72: контент-календарь ---
    "calendar.title": {"ru": "Контент-календарь", "en": "Content calendar"},
    "calendar.intro": {
        "ru": "Слева от сегодня — что реально вышло. Справа — только то, что "
              "запланировано явной датой, и брони рекламы. Посты без даты "
              "здесь не показаны: система публикует их «когда дойдёт "
              "очередь», и раскладывать их по дням значило бы придумать "
              "расписание, которого нет.",
        "en": "Left of today — what actually went out. Right — only what is "
              "planned with an explicit date, plus ad bookings. Undated posts "
              "are not shown: the system publishes them «when their turn "
              "comes», and spreading them over days would invent a schedule "
              "that does not exist.",
    },
    "calendar.channel": {"ru": "Канал", "en": "Channel"},
    "calendar.show": {"ru": "Показать", "en": "Show"},
    "calendar.queue": {"ru": "в очереди без даты: {n}", "en": "queued without a date: {n}"},
    "calendar.queue_hint": {
        "ru": "Они выйдут в ближайшие слоты расписания, по мере очереди.",
        "en": "They will go out in the next scheduled slots, in order.",
    },
    "calendar.awaiting": {"ru": "ждут владельца: {n}", "en": "awaiting owner: {n}"},
    "calendar.awaiting_title": {
        "ru": "Одобрено редактором, ждёт владельца",
        "en": "Approved by editor, awaiting owner",
    },
    "calendar.awaiting_not_owner": {
        "ru": "Подтвердить может только владелец — это и есть смысл второго "
              "уровня согласования.",
        "en": "Only the owner can confirm — that is the point of the second "
              "approval level.",
    },
    "calendar.approve": {"ru": "Подтвердить", "en": "Confirm"},
    "calendar.grid": {"ru": "Сетка", "en": "Grid"},
    "calendar.day": {"ru": "День", "en": "Day"},
    "calendar.content": {"ru": "Свои посты", "en": "Own posts"},
    "calendar.ad": {"ru": "Реклама", "en": "Ad"},
    "calendar.today": {"ru": "сегодня", "en": "today"},
    "calendar.published": {"ru": "вышло", "en": "published"},
    "calendar.planned": {"ru": "запланировано", "en": "planned"},
    "calendar.waiting_owner": {"ru": "ждёт владельца", "en": "awaiting owner"},
    "calendar.move": {"ru": "Перенести", "en": "Move"},

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
    "moderation.pending_count": {
        "ru": "В очереди: {count}", "en": "In queue: {count}",
    },
    "moderation.reject_all": {
        "ru": "❌ Отклонить всё", "en": "❌ Reject all",
    },
    "moderation.confirm_reject_all": {
        "ru": "Отклонить ВСЕ {count} постов из очереди? Отменить нельзя.",
        "en": "Reject ALL {count} posts in the queue? This cannot be undone.",
    },
    "moderation.empty": {"ru": "Очередь пуста", "en": "Queue is empty"},
    "moderation.col_kind": {"ru": "Тип", "en": "Kind"},
    "moderation.col_text": {"ru": "Текст", "en": "Text"},
    "moderation.col_created": {"ru": "Создан", "en": "Created"},

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
    # --- F62: маркировка рекламы ---
    "ads.marking_legal_name": {
        "ru": "Рекламодатель для пометки", "en": "Advertiser for the label",
    },
    "ads.marking_inn": {"ru": "ИНН (если есть)", "en": "Tax ID (if any)"},
    "ads.marking_erid": {"ru": "erid от ОРД", "en": "erid from the operator"},
    "ads.marking_missing": {"ru": "нет erid", "en": "no erid"},
    "ads.ord_title": {"ru": "Отчёт по маркировке", "en": "Marking report"},
    "ads.ord_desc": {
        "ru": "Опубликованные рекламные посты. Размещения без erid показаны "
              "здесь же намеренно: именно они и создают проблему, прятать их "
              "в красивом отчёте бессмысленно. Токен выдаёт ОРД по договору, "
              "интеграции с его API у системы нет.",
        "en": "Published ad posts. Placements without an erid are shown here "
              "on purpose: those are exactly the problem, hiding them behind "
              "a tidy report helps nobody. The token is issued by the ad-data "
              "operator under contract; the system has no API integration.",
    },
    "ads.ord_unmarked": {
        "ru": "Без erid опубликовано: {n}", "en": "Published without erid: {n}",
    },
    "ads.ord_col_date": {"ru": "Дата", "en": "Date"},
    "ads.ord_col_advertiser": {"ru": "Рекламодатель", "en": "Advertiser"},
    "ads.ord_col_text": {"ru": "Пост", "en": "Post"},
    "ads.ord_empty": {
        "ru": "Рекламных постов ещё не публиковалось.",
        "en": "No ad posts have been published yet.",
    },
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
    # Заголовки групп меню. Названы по ЗАДАЧЕ владельца, а не по устройству
    # кода: он ищет «где посмотреть выручку», а не «где F69».
    # Найдено аудитом страниц 2026-08-16: текст стоял прямо в разметке и в
    # английском интерфейсе показывался по-русски.
    "ads.inn": {"ru": "ИНН", "en": "Tax ID"},
    "calendar.awaiting_empty": {
        "ru": "Подтверждать нечего — все посты уже прошли согласование.",
        "en": "Nothing to confirm — every post has been approved.",
    },

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
}

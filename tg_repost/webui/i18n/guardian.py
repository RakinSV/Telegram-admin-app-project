"""Guardian: защита группы.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # --- Guardian: общий селектор группы (F28 — стоп-слова/домены/
    # доверенные/дашборд раздельны по каждой защищаемой группе) ---
    "guardian.select_chat_label": {"ru": "Группа", "en": "Group"},
    "guardian.no_protected_chats_warning": {
        "ru": "⚠️ Ни одна цель не отмечена галочкой «Guardian» — включи "
        "защиту хотя бы для одной группы на странице <a href=\"/targets\">Целей</a>.",
        "en": "⚠️ No target has the Guardian checkbox enabled — turn on "
        "protection for at least one group on the <a href=\"/targets\">Targets</a> page.",
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
    "guardian.settings.group.autoreply.title": {
        "ru": "Автоответчик", "en": "Auto-reply",
    },
    "guardian.settings.group.autoreply.desc": {
        "ru": "Снимает рутину: «как купить», «где правила» спрашивают каждый "
        "день. Правила — JSON-массив вида "
        "[{\"triggers\": [\"правила\"], \"reply\": \"В закрепе\"}]. "
        "Срабатывает по СЛОВУ целиком, а не по подстроке («стрим» не стрельнет "
        "на «экстримальный»). Пауза не даёт отвечать десять раз подряд на один "
        "вопрос от разных людей. Другим ботам не отвечает — иначе два бота "
        "устроят бесконечный обмен.",
        "en": "Removes routine: “how to buy”, “where are the rules” get asked "
        "daily. Rules are a JSON array like "
        "[{\"triggers\": [\"rules\"], \"reply\": \"See the pinned message\"}]. "
        "Matches WHOLE WORDS, not substrings. The cooldown prevents ten replies "
        "in a row to the same question from different people. Never replies to "
        "other bots — otherwise two bots start an endless exchange.",
    },
    "guardian.settings.field.autoreply_enabled.label": {
        "ru": "Включить автоответчик", "en": "Enable auto-reply",
    },
    "guardian.settings.field.autoreply_rules.label": {
        "ru": "Правила (JSON)", "en": "Rules (JSON)",
    },
    "guardian.settings.field.autoreply_cooldown_seconds.label": {
        "ru": "Пауза на правило, сек", "en": "Per-rule cooldown, sec",
    },
    # F61 — обязательная подписка на канал.
    "guardian.settings.group.force_subscribe.title": {
        "ru": "Обязательная подписка на канал", "en": "Required channel subscription",
    },
    "guardian.settings.group.force_subscribe.desc": {
        "ru": "Участник не может писать, пока не подписан на канал — прямая "
        "воронка «участник группы → подписчик канала». БОТ ОБЯЗАН БЫТЬ "
        "АДМИНИСТРАТОРОМ В КАНАЛЕ; если проверка не отработала, сообщения "
        "ПРОПУСКАЮТСЯ, а не блокируются. Администраторы группы освобождены.",
        "en": "A member cannot write until subscribed to the channel — a "
        "direct funnel from group member to channel subscriber. THE BOT MUST "
        "BE AN ADMIN IN THE CHANNEL; if the check fails, messages are LET "
        "THROUGH rather than blocked. Group admins are exempt.",
    },
    "guardian.settings.field.force_subscribe_enabled.label": {
        "ru": "Включена", "en": "Enabled",
    },
    "guardian.settings.field.force_subscribe_channel.label": {
        "ru": "@канал или его chat_id", "en": "@channel or its chat_id",
    },
    # F57 — обучение антиспама.
    "guardian.settings.group.spam_learning.title": {
        "ru": "Обучение антиспама", "en": "Anti-spam learning",
    },
    "guardian.settings.group.spam_learning.desc": {
        "ru": "Спорные вердикты уходят в лог-канал с кнопками «спам / не "
        "спам», размеченные примеры подмешиваются в промпт. Ничего не "
        "удаляет и не банит — только наблюдает. Примеров берётся поровну "
        "каждой метки: перекос научил бы модель называть спамом всё подряд.",
        "en": "Borderline verdicts go to the log channel with «spam / not "
        "spam» buttons; labelled examples are mixed into the prompt. Nothing "
        "is deleted or banned — it only observes. Examples are taken evenly "
        "per label: a skew would teach the model to call everything spam.",
    },
    "guardian.settings.field.spam_learning_enabled.label": {
        "ru": "Включено", "en": "Enabled",
    },
    "guardian.settings.field.spam_learning_examples_per_label.label": {
        "ru": "Примеров каждой метки", "en": "Examples per label",
    },
    # F52 — Premium как сигнал доверия.
    "guardian.settings.group.premium_trust.title": {
        "ru": "Premium как сигнал доверия", "en": "Premium as a trust signal",
    },
    "guardian.settings.group.premium_trust.desc": {
        "ru": "Premium-аккаунту капча даётся мягче: у скам-ботов платной "
        "подписки обычно нет. ВЫКЛЮЧЕНО по умолчанию — это ослабление "
        "защиты, а Premium покупается, поэтому сигнал идёт в общий скоринг, "
        "а не даёт пропуск.",
        "en": "A Premium account gets a milder captcha: scam bots rarely pay "
        "for a subscription. OFF by default — this weakens protection, and "
        "Premium can be bought, so it feeds the overall score rather than "
        "granting a bypass.",
    },
    "guardian.settings.field.premium_trust_enabled.label": {
        "ru": "Включён", "en": "Enabled",
    },
    "guardian.settings.field.premium_trust_bonus.label": {
        "ru": "Насколько смягчать", "en": "How much to soften",
    },
    "guardian.settings.group.hygiene.title": {
        "ru": "Гигиена группы", "en": "Group hygiene",
    },
    "guardian.settings.group.hygiene.desc": {
        "ru": "Мелочи, которые обычно делают руками каждый день. Чистка "
        "служебных сообщений: в активной группе «вошёл/вышел» забивают ленту "
        "сильнее самого общения. ВНИМАНИЕ по ночному режиму: Telegram не хранит "
        "прежние права чата — при открытии выставляется стандартный набор "
        "(писать / медиа / опросы / приглашать), а не «как было». Если у группы "
        "кастомные ограничения, не включай. Время — UTC.",
        "en": "The small things admins otherwise do by hand every day. Service "
        "message cleanup: in an active group “joined/left” clutter the feed more "
        "than the conversation itself. NOTE on night mode: Telegram does not "
        "store the chat's previous permissions — on reopening a standard set is "
        "applied (text / media / polls / invites), not “as it was”. Do not "
        "enable it if the group has custom restrictions. Times are UTC.",
    },
    "guardian.settings.field.delete_join_leave_messages.label": {
        "ru": "Удалять «вошёл/вышел»", "en": "Delete “joined/left” messages",
    },
    "guardian.settings.field.delete_pin_notifications.label": {
        "ru": "Удалять «закрепил сообщение»", "en": "Delete “pinned a message”",
    },
    "guardian.settings.field.delete_pin_notifications.hint": {
        "ru": "Отдельно от остальных: иногда это единственный способ участнику "
        "узнать о закреплённом.",
        "en": "Separate from the rest: sometimes this is the only way a member "
        "learns about the pinned message.",
    },
    "guardian.settings.field.delete_service_messages.label": {
        "ru": "Удалять прочую служебку", "en": "Delete other service messages",
    },
    "guardian.settings.field.delete_service_messages.hint": {
        "ru": "Смена названия/аватара группы, видеочаты.",
        "en": "Group title/photo changes, video chats.",
    },
    "guardian.settings.field.night_mode_enabled.label": {
        "ru": "Ночной режим (закрывать чат)", "en": "Night mode (close the chat)",
    },
    "guardian.settings.field.night_mode_start_hour.label": {
        "ru": "Закрывать в час UTC", "en": "Close at hour (UTC)",
    },
    "guardian.settings.field.night_mode_end_hour.label": {
        "ru": "Открывать в час UTC", "en": "Open at hour (UTC)",
    },
    "guardian.settings.field.rules_reminder_enabled.label": {
        "ru": "Напоминать правила", "en": "Remind the rules",
    },
    "guardian.settings.field.rules_reminder_enabled.hint": {
        "ru": "Правила в закрепе никто не открывает.",
        "en": "Nobody opens the rules in the pinned message.",
    },
    "guardian.settings.field.rules_reminder_hours.label": {
        "ru": "Раз в сколько часов", "en": "Every N hours",
    },
    "guardian.settings.field.rules_reminder_text.label": {
        "ru": "Текст напоминания", "en": "Reminder text",
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
    "guardian.settings.field.openai_model.label": {
        "ru": "Модель (пусто — как у репост-бота)",
        "en": "Model (empty — same as the repost bot)",
    },
    "guardian.settings.field.openai_model.hint": {
        "ru": "Адрес и ключ провайдера общие с репост-ботом и задаются в его "
              "настройках. Здесь можно выбрать модель подешевле: отличить "
              "спам проще, чем переписать пост.",
        "en": "The provider URL and key are shared with the repost bot and set "
              "in its settings. Here you can pick a cheaper model: telling "
              "spam apart is easier than rewriting a post.",
    },
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

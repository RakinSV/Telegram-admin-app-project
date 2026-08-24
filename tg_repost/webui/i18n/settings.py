"""Страница настроек: группы и поля.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
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

    # --- Настройки tg_repost: заголовки/описания групп (settings_store.py) ---
    "settings.group.telegram.title": {"ru": "Telegram (идентичность)", "en": "Telegram (identity)"},
    "settings.group.telegram.desc": {
        "ru": "Данные приложения с my.telegram.org — не токен бота, другой "
        "тип credentials.",
        "en": "Application credentials from my.telegram.org — not the bot "
        "token, a different kind of credential.",
    },
    "settings.group.proxy.title": {"ru": "Прокси", "en": "Proxy"},
    "settings.group.proxy.desc": {
        "ru": "Один прокси-раздел на всё. Включи нужный ТИП (MTProto / SOCKS5 / "
        "HTTP(S)), впиши адрес и, если нужно, логин + пароль (пароль/секрет — в "
        "карточке секретов ниже, скрыт до кнопки «показать»), затем отметь, для "
        "чего применять: Telegram, нейросеть рерайта, картиночная нейросеть. "
        "MTProto годится только для Telegram; для нейросетей — SOCKS5 или "
        "HTTP(S).",
        "en": "One proxy section for everything. Enable a TYPE (MTProto / "
        "SOCKS5 / HTTP(S)), enter its address and, if needed, login + password "
        "(password/secret lives in the secrets card below, hidden until you "
        "click “show”), then tick what to use it for: Telegram, the rewrite AI, "
        "the image AI. MTProto only works for Telegram; for the AIs use SOCKS5 "
        "or HTTP(S).",
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
    "settings.group.editorial.title": {
        "ru": "Редакция из двух агентов", "en": "Two-agent editorial",
    },
    "settings.group.editorial.desc": {
        "ru": "Профессиональный рерайт: журналист пишет черновик, редактор-"
        "фактчекер сверяет его с источниками и пишет замечания, журналист "
        "переписывает по ним. Дороже по токенам — 1 раунд правки это ТРИ "
        "вызова LLM на вариант вместо одного. 0 раундов = только черновик. "
        "Веб-сверка требует настроенного поиска (см. «Добор источников»).",
        "en": "Professional rewrite: a journalist writes a draft, an editor/"
        "fact-checker checks it against the sources and writes notes, the "
        "journalist revises. Costs more tokens — one revision round is THREE "
        "LLM calls per variant instead of one. 0 rounds = draft only. Web "
        "verification needs a configured search engine (see “Source enrichment”).",
    },
    "settings.field.editorial_enabled.label": {
        "ru": "Включить редакцию (журналист + редактор)",
        "en": "Enable editorial (journalist + editor)",
    },
    "settings.field.editorial_max_rounds.label": {
        "ru": "Максимум раундов правки", "en": "Max revision rounds",
    },
    "settings.field.editorial_max_rounds.hint": {
        "ru": "0 = только черновик без рецензии. 1 = черновик+рецензия+правка "
        "(3 вызова LLM). 2 = до пяти вызовов на вариант.",
        "en": "0 = draft only, no review. 1 = draft+review+revise (3 LLM calls). "
        "2 = up to five calls per variant.",
    },
    "settings.field.editorial_web_verify_enabled.label": {
        "ru": "Веб-сверка спорных фактов", "en": "Web-verify disputed facts",
    },
    "settings.field.editorial_web_verify_enabled.hint": {
        "ru": "Редактор помечает сомнительные утверждения, мы догоняем их "
        "поиском (тот же движок, что «Добор источников»), находки идут на правку.",
        "en": "The editor flags dubious claims, we look them up with search "
        "(same engine as “Source enrichment”), findings go into the revision.",
    },
    "settings.field.editorial_web_verify_max_claims.label": {
        "ru": "Потолок веб-запросов на пост", "en": "Web-query cap per post",
    },
    "settings.field.editorial_prompt_template.label": {
        "ru": "Промпт редактора-фактчекера", "en": "Editor/fact-checker prompt",
    },
    "settings.field.editorial_revise_prompt_template.label": {
        "ru": "Промпт правки по замечаниям", "en": "Revision prompt",
    },
    "settings.field.editorial_newsroom_enabled.label": {
        "ru": "Транслировать ход редакции в чат",
        "en": "Broadcast the editorial process to a chat",
    },
    "settings.field.editorial_newsroom_enabled.hint": {
        "ru": "«Редакционная кухня»: видно, что журналист написал, к чему "
        "придрался редактор и что получилось после правки. Инструмент отладки: "
        "при плохом тексте сразу видно, на каком шаге сломалось.",
        "en": "The “newsroom”: see what the journalist wrote, what the editor "
        "objected to and what came out after the revision. A debugging tool — "
        "when the text is bad, you see which step broke.",
    },
    "settings.field.editorial_newsroom_chat_id.label": {
        "ru": "Чат «редакционной кухни» (id)", "en": "Newsroom chat (id)",
    },
    "settings.field.editorial_newsroom_chat_id.hint": {
        "ru": "Отдельная приватная группа. Можно указать свой user_id и получать "
        "в личку, но НЕ рекомендуется: 4–5 сообщений на пост забьют ту же личку, "
        "где кнопки одобрения.",
        "en": "A separate private group. You can put your own user_id and get it "
        "in DM, but that is NOT recommended: 4–5 messages per post will bury the "
        "same DM where the approval buttons live.",
    },
    "settings.field.editorial_newsroom_verbosity.label": {
        "ru": "Что транслировать", "en": "What to broadcast",
    },
    "settings.field.editorial_newsroom_verbosity.hint": {
        "ru": "all — весь ход; problems — только когда редактор нашёл замечания "
        "(по умолчанию: пачка из 5 постов в режиме all даёт ~25 сообщений за "
        "тик); summary — одна строка-итог на пост.",
        "en": "all — the whole exchange; problems — only when the editor found "
        "something (default: a batch of 5 posts in “all” mode means ~25 messages "
        "per tick); summary — a single summary line per post.",
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
    "settings.group.semantic_dedup.title": {
        "ru": "Дубли и сюжеты", "en": "Duplicates and stories",
    },
    "settings.group.semantic_dedup.desc": {
        "ru": "Ловит перефразированные повторы через эмбеддинги — хэш видит "
        "только дословный копипаст. Повтор из другого источника не "
        "выбрасывается, а цепляется к первому посту в «сюжет» и идёт в "
        "фактчек как подтверждение. Пауза на сбор — задержка перед рерайтом, "
        "чтобы источники успели подтянуться; 0 — без ожидания.",
        "en": "Catches paraphrased duplicates via embeddings — a hash only "
        "sees literal copy-paste. A repeat from another source is not "
        "discarded but attached to the first post as a story, and feeds the "
        "fact-check as confirmation. The grace period delays the rewrite so "
        "sources can arrive; 0 means no waiting.",
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
    "settings.group.utm.title": {
        "ru": "UTM-метки на ссылках", "en": "UTM tags on links",
    },
    "settings.group.utm.desc": {
        "ru": "Дописывает метки к внешним ссылкам при публикации — внешняя "
        "аналитика видит, какой пост принёс переходы. Ссылки на Telegram НЕ "
        "размечаются: метки там бессмысленны, а инвайт-ссылку лишний "
        "параметр может сломать.",
        "en": "Appends tags to external links at publish time so external "
        "analytics can tell which post drove the visits. Telegram links are "
        "NOT tagged: tags are meaningless there, and an extra parameter can "
        "break an invite link.",
    },
    "settings.group.approval.title": {
        "ru": "Согласование постов", "en": "Post approval",
    },
    "settings.group.approval.desc": {
        "ru": "Пост, одобренный редактором, не публикуется, пока его не "
        "подтвердит владелец. По умолчанию выключено: там, где владелец "
        "работает один или полностью доверяет редактору, это только "
        "замедляет.",
        "en": "A post approved by an editor is not published until the owner "
        "confirms it. Off by default: where the owner works alone or fully "
        "trusts the editor, this only slows things down.",
    },
    "settings.group.task_queue.title": {
        "ru": "Очередь задач", "en": "Task queue",
    },
    "settings.group.task_queue.desc": {
        "ru": "Воркер, выполняющий долгие операции: рассылки по сегменту и "
        "(в будущем) шаги воронок. Всегда включён — выключателя нет "
        "намеренно, иначе можно было бы незаметно остановить доставку уже "
        "созданных рассылок.",
        "en": "The worker that runs long operations: segment broadcasts and "
        "(later) funnel steps. Always on — there is deliberately no off "
        "switch, otherwise delivery of already-created broadcasts could be "
        "stopped without anyone noticing.",
    },
    "settings.group.channel_stats.title": {
        "ru": "Статистика канала (MTProto)", "en": "Channel stats (MTProto)",
    },
    "settings.group.channel_stats.desc": {
        "ru": "Собирает данные, которых нет у ботов: долю подписчиков с "
        "ВКЛЮЧЁННЫМИ уведомлениями и средние просмотры/репосты/реакции от "
        "самого Telegram. Падение доли уведомлений — отток ДО отписки: люди "
        "ещё подписаны, но уже не читают. Требует прав АДМИНИСТРАТОРА.",
        "en": "Collects data bots cannot get: the share of subscribers with "
        "notifications ENABLED, plus average views/shares/reactions straight "
        "from Telegram. A falling notification share means churn BEFORE "
        "unsubscribing — people are still subscribed but no longer reading. "
        "Requires ADMIN rights in the channel.",
    },
    "settings.group.media_cleanup.title": {
        "ru": "Уборка старых данных", "en": "Cleanup of old data",
    },
    "settings.group.media_cleanup.desc": {
        "ru": "Обложки постов, которые уже отработаны — отклонённых, "
              "опубликованных и упавших, — удаляются вместе со ссылками в "
              "базе. Остальные не трогаются вовсе. У упавших срок двойной: их "
              "можно повторить из админки, и повтор без картинки был бы "
              "потерей, а не уборкой. Тем же проходом уходят завершённые "
              "задачи очереди (ждущие и работающие — никогда) и записи "
              "журнала действий старше своего срока. Ноль в любом поле — не "
              "убирать вовсе.",
        "en": "Covers of posts that are already done — rejected, published and "
              "failed ones — are deleted together with their references in the "
              "database. Everything else is left alone entirely. Failed posts "
              "keep theirs twice as long: they can be retried from the admin "
              "panel, and a retry without the picture would be a loss, not "
              "cleanup. The same pass removes finished queue tasks (waiting "
              "and running ones — never) and audit log records past their own "
              "horizon. Zero in any field means no cleanup at all.",
    },
    "settings.group.backup.title": {
        "ru": "Резервные копии", "en": "Backups",
    },
    "settings.group.backup.desc": {
        "ru": "Копия включает .env, обе базы и логи; складывается в "
              "data/backups на хосте и переживает пересоздание контейнера. "
              "Раньше копии делались только кнопкой и жили внутри контейнера — "
              "то есть исчезали при каждом обновлении системы. ВАЖНО: в копии "
              "лежит мастер-ключ вместе с зашифрованной базой, поэтому "
              "выгружать её наружу можно только зашифрованной.",
        "en": "A backup includes .env, both databases and the logs; it is "
              "written to data/backups on the host and survives container "
              "recreation. Backups used to be made by a button only and lived "
              "inside the container — that is, vanished on every update. NOTE: "
              "a backup holds the master key together with the encrypted "
              "database, so send it anywhere only encrypted.",
    },
    "settings.group.recycle.title": {
        "ru": "Повтор выстреливших постов", "en": "Recycling top posts",
    },
    "settings.group.recycle.desc": {
        "ru": "Удачный пост ставится в очередь ПОВТОРНО — почти бесплатный "
        "охват из уже проверенного контента. Повтор идёт в модерацию с "
        "пометкой «🔁 ПОВТОР», а не публикуется сам. Повторяются только "
        "оригиналы и только один раз. «Мин. возраст» должен быть меньше "
        "«окна поиска», иначе кандидатов не будет никогда.",
        "en": "A high-performing post is queued AGAIN — nearly free reach "
        "from content that already proved itself. The repeat goes to "
        "moderation marked «🔁 ПОВТОР» instead of publishing itself. Only "
        "originals are recycled, and only once. «Min post age» must be less "
        "than «search window», otherwise there will never be any candidates.",
    },
    "settings.group.ads.title": {"ru": "Нативная реклама", "en": "Native ads"},
    "settings.group.ads.desc": {
        "ru": "Каждый N-й опубликованный пост сопровождается рекламным из "
        "брифов (страница «Реклама»).",
        "en": "Every Nth published post is paired with an ad from a brief "
        "(the “Ads” page).",
    },
    "settings.group.paid_access.title": {
        "ru": "Платный доступ (Stars)", "en": "Paid access (Stars)",
    },
    "settings.group.paid_access.desc": {
        "ru": "Продажа доступа к закрытому каналу за Telegram Stars — 0% "
        "комиссии против 10–20% у Tribute, PaidSub и Paywall. Платёжный "
        "контур ведёт Telegram: принимает звёзды, сам списывает следующий "
        "период и сам решает, когда подписка кончилась. Наша часть — выдать "
        "персональную ссылку с лимитом в одно использование, закрыть доступ "
        "после окончания и связать оплату с карточкой человека. Бот Engage "
        "должен быть администратором канала с правом приглашать.",
        "en": "Selling access to a private channel for Telegram Stars — 0% "
        "commission against 10–20% at Tribute, PaidSub and Paywall. Telegram "
        "runs the payment loop: it takes the stars, charges the next period "
        "itself and decides when the subscription ends. Our part is issuing a "
        "single-use personal invite link, revoking access when it expires and "
        "tying the payment to the person's card. The Engage bot must be an "
        "administrator of the channel with the invite permission.",
    },
    "settings.field.paid_access_enabled.label": {
        "ru": "Включён", "en": "Enabled",
    },
    "settings.field.paid_access_chat_id.label": {
        "ru": "chat_id закрытого канала", "en": "Private channel chat_id",
    },
    "settings.field.paid_access_price_stars.label": {
        "ru": "Цена в звёздах за 30 дней", "en": "Price in stars per 30 days",
    },
    "settings.field.paid_access_title.label": {
        "ru": "Название для счёта", "en": "Title shown on the invoice",
    },
    "settings.group.shop.title": {"ru": "Магазин", "en": "Shop"},
    "settings.group.shop.desc": {
        "ru": "Продажа ФИЗИЧЕСКИХ товаров через Bot Payments API: провайдер "
        "подключается в @BotFather, его токен вводится на этой же странице "
        "как секрет. Цифровое, потребляемое внутри Telegram, сюда класть "
        "нельзя — оно продаётся только за Stars, иначе бан бота. Остаток "
        "списывается при оплате, а не при открытии счёта: иначе брошенные "
        "корзины съедают склад.",
        "en": "Selling PHYSICAL goods through the Bot Payments API: the "
        "provider is connected in @BotFather and its token is entered on this "
        "page as a secret. Anything digital consumed inside Telegram must not "
        "go here — it is sold for Stars only, otherwise the bot is banned. "
        "Stock is decremented on payment, not when the invoice is opened: "
        "otherwise abandoned carts eat the warehouse.",
    },
    "settings.field.shop_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.shop_currency.label": {
        "ru": "Валюта каталога", "en": "Catalogue currency",
    },
    "settings.group.miniapp.title": {
        "ru": "Личный кабинет (Mini App)", "en": "Dashboard (Mini App)",
    },
    "settings.group.miniapp.desc": {
        "ru": "Кабинет внутри Telegram: своя подписка, свои приглашённые, "
        "каталог и таблица лидеров. ПУСТО = кнопки в боте нет. Mini App — "
        "единственная часть системы, которая обязана быть доступна из "
        "интернета; вся остальная админка живёт за логином. Telegram "
        "принимает только https и не открывает localhost. Доступ проверяется "
        "подписью Telegram на каждый запрос, и человек видит только своё.",
        "en": "A dashboard inside Telegram: your subscription, the people you "
        "invited, the catalogue and the leaderboard. EMPTY = no button in the "
        "bot. The Mini App is the only part of the system that has to be "
        "reachable from the internet; everything else stays behind a login. "
        "Telegram accepts https only and will not open localhost. Access is "
        "verified by Telegram's signature on every request, and a person sees "
        "only their own data.",
    },
    "settings.field.miniapp_url.label": {
        "ru": "Публичный адрес (https://…)", "en": "Public URL (https://…)",
    },
    "settings.group.affiliate.title": {
        "ru": "Партнёрская программа", "en": "Affiliate programme",
    },
    "settings.group.affiliate.desc": {
        "ru": "Процент от каждой оплаты тому, кто привёл человека. НОЛЬ "
        "выключает программу. Сложную часть уже сделал F42: комиссия "
        "начисляется только за ПОДТВЕРЖДЁННОГО реферала (вступил, написал, "
        "прожил N дней), самому себе не начисляется никогда, а возврат "
        "платежа снимает начисление обратно. Выплаты записываются вручную: "
        "Telegram не даёт боту переслать звёзды человеку.",
        "en": "A percentage of every payment to whoever brought the person. "
        "ZERO disables the programme. F42 already did the hard part: the "
        "commission is accrued only for a CONFIRMED referral (joined, posted, "
        "stayed N days), never for oneself, and a refund reverses the "
        "accrual. Payouts are recorded manually: Telegram does not let a bot "
        "send stars to a person.",
    },
    "settings.field.affiliate_percent.label": {
        "ru": "Процент партнёру, %", "en": "Partner percentage, %",
    },
    "settings.group.ad_marking.title": {
        "ru": "Маркировка рекламы", "en": "Ad marking",
    },
    "settings.group.ad_marking.desc": {
        "ru": "Дописывает в НАЧАЛО рекламного поста пометку «Реклама. "
        "<рекламодатель>. erid: <токен>». В начало, а не в конец: Telegram "
        "сворачивает длинный текст, и пометка под «показать полностью» "
        "формально есть, а фактически не видна. Пока включено, рекламный "
        "пост БЕЗ erid не публикуется — опубликовать с половиной маркировки "
        "хуже, чем не опубликовать, потому что ушедший пост не отозвать. "
        "Токен выдаёт ОРД на креатив и вставляется в бриф вручную: "
        "интеграции с API оператора нет, регистрация требует договора.",
        "en": "Prepends «Реклама. <advertiser>. erid: <token>» to an ad post. "
        "At the start, not the end: Telegram collapses long text, and a label "
        "hidden behind «show more» exists formally but is not actually seen. "
        "While enabled, an ad post WITHOUT an erid is not published at all — "
        "publishing with half the marking is worse than not publishing, "
        "because a sent post cannot be recalled. The token is issued by the "
        "ad-data operator per creative and pasted into the brief by hand: "
        "there is no API integration, registration requires a contract.",
    },
    "settings.field.ad_marking_enabled.label": {
        "ru": "Включена", "en": "Enabled",
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
    "settings.field.proxy_mtproto_enabled.label": {"ru": "MTProto: включить", "en": "MTProto: enable"},
    "settings.field.proxy_mtproto_address.label": {"ru": "MTProto: адрес (host:port)", "en": "MTProto: address (host:port)"},
    "settings.field.proxy_socks5_enabled.label": {"ru": "SOCKS5: включить", "en": "SOCKS5: enable"},
    "settings.field.proxy_socks5_address.label": {"ru": "SOCKS5: адрес (host:port)", "en": "SOCKS5: address (host:port)"},
    "settings.field.proxy_socks5_login.label": {"ru": "SOCKS5: логин", "en": "SOCKS5: login"},
    "settings.field.proxy_socks5_login.hint": {
        "ru": "Необязательно — оставь пустым, если прокси без авторизации.",
        "en": "Optional — leave blank if the proxy needs no authentication.",
    },
    "settings.field.proxy_http_enabled.label": {"ru": "HTTP(S): включить", "en": "HTTP(S): enable"},
    "settings.field.proxy_http_address.label": {"ru": "HTTP(S): адрес (host:port)", "en": "HTTP(S): address (host:port)"},
    "settings.field.proxy_http_login.label": {"ru": "HTTP(S): логин", "en": "HTTP(S): login"},
    "settings.field.proxy_http_login.hint": {
        "ru": "Необязательно — оставь пустым, если прокси без авторизации.",
        "en": "Optional — leave blank if the proxy needs no authentication.",
    },
    "settings.field.proxy_use_for_telegram.label": {
        "ru": "Применять для Telegram (Telethon + бот)",
        "en": "Use for Telegram (Telethon + bot)",
    },
    "settings.field.proxy_use_for_telegram.hint": {
        "ru": "Чтение каналов (Telethon) и постинг/модерация (Bot API) пойдут через прокси.",
        "en": "Channel reading (Telethon) and posting/moderation (Bot API) will go through the proxy.",
    },
    "settings.field.proxy_use_for_rewrite.label": {
        "ru": "Применять для нейросети рерайта",
        "en": "Use for the rewrite AI",
    },
    "settings.field.proxy_use_for_images.label": {
        "ru": "Применять для картиночной нейросети",
        "en": "Use for the image AI",
    },
    "settings.field.openai_base_url.label": {"ru": "Base URL", "en": "Base URL"},
    "common.millis": {"ru": "мс", "en": "ms"},
    "settings.refresh_models_button": {
        "ru": "Обновить список моделей", "en": "Refresh the model list",
    },
    "settings.models_fetched_at": {
        "ru": "Список от {at}. Поля моделей подсказывают из него.",
        "en": "List from {at}. Model fields suggest from it.",
    },
    "settings.models_never_fetched": {
        "ru": "Список ещё не забирали — поля моделей заполняются вручную.",
        "en": "The list has not been fetched — model fields are typed by hand.",
    },
    "settings.models_refreshed": {
        "ru": "Получено моделей: {n}", "en": "Models fetched: {n}",
    },
    "settings.models_refresh_failed": {
        "ru": "Не удалось получить список моделей: {reason}",
        "en": "Could not fetch the model list: {reason}",
    },
    "settings.models_suggest_hint": {
        "ru": "Можно выбрать из {n} моделей провайдера или вписать своё.",
        "en": "Pick from {n} provider models or type your own.",
    },
    "settings.check_provider_button": {
        "ru": "Проверить подключение к ИИ",
        "en": "Check the AI connection",
    },
    "settings.check_provider_hint": {
        "ru": "Короткий запрос к провайдеру по каждой настроенной модели. "
              "Стоит несколько токенов и отвечает сразу — вместо того чтобы "
              "узнавать об ошибке по первому посту через часы.",
        "en": "A short request to the provider for every configured model. "
              "Costs a few tokens and answers at once — instead of learning "
              "about a mistake from the first post hours later.",
    },
    "settings.field.openai_model_editor.label": {
        "ru": "Модель редактора-фактчекера (пусто — основная)",
        "en": "Fact-checking editor model (empty — main one)",
    },
    "settings.field.openai_model_editor.hint": {
        "ru": "Проверка фактов выигрывает от модели посильнее: здесь ошибка "
              "уходит в опубликованный пост.",
        "en": "Fact checking benefits from a stronger model: a mistake here "
              "ends up in a published post.",
    },
    "settings.field.openai_model_quiz.label": {
        "ru": "Модель квизов (пусто — основная)",
        "en": "Quiz model (empty — main one)",
    },
    "settings.field.openai_model_aux.label": {
        "ru": "Модель вспомогательных задач (пусто — основная)",
        "en": "Model for auxiliary tasks (empty — main one)",
    },
    "settings.field.openai_model_aux.hint": {
        "ru": "Ключевые слова, отбор источников, текст рекламы, запрос для "
              "обложки, сводка дайджеста. Задачи на десяток токенов — дешёвой "
              "модели хватает.",
        "en": "Keywords, source selection, ad copy, cover prompt, digest "
              "summary. Ten-token jobs — a cheap model is enough.",
    },
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
    "settings.field.rewrite_min_source_chars.label": {
        "ru": "Минимум материала для рерайта", "en": "Minimum source material to rewrite",
    },
    "settings.field.rewrite_min_source_chars.hint": {
        "ru": "Сколько осмысленного текста (без ссылок и служебных строк) нужно, "
              "чтобы запускать рерайт. Если по ссылке не прочитана статья и в "
              "оригинале только заголовок (CVE-стабы из RSS) — рерайтить нечего, "
              "и модель начинает ВЫДУМЫВАТЬ. Такие посты отсеиваются до модели. "
              "0 — выключить защиту.",
        "en": "How much meaningful text (excluding links and boilerplate) is "
              "required before rewriting. If the article wasn't fetched and the "
              "original is only a title (RSS CVE stubs), there's nothing to "
              "rewrite and the model starts INVENTING. Such posts are filtered "
              "out before the model. 0 disables the guard.",
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
    "settings.field.cluster_grace_minutes.label": {
        "ru": "Пауза на сбор сюжета, мин", "en": "Story grace period, min",
    },
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
    "settings.field.telegraph_blank_on_delete.label": {
        "ru": "Затирать статью при удалении поста",
        "en": "Blank the article when the post is deleted",
    },
    "settings.field.telegraph_blank_on_delete.hint": {
        "ru": "Удалить страницу Telegraph нельзя — в его API нет такого "
              "метода. Галочка заменяет текст заглушкой НЕОБРАТИМО: ссылка "
              "останется рабочей, содержимого по ней не будет. Срабатывает "
              "только когда пост удалён из ВСЕХ целей — статья одна на все "
              "группы.",
        "en": "A Telegraph page cannot be deleted — its API has no such "
              "method. This replaces the text with a stub IRREVERSIBLY: the "
              "link keeps working, the content does not. Applies only once "
              "the post is deleted from ALL targets — one article serves "
              "every group.",
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
    # F59 — UTM-метки.
    "settings.field.utm_enabled.label": {"ru": "Включены", "en": "Enabled"},
    "settings.field.utm_source.label": {"ru": "utm_source", "en": "utm_source"},
    "settings.field.utm_medium.label": {"ru": "utm_medium", "en": "utm_medium"},
    "settings.field.utm_campaign.label": {
        "ru": "utm_campaign (можно {post_id})", "en": "utm_campaign (may use {post_id})",
    },
    # F72 — согласование постов.
    "settings.field.require_owner_approval.label": {
        "ru": "Редактор одобрил → ждём владельца",
        "en": "Editor approved → wait for owner",
    },
    # F64 — очередь задач.
    "settings.field.task_queue_interval_seconds.label": {
        "ru": "Период проверки, сек", "en": "Check period, sec",
    },
    # F56 — статистика канала через MTProto.
    "settings.field.channel_stats_enabled.label": {"ru": "Включена", "en": "Enabled"},
    "settings.field.channel_stats_interval_hours.label": {
        "ru": "Период сбора, часов", "en": "Collection period, hours",
    },
    "settings.field.channel_stats_window_days.label": {
        "ru": "Окно динамики, дней", "en": "Trend window, days",
    },
    # F55 — повтор выстреливших постов.
    "settings.field.media_cleanup_enabled.label": {
        "ru": "Убирать по расписанию", "en": "Scheduled cleanup",
    },
    "settings.field.media_retention_days.label": {
        "ru": "Хранить медиа, дней", "en": "Keep media for, days",
    },
    "settings.field.queue_retention_days.label": {
        "ru": "Хранить завершённые задачи, дней",
        "en": "Keep finished tasks for, days",
    },
    "settings.field.audit_retention_days.label": {
        "ru": "Хранить журнал действий, дней",
        "en": "Keep the audit log for, days",
    },
    "settings.field.backup_enabled.label": {
        "ru": "Делать копии по расписанию", "en": "Scheduled backups",
    },
    "settings.field.backup_hour.label": {"ru": "Час по UTC", "en": "Hour, UTC"},
    "settings.field.backup_keep.label": {
        "ru": "Сколько копий хранить", "en": "How many backups to keep",
    },
    "settings.field.recycle_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.recycle_interval_hours.label": {
        "ru": "Как часто искать, часов", "en": "Check every, hours",
    },
    "settings.field.recycle_top_n.label": {
        "ru": "Повторов за проход", "en": "Repeats per run",
    },
    "settings.field.recycle_window_days.label": {
        "ru": "Окно поиска, дней", "en": "Search window, days",
    },
    "settings.field.recycle_min_age_days.label": {
        "ru": "Мин. возраст поста, дней", "en": "Min post age, days",
    },
    "settings.field.recycle_min_views.label": {
        "ru": "Порог просмотров (0=без порога)", "en": "Views threshold (0=none)",
    },
    "settings.field.ad_every_nth_post.label": {"ru": "Каждый N-й пост (0=выкл)", "en": "Every Nth post (0=off)"},
    "settings.field.growth_tracking_enabled.label": {"ru": "Включён", "en": "Enabled"},
    "settings.field.growth_snapshot_interval_minutes.label": {"ru": "Период снимков, мин", "en": "Snapshot period, min"},
    "settings.field.growth_min_snapshots.label": {"ru": "Мин. снимков для отчёта", "en": "Min snapshots for a report"},
    "settings.field.growth_report_window_days.label": {"ru": "Окно отчёта, дней", "en": "Report window, days"},
    "settings.field.post_source_button_enabled.label": {"ru": "Показывать кнопку", "en": "Show button"},
    "settings.field.post_source_button_label.label": {"ru": "Текст кнопки", "en": "Button text"},
    "settings.group.quiz.title": {"ru": "Викторины по постам", "en": "Post quizzes"},
    "settings.group.quiz.desc": {
        "ru": "Бот выдаёт контент, а через паузу задаёт по нему вопрос — очки "
        "идут за ПРАВИЛЬНЫЙ ОТВЕТ, а не за количество сообщений (те "
        "превращаются в ферму флуда). Вопрос составляет LLM из уже проверенного "
        "редактором материала: +1 вызов на пост, из которого делаем квиз. "
        "Публикует бот Engage — без его токена викторины не заработают. "
        "РАБОТАЕТ ТОЛЬКО В ГРУППАХ: в канале у постов нет авторов-участников, и "
        "ответы оттуда не приходят (для канала — его discussion-группа).",
        "en": "The bot delivers content, then asks a question about it after a "
        "delay — points go for the CORRECT ANSWER, not for message count (that "
        "turns into a flood farm). The question is written by the LLM from "
        "material already checked by the editor: +1 call per post used for a "
        "quiz. Published by the Engage bot — without its token quizzes will not "
        "work. GROUPS ONLY: channel posts have no member authors and answers "
        "never arrive from there (for a channel use its discussion group).",
    },
    "settings.field.quiz_enabled.label": {
        "ru": "Включить викторины", "en": "Enable quizzes",
    },
    "settings.field.quiz_delay_minutes.label": {
        "ru": "Пауза после поста, мин", "en": "Delay after the post, min",
    },
    "settings.field.quiz_delay_minutes.hint": {
        "ru": "Спрашивать сразу — значит проверять не чтение, а скорость реакции.",
        "en": "Asking immediately tests reaction speed, not reading.",
    },
    "settings.field.quiz_every_nth_post.label": {
        "ru": "Из каждого N-го поста", "en": "From every Nth post",
    },
    "settings.field.quiz_every_nth_post.hint": {
        "ru": "1 — из каждого, 3 — из каждого третьего. Вопрос по каждому посту "
        "быстро превращается в шум.",
        "en": "1 — every post, 3 — every third. A question after every post "
        "quickly becomes noise.",
    },
    "settings.field.quiz_prompt_template.label": {
        "ru": "Промпт составителя вопроса", "en": "Quiz author prompt",
    },
    "settings.group.referrals.title": {
        "ru": "Реферальная программа", "en": "Referral programme",
    },
    "settings.group.referrals.desc": {
        "ru": "Участник берёт у бота Engage персональную ссылку (/invite) и "
        "получает очки за приведённых. АНТИНАКРУТКА встроена: реферал "
        "засчитывается, только когда приглашённый прожил в группе указанное "
        "число дней И написал хотя бы одно сообщение. Без этого механика за "
        "день превращается в ферму мультиаккаунтов.",
        "en": "A member gets a personal link from the Engage bot (/invite) and "
        "earns points for people they bring. ANTI-FRAUD is built in: a referral "
        "counts only after the invited person has stayed in the group for the "
        "configured number of days AND posted at least one message. Without "
        "that the mechanic becomes a multi-account farm within a day.",
    },
    "settings.field.referrals_enabled.label": {
        "ru": "Включить рефералы", "en": "Enable referrals",
    },
    "settings.field.referral_min_days.label": {
        "ru": "Дней в группе до зачёта", "en": "Days in group before counting",
    },
    "settings.field.referral_min_days.hint": {
        "ru": "Вместе с требованием «написал хотя бы одно сообщение» это и есть "
        "вся защита от накрутки.",
        "en": "Together with the “posted at least one message” requirement this "
        "is the entire anti-fraud protection.",
    },
    "settings.group.contests.title": {
        "ru": "Конкурсы и розыгрыши", "en": "Contests and giveaways",
    },
    "settings.group.contests.desc": {
        "ru": "Розыгрыш ВОСПРОИЗВОДИМЫЙ: seed генерируется при создании "
        "конкурса (до появления участников) и публикуется вместе с условиями, "
        "а после розыгрыша публикуется протокол — участники и победители. "
        "Имея seed, список и алгоритм, результат перепроверяет любой. Условия "
        "проверяются ДВАЖДЫ: при записи и при розыгрыше — иначе можно "
        "подписаться, записаться и сразу отписаться. Проводит бот Engage.",
        "en": "The draw is REPRODUCIBLE: the seed is generated when the contest "
        "is created (before any participant exists) and published with the "
        "rules; after the draw a protocol is published — participants and "
        "winners. Given the seed, the list and the algorithm anyone can verify "
        "the result. Conditions are checked TWICE: on entry and at draw time — "
        "otherwise one could subscribe, enter and unsubscribe right away. Run "
        "by the Engage bot.",
    },
    "settings.field.contests_enabled.label": {
        "ru": "Включить конкурсы", "en": "Enable contests",
    },
    "settings.group.suggestions.title": {
        "ru": "Предложка и онбординг", "en": "Submissions and onboarding",
    },
    "settings.group.suggestions.desc": {
        "ru": "Предложенный подписчиком пост попадает в ТУ ЖЕ очередь модерации, "
        "что и рерайты — ты решаешь, публиковать ли. Автор виден в карточке "
        "поста. Онбординг пишет новичку короткую памятку в личку, но ТОЛЬКО "
        "тем, кто уже стартовал бота: Telegram не даёт писать первым. Обе фичи "
        "работают через бота Engage.",
        "en": "A post submitted by a subscriber lands in the SAME moderation "
        "queue as rewrites — you decide whether to publish. The author is shown "
        "on the post card. Onboarding sends a short primer to a newcomer's DM, "
        "but ONLY to those who already started the bot: Telegram does not allow "
        "writing first. Both features run through the Engage bot.",
    },
    "settings.field.suggestions_enabled.label": {
        "ru": "Принимать посты от подписчиков", "en": "Accept subscriber posts",
    },
    "settings.field.onboarding_enabled.label": {
        "ru": "Онбординг новичка в личку", "en": "Onboard newcomers in DM",
    },
    "settings.group.engage_bot.title": {
        "ru": "Engage — бот вовлечения", "en": "Engage — engagement bot",
    },
    "settings.group.engage_bot.desc": {
        "ru": "ОТДЕЛЬНЫЙ бот, который говорит с УЧАСТНИКАМИ: викторины по "
        "постам, конкурсы, реферальные приглашения, предложка. Не тот же бот, "
        "что публикует посты, и не Guardian. Получить: @BotFather → /newbot. "
        "Engage — отдельный процесс: после сохранения токена его нужно "
        "перезапустить (`docker compose restart engage`).",
        "en": "A SEPARATE bot that talks to MEMBERS: post quizzes, contests, "
        "referral invites, user submissions. Not the bot that publishes posts, "
        "and not Guardian. Get one from @BotFather → /newbot. Engage is a "
        "separate process: after saving the token restart it "
        "(`docker compose restart engage`).",
    },
}

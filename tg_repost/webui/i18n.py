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
    "nav.contacts": {"ru": "Участники", "en": "Contacts"},
    "nav.segments": {"ru": "Сегменты", "en": "Segments"},
    "nav.broadcasts": {"ru": "Рассылки", "en": "Broadcasts"},
    "nav.funnels": {"ru": "Воронки", "en": "Funnels"},
    "nav.mediakit": {"ru": "Медиакит", "en": "Media kit"},
    "nav.ad_requests": {"ru": "Заявки на рекламу", "en": "Ad requests"},
    "nav.users": {"ru": "Пользователи", "en": "Users"},
    "nav.calendar": {"ru": "Календарь", "en": "Calendar"},
    "nav.support": {"ru": "Поддержка", "en": "Support"},

    # --- F68: инбокс поддержки ---
    "support.title": {"ru": "Поддержка", "en": "Support"},
    "support.intro": {
        "ru": "Сюда попадают личные сообщения боту, не подошедшие ни одной "
              "команде. Ответ уходит тем же ботом, которому человек написал.",
        "en": "Private messages to the bot that matched no command land here. "
              "The reply goes out through the same bot the person wrote to.",
    },
    "support.all": {"ru": "все", "en": "all"},
    "support.open": {"ru": "открытые", "en": "open"},
    "support.closed": {"ru": "закрытые", "en": "closed"},
    "support.unread_n": {"ru": "без ответа: {n}", "en": "unanswered: {n}"},
    "support.person": {"ru": "Человек", "en": "Person"},
    "support.messages": {"ru": "Сообщений", "en": "Messages"},
    "support.last": {"ru": "Последнее", "en": "Last"},
    "support.status": {"ru": "Статус", "en": "Status"},
    "support.status_open": {"ru": "открыт", "en": "open"},
    "support.status_closed": {"ru": "закрыт", "en": "closed"},
    "support.new": {"ru": "новое", "en": "new"},
    "support.empty": {"ru": "Обращений пока нет.", "en": "No requests yet."},
    "support.conversation": {"ru": "Переписка", "en": "Conversation"},
    "support.from_person": {"ru": "от человека", "en": "from the person"},
    "support.from_us": {"ru": "наш ответ", "en": "our reply"},
    "support.reply_placeholder": {
        "ru": "Ответ уйдёт человеку в личку", "en": "The reply goes to their DM",
    },
    "support.send": {"ru": "Отправить", "en": "Send"},
    "support.close_thread": {"ru": "Закрыть обращение", "en": "Close request"},
    "support.reopen": {"ru": "Открыть заново", "en": "Reopen"},
    "support.closed_hint": {
        "ru": "Обращение закрыто. Новое сообщение от человека откроет его "
              "заново — значит он вернулся с тем же вопросом.",
        "en": "The request is closed. A new message from the person reopens "
              "it — meaning they came back with the same question.",
    },
    "support.who_is_it": {"ru": "Кто это", "en": "Who is this"},
    "support.card_hint": {
        "ru": "Отвечать незнакомцу и отвечать человеку, который привёл вам "
              "десять друзей, — разные разговоры.",
        "en": "Answering a stranger and answering someone who brought you ten "
              "friends are different conversations.",
    },
    "support.full_card": {"ru": "Полная карточка →", "en": "Full card →"},
    "support.error_not_sent": {
        "ru": "Ответ сохранён, но не доставлен: проверьте токен Engage. "
              "Текст не потерян — можно отправить снова.",
        "en": "The reply was saved but not delivered: check the Engage token. "
              "The text is not lost — you can send it again.",
    },

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

    # --- F66: заявки рекламодателей и бронь мест ---
    "ad_requests.title": {"ru": "Заявки на рекламу", "en": "Ad requests"},
    "ad_requests.intro": {
        "ru": "Заявка → принята → опубликована. Принятие создаёт бриф для ИИ, "
              "публикация — запись дохода. Одну дату нельзя продать дважды.",
        "en": "Request → accepted → published. Accepting creates an AI brief, "
              "publishing records revenue. One date cannot be sold twice.",
    },
    "ad_requests.no_channels": {
        "ru": "Сначала добавьте целевой канал.", "en": "Add a target channel first.",
    },
    "ad_requests.channel": {"ru": "Канал", "en": "Channel"},
    "ad_requests.show": {"ru": "Показать", "en": "Show"},
    "ad_requests.calendar": {"ru": "Сетка на месяц", "en": "Month grid"},
    "ad_requests.calendar_hint": {
        "ru": "Оранжевым — занятые даты. Занимают только принятые и "
              "опубликованные заявки: отказ место не держит.",
        "en": "Orange marks booked dates. Only accepted and published "
              "requests hold a slot; a decline does not.",
    },
    "ad_requests.free": {"ru": "свободно", "en": "free"},
    "ad_requests.list": {"ru": "Заявки", "en": "Requests"},
    "ad_requests.date": {"ru": "Дата", "en": "Date"},
    "ad_requests.advertiser": {"ru": "Рекламодатель", "en": "Advertiser"},
    "ad_requests.advertiser_placeholder": {
        "ru": "@username, почта — как удобно", "en": "@username, email — whatever",
    },
    "ad_requests.brief": {"ru": "Бриф", "en": "Brief"},
    "ad_requests.brief_hint": {
        "ru": "Текст-задание, по которому ИИ напишет рекламный пост. При "
              "принятии заявки бриф создаётся с лимитом в одно "
              "использование — оплачено одно размещение.",
        "en": "The task text the AI will write the ad post from. On accepting, "
              "the brief is created with a single-use limit — one placement "
              "was paid for.",
    },
    "ad_requests.price": {"ru": "Цена", "en": "Price"},
    "ad_requests.status": {"ru": "Статус", "en": "Status"},
    "ad_requests.actions": {"ru": "Действия", "en": "Actions"},
    "ad_requests.status_new": {"ru": "новая", "en": "new"},
    "ad_requests.status_accepted": {"ru": "принята", "en": "accepted"},
    "ad_requests.status_declined": {"ru": "отклонена", "en": "declined"},
    "ad_requests.status_published": {"ru": "опубликована", "en": "published"},
    "ad_requests.accept": {"ru": "Принять", "en": "Accept"},
    "ad_requests.decline": {"ru": "Отклонить", "en": "Decline"},
    "ad_requests.publish": {"ru": "Размещено", "en": "Published"},
    "ad_requests.publish_hint": {
        "ru": "Сумму можно поправить: договорились на одну, получили другую.",
        "en": "The amount can be corrected: agreed one, received another.",
    },
    "ad_requests.confirm_delete": {
        "ru": "Удалить заявку?", "en": "Delete this request?",
    },
    "ad_requests.empty": {"ru": "Заявок пока нет.", "en": "No requests yet."},
    "ad_requests.new": {"ru": "Новая заявка", "en": "New request"},
    "ad_requests.error_bad_date": {
        "ru": "Дата не распознана.", "en": "Date not recognised.",
    },
    "ad_requests.error_bad_price": {
        "ru": "Цена должна быть числом.", "en": "Price must be a number.",
    },
    "ad_requests.error_need_fields": {
        "ru": "Нужны рекламодатель и бриф.", "en": "Advertiser and brief are required.",
    },
    "ad_requests.error_slot_taken": {
        "ru": "На {date} уже принята заявка от {who}. Продать одно место "
              "дважды нельзя — сначала откажите одному из них.",
        "en": "A request from {who} is already accepted for {date}. One slot "
              "cannot be sold twice — decline one of them first.",
    },

    # --- F65: медиакит для рекламодателя ---
    "mediakit.title": {"ru": "Медиакит", "en": "Media kit"},
    "mediakit.intro": {
        "ru": "Карточка канала для рекламодателя. Собрана из уже накопленных "
              "данных — ничего дополнительно не измеряется.",
        "en": "A channel card for advertisers. Assembled from data already "
              "collected — nothing extra is measured.",
    },
    "mediakit.channel": {"ru": "Канал", "en": "Channel"},
    "mediakit.period": {"ru": "Период", "en": "Period"},
    "mediakit.days": {"ru": "{n} дн.", "en": "{n} days"},
    "mediakit.show": {"ru": "Показать", "en": "Show"},
    "mediakit.print_hint": {
        "ru": "Чтобы отправить рекламодателю — распечатайте страницу в PDF "
              "(Ctrl+P). Публичной ссылки нет намеренно: она сделала бы "
              "админку доступной снаружи.",
        "en": "To send it to an advertiser, print the page to PDF (Ctrl+P). "
              "There is deliberately no public link: it would expose the "
              "admin panel to the outside.",
    },
    "mediakit.no_channels": {
        "ru": "Сначала добавьте целевой канал.", "en": "Add a target channel first.",
    },
    "mediakit.subtitle": {
        "ru": "Данные за {days} дн. · собрано {date}",
        "en": "Data for {days} days · compiled {date}",
    },
    "mediakit.not_enough": {
        "ru": "Данных пока мало: нет ни одного поста со снятыми метриками. "
              "Медиакит без охватов рекламодателю ничего не скажет.",
        "en": "Not enough data yet: not a single post has measured metrics. "
              "A media kit without reach tells an advertiser nothing.",
    },
    "mediakit.subscribers": {"ru": "Подписчиков", "en": "Subscribers"},
    "mediakit.for_period": {"ru": "за период", "en": "for the period"},
    "mediakit.avg_views": {"ru": "Средний охват поста", "en": "Average post reach"},
    "mediakit.err": {"ru": "ERR", "en": "ERR"},
    "mediakit.err_hint": {
        "ru": "охват к подписчикам", "en": "reach to subscribers",
    },
    "mediakit.er": {"ru": "ER", "en": "ER"},
    "mediakit.er_hint": {
        "ru": "реакции и репосты к охвату", "en": "reactions and shares to reach",
    },
    "mediakit.notifications": {"ru": "Уведомления включены", "en": "Notifications on"},
    "mediakit.notifications_hint": {
        "ru": "доля подписчиков", "en": "share of subscribers",
    },
    "mediakit.posts": {"ru": "Постов", "en": "Posts"},
    "mediakit.coverage": {
        "ru": "Средние посчитаны по {measured} постам из {total} — по "
              "остальным метрики ещё не снимались.",
        "en": "Averages are based on {measured} posts out of {total} — the "
              "rest have no measured metrics yet.",
    },
    "mediakit.top_posts": {"ru": "Лучшие посты периода", "en": "Top posts"},
    "mediakit.post": {"ru": "Пост", "en": "Post"},
    "mediakit.views": {"ru": "Просмотры", "en": "Views"},
    "mediakit.date": {"ru": "Дата", "en": "Date"},

    # --- F71: воронки ---
    "funnels.title": {"ru": "Воронки", "en": "Funnels"},
    "funnels.intro": {
        "ru": "Цепочка сообщений с задержками: человек нажал «Запустить» у "
              "бота — и получает шаги по очереди. Цепочка обрывается, если "
              "он отписался, заблокировал бота или воронку выключили.",
        "en": "A chain of messages with delays: a person presses «Start» in "
              "the bot and receives the steps one by one. The chain stops if "
              "they unsubscribe, block the bot, or the funnel is turned off.",
    },
    "funnels.create": {"ru": "Новая воронка", "en": "New funnel"},
    "funnels.name": {"ru": "Название", "en": "Name"},
    "funnels.steps": {"ru": "Шаги", "en": "Steps"},
    "funnels.steps_n": {"ru": "{n} шт.", "en": "{n}"},
    "funnels.total_span": {"ru": "растянута на {h} ч", "en": "spans {h} h"},
    "funnels.people": {"ru": "Люди", "en": "People"},
    "funnels.running_n": {"ru": "идут: {n}", "en": "in progress: {n}"},
    "funnels.done_n": {"ru": "дошли: {n}", "en": "finished: {n}"},
    "funnels.stopped_n": {"ru": "сорвались: {n}", "en": "stopped: {n}"},
    "funnels.state": {"ru": "Состояние", "en": "State"},
    "funnels.active": {"ru": "включена", "en": "on"},
    "funnels.paused": {"ru": "выключена", "en": "off"},
    "funnels.start": {"ru": "Включить", "en": "Turn on"},
    "funnels.stop": {"ru": "Выключить", "en": "Turn off"},
    "funnels.delete": {"ru": "Удалить", "en": "Delete"},
    "funnels.confirm_activate": {
        "ru": "Включить воронку? С этого момента каждый, кто запустит бота, "
              "начнёт получать цепочку.",
        "en": "Turn the funnel on? From now on everyone who starts the bot "
              "will begin receiving the chain.",
    },
    "funnels.confirm_delete": {
        "ru": "Удалить воронку? Вместе с ней пропадёт история прохождений, "
              "восстановить её нечем.",
        "en": "Delete the funnel? Its run history goes with it and cannot be "
              "restored.",
    },
    "funnels.empty": {"ru": "Воронок пока нет.", "en": "No funnels yet."},
    "funnels.reach_note": {
        "ru": "Воронка доходит только до тех, кто запускал бота: Telegram не "
              "даёт боту написать первым.",
        "en": "A funnel only reaches people who started the bot: Telegram "
              "does not let a bot write first.",
    },
    "funnels.trigger_note": {
        "ru": "Запускается, когда человек нажимает «Запустить» у бота. Других "
              "триггеров намеренно нет: каждый — это точка, где воронка может "
              "выстрелить неожиданно.",
        "en": "Starts when a person presses «Start» in the bot. Other "
              "triggers are deliberately absent: each one is a place where a "
              "funnel could fire unexpectedly.",
    },
    "funnels.steps_hint": {
        "ru": "Часы отсчитываются от предыдущего шага, а у первого — от "
              "запуска. Пустой текст = строки нет: так шаг и добавляется, и "
              "удаляется.",
        "en": "Hours count from the previous step, and for the first one from "
              "enrollment. Empty text = no row: that is how a step is both "
              "added and removed.",
    },
    "funnels.after_hours": {"ru": "Шаг {n}, через (ч)", "en": "Step {n}, after (h)"},
    "funnels.step_placeholder": {
        "ru": "Текст сообщения. Пусто — шага нет.",
        "en": "Message text. Empty means no step.",
    },
    "funnels.save": {"ru": "Сохранить", "en": "Save"},
    "funnels.back": {"ru": "К списку", "en": "Back to list"},
    "funnels.warn_in_flight": {
        "ru": "Сейчас по цепочке идут {n} чел. Позиция хранится номером шага: "
              "вставите шаг в середину — ушедшие дальше получат чужое "
              "сообщение, уберёте хвост — их цепочка закончится досрочно.",
        "en": "{n} people are going through the chain right now. Position is "
              "stored as a step number: insert a step in the middle and those "
              "further along get someone else's message; cut the tail and "
              "their chain ends early.",
    },
    "funnels.error_no_steps": {
        "ru": "У воронки нет шагов — включать нечего.",
        "en": "The funnel has no steps — there is nothing to turn on.",
    },
    "funnels.error_delay_not_number": {
        "ru": "Шаг {n}: задержка должна быть числом часов.",
        "en": "Step {n}: the delay must be a number of hours.",
    },

    # --- F64: рассылки по сегменту ---
    "broadcasts.title": {"ru": "Рассылки", "en": "Broadcasts"},
    "broadcasts.intro": {
        "ru": "Сообщение уходит в личку каждому, кто подходит под сегмент И "
              "запускал бота. Telegram не даёт боту написать первым, поэтому "
              "получателей всегда меньше, чем людей в сегменте — сколько "
              "именно, будет видно до отправки.",
        "en": "The message goes to everyone who matches the segment AND has "
              "started the bot. Telegram does not let a bot write first, so "
              "there are always fewer recipients than people in the segment — "
              "you will see how many before sending.",
    },
    "broadcasts.new": {"ru": "Новая рассылка", "en": "New broadcast"},
    "broadcasts.segment": {"ru": "Сегмент", "en": "Segment"},
    "broadcasts.text": {"ru": "Текст", "en": "Text"},
    "broadcasts.preview_button": {
        "ru": "Посмотреть, кому уйдёт", "en": "See who will receive it",
    },
    "broadcasts.unsubscribe_note": {
        "ru": "В каждое сообщение автоматически добавляется кнопка «Отписаться "
              "от рассылок». Без неё единственным способом прекратить поток "
              "остаётся блокировка бота — а это потеря человека целиком, "
              "вместе с ответами на его вопросы.",
        "en": "Every message automatically carries an «Unsubscribe» button. "
              "Without it the only way to stop the flow is blocking the bot — "
              "which loses the person entirely, including answers to their "
              "own questions.",
    },
    "broadcasts.no_segments": {
        "ru": "Сначала создайте <a href=\"/segments\">сегмент</a> — "
              "рассылка отправляется по нему.",
        "en": "Create a <a href=\"/segments\">segment</a> first — a broadcast "
              "is sent to one.",
    },
    "broadcasts.history": {"ru": "Отправленные", "en": "Sent"},
    "broadcasts.result": {"ru": "Результат", "en": "Result"},
    "broadcasts.status": {"ru": "Состояние", "en": "State"},
    "broadcasts.delivered": {
        "ru": "доставлено {n} из {reachable}", "en": "delivered {n} of {reachable}",
    },
    "broadcasts.blocked_n": {
        "ru": "заблокировали бота: {n}", "en": "blocked the bot: {n}",
    },
    "broadcasts.failed_n": {"ru": "ошибок: {n}", "en": "errors: {n}"},
    "broadcasts.gap_hint": {
        "ru": "в сегменте было {total} — остальные не запускали бота, "
              "заблокировали его или отписались",
        "en": "the segment had {total} — the rest never started the bot, "
              "blocked it or unsubscribed",
    },
    "broadcasts.status_planned": {"ru": "в очереди", "en": "queued"},
    "broadcasts.status_running": {"ru": "отправляется", "en": "sending"},
    "broadcasts.status_done": {"ru": "завершена", "en": "finished"},
    "broadcasts.status_canceled": {"ru": "остановлена", "en": "stopped"},
    "broadcasts.stop": {"ru": "Остановить", "en": "Stop"},
    "broadcasts.confirm_cancel": {
        "ru": "Остановить рассылку? Уже отправленное вернуть нельзя.",
        "en": "Stop the broadcast? Already sent messages cannot be recalled.",
    },
    "broadcasts.empty": {"ru": "Рассылок ещё не было.", "en": "No broadcasts yet."},
    "broadcasts.error_need_segment_and_text": {
        "ru": "Нужны и сегмент, и текст.", "en": "Both a segment and text are required.",
    },
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

    # --- F63: CRM участников ---
    "contacts.title": {"ru": "Участники", "en": "Contacts"},
    "contacts.intro": {
        "ru": "Карточка собирается из всех источников: откуда пришёл, кто "
              "привёл, насколько активен, как ведёт себя в чате. Хранятся "
              "только ваши теги и заметки — остальное читается из системы.",
        "en": "The card is assembled from every source: where they came from, "
              "who invited them, how active they are, how they behave in chat. "
              "Only your tags and notes are stored — the rest is read live.",
    },
    "contacts.filter_label": {"ru": "Фильтр по тегу", "en": "Filter by tag"},
    "contacts.all_tagged": {"ru": "все с тегами", "en": "all tagged"},
    "contacts.person": {"ru": "Человек", "en": "Person"},
    "contacts.tags": {"ru": "Теги", "en": "Tags"},
    "contacts.origin": {"ru": "Источник", "en": "Origin"},
    "contacts.points": {"ru": "Очки", "en": "Points"},
    "contacts.invites": {"ru": "Привёл", "en": "Invited"},
    "contacts.status": {"ru": "Статус", "en": "Status"},
    "contacts.organic": {"ru": "органика", "en": "organic"},
    "contacts.banned": {"ru": "бан", "en": "banned"},
    "contacts.trusted": {"ru": "доверенный", "en": "trusted"},
    "contacts.left": {"ru": "ушёл", "en": "left"},
    "contacts.empty": {
        "ru": "Пока никого. Теги появляются, когда вы их проставите — "
              "начните с карточки любого участника.",
        "en": "Nobody yet. Tags appear once you add them — start from any "
              "member's card.",
    },
    "contacts.truncated": {
        "ru": "Показано {shown} из {total}. Для полной выборки — «Экспорт».",
        "en": "Showing {shown} of {total}. Use Export for the full list.",
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
    "segments.title": {"ru": "Сегменты", "en": "Segments"},
    "segments.intro": {
        "ru": "Сегмент — это ЗАПРОС, а не список. Состав пересчитывается "
              "каждый раз, поэтому он не устаревает: получил человек тег — "
              "сразу попал, ушёл из чата — сразу выпал.",
        "en": "A segment is a QUERY, not a list. Membership is recomputed "
              "every time, so it never goes stale: tag someone and they are "
              "in, they leave the chat and they are out.",
    },
    "segments.name": {"ru": "Название", "en": "Name"},
    "segments.conditions": {"ru": "Условия", "en": "Conditions"},
    "segments.size": {"ru": "Сейчас в сегменте", "en": "Currently in segment"},
    "segments.size_hint": {
        "ru": "посчитано только что", "en": "computed just now",
    },
    "segments.empty": {"ru": "Сегментов пока нет.", "en": "No segments yet."},
    "segments.new": {"ru": "Новый сегмент", "en": "New segment"},
    "segments.field_tag": {"ru": "Есть тег", "en": "Has tag"},
    "segments.field_min_points": {"ru": "Очков не меньше", "en": "Points at least"},
    "segments.field_origin": {"ru": "Пришёл по кампании", "en": "Came from campaign"},
    "segments.field_active_only": {
        "ru": "Только те, кто ещё в чате", "en": "Only those still in chat",
    },
    "segments.field_everyone": {"ru": "ВСЕ участники", "en": "EVERYONE"},
    "segments.everyone_hint": {
        "ru": "«Все» — отдельная галочка и ни с чем не сочетается. Так "
              "сегмент на всю базу нельзя получить по ошибке: разосланные "
              "сообщения не отзываются.",
        "en": "«Everyone» is a separate checkbox and combines with nothing. "
              "That way a whole-base segment cannot happen by accident: sent "
              "messages cannot be recalled.",
    },
    "segments.confirm_delete": {
        "ru": "Удалить сегмент?", "en": "Delete this segment?",
    },
    "segments.error_points_number": {
        "ru": "«Очков не меньше» должно быть числом",
        "en": "«Points at least» must be a number",
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
    "invites.origins_title": {
        "ru": "Откуда пришли подписчики", "en": "Where subscribers came from",
    },
    "invites.origins_desc": {
        "ru": "Заведи отдельную ссылку под каждое размещение и впиши его "
        "стоимость выше — тогда видно, сколько людей оно принесло, сколько из "
        "них осталось и во что обошёлся один оставшийся. Считается только по "
        "вступлениям после включения этой функции: Telegram не отдаёт историю "
        "задним числом.",
        "en": "Create a separate link per ad placement and enter its cost above "
        "— then you can see how many people it brought, how many stayed and "
        "what one remaining subscriber cost. Counts only joins after this "
        "feature was enabled: Telegram does not provide history retroactively.",
    },
    "invites.origins_empty": {
        "ru": "Пока никто не вступал (или бот ещё не админ в группе — без прав "
        "администратора Telegram не сообщает о вступлениях).",
        "en": "Nobody has joined yet (or the bot is not an admin in the group — "
        "without admin rights Telegram does not report joins).",
    },
    "invites.origin_direct": {
        "ru": "Без ссылки (поиск, приглашение админом)",
        "en": "No link (search, added by an admin)",
    },
    "invites.col_origin": {"ru": "Источник", "en": "Source"},
    "invites.col_joined": {"ru": "Пришло", "en": "Joined"},
    "invites.col_still_here": {"ru": "Осталось", "en": "Still here"},
    "invites.col_left": {"ru": "Ушло", "en": "Left"},
    "invites.col_retention7": {"ru": "Через 7д", "en": "After 7d"},
    "invites.col_retention30": {"ru": "Через 30д", "en": "After 30d"},
    "invites.col_cpa": {"ru": "Цена подписчика", "en": "Cost per subscriber"},
    "invites.col_cost": {"ru": "Стоимость размещения", "en": "Placement cost"},
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

    # --- F49: подписчики платного канала ---
    "nav.subscriptions": {"ru": "Подписки", "en": "Subscriptions"},
    "subscriptions.title": {"ru": "Платные подписки", "en": "Paid subscriptions"},
    "subscriptions.intro": {
        "ru": "Оплата идёт звёздами через Telegram — комиссии у него нет. "
        "Списание следующего периода ведёт сам Telegram; наша часть — выдать "
        "персональную ссылку и закрыть доступ, когда подписка кончилась.",
        "en": "Payment goes through Telegram Stars — Telegram takes no "
        "commission. Telegram itself charges the next period; our part is "
        "issuing a personal invite link and revoking access when the "
        "subscription ends.",
    },
    "subscriptions.active": {"ru": "Активных", "en": "Active"},
    "subscriptions.revenue": {"ru": "Получено, за вычетом возвратов", "en": "Received, refunds deducted"},
    "subscriptions.col_user": {"ru": "Человек", "en": "Person"},
    "subscriptions.col_channel": {"ru": "Канал", "en": "Channel"},
    "subscriptions.col_paid_until": {"ru": "Оплачено до", "en": "Paid until"},
    "subscriptions.col_status": {"ru": "Состояние", "en": "State"},
    "subscriptions.status_active": {"ru": "активна", "en": "active"},
    "subscriptions.status_expired": {"ru": "истекла", "en": "expired"},
    "subscriptions.status_canceled": {"ru": "отменена", "en": "canceled"},
    "subscriptions.status_refunded": {"ru": "возвращена", "en": "refunded"},
    "subscriptions.refund": {"ru": "Вернуть деньги", "en": "Refund"},
    "subscriptions.confirm_refund": {
        "ru": "Вернуть деньги и закрыть доступ? Отменить возврат нельзя.",
        "en": "Refund the money and revoke access? A refund cannot be undone.",
    },
    "subscriptions.empty": {
        "ru": "Подписок пока нет.", "en": "No subscriptions yet.",
    },
    "subscriptions.stars_note": {
        "ru": "Звёзды выводятся в TON через Fragment — они доступны через 21 "
        "день после получения. Человек может купить сами звёзды за TON, так "
        "что оплата криптой для него возможна, а правила Telegram для "
        "цифровых товаров при этом не нарушаются.",
        "en": "Stars are withdrawn to TON via Fragment and become available 21 "
        "days after being received. A person can buy the stars themselves for "
        "TON, so paying with crypto is possible for them without breaking "
        "Telegram's rules for digital goods.",
    },

    # --- F70: приём криптовалюты ---
    "nav.crypto": {"ru": "Крипта", "en": "Crypto"},
    "crypto.title": {"ru": "Приём криптовалюты", "en": "Accepting crypto"},
    "crypto.intro": {
        "ru": "Способов можно завести сколько угодно и назначить свой каждой "
        "группе. Ключи хранятся зашифрованными и не показываются обратно "
        "никогда — даже вам.",
        "en": "You can configure any number of methods and assign one to each "
        "group. Keys are stored encrypted and are never shown back — not even "
        "to you.",
    },
    "crypto.name": {"ru": "Название", "en": "Name"},
    "crypto.name_placeholder": {"ru": "Касса основного канала", "en": "Main channel till"},
    "crypto.kind": {"ru": "Способ", "en": "Method"},
    "crypto.kind_cryptobot": {"ru": "CryptoBot (Crypto Pay)", "en": "CryptoBot (Crypto Pay)"},
    "crypto.kind_walletpay": {"ru": "Wallet Pay", "en": "Wallet Pay"},
    "crypto.kind_ton_direct": {
        "ru": "Прямо на TON-кошелёк", "en": "Straight to a TON wallet",
    },
    "crypto.credential": {"ru": "Токен или адрес", "en": "Token or address"},
    "crypto.credential_placeholder": {
        "ru": "токен провайдера либо адрес кошелька EQ…",
        "en": "provider token or wallet address EQ…",
    },
    "crypto.kinds_hint": {
        "ru": "CryptoBot и Wallet Pay — посредники: им называют сумму в рублях, "
        "и они сами пересчитывают в криптовалюту. Прямой перевод посредника не "
        "имеет: комиссии нет совсем, но и пересчитывать некому — товар для него "
        "должен быть оценён в TON. Курс мы не берём со сторонних сервисов "
        "намеренно: чужой сервис соврёт — вы недополучите деньги и заметите "
        "через месяц.",
        "en": "CryptoBot and Wallet Pay are intermediaries: you name the fiat "
        "amount and they convert it. A direct transfer has no intermediary: "
        "there is no fee at all, but nobody converts either — a product sold "
        "this way must be priced in TON. We deliberately do not pull rates "
        "from third-party services: if one lies, you get underpaid and notice "
        "a month later.",
    },
    "crypto.address": {"ru": "Адрес", "en": "Address"},
    "crypto.key_hidden": {"ru": "ключ скрыт", "en": "key hidden"},
    "crypto.state": {"ru": "Состояние", "en": "State"},
    "crypto.active": {"ru": "включён", "en": "enabled"},
    "crypto.default": {"ru": "по умолчанию", "en": "default"},
    "crypto.default_short": {"ru": "по умолчанию", "en": "default"},
    "crypto.on": {"ru": "работает", "en": "on"},
    "crypto.off": {"ru": "выключен", "en": "off"},
    "crypto.add": {"ru": "Добавить способ", "en": "Add method"},
    "crypto.empty": {"ru": "Способов пока нет.", "en": "No methods yet."},
    "crypto.by_group": {"ru": "Какой кошелёк в какой группе", "en": "Which wallet in which group"},
    "crypto.by_group_intro": {
        "ru": "Товар, привязанный к группе, оплачивается её кошельком. Товары "
        "общего каталога — способом по умолчанию.",
        "en": "A product tied to a group is paid into that group's wallet. "
        "Products in the shared catalogue use the default method.",
    },
    "crypto.group": {"ru": "Группа", "en": "Group"},
    "crypto.wallet": {"ru": "Кошелёк", "en": "Wallet"},
    "crypto.uses_default": {"ru": "по умолчанию", "en": "default"},
    "crypto.bind": {"ru": "Назначить", "en": "Assign"},
    "crypto.no_groups": {"ru": "Целевых групп пока нет.", "en": "No target groups yet."},
    "crypto.legal_note": {
        "ru": "Криптой оплачиваются ТОЛЬКО физические товары магазина. Доступ "
        "в канал и другое цифровое — только за Telegram Stars: обход этого "
        "правила ведёт к бану бота.",
        "en": "Crypto pays for PHYSICAL shop goods only. Channel access and "
        "anything digital go through Telegram Stars: bypassing that rule gets "
        "the bot banned.",
    },

    # --- F44: конкурсы ---
    "nav.contests": {"ru": "Конкурсы", "en": "Contests"},
    "contests.title": {"ru": "Конкурсы и розыгрыши", "en": "Contests and giveaways"},
    "contests.intro": {
        "ru": "Участие идёт по кнопке из поста, победителей тянет бот, когда "
        "срок вышел. Розыгрыш воспроизводим: он считается по зерну, "
        "записанному при создании, и любой участник может его проверить.",
        "en": "People enter from a button in the post, and the bot draws the "
        "winners once the deadline passes. The draw is reproducible: it is "
        "computed from a seed recorded at creation, and any participant can "
        "verify it.",
    },
    "contests.chat": {"ru": "Где проводим", "en": "Where"},
    "contests.name": {"ru": "Название", "en": "Name"},
    "contests.prize": {"ru": "Приз", "en": "Prize"},
    "contests.winners": {"ru": "Победителей", "en": "Winners"},
    "contests.ends_at": {"ru": "Окончание", "en": "Ends at"},
    "contests.utc_note": {"ru": "время в UTC", "en": "time in UTC"},
    "contests.min_points": {"ru": "Минимум очков", "en": "Minimum points"},
    "contests.min_referrals": {"ru": "Минимум приглашённых", "en": "Minimum invites"},
    "contests.create": {"ru": "Создать конкурс", "en": "Create contest"},
    "contests.participants": {"ru": "Участников", "en": "Entries"},
    "contests.result": {"ru": "Итог", "en": "Result"},
    "contests.running": {"ru": "идёт", "en": "running"},
    "contests.drawing": {"ru": "срок вышел, тянем", "en": "deadline passed, drawing"},
    "contests.winners_are": {"ru": "Победители:", "en": "Winners:"},
    "contests.empty": {"ru": "Конкурсов пока не было.", "en": "No contests yet."},
    "contests.no_targets": {
        "ru": "Сначала добавьте активную целевую группу — конкурс проводится в ней.",
        "en": "Add an active target group first — a contest runs in one.",
    },
    "contests.draw_note": {
        "ru": "Кнопки «разыграть сейчас» нет намеренно: конкурс, который "
        "владелец может перетянуть, — это не конкурс. Победителей тянет бот "
        "по истечении срока.",
        "en": "There is deliberately no «draw now» button: a contest the "
        "owner can re-roll is not a contest. The bot draws once the deadline "
        "passes.",
    },
    "contests.error_need_title_and_prize": {
        "ru": "Нужны название и приз.", "en": "A name and a prize are required.",
    },
    "contests.error_numbers": {
        "ru": "Числовые поля должны быть числами.",
        "en": "Numeric fields must be numbers.",
    },
    "contests.error_winners": {
        "ru": "Победителей должно быть хотя бы один.",
        "en": "There must be at least one winner.",
    },
    "contests.error_date": {
        "ru": "Не разобрана дата окончания.", "en": "The end date is unreadable.",
    },
    "contests.error_past_date": {
        "ru": "Дата окончания уже прошла: такой конкурс разыграется первым же "
        "проходом, до того как кто-либо успеет участвовать.",
        "en": "The end date is in the past: such a contest would be drawn on "
        "the very first pass, before anyone could enter.",
    },
    "contests.error_not_created": {
        "ru": "Конкурс не создан — проверьте поля.",
        "en": "The contest was not created — check the fields.",
    },

    # --- F73: интеграции ---
    "nav.integrations": {"ru": "Интеграции", "en": "Integrations"},
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

    # --- F69/F70: магазин ---
    "nav.shop": {"ru": "Магазин", "en": "Shop"},
    "shop.title": {"ru": "Магазин", "en": "Shop"},
    "shop.intro": {
        "ru": "Только физические товары и реальные услуги. Цифровое, что "
        "потребляется внутри Telegram, продаётся ТОЛЬКО за Stars (подписка) — "
        "обход этого правила ведёт к бану бота.",
        "en": "Physical goods and real-world services only. Anything digital "
        "consumed inside Telegram is sold ONLY for Stars (subscription) — "
        "working around that rule gets the bot banned.",
    },
    "shop.disabled": {
        "ru": "Магазин выключен: витрина не показывается, счета не "
              "выставляются. Включается в настройках.",
        "en": "The shop is off: the catalogue is hidden and no invoices are "
              "issued. Enable it in settings.",
    },
    "shop.revenue": {"ru": "Выручка, {currency}", "en": "Revenue, {currency}"},
    "shop.orders_count": {"ru": "Заказов", "en": "Orders"},
    "shop.catalog": {"ru": "Каталог", "en": "Catalogue"},
    "shop.name": {"ru": "Название", "en": "Name"},
    "shop.price": {"ru": "Цена", "en": "Price"},
    "shop.price_placeholder": {"ru": "цена, напр. 1499", "en": "price, e.g. 1499"},
    "shop.stock": {"ru": "Остаток", "en": "Stock"},
    "shop.stock_placeholder": {
        "ru": "остаток (пусто — без ограничения)",
        "en": "stock (empty — unlimited)",
    },
    "shop.description": {"ru": "Описание", "en": "Description"},
    "shop.physical_only": {
        "ru": "Цена вводится в рублях, хранится в копейках. Товар создаётся "
        "СКРЫТЫМ: попасть в продажу в момент создания он не должен.",
        "en": "The price is entered in whole units and stored in minor ones. "
        "A product is created HIDDEN: it must not go on sale the moment it "
        "is created.",
    },
    "shop.state": {"ru": "Состояние", "en": "State"},
    "shop.on_sale": {"ru": "в продаже", "en": "on sale"},
    "shop.hidden": {"ru": "скрыт", "en": "hidden"},
    "shop.publish": {"ru": "В продажу", "en": "Put on sale"},
    "shop.hide": {"ru": "Скрыть", "en": "Hide"},
    "shop.confirm_delete": {
        "ru": "Удалить товар? Заказы на него останутся — в них своя копия "
              "названия и суммы.",
        "en": "Delete the product? Orders for it remain — they keep their own "
              "copy of the name and amount.",
    },
    "shop.no_products": {"ru": "Товаров пока нет.", "en": "No products yet."},
    "shop.orders": {"ru": "Заказы", "en": "Orders"},
    "shop.buyer": {"ru": "Покупатель", "en": "Buyer"},
    "shop.product": {"ru": "Товар", "en": "Product"},
    "shop.amount": {"ru": "Сумма", "en": "Amount"},
    "shop.shipping": {"ru": "Доставка", "en": "Shipping"},
    "shop.status_new": {"ru": "новый", "en": "new"},
    "shop.status_paid": {"ru": "оплачен", "en": "paid"},
    "shop.status_shipped": {"ru": "отправлен", "en": "shipped"},
    "shop.status_canceled": {"ru": "отменён", "en": "canceled"},
    "shop.mark_shipped": {"ru": "Отправлен", "en": "Mark shipped"},
    "shop.oversold": {
        "ru": "продано сверх остатка", "en": "sold beyond stock",
    },
    "shop.no_orders": {"ru": "Заказов пока нет.", "en": "No orders yet."},
    "shop.error_price": {
        "ru": "Цена должна быть числом больше нуля.",
        "en": "The price must be a number greater than zero.",
    },
    "shop.error_no_stock": {
        "ru": "Товар закончился — в продажу его вернуть нельзя, сначала "
              "пополните остаток.",
        "en": "The product is out of stock — restock it before putting it "
              "back on sale.",
    },

    # --- F67: партнёрская программа ---
    "nav.affiliate": {"ru": "Партнёры", "en": "Partners"},
    "affiliate.title": {"ru": "Партнёрская программа", "en": "Affiliate programme"},
    "affiliate.intro": {
        "ru": "Комиссия начисляется за ПОДТВЕРЖДЁННОГО реферала: приглашённый "
        "вступил, написал и прожил заданное число дней. Возврат платежа "
        "снимает начисление обратно, самому себе комиссия не начисляется.",
        "en": "The commission is accrued for a CONFIRMED referral: the invited "
        "person joined, posted and stayed the configured number of days. A "
        "refund reverses the accrual; nobody earns commission on themselves.",
    },
    "affiliate.disabled": {
        "ru": "Программа выключена: процент равен нулю. Включается в настройках.",
        "en": "The programme is off: the percentage is zero. Enable it in settings.",
    },
    "affiliate.percent": {"ru": "Процент партнёру", "en": "Partner percentage"},
    "affiliate.owed": {"ru": "Должны партнёрам", "en": "Owed to partners"},
    "affiliate.col_partner": {"ru": "Партнёр", "en": "Partner"},
    "affiliate.col_earned": {"ru": "Заработал", "en": "Earned"},
    "affiliate.col_paid": {"ru": "Выплачено", "en": "Paid out"},
    "affiliate.col_owed": {"ru": "К выплате", "en": "Owed"},
    "affiliate.col_when": {"ru": "Когда", "en": "When"},
    "affiliate.col_kind": {"ru": "Что", "en": "What"},
    "affiliate.col_amount": {"ru": "Сумма", "en": "Amount"},
    "affiliate.col_payer": {"ru": "За кого", "en": "For whom"},
    "affiliate.col_note": {"ru": "Примечание", "en": "Note"},
    "affiliate.kind_accrual": {"ru": "начислено", "en": "accrued"},
    "affiliate.kind_reversal": {"ru": "снято (возврат)", "en": "reversed (refund)"},
    "affiliate.kind_payout": {"ru": "выплачено", "en": "paid out"},
    "affiliate.record_payout": {"ru": "Записать выплату", "en": "Record payout"},
    "affiliate.note_placeholder": {
        "ru": "как перевели", "en": "how it was transferred",
    },
    "affiliate.detail_title": {"ru": "Партнёр", "en": "Partner"},
    "affiliate.back": {"ru": "К списку", "en": "Back to list"},
    "affiliate.empty": {"ru": "Пока пусто.", "en": "Nothing yet."},
    "affiliate.error_amount": {
        "ru": "Сумма должна быть целым числом звёзд.",
        "en": "The amount must be a whole number of stars.",
    },
    "affiliate.error_too_much": {
        "ru": "Выплата больше долга — записать нельзя.",
        "en": "The payout exceeds the debt and cannot be recorded.",
    },
    "affiliate.payout_note": {
        "ru": "«Записать выплату» — это ЗАПИСЬ ФАКТА, а не перевод. Telegram "
        "не даёт боту переслать звёзды человеку: вывод идёт через Fragment на "
        "ваш кошелёк, а дальше вы платите партнёру как договорились. Кнопка, "
        "которая делает вид, что переводит деньги, была бы обманом.",
        "en": "«Record payout» RECORDS A FACT, it does not transfer anything. "
        "Telegram does not let a bot send stars to a person: the withdrawal "
        "goes through Fragment to your wallet, and you pay the partner as "
        "agreed. A button pretending to move money would be a lie.",
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

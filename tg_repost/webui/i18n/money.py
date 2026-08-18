"""Деньги: подписки, магазин, крипта, партнёры.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
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
    "crypto.error_bad_chat_id": {
        "ru": "Не понял, какой это чат: нужен числовой идентификатор.",
        "en": "Could not tell which chat this is: a numeric id is required.",
    },
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
}

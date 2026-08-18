"""Аудитория: участники, рассылки, конкурсы, поддержка.

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
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

    # --- F75, шаг 6: перенос воронок в конструктор ---

    # --- F71: воронки ---

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
    "broadcasts.error_segment_gone": {
        "ru": "Сегмент удалили, пока вы смотрели предпросмотр. Рассылка НЕ "
        "отправлена — выберите другой сегмент.",
        "en": "The segment was deleted while you were reviewing the preview. "
        "The broadcast was NOT sent — pick another segment.",
    },
    "contacts.level": {"ru": "ур.", "en": "lvl"},
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
}

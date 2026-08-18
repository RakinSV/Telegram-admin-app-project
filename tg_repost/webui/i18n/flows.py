"""Конструктор ботов и сценариев (F75).

Часть общего каталога переводов. Собирается в `webui/i18n/__init__.py`;
ключи не должны повторяться между частями — за этим следит
`tests/test_i18n.py::test_no_duplicate_keys_between_parts`.
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "bots.title": {"ru": "Боты", "en": "Bots"},
    "bots.intro": {
        "ru": "Столько ботов, сколько нужно: у каждого свои сценарии. Токен "
              "проверяется у Telegram при сохранении и наружу больше не "
              "отдаётся — ни в форме, ни в журнале.",
        "en": "As many bots as you need, each with its own scenarios. The token "
              "is verified with Telegram on save and never shown again — "
              "neither in the form nor in the log.",
    },
    "bots.name": {"ru": "Название", "en": "Name"},
    "bots.username": {"ru": "Имя в Telegram", "en": "Telegram handle"},
    "bots.token": {"ru": "Токен", "en": "Token"},
    "bots.token_hint": {
        "ru": "При правке оставьте пустым, чтобы не менять токен.",
        "en": "Leave empty when editing to keep the current token.",
    },
    "bots.flows": {"ru": "Сценарии", "en": "Scenarios"},
    "bots.flows_n": {"ru": "{n} шт.", "en": "{n}"},
    "bots.state": {"ru": "Состояние", "en": "State"},
    "bots.active": {"ru": "Работает", "en": "Running"},
    "bots.paused": {"ru": "Выключен", "en": "Off"},
    "bots.start": {"ru": "Включить", "en": "Turn on"},
    "bots.stop": {"ru": "Выключить", "en": "Turn off"},
    "bots.delete": {"ru": "Удалить", "en": "Delete"},
    "bots.add": {"ru": "Добавить бота", "en": "Add a bot"},
    "bots.save": {"ru": "Сохранить", "en": "Save"},
    "bots.saved": {"ru": "Бот сохранён.", "en": "Bot saved."},
    "bots.activate_now": {"ru": "Включить сразу", "en": "Turn on right away"},
    "bots.empty": {"ru": "Ботов пока нет.", "en": "No bots yet."},
    "bots.confirm_activate": {
        "ru": "Включить бота? Он начнёт отвечать людям по опубликованным сценариям.",
        "en": "Turn the bot on? It will start answering people per published scenarios.",
    },
    "bots.confirm_delete": {
        "ru": "Удалить бота? Если у него есть сценарии, он будет только выключен.",
        "en": "Delete the bot? If it has scenarios it will only be turned off.",
    },
    "bots.error_has_flows": {
        "ru": "У бота {n} сценариев — он выключен, но не удалён: внутри них "
              "есть прохождения живых людей.",
        "en": "The bot has {n} scenarios — it was turned off, not deleted: "
              "people are in the middle of them.",
    },
    "bots.where_to_get": {
        "ru": "Токен даёт @BotFather: команда /newbot. Один бот — один токен; "
              "тот же бот, добавленный дважды, отвечает человеку по два раза.",
        "en": "Get the token from @BotFather with /newbot. One bot, one token: "
              "the same bot added twice answers a person twice.",
    },

    "flows.title": {"ru": "Сценарии: {bot}", "en": "Scenarios: {bot}"},
    "flows.intro": {
        "ru": "Сценарий — это граф: узлы «показать», «спросить», «подождать», "
              "«решить» и «сделать», соединённые переходами. Правки идут в "
              "черновик, а публикация снимает неизменяемую копию — люди, "
              "начавшие раньше, доигрывают по своей версии.",
        "en": "A scenario is a graph: show, ask, wait, decide and do nodes "
              "joined by transitions. Edits go to a draft; publishing takes an "
              "immutable copy, so people who started earlier finish on theirs.",
    },
    "flows.back_to_bots": {"ru": "Все боты", "en": "All bots"},
    "flows.bot_is_off": {
        "ru": "Бот выключен — сценарии никому не отвечают.",
        "en": "The bot is off — scenarios answer nobody.",
    },
    "flows.name": {"ru": "Название", "en": "Name"},
    "flows.trigger": {"ru": "Повод начать", "en": "Trigger"},
    "flows.trigger_start": {"ru": "Команда /start", "en": "/start command"},
    "flows.trigger_command": {"ru": "Своя команда", "en": "Custom command"},
    "flows.trigger_keyword": {"ru": "Слово в сообщении", "en": "Keyword"},
    "flows.launch_value": {"ru": "Команда или слово", "en": "Command or word"},
    "flows.launch_value_hint": {
        "ru": "Для /start не нужно. Регистр не важен.",
        "en": "Not needed for /start. Case-insensitive.",
    },
    "flows.published": {"ru": "Публикация", "en": "Published"},
    "flows.version_n": {"ru": "версия {n}", "en": "version {n}"},
    "flows.draft_only": {"ru": "только черновик", "en": "draft only"},
    "flows.people": {"ru": "Люди", "en": "People"},
    "flows.running_n": {"ru": "идут: {n}", "en": "running: {n}"},
    "flows.done_n": {"ru": "дошли: {n}", "en": "finished: {n}"},
    "flows.stopped_n": {"ru": "сорвались: {n}", "en": "dropped: {n}"},
    "flows.delete": {"ru": "Удалить", "en": "Delete"},
    "flows.confirm_delete": {
        "ru": "Удалить сценарий? Вместе с ним пропадут прохождения людей.",
        "en": "Delete the scenario? Progress of everyone inside goes with it.",
    },
    "flows.empty": {"ru": "Сценариев пока нет.", "en": "No scenarios yet."},
    "flows.create": {"ru": "Новый сценарий", "en": "New scenario"},
    "flows.create_button": {"ru": "Создать", "en": "Create"},
    "flows.save_draft": {"ru": "Сохранить черновик", "en": "Save draft"},
    "flows.publish": {"ru": "Опубликовать", "en": "Publish"},
    "flows.confirm_publish": {
        "ru": "Опубликовать сценарий? Новые люди пойдут по этой версии.",
        "en": "Publish the scenario? New people will follow this version.",
    },
    "flows.published_note": {
        "ru": "Опубликована версия {n}. Сейчас внутри {running} человек — их "
              "правки черновика не касаются.",
        "en": "Version {n} is published. {running} people are inside — draft "
              "edits do not affect them.",
    },
    "flows.not_published_yet": {
        "ru": "Сценарий не опубликован: по нему пока никто не пойдёт.",
        "en": "Not published yet: nobody will go through it.",
    },
    "flows.publish_done": {"ru": "Опубликовано: версия {n}.", "en": "Published: version {n}."},
    "flows.publish_failed": {
        "ru": "Публикация отклонена: {problems}",
        "en": "Publishing refused: {problems}",
    },
    "flows.palette": {"ru": "Типы узлов", "en": "Node types"},
    "flows.palette_open": {"ru": "Добавить узел", "en": "Add a node"},
    "flows.inspector": {"ru": "Настройки узла", "en": "Node settings"},
    "flows.canvas_hint": {
        "ru": "Узел добавляется слева, перетаскивается мышью, настраивается "
              "справа. Связь: кнопка «→» на узле, затем щелчок по тому, куда "
              "идти дальше.",
        "en": "Add a node on the left, drag it with the mouse, configure it on "
              "the right. To connect: press «→» on a node, then click the node "
              "it should lead to.",
    },
    # Категории узлов.
    "flows.category_show": {"ru": "Показать", "en": "Show"},
    "flows.category_ask": {"ru": "Спросить", "en": "Ask"},
    "flows.category_wait": {"ru": "Подождать", "en": "Wait"},
    "flows.category_decide": {"ru": "Решить", "en": "Decide"},
    "flows.category_do": {"ru": "Сделать", "en": "Do"},
    # Типы узлов.
    "flows.kind_show_text": {"ru": "Текст", "en": "Text"},
    "flows.kind_show_photo": {"ru": "Картинка", "en": "Photo"},
    "flows.kind_show_video": {"ru": "Видео", "en": "Video"},
    "flows.kind_show_document": {"ru": "Файл", "en": "Document"},
    "flows.kind_ask_buttons": {"ru": "Вопрос с кнопками", "en": "Question with buttons"},
    "flows.kind_ask_quiz": {"ru": "Тест с проверкой", "en": "Quiz with checking"},
    "flows.kind_ask_text": {"ru": "Ответ текстом", "en": "Free-text answer"},
    "flows.kind_wait_timer": {"ru": "Пауза", "en": "Pause"},
    "flows.kind_decide_condition": {"ru": "Условие", "en": "Condition"},
    "flows.kind_do_tag": {"ru": "Поставить метку", "en": "Add a tag"},
    "flows.kind_do_points": {"ru": "Дать очки", "en": "Award points"},
    "flows.kind_do_access": {"ru": "Открыть доступ", "en": "Grant access"},
    "flows.kind_do_webhook": {"ru": "Позвать вебхук", "en": "Call a webhook"},
    # Условия переходов.
    "flows.condition_always": {"ru": "дальше", "en": "next"},
    "flows.condition_button": {"ru": "по кнопке", "en": "on button"},
    "flows.condition_correct": {"ru": "верный ответ", "en": "correct answer"},
    "flows.condition_wrong": {"ru": "неверный ответ", "en": "wrong answer"},
    "flows.condition_true": {"ru": "условие выполнено", "en": "condition true"},
    "flows.condition_false": {"ru": "условие не выполнено", "en": "condition false"},
    "flows.condition_timeout": {"ru": "не ответил в срок", "en": "no answer in time"},
    # Операторы условия.
    "flows.operator_eq": {"ru": "равно", "en": "equals"},
    "flows.operator_ne": {"ru": "не равно", "en": "not equal"},
    "flows.operator_contains": {"ru": "содержит", "en": "contains"},
    "flows.operator_gt": {"ru": "больше", "en": "greater than"},
    "flows.operator_lt": {"ru": "меньше", "en": "less than"},
    "flows.operator_is_set": {"ru": "заполнено", "en": "is set"},
    "flows.operator_is_empty": {"ru": "пусто", "en": "is empty"},
    # Поля узлов.
    "flows.field_text": {"ru": "Текст", "en": "Text"},
    "flows.field_caption": {"ru": "Подпись", "en": "Caption"},
    "flows.field_file_id": {"ru": "file_id вложения", "en": "Attachment file_id"},
    "flows.field_buttons": {"ru": "Кнопки", "en": "Buttons"},
    "flows.field_timeout_hours": {"ru": "Ждать ответа, часов", "en": "Wait for answer, hours"},
    "flows.field_question": {"ru": "Вопрос", "en": "Question"},
    "flows.field_options": {"ru": "Варианты ответа", "en": "Answer options"},
    "flows.field_correct_index": {"ru": "Номер верного (с нуля)", "en": "Correct index (from 0)"},
    "flows.field_explanation": {"ru": "Пояснение к верному", "en": "Explanation for correct"},
    "flows.field_wrong_text": {"ru": "Что сказать при ошибке", "en": "What to say on a mistake"},
    "flows.field_variable": {"ru": "Имя переменной", "en": "Variable name"},
    "flows.field_hours": {"ru": "Пауза, часов", "en": "Pause, hours"},
    "flows.field_operator": {"ru": "Сравнение", "en": "Comparison"},
    "flows.field_value": {"ru": "Значение", "en": "Value"},
    "flows.field_tag": {"ru": "Метка", "en": "Tag"},
    "flows.field_points": {"ru": "Очки", "en": "Points"},
    "flows.field_chat_id": {"ru": "ID чата", "en": "Chat ID"},
    "flows.field_days": {"ru": "Дней доступа", "en": "Days of access"},
    "flows.field_payload": {"ru": "Что отправить", "en": "Payload"},
    # Холст.
    "flows.undo": {"ru": "Отменить", "en": "Undo"},
    "flows.canvas_undone": {
        "ru": "Последнее действие отменено.",
        "en": "Last action undone.",
    },
    "flows.canvas_nothing_to_undo": {
        "ru": "Отменять нечего.",
        "en": "Nothing to undo.",
    },
    "flows.canvas_copy_node": {"ru": "Сделать копию", "en": "Duplicate"},
    "flows.canvas_unsaved": {"ru": "Есть несохранённые правки.", "en": "Unsaved changes."},
    "flows.canvas_saved": {"ru": "Черновик сохранён.", "en": "Draft saved."},
    "flows.canvas_saving": {"ru": "Сохраняю…", "en": "Saving…"},
    "flows.canvas_save_failed": {"ru": "Не сохранилось:", "en": "Not saved:"},
    "flows.canvas_connect": {"ru": "Провести связь", "en": "Draw a connection"},
    "flows.canvas_connecting_hint": {
        "ru": "Теперь щёлкните узел, к которому ведёт связь.",
        "en": "Now click the node this connection leads to.",
    },
    "flows.canvas_choose_condition": {
        "ru": "При каком условии идти по этой связи?",
        "en": "Under which condition should this connection be taken?",
    },
    "flows.canvas_select_hint": {
        "ru": "Выберите узел, чтобы настроить его.",
        "en": "Pick a node to configure it.",
    },
    "flows.canvas_cancel": {"ru": "Отмена", "en": "Cancel"},
    "flows.canvas_node_key": {"ru": "Ключ", "en": "Key"},
    "flows.canvas_edges_out": {"ru": "Куда ведёт", "en": "Leads to"},
    "flows.canvas_no_edges": {
        "ru": "Никуда — здесь сценарий заканчивается.",
        "en": "Nowhere — the scenario ends here.",
    },
    "flows.canvas_delete_edge": {"ru": "Убрать", "en": "Remove"},
    "flows.canvas_delete_node": {"ru": "Удалить узел", "en": "Delete node"},
    "flows.canvas_condition_value": {"ru": "значение", "en": "value"},
    "flows.canvas_buttons_hint": {
        "ru": "По строке на кнопку: Подпись | значение",
        "en": "One button per line: Label | value",
    },
    "flows.canvas_list_hint": {
        "ru": "По строке на вариант",
        "en": "One option per line",
    },
    "flows.canvas_hours_n": {"ru": "{n} ч", "en": "{n} h"},
}

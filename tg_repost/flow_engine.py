"""Исполнение сценария-графа (F75).

ОДИН ПРОХОД ИДЁТ ДО ПЕРВОЙ ОСТАНОВКИ. Узлы «показать», «решить» и «сделать»
человека не задерживают: движок проходит их подряд, пока не встретит «спросить»
или «подождать». Иначе владельцу пришлось бы ставить таймер между картинкой и
текстом, а человек получал бы сценарий по кусочку в минуту.

ПРЕДОХРАНИТЕЛЬ ОТ ЦИКЛОВ НА ИСПОЛНЕНИИ, А НЕ ТОЛЬКО ПРИ ПУБЛИКАЦИИ. Проверка
графа ловит закольцованность заранее, но версия могла быть опубликована до
появления проверки, а данные — пережить смену кода. Цена ошибки здесь — сотня
сообщений живому человеку за секунды, поэтому предел шагов стоит и тут.

ТЕСТ СДЕЛАН КНОПКАМИ, А НЕ ВСТРОЕННЫМ ОПРОСОМ TELEGRAM. Опрос-квиз даёт
красивую анимацию, но ответ приходит отдельным апдейтом с идентификатором
опроса, который надо связать с прохождением через ещё одну таблицу. Кнопки
несут в себе и прохождение, и номер варианта, правильность определяем сами, и
в личке они ведут себя так же предсказуемо, как в группе. Анимация не стоит
лишнего звена в цепочке, где на другом конце обучение человека.

ОТВЕТ ЗАПОМИНАЕТСЯ В ПЕРЕМЕННЫХ. Без этого ветвиться дальше не по чему: смысл
конструктора в том, что третий узел знает, что человек ответил в первом.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from tg_repost import flows_repo as flows
from tg_repost.db.models import Flow, FlowRun
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

TASK_KIND = "flow_step"

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_STOPPED = "stopped"

# Сколько узлов движок проходит за один вызов, прежде чем решить, что схема
# закольцована. Двадцать пять — заведомо больше любого осмысленного отрезка
# между двумя вопросами и заведомо меньше того, что человек примет за спам.
MAX_STEPS = 25

# Сколько ждать ответа, если владелец не указал срок. Сутки: меньше — люди не
# успевают, больше — прохождения копятся месяцами.
DEFAULT_WAIT_HOURS = 24

CALLBACK_PREFIX = "flow"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_callback(run_id: int, node_key: str, value: str) -> str:
    """Данные кнопки: прохождение, узел и выбор.

    Узел входит в данные намеренно. Человек может нажать кнопку из
    ПОЗАПРОШЛОГО сообщения — старые сообщения не исчезают. Без ключа узла
    такое нажатие увело бы его на ветку из другого места сценария.
    """
    return f"{CALLBACK_PREFIX}:{run_id}:{node_key}:{value}"[:64]


def parse_callback(data: str) -> tuple[int, str, str] | None:
    parts = (data or "").split(":", 3)
    if len(parts) != 4 or parts[0] != CALLBACK_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2], parts[3]


# --- состояние прохождения ---


def _variables(run: FlowRun) -> dict[str, Any]:
    try:
        return json.loads(run.variables_json or "{}")
    except json.JSONDecodeError:
        return {}


def _stop(run_id: int, reason: str) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            return
        run.status = STATUS_STOPPED
        run.stop_reason = reason
        run.waiting_for = None
        run.wait_until = None
        run.finished_at = _utcnow()
    logger.info("F75: прохождение #%d остановлено: %s", run_id, reason)


def _finish(run_id: int) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            return
        run.status = STATUS_DONE
        run.waiting_for = None
        run.wait_until = None
        run.current_node_key = None
        run.finished_at = _utcnow()


# --- запуск ---


def start(flow_id: int, user_id: int) -> int | None:
    """Записать человека в сценарий. `None` — записывать некуда.

    Прохождение привязывается к ОПУБЛИКОВАННОЙ версии в момент старта: с этого
    мгновения правки владельца его не касаются.

    ИДУЩЕЕ ПРОХОЖДЕНИЕ НЕ ТРОГАЕМ — дважды нажатый «Запустить» иначе повёл бы
    человека по двум копиям сценария одновременно.

    ЗАКОНЧЕННОЕ — НАЧИНАЕТСЯ ЗАНОВО, по той же строке. «Прошёл обучение,
    хочу пройти снова» — обычная просьба, а отказ выглядел бы поломкой бота:
    человек пишет «/start», а в ответ тишина навсегда. Строка одна на
    человека и сценарий, поэтому новая попытка переиспользует её, а не
    ложится рядом.
    """
    with session_scope() as session:
        flow = session.get(Flow, flow_id)
        if flow is None or flow.published_version is None:
            return None

        graph = flows.load(flow_id, flow.published_version)
        start_key = graph.start_key
        if start_key is None:
            logger.error(
                "F75: у опубликованного сценария #%d нет однозначного начала",
                flow_id,
            )
            return None

        run = (
            session.query(FlowRun)
            .filter(FlowRun.flow_id == flow_id, FlowRun.user_id == user_id)
            .first()
        )
        if run is not None:
            if run.status == STATUS_RUNNING:
                return None
            logger.info(
                "F75: человек %s начинает сценарий «%s» заново (прошлый раз: %s)",
                user_id, flow.name, run.stop_reason or run.status,
            )
            run.flow_version = flow.published_version
            run.bot_id = flow.bot_id
            run.current_node_key = start_key
            run.status = STATUS_RUNNING
            run.waiting_for = None
            run.wait_until = None
            run.variables_json = "{}"
            run.stop_reason = None
            run.finished_at = None
            return run.id

        run = FlowRun(
            flow_id=flow_id, flow_version=flow.published_version,
            bot_id=flow.bot_id, user_id=user_id, current_node_key=start_key,
        )
        session.add(run)
        session.flush()
        logger.info(
            "F75: человек %s записан в сценарий «%s» (прохождение #%d)",
            user_id, flow.name, run.id,
        )
        return run.id


# --- обход ---


async def advance(run_id: int, bot) -> None:  # noqa: ANN001 — aiogram Bot
    """Пройти по графу до остановки, конца или предохранителя."""
    for _ in range(MAX_STEPS):
        with session_scope() as session:
            run = session.get(FlowRun, run_id)
            if run is None or run.status != STATUS_RUNNING:
                return
            if run.waiting_for:
                # Ждём человека — двигаться нельзя, иначе обгоним его ответ.
                return
            flow_id, version = run.flow_id, run.flow_version
            user_id, node_key = run.user_id, run.current_node_key
            variables = _variables(run)

        if node_key is None:
            _finish(run_id)
            return

        graph = flows.load(flow_id, version)
        node = graph.nodes.get(node_key)
        if node is None:
            # В замороженной версии такого быть не должно; если случилось —
            # данные повреждены, и молча продолжать нельзя.
            _stop(run_id, "узел сценария не найден")
            return

        try:
            moved = await _run_node(
                run_id=run_id, bot=bot, user_id=user_id,
                graph=graph, node=node, variables=variables,
            )
        except _PersonUnreachable:
            _stop(run_id, "человек недоступен")
            return

        if not moved:
            # Узел остановил проход: ждём ответа или таймера.
            return

    _stop(run_id, "сценарий закольцован")
    logger.warning(
        "F75: прохождение #%d прервано предохранителем — больше %d шагов подряд",
        run_id, MAX_STEPS,
    )


class _PersonUnreachable(Exception):
    """Человек заблокировал бота — писать некуда."""


def _move_to(run_id: int, node_key: str | None) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is not None:
            run.current_node_key = node_key


def _wait_for(run_id: int, kind: str, hours: int) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is not None:
            run.waiting_for = kind
            run.wait_until = _utcnow() + timedelta(hours=max(1, hours))


def _remember(run_id: int, name: str, value: Any) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None:
            return
        data = _variables(run)
        data[name] = value
        run.variables_json = json.dumps(data, ensure_ascii=False)


async def _send(bot, user_id: int, node: flows.NodeView) -> None:  # noqa: ANN001
    """Отправить содержимое узла «показать».

    Медиа уходит по `file_id`: файл загружен один раз, дальше Telegram отдаёт
    его мгновенно и бесплатно, а нам не нужно ни хранилище, ни раздача.
    """
    config = node.config
    try:
        if node.kind == flows.SHOW_TEXT:
            await bot.send_message(user_id, config.get("text") or "")
        elif node.kind == flows.SHOW_PHOTO:
            await bot.send_photo(
                user_id, config.get("file_id"), caption=config.get("caption"),
            )
        elif node.kind == flows.SHOW_VIDEO:
            await bot.send_video(
                user_id, config.get("file_id"), caption=config.get("caption"),
            )
        elif node.kind == flows.SHOW_DOCUMENT:
            await bot.send_document(
                user_id, config.get("file_id"), caption=config.get("caption"),
            )
    except Exception as exc:  # noqa: BLE001 — разбираем по тексту
        if "blocked" in str(exc).lower():
            raise _PersonUnreachable from exc
        raise


def _keyboard(run_id: int, node: flows.NodeView, labels: list[tuple[str, str]]):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=label, callback_data=build_callback(run_id, node.node_key, value),
        )]
        for label, value in labels
    ])


def _evaluate(config: dict, variables: dict) -> bool:
    """Условие в фоне: сравнить запомненный ответ с ожидаемым.

    Неизвестный оператор считается НЕВЫПОЛНЕННЫМ условием, а не ошибкой:
    ронять прохождение живого человека из-за опечатки владельца хуже, чем
    увести его по ветке «иначе», которая по правилам обязана существовать.
    """
    left = variables.get(str(config.get("variable") or ""))
    right = config.get("value")
    operator = str(config.get("operator") or "eq")

    if operator == "is_set":
        return left not in (None, "")
    if operator == "is_empty":
        return left in (None, "")
    if left is None:
        return False
    if operator == "eq":
        return str(left) == str(right)
    if operator == "ne":
        return str(left) != str(right)
    if operator == "contains":
        return str(right or "") in str(left)
    if operator in ("gt", "lt"):
        try:
            a, b = float(str(left)), float(str(right))
        except (TypeError, ValueError):
            # Сравнивать нечисло с числом — не ошибка владельца, а обычный
            # случай: человек написал «не знаю» там, где ждали количество.
            # Условие просто не выполнено.
            return False
        return a > b if operator == "gt" else a < b
    logger.warning("F75: неизвестный оператор условия %r — считаю ложью", operator)
    return False


async def _do_action(node: flows.NodeView, user_id: int) -> None:
    """Узлы «сделать»: связывают сценарий с тем, что уже есть в системе.

    Сбой действия НЕ рвёт прохождение: человек проходит обучение, а не
    обслуживает нашу интеграцию. Причина уходит в лог.
    """
    config = node.config
    try:
        if node.kind == flows.DO_TAG:
            from tg_repost import contacts_repo

            contacts_repo.add_tag(user_id, str(config.get("tag") or "").strip())
        elif node.kind == flows.DO_POINTS:
            # Очки геймификации (F43) живут ПО ЧАТУ: таблица лидеров у каждой
            # группы своя. Поэтому узлу нужен чат, а не только количество —
            # иначе непонятно, в чьём зачёте человек поднялся.
            _award_points(
                user_id=user_id,
                chat_id=int(config.get("chat_id") or 0),
                points=int(config.get("points") or 0),
            )
        elif node.kind == flows.DO_ACCESS:
            from datetime import timedelta as _td

            from tg_repost import subscriptions_repo

            days = int(config.get("days") or 30)
            subscriptions_repo.grant(
                chat_id=int(config.get("chat_id") or 0), user_id=user_id,
                paid_until=_utcnow() + _td(days=days),
            )
        elif node.kind == flows.DO_WEBHOOK:
            from tg_repost import webhooks_repo

            webhooks_repo.emit(
                webhooks_repo.EVENT_MEMBER_JOINED,
                {"user_id": user_id, "node": node.node_key,
                 "payload": config.get("payload")},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F75: действие узла %s для %s не выполнено: %s",
            node.node_key, user_id, exc,
        )


def _award_points(*, user_id: int, chat_id: int, points: int) -> None:
    """Начислить очки геймификации (F43) за шаг сценария.

    Строка активности СОЗДАЁТСЯ, если человека там ещё нет: он мог прийти в
    сценарий, ни разу не ответив на викторину в группе. Молча уронить
    начисление значило бы, что владелец поставил узел «дать очки», а очков
    никто не увидел.

    Начисление ОДНИМ запросом там, где строка уже есть: тот же класс потери,
    что чинили на остатках товара.
    """
    if points <= 0 or not chat_id:
        return
    from sqlalchemy import update

    from tg_repost.db.models import UserActivity

    with session_scope() as session:
        result = session.execute(
            update(UserActivity)
            .where(
                UserActivity.user_id == user_id,
                UserActivity.chat_id == chat_id,
            )
            .values(points=UserActivity.points + points)
        )
        if result.rowcount == 0:
            session.add(UserActivity(
                chat_id=chat_id, user_id=user_id, points=points,
            ))


async def _run_node(
    *,
    run_id: int,
    bot,  # noqa: ANN001
    user_id: int,
    graph: flows.Graph,
    node: flows.NodeView,
    variables: dict,
) -> bool:
    """Исполнить один узел. `True` — можно идти дальше, `False` — остановились."""
    key = node.node_key
    config = node.config

    if node.kind in flows.SHOW_KINDS:
        await _send(bot, user_id, node)
        nxt = graph.next_key(key, flows.ALWAYS)
        if nxt is None:
            _finish(run_id)
            return False
        _move_to(run_id, nxt)
        return True

    if node.kind == flows.ASK_BUTTONS:
        buttons = [
            (str(b.get("label") or "?"), str(b.get("value") or str(i)))
            for i, b in enumerate(config.get("buttons") or [])
        ]
        await bot.send_message(
            user_id, config.get("text") or "",
            reply_markup=_keyboard(run_id, node, buttons),
        )
        _wait_for(run_id, "buttons", int(config.get("timeout_hours") or DEFAULT_WAIT_HOURS))
        return False

    if node.kind == flows.ASK_QUIZ:
        options = list(config.get("options") or [])
        labels = [(str(text), str(i)) for i, text in enumerate(options)]
        await bot.send_message(
            user_id, config.get("question") or "",
            reply_markup=_keyboard(run_id, node, labels),
        )
        _wait_for(run_id, "quiz", int(config.get("timeout_hours") or DEFAULT_WAIT_HOURS))
        return False

    if node.kind == flows.ASK_TEXT:
        await bot.send_message(user_id, config.get("text") or "")
        _wait_for(run_id, "text", int(config.get("timeout_hours") or DEFAULT_WAIT_HOURS))
        return False

    if node.kind == flows.WAIT_TIMER:
        hours = int(config.get("hours") or 1)
        _schedule(run_id, hours)
        _wait_for(run_id, "timer", hours)
        return False

    if node.kind == flows.DECIDE_CONDITION:
        outcome = _evaluate(config, variables)
        nxt = graph.next_key(key, flows.ON_TRUE if outcome else flows.ON_FALSE)
        if nxt is None:
            _stop(run_id, "у условия нет нужной ветки")
            return False
        _move_to(run_id, nxt)
        return True

    if node.kind in flows.DO_KINDS:
        await _do_action(node, user_id)
        nxt = graph.next_key(key, flows.ALWAYS)
        if nxt is None:
            _finish(run_id)
            return False
        _move_to(run_id, nxt)
        return True

    _stop(run_id, f"неизвестный тип узла: {node.kind}")
    return False


def _schedule(run_id: int, hours: int) -> None:
    from tg_repost import task_queue

    task_queue.enqueue(
        TASK_KIND, {"run_id": run_id},
        run_after=_utcnow() + timedelta(hours=max(1, hours)),
    )


# --- ответы человека ---


async def handle_button(
    run_id: int, node_key: str, value: str, bot, *,  # noqa: ANN001
    by_user_id: int | None = None,
) -> bool:
    """Нажатие кнопки. `False` — нажатие не к месту и проигнорировано.

    Ключ узла сверяется с текущим: человек мог нажать кнопку из позапрошлого
    сообщения — старые сообщения в Telegram не исчезают. Без сверки такое
    нажатие увело бы его на ветку из другого места сценария.

    ХОЗЯИН НАЖАТИЯ СВЕРЯЕТСЯ ТОЖЕ. Пересланное сообщение СОХРАНЯЕТ кнопки
    вместе с их данными: получатель пересылки нажимает — и двигает чужое
    прохождение, а сообщения сценария летят тому, кто его начал. Проверка
    стоит здесь, а не в обработчике: обработчиков будет больше одного, а
    забыть проверку достаточно в одном.
    """
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None or run.status != STATUS_RUNNING:
            return False
        if by_user_id is not None and run.user_id != by_user_id:
            logger.warning(
                "F75: %s нажал кнопку чужого прохождения #%d — отклонено",
                by_user_id, run_id,
            )
            return False
        if run.current_node_key != node_key or not run.waiting_for:
            logger.info(
                "F75: нажатие в прохождении #%d относится к узлу %s, а человек в %s",
                run_id, node_key, run.current_node_key,
            )
            return False
        flow_id, version = run.flow_id, run.flow_version
        waiting = run.waiting_for
        user_id = run.user_id

    graph = flows.load(flow_id, version)
    node = graph.nodes.get(node_key)
    if node is None:
        _stop(run_id, "узел сценария не найден")
        return False

    if waiting == "quiz":
        correct_index = str(node.config.get("correct_index"))
        is_correct = value == correct_index
        _remember(run_id, f"{node_key}_correct", is_correct)
        _remember(run_id, f"{node_key}_answer", value)
        condition = flows.ON_CORRECT if is_correct else flows.ON_WRONG
        # Пояснение — то, ради чего обучающий тест и нужен: человек должен
        # понять, ПОЧЕМУ верно, а не только что неверно. Но текст на верный
        # ответ («Верно, четыре») человеку, который ошибся, отправлять нельзя:
        # он прочтёт похвалу за промах. Отдельный текст на ошибку не обязателен
        # — если владелец его не написал, молчим и ведём по ветке.
        explanation = (
            node.config.get("explanation") if is_correct
            else node.config.get("wrong_text")
        )
        if explanation:
            await bot.send_message(user_id, str(explanation))
    else:
        _remember(run_id, node_key, value)
        condition = flows.ON_BUTTON

    nxt = graph.next_key(node_key, condition, value)
    if nxt is None and condition == flows.ON_WRONG:
        # Ветки на неверный ответ нет: значит владелец считает вопрос
        # необязательным. Идём по верной — застревать человеку не за что.
        nxt = graph.next_key(node_key, flows.ON_CORRECT)

    _clear_wait(run_id)
    if nxt is None:
        _finish(run_id)
        return True
    _move_to(run_id, nxt)
    await advance(run_id, bot)
    return True


async def handle_text(run_id: int, text: str, bot) -> bool:  # noqa: ANN001
    """Свободный ответ текстом."""
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None or run.status != STATUS_RUNNING or run.waiting_for != "text":
            return False
        flow_id, version = run.flow_id, run.flow_version
        node_key = run.current_node_key

    graph = flows.load(flow_id, version)
    node = graph.nodes.get(node_key or "")
    if node is None:
        _stop(run_id, "узел сценария не найден")
        return False

    name = str(node.config.get("variable") or node_key)
    _remember(run_id, name, text)
    _clear_wait(run_id)

    nxt = graph.next_key(node_key or "", flows.ALWAYS)
    if nxt is None:
        _finish(run_id)
        return True
    _move_to(run_id, nxt)
    await advance(run_id, bot)
    return True


def _clear_wait(run_id: int) -> None:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is not None:
            run.waiting_for = None
            run.wait_until = None


def _user_of(run_id: int) -> int:
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        return run.user_id if run is not None else 0


def waiting_run_for(user_id: int, bot_id: int, kind: str) -> int | None:
    """Какое прохождение ждёт от человека ответ такого вида.

    БОТ В УСЛОВИИ ОБЯЗАТЕЛЕН. Один человек может проходить сценарии у двух
    ботов сразу, и оба могут ждать текст. Без бота ответ, написанный одному,
    ушёл бы в прохождение у другого — человек увидел бы продолжение чужой
    ветки от чужого имени.

    Одним запросом: обработчик входящего сообщения дёргается на каждое
    сообщение в личке, и разбирать ради этого граф было бы расточительно.
    """
    with session_scope() as session:
        row = (
            session.query(FlowRun.id)
            .filter(
                FlowRun.user_id == user_id,
                FlowRun.bot_id == bot_id,
                FlowRun.status == STATUS_RUNNING,
                FlowRun.waiting_for == kind,
            )
            .order_by(FlowRun.updated_at.desc())
            .first()
        )
        return row[0] if row else None


def running_run_for(user_id: int, bot_id: int) -> int | None:
    """Идущее прохождение человека у этого бота — для команды выхода."""
    with session_scope() as session:
        row = (
            session.query(FlowRun.id)
            .filter(
                FlowRun.user_id == user_id,
                FlowRun.bot_id == bot_id,
                FlowRun.status == STATUS_RUNNING,
            )
            .order_by(FlowRun.updated_at.desc())
            .first()
        )
        return row[0] if row else None


def stop_by_person(run_id: int) -> None:
    """Человек вышел сам.

    Отдельная причина, а не «остановлено»: владелец должен отличать «ушёл»
    от «бот не смог» — первое про сценарий, второе про поломку.
    """
    _stop(run_id, "человек вышел сам")


# --- просроченное ожидание ---


async def sweep_timeouts(bot_for) -> int:  # noqa: ANN001 — callable(bot_id) -> Bot | None
    """Разобрать прохождения, у которых вышел срок ответа.

    Возвращает число разобранных. Без этого прохождения зависают навсегда: у
    человека висит вопрос, у владельца — вечно «идёт».
    """
    now = _utcnow()
    with session_scope() as session:
        rows = (
            session.query(FlowRun.id)
            .filter(
                FlowRun.status == STATUS_RUNNING,
                FlowRun.wait_until.isnot(None),
                FlowRun.wait_until < now,
            )
            .all()
        )
        run_ids = [row[0] for row in rows]

    handled = 0
    for run_id in run_ids:
        with session_scope() as session:
            run = session.get(FlowRun, run_id)
            if run is None:
                continue
            flow_id, version = run.flow_id, run.flow_version
            node_key, bot_id = run.current_node_key, run.bot_id
            waiting = run.waiting_for

        graph = flows.load(flow_id, version)
        # Таймер — это не «не ответил»: срок вышел, значит пора идти дальше.
        condition = flows.ALWAYS if waiting == "timer" else flows.ON_TIMEOUT
        nxt = graph.next_key(node_key or "", condition)

        if nxt is None:
            _clear_wait(run_id)
            if waiting == "timer":
                _finish(run_id)
            else:
                _stop(run_id, "не ответил в срок")
            handled += 1
            continue

        bot = bot_for(bot_id)
        if bot is None:
            # Бот выключен или удалён — сообщение отправить нечем. Прохождение
            # остаётся КАК ЕСТЬ, со просроченным сроком: срок — единственный
            # признак, по которому этот проход вообще находится. Сдвинуть его
            # сейчас значило бы потерять человека навсегда: ждать он перестал
            # бы, а искать его было бы уже нечем.
            logger.info("F75: прохождение #%d ждёт бота #%s", run_id, bot_id)
            continue

        _clear_wait(run_id)
        _move_to(run_id, nxt)
        await advance(run_id, bot)
        handled += 1
    return handled


async def handle_timer_task(view) -> str | None:  # noqa: ANN001 — task_queue.TaskView
    """Обработчик очереди: у прохождения истёк таймер.

    ЖДЁТ ЛИ ПРОХОЖДЕНИЕ ТАЙМЕРА — проверяется здесь, и это не формальность.
    Срок ожидания сторожат ДВА независимых механизма: эта задача и подметание
    просроченных (`sweep_timeouts`). Кто сработает первым — не наше дело, но
    второй обязан ничего не делать. Без проверки он закрывал бы прохождение,
    которое первый уже увёл дальше, — человек оставался бы с оборванным
    сценарием на середине.
    """
    from tg_repost.flow_bots import bot_for

    run_id = int(view.payload["run_id"])
    with session_scope() as session:
        run = session.get(FlowRun, run_id)
        if run is None or run.status != STATUS_RUNNING or run.waiting_for != "timer":
            return None
        bot_id = run.bot_id
        graph = flows.load(run.flow_id, run.flow_version)
        graph_next = graph.next_key(run.current_node_key or "", flows.ALWAYS)

    bot = bot_for(bot_id)
    if bot is None:
        # Срок остаётся просроченным: подметание подберёт прохождение, когда
        # бота включат. Тот же расчёт, что в `sweep_timeouts`.
        logger.info("F75: таймер прохождения #%d — бот #%s недоступен", run_id, bot_id)
        return None

    _clear_wait(run_id)
    if graph_next is None:
        _finish(run_id)
        return None
    _move_to(run_id, graph_next)
    await advance(run_id, bot)
    return None


def register_handler() -> None:
    from tg_repost import task_queue

    task_queue.register(TASK_KIND, handle_timer_task)

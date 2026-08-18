"""Перевод линейных воронок (F71) в сценарии конструктора (F75, шаг 6).

ЗАЧЕМ ЭТО ВООБЩЕ. Воронка — это сценарий из одной ветки: подождать, сказать,
подождать, сказать. Конструктор умеет то же самое и ещё десяток вещей, поэтому
держать два движка, делающих одно, значит чинить каждую беду дважды.

ПЕРЕНОС ЛЕЧИТ ДЕФЕКТ, КОТОРЫЙ В САМИХ ВОРОНКАХ НЕ ЧИНИТСЯ. Человек попадает в
воронку, нажав «Запустить» у бота Engage, а шаги ему отправляет БОТ МОДЕРАЦИИ —
другой токен. Telegram не разрешает боту заговорить первым, поэтому тому, кто
боту модерации никогда не писал, цепочка не доходит совсем: задача уходит в
очередь, повторяется до предела и умирает в «failed», где владелец её не видит.
У сценария такой развилки нет по устройству: сценарий принадлежит боту, и
пишет человеку тот самый бот, которому человек написал сам.

СТАРАЯ ВОРОНКА НЕ ВЫКЛЮЧАЕТСЯ АВТОМАТИЧЕСКИ. Выключение обрывает цепочку всем,
кто сейчас внутри (`handle_step_task` останавливает запуск с причиной «воронка
выключена»). Поэтому перенос ничего не ломает: он создаёт сценарий, а решение
«старую больше не нужно» остаётся владельцу — вместе с числом людей, которым
это решение стоит оборванной цепочки.
"""

from __future__ import annotations

from dataclasses import dataclass

from tg_repost import funnels_repo, managed_bots_repo
from tg_repost import flows_repo as flows
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Отступы узлов на холсте. Цепочка рисуется столбиком: перенесённая воронка
# должна открываться в понятном виде, а не кучей карточек в одной точке.
_X = 40
_Y_START = 30
_Y_STEP = 130


class MigrationRefused(ValueError):
    """Перенос невозможен — с объяснением для владельца."""


@dataclass(frozen=True)
class Migrated:
    funnel_id: int
    flow_id: int
    published_version: int | None
    # Сколько людей сейчас идёт по СТАРОЙ воронке: именно им стоит выключение.
    people_inside: int


def build_graph(steps) -> tuple[list[dict], list[dict]]:  # noqa: ANN001 — tuple[Step, ...]
    """Собрать узлы и переходы из шагов воронки.

    Задержка становится ОТДЕЛЬНЫМ узлом «пауза», а не свойством сообщения:
    в конструкторе ожидание — это шаг, который видно на холсте и который можно
    подвинуть, удалить или заменить на вопрос.

    Нулевая задержка узла не порождает: пауза «ноль часов» была бы ложью на
    холсте, а движок всё равно ждал бы минимум час.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    previous: str | None = None
    y = _Y_START

    for index, step in enumerate(steps, start=1):
        if step.delay_hours > 0:
            key = f"pause{index}"
            nodes.append({
                "node_key": key, "kind": flows.WAIT_TIMER,
                "config": {"hours": step.delay_hours}, "x": _X, "y": y,
            })
            if previous is not None:
                edges.append({"from_key": previous, "to_key": key,
                              "condition": flows.ALWAYS})
            previous = key
            y += _Y_STEP

        key = f"say{index}"
        nodes.append({
            "node_key": key, "kind": flows.SHOW_TEXT,
            "config": {"text": step.text}, "x": _X, "y": y,
        })
        if previous is not None:
            edges.append({"from_key": previous, "to_key": key,
                          "condition": flows.ALWAYS})
        previous = key
        y += _Y_STEP

    return nodes, edges


def migrate(funnel_id: int, bot_id: int) -> Migrated:
    """Перенести одну воронку в сценарий выбранного бота.

    Сценарий ПУБЛИКУЕТСЯ сразу: перенос без публикации оставил бы владельца с
    черновиком, который выглядит готовым и никому не отвечает. Если граф
    почему-то не проходит проверку, перенос отменяется целиком — половина
    сценария хуже, чем его отсутствие.
    """
    funnel = funnels_repo.get(funnel_id)
    if funnel is None:
        raise MigrationRefused("Воронка не найдена")
    if not funnel.steps:
        raise MigrationRefused("В воронке нет шагов — переносить нечего")

    bot = managed_bots_repo.get(bot_id)
    if bot is None:
        raise MigrationRefused("Бот не найден")

    # Два сценария с одним поводом на одном боте — это спор за «/start»:
    # сработает один, а владелец будет думать, что работают оба.
    for existing in flows.list_for_bot(bot_id):
        if existing.trigger == "start" and existing.is_published:
            raise MigrationRefused(
                f"У бота «{bot.name}» уже есть сценарий «{existing.name}» на "
                "«/start». Два сценария на один повод спорят за него: "
                "сработает только один."
            )

    nodes, edges = build_graph(funnel.steps)
    flow_id = flows.create(bot_id, funnel.name, trigger="start")
    try:
        flows.save_draft(flow_id, nodes, edges)
        version = flows.publish(flow_id)
    except flows.InvalidFlow as exc:
        # Откатываем целиком: недоделанный сценарий в списке выглядит
        # рабочим, а им не является.
        flows.delete(flow_id)
        raise MigrationRefused(f"Сценарий не собрался: {exc}") from exc

    inside = funnels_repo.runs_of(funnel_id)["running"]
    logger.info(
        "F75: воронка «%s» перенесена в сценарий #%d бота «%s» (версия %d)",
        funnel.name, flow_id, bot.name, version,
    )
    return Migrated(
        funnel_id=funnel_id, flow_id=flow_id,
        published_version=version, people_inside=inside,
    )


def pending() -> list[funnels_repo.FunnelView]:
    """Воронки, которые ещё имеет смысл переносить.

    Пустые сюда не попадают: переносить нечего, а показывать владельцу строку,
    на которой перенос всегда откажет, — издевательство.
    """
    return [view for view in funnels_repo.list_all() if view.steps]

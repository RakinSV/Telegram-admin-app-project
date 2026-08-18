"""Сценарии-графы: чтение, правка, публикация, проверка (F75).

ЧЕРНОВИК И ПУБЛИКАЦИЯ — ГЛАВНОЕ ЗДЕСЬ. Правки идут в версию 0; публикация
снимает НЕИЗМЕНЯЕМУЮ копию под новым номером. Прохождения помнят свою версию
и доигрывают по ней, даже если владелец успел переставить половину узлов.
Без этого удалённый узел оставляет человека в пустоте — в F71 на это стоит
только предупреждение в интерфейсе, и это была слабость, а не решение.

ПРОВЕРКА ГРАФА ПЕРЕД ПУБЛИКАЦИЕЙ ОБЯЗАТЕЛЬНА. Конструктор позволяет собрать
то, что линейная цепочка не позволяла в принципе: узел, замкнутый на себя;
ветку, из которой нет выхода; узел, до которого не добраться. Первое засыпает
человека сообщениями, второе оставляет его висеть, третье — мёртвый труд
владельца. Ловить это в бою поздно, поэтому публикация проверяет граф и
отказывает с перечнем проблем.

ССЫЛКИ ПО `node_key`, А НЕ ПО `id`. При копировании в новую версию строки
получают новые `id`; ссылки по `id` указывали бы после публикации в чужую
версию.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func

from tg_repost.db.models import Flow, FlowEdge, FlowNode
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

DRAFT = 0

# --- типы узлов, по четырём категориям ---

# Показать и идти дальше.
SHOW_TEXT = "show_text"
SHOW_PHOTO = "show_photo"
SHOW_VIDEO = "show_video"
SHOW_DOCUMENT = "show_document"
# Спросить и ОСТАНОВИТЬСЯ до ответа.
ASK_BUTTONS = "ask_buttons"
ASK_QUIZ = "ask_quiz"
ASK_TEXT = "ask_text"
# Подождать.
WAIT_TIMER = "wait_timer"
# Решить в фоне, человек не видит.
DECIDE_CONDITION = "decide_condition"
# Сделать в фоне.
DO_TAG = "do_tag"
DO_POINTS = "do_points"
DO_ACCESS = "do_access"
DO_WEBHOOK = "do_webhook"

SHOW_KINDS = (SHOW_TEXT, SHOW_PHOTO, SHOW_VIDEO, SHOW_DOCUMENT)
ASK_KINDS = (ASK_BUTTONS, ASK_QUIZ, ASK_TEXT)
DO_KINDS = (DO_TAG, DO_POINTS, DO_ACCESS, DO_WEBHOOK)
ALL_KINDS = (*SHOW_KINDS, *ASK_KINDS, WAIT_TIMER, DECIDE_CONDITION, *DO_KINDS)

# --- условия переходов ---

ALWAYS = "always"
ON_BUTTON = "button"
ON_CORRECT = "correct"
ON_WRONG = "wrong"
ON_TRUE = "true"
ON_FALSE = "false"
ON_TIMEOUT = "timeout"
ALL_CONDITIONS = (
    ALWAYS, ON_BUTTON, ON_CORRECT, ON_WRONG, ON_TRUE, ON_FALSE, ON_TIMEOUT,
)

# Какие условия осмысленны для какого типа узла. Проверяется при публикации:
# переход «по верному ответу» из узла с картинкой — это не опечатка, а
# ветка, которая никогда не сработает, и человек застрянет.
_ALLOWED: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(SHOW_KINDS, (ALWAYS,)),
    **dict.fromkeys(DO_KINDS, (ALWAYS,)),
    WAIT_TIMER: (ALWAYS,),
    ASK_BUTTONS: (ON_BUTTON, ON_TIMEOUT),
    ASK_QUIZ: (ON_CORRECT, ON_WRONG, ON_TIMEOUT),
    ASK_TEXT: (ALWAYS, ON_TIMEOUT),
    DECIDE_CONDITION: (ON_TRUE, ON_FALSE),
}


class InvalidFlow(ValueError):
    """Сценарий не прошёл проверку."""


@dataclass(frozen=True)
class NodeView:
    node_key: str
    kind: str
    config: dict
    x: int
    y: int


@dataclass(frozen=True)
class EdgeView:
    from_key: str
    to_key: str
    condition: str
    condition_value: str | None


@dataclass(frozen=True)
class FlowView:
    id: int
    bot_id: int
    name: str
    trigger: str
    trigger_value: str | None
    published_version: int | None

    @property
    def is_published(self) -> bool:
        return self.published_version is not None


@dataclass
class Graph:
    """Узлы и переходы одной версии, готовые к обходу."""

    nodes: dict[str, NodeView] = field(default_factory=dict)
    edges: list[EdgeView] = field(default_factory=list)

    @property
    def start_key(self) -> str | None:
        """Узел, с которого начинается сценарий: единственный, в который не
        ведёт ни один переход.

        Определяется вычислением, а не флагом на узле: флаг можно забыть
        переставить, и сценарий начнётся с середины.
        """
        targets = {edge.to_key for edge in self.edges}
        roots = [key for key in self.nodes if key not in targets]
        return roots[0] if len(roots) == 1 else None

    def outgoing(self, node_key: str) -> list[EdgeView]:
        return [e for e in self.edges if e.from_key == node_key]

    def next_key(
        self, node_key: str, condition: str, value: str | None = None,
    ) -> str | None:
        """Куда идти из узла при таком условии.

        Для кнопок сначала ищется переход с ТОЧНЫМ значением, потом — без
        значения (общий выход на любую кнопку). Иначе владельцу пришлось бы
        рисовать по переходу на каждую кнопку даже там, где все ведут в одно
        место.
        """
        candidates = [e for e in self.outgoing(node_key) if e.condition == condition]
        if value is not None:
            exact = [e for e in candidates if e.condition_value == value]
            if exact:
                return exact[0].to_key
        loose = [e for e in candidates if not e.condition_value]
        return loose[0].to_key if loose else None


def _flow_view(row: Flow) -> FlowView:
    return FlowView(
        id=row.id, bot_id=row.bot_id, name=row.name, trigger=row.trigger,
        trigger_value=row.trigger_value,
        published_version=row.published_version,
    )


# --- сценарии ---


def create(bot_id: int, name: str, *, trigger: str = "start",
           trigger_value: str | None = None) -> int:
    clean = name.strip()
    if not clean:
        raise InvalidFlow("Название сценария не может быть пустым")
    with session_scope() as session:
        row = Flow(
            bot_id=bot_id, name=clean, trigger=trigger,
            trigger_value=(trigger_value or "").strip() or None,
        )
        session.add(row)
        session.flush()
        return row.id


def get(flow_id: int) -> FlowView | None:
    with session_scope() as session:
        row = session.get(Flow, flow_id)
        return _flow_view(row) if row is not None else None


def list_for_bot(bot_id: int) -> list[FlowView]:
    with session_scope() as session:
        rows = (
            session.query(Flow)
            .filter(Flow.bot_id == bot_id)
            .order_by(Flow.name.asc())
            .all()
        )
        return [_flow_view(row) for row in rows]


def allowed_conditions(kind: str) -> tuple[str, ...]:
    """Какие переходы осмысленны из узла такого типа.

    Нужно холсту: предложить «переход по верному ответу» из узла с картинкой
    значило бы дать владельцу нарисовать ветку, которая никогда не сработает.
    """
    return _ALLOWED.get(kind, (ALWAYS,))


def runs_of(flow_id: int) -> dict[str, int]:
    """Сколько людей в сценарии: идут, дошли, сорвались.

    Владельцу это нужно раньше, чем что-либо ещё: правка сценария, по которому
    идут люди, касается их немедленно.
    """
    from tg_repost.db.models import FlowRun

    counts = {"running": 0, "done": 0, "stopped": 0}
    with session_scope() as session:
        rows = (
            session.query(FlowRun.status, func.count(FlowRun.id))
            .filter(FlowRun.flow_id == flow_id)
            .group_by(FlowRun.status)
            .all()
        )
    for status, count in rows:
        if status in counts:
            counts[status] = count
    return counts


def find_by_trigger(
    bot_id: int, trigger: str, value: str | None = None,
) -> FlowView | None:
    """Какой сценарий этого бота начинается по такому поводу.

    Только ОПУБЛИКОВАННЫЕ: черновик — не сценарий, запускать по нему нечего, а
    человек, написавший боту, не должен получить в ответ тишину из-за того, что
    владелец не нажал «Опубликовать».

    Слово ищется без учёта регистра: человек пишет «Старт», а владелец
    записал «старт», и упереться в это было бы обидно с обеих сторон.
    """
    clean = (value or "").strip().lower()
    with session_scope() as session:
        query = (
            session.query(Flow)
            .filter(
                Flow.bot_id == bot_id,
                Flow.trigger == trigger,
                Flow.published_version.isnot(None),
            )
        )
        for row in query.order_by(Flow.id.asc()).all():
            if trigger == "start":
                return _flow_view(row)
            if (row.trigger_value or "").strip().lower() == clean:
                return _flow_view(row)
        return None


def delete(flow_id: int) -> bool:
    with session_scope() as session:
        row = session.get(Flow, flow_id)
        if row is None:
            return False
        # Узлы, переходы и прохождения чистим явно: каскад во внешнем ключе на
        # SQLite декоративен — `PRAGMA foreign_keys` по умолчанию выключен.
        from tg_repost.db.models import FlowRun

        session.query(FlowRun).filter(FlowRun.flow_id == flow_id).delete()
        session.query(FlowEdge).filter(FlowEdge.flow_id == flow_id).delete()
        session.query(FlowNode).filter(FlowNode.flow_id == flow_id).delete()
        session.delete(row)
        return True


# --- правка черновика ---


def save_draft(flow_id: int, nodes: list[dict], edges: list[dict]) -> None:
    """Заменить черновик целиком.

    ЦЕЛИКОМ, а не по одному узлу: холст присылает всю схему, и точечные
    правки означали бы сверку двух состояний на каждое перетаскивание — с
    риском разойтись. Опубликованные версии не трогаются.
    """
    prepared_nodes = []
    seen: set[str] = set()
    for raw in nodes:
        key = str(raw.get("node_key") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if not key:
            raise InvalidFlow("У узла нет ключа")
        if key in seen:
            raise InvalidFlow(f"Ключ узла повторяется: {key}")
        if kind not in ALL_KINDS:
            raise InvalidFlow(f"Неизвестный тип узла: {kind}")
        seen.add(key)
        prepared_nodes.append((key, kind, raw.get("config") or {},
                               int(raw.get("x") or 0), int(raw.get("y") or 0)))

    prepared_edges = []
    for raw in edges:
        from_key = str(raw.get("from_key") or "").strip()
        to_key = str(raw.get("to_key") or "").strip()
        condition = str(raw.get("condition") or ALWAYS).strip()
        if from_key not in seen or to_key not in seen:
            raise InvalidFlow(f"Переход ведёт в неизвестный узел: {from_key}→{to_key}")
        if condition not in ALL_CONDITIONS:
            raise InvalidFlow(f"Неизвестное условие перехода: {condition}")
        value = raw.get("condition_value")
        prepared_edges.append(
            (from_key, to_key, condition, str(value) if value not in (None, "") else None)
        )

    with session_scope() as session:
        session.query(FlowNode).filter(
            FlowNode.flow_id == flow_id, FlowNode.version == DRAFT,
        ).delete()
        session.query(FlowEdge).filter(
            FlowEdge.flow_id == flow_id, FlowEdge.version == DRAFT,
        ).delete()
        for key, kind, config, x, y in prepared_nodes:
            session.add(FlowNode(
                flow_id=flow_id, version=DRAFT, node_key=key, kind=kind,
                config_json=json.dumps(config, ensure_ascii=False), x=x, y=y,
            ))
        for from_key, to_key, condition, value in prepared_edges:
            session.add(FlowEdge(
                flow_id=flow_id, version=DRAFT, from_key=from_key,
                to_key=to_key, condition=condition, condition_value=value,
            ))


def load(flow_id: int, version: int) -> Graph:
    """Прочитать версию сценария целиком.

    Целиком и одним разом: обход графа дёргает соседей десятки раз, и запрос
    на каждый шаг превратил бы прохождение в N+1 по живому боту.
    """
    graph = Graph()
    with session_scope() as session:
        nodes = (
            session.query(FlowNode)
            .filter(FlowNode.flow_id == flow_id, FlowNode.version == version)
            .all()
        )
        edges = (
            session.query(FlowEdge)
            .filter(FlowEdge.flow_id == flow_id, FlowEdge.version == version)
            .all()
        )
        for node in nodes:
            graph.nodes[node.node_key] = NodeView(
                node_key=node.node_key, kind=node.kind,
                config=json.loads(node.config_json or "{}"),
                x=node.x, y=node.y,
            )
        graph.edges = [
            EdgeView(
                from_key=e.from_key, to_key=e.to_key,
                condition=e.condition, condition_value=e.condition_value,
            )
            for e in edges
        ]
    return graph


# --- проверка графа ---


def validate(graph: Graph) -> list[str]:
    """Что не так с графом. Пустой список — можно публиковать.

    Возвращает ПЕРЕЧЕНЬ, а не первую ошибку: владелец правит схему целиком, и
    находить проблемы по одной, публикуя заново, — издевательство.
    """
    problems: list[str] = []

    if not graph.nodes:
        return ["В сценарии нет ни одного узла"]

    targets = {e.to_key for e in graph.edges}
    roots = [k for k in graph.nodes if k not in targets]
    if not roots:
        problems.append(
            "Нет начала: в каждый узел ведёт переход, значит сценарий начинать неоткуда"
        )
    elif len(roots) > 1:
        problems.append(
            "Несколько начал: " + ", ".join(sorted(roots))
            + " — непонятно, с какого начинать"
        )

    # Недостижимые узлы: труд владельца, который никто не увидит.
    if len(roots) == 1:
        reachable: set[str] = set()
        stack = [roots[0]]
        while stack:
            key = stack.pop()
            if key in reachable:
                continue
            reachable.add(key)
            stack.extend(e.to_key for e in graph.outgoing(key))
        orphans = sorted(set(graph.nodes) - reachable)
        if orphans:
            problems.append("До этих узлов не добраться: " + ", ".join(orphans))

    # Импорт локальный: схема полей знает про типы узлов, объявленные здесь.
    from tg_repost import flow_schema

    for key, node in sorted(graph.nodes.items()):
        outgoing = graph.outgoing(key)
        allowed = _ALLOWED.get(node.kind, (ALWAYS,))

        # Незаполненное обязательное поле видно только в бою: узел «показать
        # видео» без файла ничего не покажет, а человек будет ждать.
        unfilled = flow_schema.problems_in_config(node.kind, node.config)
        if unfilled:
            problems.append(
                f"Узел {key} ({node.kind}): не заполнено — " + ", ".join(unfilled)
            )

        for edge in outgoing:
            if edge.condition not in allowed:
                problems.append(
                    f"Узел {key} ({node.kind}): переход «{edge.condition}» здесь "
                    "никогда не сработает"
                )

        # Два одинаковых выхода из одного узла: сработает первый, второй мёртв,
        # и владелец об этом не узнает — он видит на холсте две линии и считает,
        # что нарисовал выбор. Обход берёт первый подходящий переход, поэтому
        # неоднозначность надо ловить здесь, а не «как-нибудь решать» в бою.
        seen_outs: set[tuple[str, str | None]] = set()
        for edge in outgoing:
            signature = (edge.condition, edge.condition_value)
            if signature in seen_outs:
                problems.append(
                    f"Узел {key}: два перехода «{edge.condition}»"
                    + (f" со значением «{edge.condition_value}»"
                       if edge.condition_value else "")
                    + " — сработает только первый"
                )
            seen_outs.add(signature)

        if node.kind == DECIDE_CONDITION:
            have = {e.condition for e in outgoing}
            missing = {ON_TRUE, ON_FALSE} - have
            if missing:
                problems.append(
                    f"Условие {key}: не хватает ветки "
                    + ", ".join(sorted(missing))
                    + " — человек упрётся в тупик"
                )
        elif node.kind == ASK_QUIZ:
            have = {e.condition for e in outgoing}
            if ON_CORRECT not in have:
                problems.append(f"Тест {key}: нет ветки на верный ответ")
        elif node.kind == ASK_BUTTONS:
            if not any(e.condition == ON_BUTTON for e in outgoing):
                problems.append(f"Кнопки {key}: ни одна кнопка никуда не ведёт")

        # Узел без выхода — это конец сценария, и это нормально ТОЛЬКО если он
        # так и задуман. Отличить нельзя, поэтому молчим: тупик ловится
        # проверкой «условие без ветки» выше, а осмысленный финал выходов и
        # не имеет.

    # Цикл без выхода: из группы узлов нельзя выйти наружу. Именно он
    # засыпает человека сообщениями за секунды.
    problems.extend(_dead_loops(graph))
    return problems


def _dead_loops(graph: Graph) -> list[str]:
    """Циклы, из которых нет выхода к узлу без исходящих переходов."""
    # Узлы, откуда достижим финал (узел без выходов).
    can_finish: set[str] = set()
    changed = True
    while changed:
        changed = False
        for key in graph.nodes:
            if key in can_finish:
                continue
            outgoing = graph.outgoing(key)
            if not outgoing or any(e.to_key in can_finish for e in outgoing):
                can_finish.add(key)
                changed = True

    stuck = sorted(set(graph.nodes) - can_finish)
    if stuck:
        return [
            "Из этих узлов невозможно выйти — сценарий закольцован: "
            + ", ".join(stuck)
        ]
    return []


# --- публикация ---


def publish(flow_id: int) -> int:
    """Снять неизменяемую копию черновика. Возвращает номер версии.

    Бросает `InvalidFlow` с перечнем проблем, если граф собран неверно:
    выпустить в работу сценарий, в котором человек застрянет или получит
    сотню сообщений, хуже, чем не выпустить вовсе.
    """
    graph = load(flow_id, DRAFT)
    problems = validate(graph)
    if problems:
        raise InvalidFlow("; ".join(problems))

    with session_scope() as session:
        row = session.get(Flow, flow_id)
        if row is None:
            raise InvalidFlow("Сценарий не найден")

        highest = (
            session.query(FlowNode.version)
            .filter(FlowNode.flow_id == flow_id)
            .order_by(FlowNode.version.desc())
            .first()
        )
        version = (highest[0] if highest else 0) + 1

        for key, node in graph.nodes.items():
            session.add(FlowNode(
                flow_id=flow_id, version=version, node_key=key, kind=node.kind,
                config_json=json.dumps(node.config, ensure_ascii=False),
                x=node.x, y=node.y,
            ))
        for edge in graph.edges:
            session.add(FlowEdge(
                flow_id=flow_id, version=version, from_key=edge.from_key,
                to_key=edge.to_key, condition=edge.condition,
                condition_value=edge.condition_value,
            ))
        row.published_version = version
        logger.info("F75: сценарий #%d опубликован как версия %d", flow_id, version)
        return version

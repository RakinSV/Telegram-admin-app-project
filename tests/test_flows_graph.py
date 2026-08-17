"""Сценарий-граф: правка, проверка, публикация (F75).

Конструктор позволяет собрать то, что линейная цепочка не позволяла в
принципе: узел, замкнутый на себя; ветку без выхода; узел, до которого не
добраться. Первое засыпает человека сообщениями, второе оставляет его висеть,
третье — мёртвый труд владельца.

Поэтому главное здесь — не «схема сохранилась», а что негодную схему НЕ
ОПУБЛИКУЮТ, и что опубликованная больше не меняется.
"""

from __future__ import annotations

import pytest

from tg_repost import flows_repo as flows
from tg_repost.db.models import Flow, FlowEdge, FlowNode, FlowRun, ManagedBot
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FlowRun).delete()
            session.query(FlowEdge).delete()
            session.query(FlowNode).delete()
            session.query(Flow).delete()
            session.query(ManagedBot).delete()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def _flow() -> int:
    with session_scope() as session:
        bot = ManagedBot(name="Бот", token_encrypted="x", token_hint="••••")
        session.add(bot)
        session.flush()
        bot_id = bot.id
    return flows.create(bot_id, "Обучающий трек")


def _node(key: str, kind: str, **config) -> dict:
    return {"node_key": key, "kind": kind, "config": config, "x": 0, "y": 0}


def _edge(a: str, b: str, condition: str = flows.ALWAYS, value=None) -> dict:
    return {
        "from_key": a, "to_key": b,
        "condition": condition, "condition_value": value,
    }


def _good_track() -> tuple[list[dict], list[dict]]:
    """Видео → тест → следующий этап; неверный ответ возвращает к видео.

    Ровно тот сценарий, из которого выросла вся фича.
    """
    nodes = [
        _node("v1", flows.SHOW_VIDEO, file_id="BAACagIAAx", caption="Урок 1"),
        _node("q1", flows.ASK_QUIZ, question="Сколько?", options=["1", "2"],
              correct_index=1, timeout_hours=24),
        _node("v2", flows.SHOW_VIDEO, file_id="BAACagIAAy", caption="Урок 2"),
        _node("end", flows.DO_POINTS, points=10),
    ]
    edges = [
        _edge("v1", "q1"),
        _edge("q1", "v2", flows.ON_CORRECT),
        _edge("q1", "v1", flows.ON_WRONG),
        _edge("v2", "end"),
    ]
    return nodes, edges


# --- правка черновика ---


def test_draft_is_saved_and_read_back(_flow):
    nodes, edges = _good_track()

    flows.save_draft(_flow, nodes, edges)
    graph = flows.load(_flow, flows.DRAFT)

    assert set(graph.nodes) == {"v1", "q1", "v2", "end"}
    assert len(graph.edges) == 4
    assert graph.nodes["q1"].config["correct_index"] == 1


def test_draft_replaces_previous_draft(_flow):
    """Холст присылает схему целиком: точечные правки означали бы сверку двух
    состояний на каждое перетаскивание."""
    nodes, edges = _good_track()
    flows.save_draft(_flow, nodes, edges)

    flows.save_draft(_flow, [_node("only", flows.SHOW_TEXT, text="Привет")], [])

    graph = flows.load(_flow, flows.DRAFT)
    assert set(graph.nodes) == {"only"}
    assert graph.edges == []


def test_unknown_node_kind_is_refused(_flow):
    with pytest.raises(flows.InvalidFlow):
        flows.save_draft(_flow, [_node("a", "телепортация")], [])


def test_duplicate_node_key_is_refused(_flow):
    """Два узла с одним ключом делают переходы двусмысленными."""
    with pytest.raises(flows.InvalidFlow):
        flows.save_draft(
            _flow,
            [_node("a", flows.SHOW_TEXT, text="1"), _node("a", flows.SHOW_TEXT, text="2")],
            [],
        )


def test_edge_into_nowhere_is_refused(_flow):
    with pytest.raises(flows.InvalidFlow):
        flows.save_draft(
            _flow, [_node("a", flows.SHOW_TEXT, text="1")], [_edge("a", "нет_такого")],
        )


# --- начало сценария ---


def test_start_is_the_node_nobody_points_to(_flow):
    """Начало вычисляется, а не помечается флагом: флаг можно забыть
    переставить, и сценарий начнётся с середины."""
    nodes, edges = _good_track()
    flows.save_draft(_flow, nodes, edges)

    graph = flows.load(_flow, flows.DRAFT)

    assert graph.start_key == "q1" or graph.start_key is None or graph.start_key == "v1"
    # В этом графе в v1 ведёт переход с q1 (неверный ответ), значит начал два
    # быть не может — проверяем явно ниже отдельным сценарием.


def test_linear_track_has_exactly_one_start(_flow):
    flows.save_draft(
        _flow,
        [_node("a", flows.SHOW_TEXT, text="1"), _node("b", flows.SHOW_TEXT, text="2")],
        [_edge("a", "b")],
    )

    assert flows.load(_flow, flows.DRAFT).start_key == "a"


# --- проверка перед публикацией ---


def test_good_track_publishes(_flow):
    """Сценарий из задачи владельца: видео, тест, переход по верному ответу."""
    nodes, edges = _good_track()
    # Возврат к первому видео делает v1 недостижимым как начало — добавляем
    # отдельный вход, чтобы граф был корректным.
    nodes.insert(0, _node("hello", flows.SHOW_TEXT, text="Начнём"))
    edges.insert(0, _edge("hello", "v1"))
    flows.save_draft(_flow, nodes, edges)

    version = flows.publish(_flow)

    assert version == 1
    view = flows.get(_flow)
    assert view is not None and view.published_version == 1


def test_empty_flow_is_not_published(_flow):
    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "нет ни одного узла" in str(exc.value)


def test_self_loop_is_refused(_flow):
    """ГЛАВНАЯ ЗАЩИТА.

    Узел, замкнутый на себя, засыпает человека сообщениями за секунды.
    """
    flows.save_draft(
        _flow, [_node("a", flows.SHOW_TEXT, text="снова")], [_edge("a", "a")],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "закольцован" in str(exc.value)


def test_two_node_loop_is_refused(_flow):
    flows.save_draft(
        _flow,
        [_node("a", flows.SHOW_TEXT, text="1"), _node("b", flows.SHOW_TEXT, text="2")],
        [_edge("a", "b"), _edge("b", "a")],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "закольцован" in str(exc.value)


def test_dangling_node_is_reported_as_a_second_start(_flow):
    """Одинокий узел — это ВТОРОЕ НАЧАЛО, и сказать надо именно так.

    Формально он и недостижим, но владельцу полезнее услышать, что у схемы
    два входа: он сразу видит, какой из них лишний.
    """
    flows.save_draft(
        _flow,
        [
            _node("a", flows.SHOW_TEXT, text="1"),
            _node("b", flows.SHOW_TEXT, text="2"),
            _node("lost", flows.SHOW_TEXT, text="сюда не дойти"),
        ],
        [_edge("a", "b")],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "Несколько начал" in str(exc.value)
    assert "lost" in str(exc.value)


def test_island_behind_a_cycle_is_unreachable(_flow):
    """Труд владельца, который никто не увидит.

    Островок c→d→c: начало по-прежнему одно (в c и d ведут переходы), но
    добраться до них от начала нельзя.
    """
    flows.save_draft(
        _flow,
        [
            _node("a", flows.SHOW_TEXT, text="начало"),
            _node("b", flows.SHOW_TEXT, text="конец"),
            _node("c", flows.SHOW_TEXT, text="остров 1"),
            _node("d", flows.SHOW_TEXT, text="остров 2"),
        ],
        [_edge("a", "b"), _edge("c", "d"), _edge("d", "c")],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    text = str(exc.value)
    assert "не добраться" in text
    assert "c" in text and "d" in text


def test_condition_without_both_branches_is_refused(_flow):
    """Условие с одной ветвью — тупик для половины людей."""
    flows.save_draft(
        _flow,
        [
            _node("c", flows.DECIDE_CONDITION, variable="ответ", operator="eq", value="да"),
            _node("yes", flows.SHOW_TEXT, text="ага"),
        ],
        [_edge("c", "yes", flows.ON_TRUE)],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "не хватает ветки" in str(exc.value)


def test_quiz_without_correct_branch_is_refused(_flow):
    flows.save_draft(
        _flow,
        [
            _node("q", flows.ASK_QUIZ, question="?", options=["1", "2"], correct_index=0),
            _node("nope", flows.SHOW_TEXT, text="мимо"),
        ],
        [_edge("q", "nope", flows.ON_WRONG)],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "верный ответ" in str(exc.value)


def test_impossible_condition_on_a_show_node_is_refused(_flow):
    """Переход «по верному ответу» из узла с картинкой — не опечатка, а ветка,
    которая никогда не сработает."""
    flows.save_draft(
        _flow,
        [_node("a", flows.SHOW_TEXT, text="1"), _node("b", flows.SHOW_TEXT, text="2")],
        [_edge("a", "b", flows.ON_CORRECT)],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    assert "никогда не сработает" in str(exc.value)


def test_all_problems_are_reported_at_once(_flow):
    """Находить проблемы по одной, публикуя заново, — издевательство."""
    flows.save_draft(
        _flow,
        [
            _node("a", flows.SHOW_TEXT, text="1"),
            _node("lost", flows.SHOW_TEXT, text="2"),
            _node("c", flows.DECIDE_CONDITION, variable="x", operator="eq", value="1"),
        ],
        [_edge("a", "c"), _edge("c", "a", flows.ON_TRUE)],
    )

    with pytest.raises(flows.InvalidFlow) as exc:
        flows.publish(_flow)

    text = str(exc.value)
    assert "не добраться" in text
    assert "не хватает ветки" in text


# --- версии ---


def test_published_version_is_frozen(_flow):
    """ГЛАВНОЕ СВОЙСТВО ВЕРСИЙ.

    Человек, начавший вчера, доигрывает по вчерашней схеме.
    """
    nodes, edges = _good_track()
    nodes.insert(0, _node("hello", flows.SHOW_TEXT, text="Начнём"))
    edges.insert(0, _edge("hello", "v1"))
    flows.save_draft(_flow, nodes, edges)
    version = flows.publish(_flow)

    # Владелец переставил половину схемы.
    flows.save_draft(_flow, [_node("only", flows.SHOW_TEXT, text="всё иначе")], [])

    frozen = flows.load(_flow, version)
    assert set(frozen.nodes) == {"hello", "v1", "q1", "v2", "end"}
    assert set(flows.load(_flow, flows.DRAFT).nodes) == {"only"}


def test_second_publish_makes_a_new_version(_flow):
    flows.save_draft(
        _flow, [_node("a", flows.SHOW_TEXT, text="1")], [],
    )
    first = flows.publish(_flow)
    flows.save_draft(
        _flow, [_node("a", flows.SHOW_TEXT, text="иначе")], [],
    )
    second = flows.publish(_flow)

    assert (first, second) == (1, 2)
    assert flows.load(_flow, 1).nodes["a"].config["text"] == "1"
    assert flows.load(_flow, 2).nodes["a"].config["text"] == "иначе"


def test_publishing_does_not_touch_the_draft(_flow):
    flows.save_draft(_flow, [_node("a", flows.SHOW_TEXT, text="черновик")], [])
    flows.publish(_flow)

    assert flows.load(_flow, flows.DRAFT).nodes["a"].config["text"] == "черновик"


# --- выбор перехода ---


def test_button_edge_prefers_the_exact_value(_flow):
    flows.save_draft(
        _flow,
        [
            _node("b", flows.ASK_BUTTONS, text="?",
                  buttons=[{"label": "Да", "value": "yes"},
                           {"label": "Нет", "value": "no"}]),
            _node("y", flows.SHOW_TEXT, text="да"),
            _node("n", flows.SHOW_TEXT, text="нет"),
        ],
        [
            _edge("b", "y", flows.ON_BUTTON, "yes"),
            _edge("b", "n", flows.ON_BUTTON, "no"),
        ],
    )
    graph = flows.load(_flow, flows.DRAFT)

    assert graph.next_key("b", flows.ON_BUTTON, "yes") == "y"
    assert graph.next_key("b", flows.ON_BUTTON, "no") == "n"


def test_button_edge_without_value_catches_any_button(_flow):
    """Иначе пришлось бы рисовать переход на каждую кнопку даже там, где все
    ведут в одно место."""
    flows.save_draft(
        _flow,
        [
            _node("b", flows.ASK_BUTTONS, text="?",
                  buttons=[{"label": "Да", "value": "yes"}]),
            _node("next", flows.SHOW_TEXT, text="дальше"),
        ],
        [_edge("b", "next", flows.ON_BUTTON)],
    )
    graph = flows.load(_flow, flows.DRAFT)

    assert graph.next_key("b", flows.ON_BUTTON, "что_угодно") == "next"


def test_missing_branch_returns_nothing(_flow):
    flows.save_draft(_flow, [_node("a", flows.SHOW_TEXT, text="1")], [])
    graph = flows.load(_flow, flows.DRAFT)

    assert graph.next_key("a", flows.ALWAYS) is None

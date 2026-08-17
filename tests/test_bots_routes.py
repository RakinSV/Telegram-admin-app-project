"""Страницы конструктора: боты, сценарии, холст (F75).

ФИЧА, ДО КОТОРОЙ НЕЛЬЗЯ ДОЙТИ, НЕ РЕАЛИЗОВАНА. Движок и граф покрыты
отдельно; здесь проверяется, что владелец может завести бота, собрать
сценарий и опубликовать его, ни разу не открыв терминал, — и что токен при
этом наружу не выходит.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import flow_bots, managed_bots_repo
from tg_repost import flows_repo as flows
from tg_repost.db.models import Flow, FlowEdge, FlowNode, FlowRun, ManagedBot
from tg_repost.db.session import session_scope

TOKEN = "111111111:AAHkQeExampleTokenValueForTestsOnly1"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FlowRun).delete()
            session.query(FlowEdge).delete()
            session.query(FlowNode).delete()
            session.query(Flow).delete()
            session.query(ManagedBot).delete()
        flow_bots._instances.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture(autouse=True)
def _no_polling():
    """Опрос ботов в тестах не поднимаем: страница сохраняет бота и просит
    супервизор перечитать реестр, а тот тянет за собой Telethon."""
    with patch("tg_repost.webui.bots_routes._restart_bots", new=AsyncMock()) as spy:
        yield spy


def _add_bot(name: str = "Наставник", *, active: bool = True) -> int:
    encrypted, hint = managed_bots_repo._encrypt(TOKEN)
    with session_scope() as session:
        row = ManagedBot(
            name=name, token_encrypted=encrypted, token_hint=hint,
            username=name.lower(), is_active=active,
        )
        session.add(row)
        session.flush()
        return row.id


# --- боты ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/bots").status_code == 200


def test_bot_appears_in_the_menu():
    """Пункт меню — единственный способ узнать, что конструктор существует."""
    client = _client()
    _bootstrap(client)

    assert 'href="/bots"' in client.get("/").text


def test_token_is_never_rendered():
    """ГЛАВНОЕ ПРО БЕЗОПАСНОСТЬ ЗДЕСЬ.

    Токен бота — полный доступ к нему у Telegram. Он не показывается даже
    владельцу: в объект для шаблона он не попадает вовсе.
    """
    client = _client()
    _bootstrap(client)
    _add_bot()

    page = client.get("/bots").text

    assert TOKEN not in page
    assert "••••" in page, "маска токена должна быть, иначе двух ботов не отличить"


def test_saving_a_bot_verifies_the_token_with_telegram():
    """Неверный токен, принятый молча, оборачивается ботом, который «есть в
    списке и не работает»."""
    client = _client()
    _bootstrap(client)

    with patch(
        "tg_repost.managed_bots_repo.verify_token",
        new=AsyncMock(return_value=(False, "Unauthorized")),
    ):
        response = client.post(
            "/bots/save", data={"name": "Плохой", "token": TOKEN},
        )

    assert response.status_code == 400
    assert "Unauthorized" in response.text
    with session_scope() as session:
        assert session.query(ManagedBot).count() == 0


def test_saved_bot_leads_straight_to_its_scenarios(_no_polling):
    """Заведя бота, владелец хочет собрать сценарий, а не искать, куда идти."""
    client = _client()
    _bootstrap(client)

    with patch(
        "tg_repost.managed_bots_repo.verify_token",
        new=AsyncMock(return_value=(True, "my_bot")),
    ):
        response = client.post(
            "/bots/save", data={"name": "Наставник", "token": TOKEN, "is_active": "1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/flows")
    assert _no_polling.await_count == 1, "опрос ботов не перечитан"


def test_editing_without_a_token_keeps_the_old_one(_no_polling):
    """Показать сохранённый токен невозможно, поэтому пустое поле означает «не
    меняли»: иначе переименование бота стирало бы ему токен."""
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()

    client.post("/bots/save", data={"name": "Новое имя", "bot_id": str(bot_id)})

    assert managed_bots_repo.decrypt_token(bot_id) == TOKEN
    view = managed_bots_repo.get(bot_id)
    assert view is not None and view.name == "Новое имя"


def test_toggle_switches_the_bot_and_rereads_the_registry(_no_polling):
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot(active=False)

    client.post(f"/bots/{bot_id}/toggle")

    view = managed_bots_repo.get(bot_id)
    assert view is not None and view.is_active is True
    assert _no_polling.await_count == 1


def test_bot_with_scenarios_is_turned_off_instead_of_deleted(_no_polling):
    """Прохождения людей внутри сценариев ссылаются на узлы: удалить бота
    значило бы оставить их в пустоте."""
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flows.create(bot_id, "Урок")

    response = client.post(f"/bots/{bot_id}/delete")

    assert response.status_code == 400
    view = managed_bots_repo.get(bot_id)
    assert view is not None and view.is_active is False


# --- сценарии ---


def test_scenarios_page_warns_when_the_bot_is_off():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot(active=False)

    page = client.get(f"/bots/{bot_id}/flows").text

    assert "выключен" in page.lower()


def test_created_scenario_opens_the_canvas():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()

    response = client.post(
        f"/bots/{bot_id}/flows/create",
        data={"name": "Обучение", "trigger": "keyword", "trigger_value": "урок"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/flows/")
    canvas = client.get(response.headers["location"]).text
    assert 'id="flow-canvas"' in canvas
    assert "flow_canvas.js" in canvas


def test_canvas_carries_the_schema_and_the_draft():
    """Схема полей приходит с сервера: вторая её копия в JavaScript однажды
    разошлась бы с первой, и узел молча перестал бы работать."""
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")
    flows.save_draft(
        flow_id,
        [{"node_key": "a", "kind": flows.SHOW_TEXT,
          "config": {"text": "Привет"}, "x": 10, "y": 20}],
        [],
    )

    page = client.get(f"/flows/{flow_id}").text

    assert "show_text" in page
    assert "Привет" in page
    # Все двенадцать типов узлов доступны в палитре — иначе часть движка
    # написана и недостижима.
    for kind in flows.ALL_KINDS:
        assert kind in page, kind


def test_canvas_saves_the_draft_and_returns_problems():
    """Проблемы графа показываются СРАЗУ после сохранения: узнать о тупике
    через неделю, когда в сценарий пойдут люди, — поздно."""
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")

    response = client.post(
        f"/flows/{flow_id}/save",
        json={
            "nodes": [
                {"node_key": "q", "kind": flows.ASK_QUIZ, "x": 0, "y": 0,
                 "config": {"question": "?", "options": ["a", "b"],
                            "correct_index": 1}},
            ],
            "edges": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # У теста нет ветки на верный ответ — человек упрётся в тупик.
    assert any("верный ответ" in problem for problem in body["problems"])
    graph = flows.load(flow_id, flows.DRAFT)
    assert set(graph.nodes) == {"q"}


def test_broken_draft_is_refused_with_an_explanation():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")

    response = client.post(
        f"/flows/{flow_id}/save",
        json={"nodes": [{"node_key": "a", "kind": "телепортация", "config": {}}],
              "edges": []},
    )

    assert response.status_code == 400
    assert "тип узла" in response.json()["error"]


def test_publish_refuses_a_broken_graph_and_says_why():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")
    flows.save_draft(
        flow_id,
        [{"node_key": "v", "kind": flows.SHOW_VIDEO, "config": {}, "x": 0, "y": 0}],
        [],
    )

    client.post(f"/flows/{flow_id}/publish", follow_redirects=False)
    page = client.get(f"/flows/{flow_id}").text

    assert "file_id" in page, "владельцу не сказали, чего не хватает"
    assert flows.get(flow_id).published_version is None


def test_publish_succeeds_and_shows_the_version():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")
    flows.save_draft(
        flow_id,
        [
            {"node_key": "a", "kind": flows.SHOW_TEXT,
             "config": {"text": "Привет"}, "x": 0, "y": 0},
            {"node_key": "b", "kind": flows.SHOW_TEXT,
             "config": {"text": "Пока"}, "x": 0, "y": 120},
        ],
        [{"from_key": "a", "to_key": "b", "condition": flows.ALWAYS}],
    )

    client.post(f"/flows/{flow_id}/publish", follow_redirects=False)
    page = client.get(f"/flows/{flow_id}").text

    assert flows.get(flow_id).published_version == 1
    assert "версия 1" in page.lower() or "версии 1" in page.lower()


def test_deleting_a_scenario_returns_to_the_bot():
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, "Обучение")

    response = client.post(f"/flows/{flow_id}/delete", follow_redirects=False)

    assert response.headers["location"] == f"/bots/{bot_id}/flows"
    assert flows.get(flow_id) is None


def test_canvas_json_is_valid_for_the_browser():
    """Разметка отдаёт схему и граф блоками JSON. Сломанный JSON — пустая
    страница без единого сообщения об ошибке."""
    client = _client()
    _bootstrap(client)
    bot_id = _add_bot()
    flow_id = flows.create(bot_id, 'Кавычки "внутри" и \'апострофы\'')
    flows.save_draft(
        flow_id,
        [{"node_key": "a", "kind": flows.SHOW_TEXT, "x": 0, "y": 0,
          "config": {"text": 'Текст с "кавычками" и <тегами> и \\обратным слэшем'}}],
        [],
    )

    page = client.get(f"/flows/{flow_id}").text

    for block_id in ("flow-kinds", "flow-graph", "flow-text"):
        start = page.index(f'id="{block_id}"')
        opened = page.index(">", start) + 1
        closed = page.index("</script>", opened)
        json.loads(page[opened:closed])

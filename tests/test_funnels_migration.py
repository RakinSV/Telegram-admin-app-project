"""Перевод воронок (F71) в сценарии конструктора (F75, шаг 6).

Перенос трогает то, что уже работает у живых людей, поэтому проверяется не
только «получился сценарий», но и три вещи, которых он делать НЕ должен:
выключать старую воронку, терять шаги и оставлять после себя половину.
"""

from __future__ import annotations

import pytest

# Изолирующая фикстура окружения — без неё роут поднимает настоящий
# Telethon-клиент и тест падает на отсутствующей сессии.
from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import flows_repo as flows
from tg_repost import funnels_migration, funnels_repo, managed_bots_repo
from tg_repost.db.models import (
    Flow,
    FlowEdge,
    FlowNode,
    FlowRun,
    Funnel,
    FunnelRun,
    ManagedBot,
    QueuedTask,
)
from tg_repost.db.session import session_scope

ALICE = 60601
TOKEN = "111111111:AAHkQeExampleTokenValueForTestsOnly1"

STEPS = [
    {"delay_hours": 0, "text": "Привет! Это первый шаг."},
    {"delay_hours": 24, "text": "Прошли сутки — второй шаг."},
    {"delay_hours": 48, "text": "Ещё через двое суток — третий."},
]


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(FlowRun).delete()
            session.query(FlowEdge).delete()
            session.query(FlowNode).delete()
            session.query(Flow).delete()
            session.query(ManagedBot).delete()
            session.query(FunnelRun).delete()
            session.query(Funnel).delete()
            session.query(QueuedTask).delete()

    _wipe()
    yield
    _wipe()


def _bot(name: str = "Наставник") -> int:
    encrypted, hint = managed_bots_repo._encrypt(TOKEN)
    with session_scope() as session:
        row = ManagedBot(
            name=name, token_encrypted=encrypted, token_hint=hint,
            username=name.lower(), is_active=True,
        )
        session.add(row)
        session.flush()
        return row.id


def _funnel(name: str = "Онбординг", *, steps=None, active: bool = True) -> int:
    return funnels_repo.save(
        name, steps if steps is not None else STEPS, is_active=active,
    )


# --- перенос шагов ---


def test_every_step_becomes_a_message():
    """Потерянный шаг обнаружился бы через сутки после запуска — когда
    исправлять поздно."""
    bot_id = _bot()
    funnel_id = _funnel()

    result = funnels_migration.migrate(funnel_id, bot_id)

    graph = flows.load(result.flow_id, result.published_version)
    texts = [
        node.config["text"] for node in graph.nodes.values()
        if node.kind == flows.SHOW_TEXT
    ]
    assert sorted(texts) == sorted(step["text"] for step in STEPS)


def test_delay_becomes_a_pause_node():
    """Задержка — отдельный узел, а не свойство сообщения: в конструкторе
    ожидание видно на холсте, его можно подвинуть или заменить вопросом."""
    bot_id = _bot()
    funnel_id = _funnel()

    result = funnels_migration.migrate(funnel_id, bot_id)

    graph = flows.load(result.flow_id, result.published_version)
    pauses = sorted(
        node.config["hours"] for node in graph.nodes.values()
        if node.kind == flows.WAIT_TIMER
    )
    assert pauses == [24, 48], "паузы не совпали с задержками воронки"


def test_zero_delay_does_not_create_a_pause():
    """Пауза «ноль часов» была бы ложью на холсте: движок всё равно ждёт
    минимум час."""
    bot_id = _bot()
    funnel_id = _funnel(steps=[{"delay_hours": 0, "text": "Сразу"}])

    result = funnels_migration.migrate(funnel_id, bot_id)

    graph = flows.load(result.flow_id, result.published_version)
    assert all(node.kind != flows.WAIT_TIMER for node in graph.nodes.values())


def test_order_of_steps_is_preserved():
    """Порядок — это и есть воронка. Перепутанные шаги превращают её в набор
    несвязных сообщений."""
    bot_id = _bot()
    funnel_id = _funnel()

    result = funnels_migration.migrate(funnel_id, bot_id)

    graph = flows.load(result.flow_id, result.published_version)
    order = []
    key = graph.start_key
    while key is not None:
        node = graph.nodes[key]
        if node.kind == flows.SHOW_TEXT:
            order.append(node.config["text"])
        key = graph.next_key(key, flows.ALWAYS)

    assert order == [step["text"] for step in STEPS]


def test_migrated_scenario_is_published_right_away():
    """Черновик после переноса выглядел бы готовым и никому не отвечал."""
    bot_id = _bot()
    funnel_id = _funnel()

    result = funnels_migration.migrate(funnel_id, bot_id)

    view = flows.get(result.flow_id)
    assert view is not None
    assert view.is_published
    assert view.trigger == "start"
    assert result.published_version == 1


def test_scenario_keeps_the_funnel_name():
    bot_id = _bot()
    funnel_id = _funnel("Цепочка новичка")

    result = funnels_migration.migrate(funnel_id, bot_id)

    assert flows.get(result.flow_id).name == "Цепочка новичка"


# --- чего перенос делать НЕ должен ---


def test_old_funnel_keeps_running():
    """ГЛАВНОЕ ОГРАНИЧЕНИЕ ПЕРЕНОСА.

    Выключение воронки останавливает цепочку всем, кто сейчас внутри
    (`handle_step_task` завершает запуск с причиной «воронка выключена»).
    Решать это за владельца нельзя.
    """
    bot_id = _bot()
    funnel_id = _funnel(active=True)

    funnels_migration.migrate(funnel_id, bot_id)

    view = funnels_repo.get(funnel_id)
    assert view is not None and view.is_active is True


def test_people_inside_are_counted_for_the_owner():
    """Владельцу нужно знать цену выключения ДО того, как он его нажмёт."""
    from tg_repost import subscribers_repo

    bot_id = _bot()
    funnel_id = _funnel()
    subscribers_repo.record_contact(ALICE)
    funnels_repo.enroll(ALICE)

    result = funnels_migration.migrate(funnel_id, bot_id)

    assert result.people_inside == 1


def test_empty_funnel_is_refused():
    bot_id = _bot()
    with session_scope() as session:
        row = Funnel(name="Пустая", trigger="start", steps_json="[]")
        session.add(row)
        session.flush()
        funnel_id = row.id

    with pytest.raises(funnels_migration.MigrationRefused):
        funnels_migration.migrate(funnel_id, bot_id)


def test_second_funnel_on_the_same_bot_is_refused():
    """Два сценария на «/start» у одного бота спорят за него: сработает один,
    а владелец будет думать, что работают оба."""
    bot_id = _bot()
    first = _funnel("Первая")
    second = _funnel("Вторая")
    funnels_migration.migrate(first, bot_id)

    with pytest.raises(funnels_migration.MigrationRefused) as exc:
        funnels_migration.migrate(second, bot_id)

    assert "уже есть сценарий" in str(exc.value)


def test_two_funnels_can_go_to_two_bots():
    """Обратная проверка: у каждого бота свой сценарий — это и есть смысл
    реестра ботов."""
    first_bot, second_bot = _bot("Первый"), _bot("Второй")

    first = funnels_migration.migrate(_funnel("Одна"), first_bot)
    second = funnels_migration.migrate(_funnel("Другая"), second_bot)

    assert flows.get(first.flow_id).bot_id == first_bot
    assert flows.get(second.flow_id).bot_id == second_bot


def test_unknown_bot_is_refused():
    funnel_id = _funnel()

    with pytest.raises(funnels_migration.MigrationRefused):
        funnels_migration.migrate(funnel_id, 99999)


def test_failed_publication_leaves_nothing_behind(monkeypatch):
    """Половина сценария в списке выглядит рабочей, а ею не является.

    Публикация ломается ИСКУССТВЕННО: линейная цепочка из воронки проверку
    проходит всегда, а проверить надо именно откат — путь, на который в
    обычной жизни попадёшь только со сломанными данными.
    """
    bot_id = _bot()
    funnel_id = _funnel()

    def _refuse(_flow_id):
        raise flows.InvalidFlow("проверка не прошла")

    monkeypatch.setattr(funnels_migration.flows, "publish", _refuse)

    with pytest.raises(funnels_migration.MigrationRefused):
        funnels_migration.migrate(funnel_id, bot_id)

    assert flows.list_for_bot(bot_id) == [], "недоделанный сценарий остался в списке"


def test_pending_skips_funnels_without_steps():
    _funnel("С шагами")
    with session_scope() as session:
        session.add(Funnel(name="Пустая", trigger="start", steps_json="[]"))

    names = [view.name for view in funnels_migration.pending()]

    assert names == ["С шагами"]


# --- через страницу ---


def test_migration_from_the_page_opens_the_canvas():
    client = _client()
    _bootstrap(client)
    bot_id = _bot()
    funnel_id = _funnel()

    response = client.post(
        f"/funnels/{funnel_id}/migrate", data={"bot_id": str(bot_id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/flows/")


def test_page_without_a_chosen_bot_explains_instead_of_failing():
    client = _client()
    _bootstrap(client)
    funnel_id = _funnel()

    response = client.post(f"/funnels/{funnel_id}/migrate", data={"bot_id": ""})

    assert response.status_code == 400
    assert "бота" in response.text

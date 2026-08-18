"""Здоровье процесса и режим журнала БД (разбор архитектуры 2026-08-18).

Обе проверки — про то, что видно только на живой системе. `/health` был
разрешён в политике доступа, но самого роута не существовало: контейнер
показывал «Up», когда внутри не поднялся ни один компонент. А база работала в
режиме `delete`, хотя пишут её два процесса.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401


def test_health_answers_without_login():
    """Адрес нужен docker-healthcheck и внешнему монитору, у которых пароля
    нет."""
    client = _client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_lists_components_and_names_the_dead_ones():
    """Владельцу и монитору нужен не факт «жив», а состав: что именно молчит."""
    from tg_repost.webui import runtime_state

    runtime_state.set_component_status("listener", False)
    runtime_state.set_component_status("scheduler", True)
    client = _client()

    body = client.get("/health").json()

    assert body["components"]["scheduler"] is True
    assert "listener" in body["degraded"]
    assert "scheduler" not in body["degraded"]


def test_health_stays_200_with_dead_components():
    """ГЛАВНОЕ РЕШЕНИЕ ЗДЕСЬ.

    Здоровье процесса и здоровье связи с Telegram — разные вещи. Админка
    обязана работать именно тогда, когда Telegram недоступен: чинят это в ней.
    Пятисотка отсюда означала бы перезапуск контейнера при каждом сбое
    провайдера — то есть лечение того, что лечения не требует.
    """
    from tg_repost.webui import runtime_state

    for name in ("listener", "bot", "scheduler"):
        runtime_state.set_component_status(name, False)
    client = _client()

    response = client.get("/health")

    assert response.status_code == 200
    assert set(response.json()["degraded"]) >= {"listener", "bot", "scheduler"}


def test_health_does_not_leak_settings():
    """Адрес открыт без пароля — наружу уходит только состав компонентов."""
    client = _client()

    text = client.get("/health").text.lower()

    for secret_word in ("token", "api_key", "password", "session"):
        assert secret_word not in text


@pytest.mark.parametrize(
    "module_name",
    ["tg_repost.db.session", "guardian.db.session"],
)
def test_file_database_gets_wal_from_our_own_setup(module_name, tmp_path):
    """Проверяется НАША функция настройки, а не SQLAlchemy.

    Первая версия этого теста вешала свой обработчик на свой engine и потому
    проходила бы и на полностью выключенном WAL в проекте — то есть была
    бесполезна. Теперь берётся ровно та функция, которую проект вешает на
    соединение, и применяется к настоящему файлу: у `:memory:` WAL не бывает
    вовсе, поэтому обычные тесты этого места не видят.
    """
    import importlib
    import sqlite3

    module = importlib.import_module(module_name)
    connection = sqlite3.connect(tmp_path / "probe.db")
    try:
        module.apply_sqlite_pragmas(connection)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 15000
    finally:
        connection.close()

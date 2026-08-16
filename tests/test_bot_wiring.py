"""Сборка диспетчеров ботов (аудит 2026-08-16).

Роутеры подключаются списком в одном месте, и ошибка там не видна ни одному
тесту фичи: каждый обработчик по отдельности работает, а бот при этом не
стартует вовсе. Aiogram не даёт подключить один роутер дважды и падает
`RuntimeError` — ровно на запуске, то есть у пользователя, а не в CI.

Здесь диспетчер собирается по-настоящему.
"""

from __future__ import annotations

import pytest


def test_engage_dispatcher_assembles():
    """ГЛАВНАЯ ПРОВЕРКА.

    Один и тот же роутер, подключённый дважды (типовая ошибка при вставке
    новой фичи в список), роняет бот на старте.

    Роутеры — МОДУЛЬНЫЕ СИНГЛТОНЫ и после подключения помнят родителя
    навсегда. Поэтому привязку приходится снимать вручную: иначе этот тест
    сломал бы любой следующий, который тоже собирает диспетчер, и падение
    выглядело бы как ошибка в чужой фиче.
    """
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from engage.handlers import (
        cabinet,
        contest,
        quiz,
        referral,
        shop,
        start,
        subscription,
        suggest,
        support,
    )

    routers = (
        start.router, quiz.router, referral.router, contest.router,
        cabinet.router, suggest.router, subscription.router, shop.router,
        support.router,
    )
    dp = Dispatcher(storage=MemoryStorage())
    try:
        for router in routers:
            dp.include_router(router)
        assert len(dp.sub_routers) == len(routers)
    finally:
        for router in routers:
            router._parent_router = None


def test_double_registration_is_actually_fatal():
    """Проверка самой проверки.

    Если бы aiogram молча терпел повтор, тест выше ничего не охранял бы.
    Берётся ЧИСТЫЙ роутер, а не боевой: боевой остался бы привязанным к
    выброшенному диспетчеру и сломал бы соседние тесты.
    """
    from aiogram import Dispatcher, Router
    from aiogram.fsm.storage.memory import MemoryStorage

    dp = Dispatcher(storage=MemoryStorage())
    router = Router(name="проверка")
    dp.include_router(router)

    with pytest.raises(RuntimeError):
        dp.include_router(router)


def test_support_router_is_last_in_source():
    """Поддержка ловит любое личное сообщение. Поставленная раньше, она
    проглотит текст, которого ждёт предложка, а обнаружится это тишиной в
    ответ на обычные команды."""
    import pathlib
    import re

    source = pathlib.Path("engage/bot.py").read_text(encoding="utf-8")
    order = re.findall(r"dp\.include_router\((\w+)\.router\)", source)

    assert order[-1] == "support", f"порядок: {order}"


def test_no_router_registered_twice_in_source():
    import pathlib
    import re

    source = pathlib.Path("engage/bot.py").read_text(encoding="utf-8")
    order = re.findall(r"dp\.include_router\((\w+)\.router\)", source)

    assert len(order) == len(set(order)), f"дубли: {order}"

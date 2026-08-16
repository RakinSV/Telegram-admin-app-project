"""Достижимость фич из интерфейса (аудит 2026-08-16).

ФИЧА, ДО КОТОРОЙ НЕЛЬЗЯ ДОЙТИ, НЕ РЕАЛИЗОВАНА — как бы хорошо она ни была
покрыта тестами. Аудит нашёл три таких случая подряд, и все они выглядели
одинаково: repo написан, тесты зелёные, статус «РЕАЛИЗОВАНО», а вызвать это
владельцу нечем.

Здесь проверяется САМОЕ СЛАБОЕ ЗВЕНО каждой цепочки — та функция, без
вызова которой фича мертва целиком.
"""

from __future__ import annotations

import pathlib

import pytest

_SKIP_DIRS = {"__pycache__", "migrations"}


def _production_sources() -> str:
    parts = []
    for pkg in ("tg_repost", "guardian", "engage"):
        for path in pathlib.Path(pkg).rglob("*.py"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            parts.append((path, path.read_text(encoding="utf-8", errors="ignore")))
    return parts


# (что зовём, где НЕ считать вызовом, чем это грозит)
ENTRY_POINTS = [
    (
        "create_contest",
        "contests_repo.py",
        "конкурс невозможно создать: розыгрыш и участие написаны, "
        "а завести конкурс владельцу нечем",
    ),
    (
        "mark_joined",
        "referrals_repo.py",
        "реферал никогда не подтвердится: условие «вступил» не выставляется",
    ),
    (
        "mark_first_message",
        "referrals_repo.py",
        "реферал никогда не подтвердится: условие «написал» не выставляется",
    ),
    (
        "mark_approved",
        "calendar_repo.py",
        "согласование владельцем не включается: флаг ожидания не выставляется",
    ),
    (
        "top_inviters",
        "referrals_repo.py",
        "лидерборд пригласивших никому не показывается: написан и невидим",
    ),
    (
        "resubscribe",
        "subscribers_repo.py",
        "отписавшийся не может вернуться: обратного пути нет",
    ),
]


@pytest.mark.parametrize("func,home,damage", ENTRY_POINTS)
def test_entry_point_is_called_from_production(func, home, damage):
    callers = [
        str(path) for path, text in _production_sources()
        if path.name != home and f"{func}(" in text
    ]

    assert callers, f"{func}: никто не зовёт — {damage}"

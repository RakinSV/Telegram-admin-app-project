"""Ключи переводов, которые собираются НА ЛЕТУ (аудит 2026-08-16).

Шаблоны местами строят ключ из значения: `t('users.role_' ~ row.role)`,
`t('broadcasts.status_' ~ row.status)`. Такой ключ не найти поиском по
каталогу, и обычные проверки полноты переводов его не видят: они ходят по
отрисованным страницам, а страница с новым статусом появится только когда
этот статус кто-то получит.

Цена пропуска — сырое `[broadcasts.status_paused]` в интерфейсе вместо
подписи. Поэтому здесь каждое перечисление сверяется с каталогом целиком:
добавили статус или роль — тест назовёт недостающий перевод сразу.
"""

from __future__ import annotations

import pytest

# Воронок здесь нет намеренно: их статусы показываются отдельными подписями
# («идут», «дошли», «сорвались»), а не ключом, собранным из значения.
from tg_repost import ad_requests_repo, broadcasts_repo, support_repo
from tg_repost.rss import presets
from tg_repost.webui import access
from tg_repost.webui.i18n import STRINGS

# (префикс ключа, значения, откуда взяты) — значения берутся из САМОГО кода,
# а не переписаны сюда руками: список, скопированный в тест, устареет вместе
# с ним и перестанет ловить именно то, ради чего написан.
FAMILIES = [
    ("users.role_", access.ALL_ROLES),
    ("sources.rss_preset.", tuple(presets.PRESET_GROUPS)),
    ("ad_requests.status_", (
        ad_requests_repo.STATUS_NEW,
        ad_requests_repo.STATUS_ACCEPTED,
        ad_requests_repo.STATUS_DECLINED,
        ad_requests_repo.STATUS_PUBLISHED,
    )),
    ("broadcasts.status_", (
        broadcasts_repo.STATUS_PLANNED,
        broadcasts_repo.STATUS_RUNNING,
        broadcasts_repo.STATUS_DONE,
        broadcasts_repo.STATUS_CANCELED,
    )),
    ("support.status_", (support_repo.STATUS_OPEN, support_repo.STATUS_CLOSED)),
    ("fraud.code_", ("sawtooth", "growth_without_reach")),
    ("common.source.", ("db", "env", "unset")),
]


@pytest.mark.parametrize("prefix,values", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_every_value_has_a_translation(prefix, values):
    missing = [v for v in values if f"{prefix}{v}" not in STRINGS]

    assert not missing, f"нет переводов: {[prefix + v for v in missing]}"


@pytest.mark.parametrize("prefix,values", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_translations_exist_in_every_language(prefix, values):
    """Перевод только на русский — это `[key]` для англоязычного интерфейса."""
    from tg_repost.webui.i18n import SUPPORTED_LANGS

    incomplete = [
        f"{prefix}{v}.{lang}"
        for v in values
        for lang in SUPPORTED_LANGS
        if f"{prefix}{v}" in STRINGS and not STRINGS[f"{prefix}{v}"].get(lang)
    ]

    assert not incomplete, f"неполные переводы: {incomplete}"


def test_no_stale_keys_in_status_families():
    """Лишний ключ — след удалённого статуса.

    Сам по себе он безвреден, но врёт о наборе состояний: следующий, кто
    будет разбираться, поверит каталогу.
    """
    stale = []
    for prefix, values in FAMILIES:
        expected = {f"{prefix}{v}" for v in values}
        actual = {k for k in STRINGS if k.startswith(prefix)}
        stale.extend(sorted(actual - expected))

    assert not stale, f"переводы без соответствующего значения: {stale}"

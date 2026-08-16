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
from tg_repost import (
    ad_requests_repo,
    affiliate_repo,
    api_keys_repo,
    broadcasts_repo,
    shop_repo,
    subscriptions_repo,
    support_repo,
)
from tg_repost.rss import presets
from tg_repost import crypto_rails
from tg_repost.webui import access
from tg_repost.webui.i18n import STRINGS

# (префикс ключа, значения, откуда взяты) — значения берутся из САМОГО кода,
# а не переписаны сюда руками: список, скопированный в тест, устареет вместе
# с ним и перестанет ловить именно то, ради чего написан.
FAMILIES = [
    ("users.role_", access.ALL_ROLES),
    # F73: области прав ключа API. Список берётся из самого репозитория —
    # добавят новую область, и тест потребует перевод, а не промолчит.
    ("integrations.scope_", api_keys_repo.SCOPES),
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
    # Добавлены аудитом 2026-08-16: три семейства появились вместе с блоком
    # денег и в сторож не попали — то есть сторож, написанный ровно против
    # этого класса пропусков, сам от него не был защищён. Проверка полноты
    # списка теперь ниже, в `test_every_dynamic_family_is_guarded`.
    ("subscriptions.status_", (
        subscriptions_repo.STATUS_ACTIVE,
        subscriptions_repo.STATUS_EXPIRED,
        subscriptions_repo.STATUS_CANCELED,
        subscriptions_repo.STATUS_REFUNDED,
    )),
    ("affiliate.kind_", (
        affiliate_repo.KIND_ACCRUAL,
        affiliate_repo.KIND_REVERSAL,
        affiliate_repo.KIND_PAYOUT,
    )),
    ("shop.status_", (
        shop_repo.STATUS_NEW,
        shop_repo.STATUS_PAID,
        shop_repo.STATUS_SHIPPED,
        shop_repo.STATUS_CANCELED,
    )),
    # F70: способы приёма крипты. Список из самого пакета — заведут
    # четвёртый способ, и тест потребует перевод, а не промолчит.
    ("crypto.kind_", crypto_rails.KINDS),
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


def test_every_dynamic_family_is_guarded():
    """СТОРОЖ НАД СТОРОЖЕМ.

    Список семейств выше заполняется руками, а значит однажды отстанет от
    шаблонов — ровно это и случилось: `shop.status_`, `subscriptions.status_`
    и `affiliate.kind_` появились вместе с блоком денег и в список не попали.
    Здесь шаблоны сканируются на конструкцию `t('префикс' ~ значение)`, и
    каждый найденный префикс обязан быть в `FAMILIES`.
    """
    import pathlib
    import re

    pattern = re.compile(r"""t\(\s*['"]([a-zA-Z0-9_.]+)['"]\s*(?:\+|~)""")
    found: set[str] = set()
    for path in pathlib.Path("tg_repost/webui/templates").rglob("*.html"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))

    guarded = {prefix for prefix, _ in FAMILIES}

    assert found <= guarded, (
        "семейства ключей есть в шаблонах, но не под сторожем: "
        f"{sorted(found - guarded)}"
    )


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

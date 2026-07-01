"""Журнал изменений из веб-админки (F23, Фаза 5.4).

Каждое мутирующее действие из веб-роутов пишет ОДНОВРЕМЕННО: `logger.info(...)`
(операционный лог) и строку в `audit_log` (журнал подотчётности, `/audit`) —
два разных назначения из одной точки кода, см. план Фазы 5. Вызывается только
из веб-роутов (`webui/app.py`, `webui/crud_routes.py`), НЕ из общих
repo-модулей (`sources_repo.py` и т.д.) — те же функции использует и `cli.py`,
а `audit_log` по определению (см. `db.models.AuditLog`) — журнал действий
именно из админки, не CLI и не автоматических фоновых процессов.

НИКОГДА не пишет значения секретов — только факт изменения и его адрес
(`target`), как и сам `Secret`/`/secrets` (write-only).
"""

from __future__ import annotations

from tg_repost.db.models import AuditLog
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_MAX_DETAIL_LEN = 500


def record_audit(action: str, target: str | None = None, detail: str | None = None) -> None:
    """Записать действие в `audit_log` и продублировать в обычный лог."""
    if detail is not None and len(detail) > _MAX_DETAIL_LEN:
        detail = detail[:_MAX_DETAIL_LEN] + "…"
    with session_scope() as session:
        session.add(AuditLog(action=action, target=target, detail=detail))
    logger.info(
        "audit: %s%s%s",
        action,
        f" [{target}]" if target else "",
        f" — {detail}" if detail else "",
    )


# Публичная константа (без подчёркивания) — переиспользуется роутом
# `/audit` в `crud_routes.py` для расчёта числа страниц.
PAGE_SIZE = 50


def list_audit_log(limit: int = 200, offset: int = 0) -> list[AuditLog]:
    """Записи журнала, новые сверху, с пагинацией (`offset`/`limit`).

    Сортировка по `id`, а НЕ по `created_at` — один HTTP-запрос может писать
    несколько записей подряд (например `settings_save` по каждому полю
    группы), и они легко получают ОДИНАКОВОЕ значение `created_at` (точность
    `datetime.now()` грубее, чем интервал между вызовами) — при сортировке по
    времени порядок между такими записями не гарантирован. `id` монотонно
    растёт при вставке всегда, независимо от точности часов.

    Раньше `limit` был жёстко зашит в 200 без способа посмотреть более
    старые записи из UI (они оставались в БД, но были недоступны из
    `/audit`) — найдено при аудите Фазы 5, добавлена пагинация.
    """
    with session_scope() as session:
        return (
            session.query(AuditLog)
            .order_by(AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


def count_audit_log() -> int:
    """Общее число записей журнала (для пагинации в `/audit`)."""
    with session_scope() as session:
        return session.query(AuditLog).count()

"""Ключи внешнего доступа к API (F73).

КЛЮЧ ПОКАЗЫВАЕТСЯ ОДИН РАЗ. В базе лежит только хэш — тот же приём, что с
паролями админов. Причина не в аккуратности: ключ в открытом виде означает,
что утечка базы (бэкап на диске, снимок в чужих руках) сразу даёт доступ к
системе, и понять, что им воспользовались, будет нечем.

ПОИСК ПО ПРЕФИКСУ, СРАВНЕНИЕ ПО ХЭШУ. Хранить только хэш и искать по нему
нельзя — пришлось бы перебирать все строки на каждый запрос. Поэтому первые
символы ключа лежат открыто и играют роль имени: по ним строка находится за
один запрос, а сам ключ по префиксу не восстанавливается.

ОГРАНИЧЕНИЕ ЧАСТОТЫ У КАЖДОГО КЛЮЧА СВОЁ, И НУЛЯ НЕТ. Ключ без предела
превращает ошибку в чужом скрипте — цикл без паузы — в отказ обслуживания
для всей системы. «Без ограничения» не предусмотрено намеренно.

СЧЁТЧИК ЧАСТОТЫ В ПАМЯТИ ПРОЦЕССА, а не в базе и не в Redis. Это осознанный
предел: при нескольких процессах предел размажется по ним. Redis ради этого
противоречит правилу проекта («долгие операции — таблица-очередь, не
брокер»), а запись в базу на КАЖДЫЙ запрос делает ограничитель дороже
самого запроса.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import ApiKey
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPES = (SCOPE_READ, SCOPE_WRITE)

PREFIX_LENGTH = 8
SECRET_LENGTH = 32

DEFAULT_RATE_LIMIT = 60
MAX_RATE_LIMIT = 6000


class InvalidKey(ValueError):
    """Ключ не прошёл проверку при создании."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    """SHA-256 вместо argon2 — и это осознанно.

    У паролей медленный хэш защищает от перебора, потому что пароль выбирает
    человек и он угадываем. Здесь секрет — 32 случайных байта: перебирать
    его бессмысленно при любой скорости хэша, а медленный хэш на КАЖДЫЙ
    запрос API стал бы самой дорогой частью обработки.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ApiKeyView:
    id: int
    name: str
    prefix: str
    scope: str
    rate_limit: int
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


def _view(row: ApiKey) -> ApiKeyView:
    return ApiKeyView(
        id=row.id, name=row.name, prefix=row.prefix, scope=row.scope,
        rate_limit=row.rate_limit, is_active=row.is_active,
        last_used_at=row.last_used_at, created_at=row.created_at,
    )


def create(
    name: str,
    *,
    scope: str = SCOPE_READ,
    rate_limit: int = DEFAULT_RATE_LIMIT,
) -> tuple[ApiKeyView, str]:
    """Создать ключ. Возвращает (описание, САМ КЛЮЧ).

    Ключ возвращается ЕДИНСТВЕННЫЙ раз в жизни — дальше его в системе нет.
    """
    clean_name = name.strip()
    if not clean_name:
        raise InvalidKey("Название ключа не может быть пустым")
    if scope not in SCOPES:
        raise InvalidKey(f"Неизвестная область прав: {scope}")
    if rate_limit < 1 or rate_limit > MAX_RATE_LIMIT:
        raise InvalidKey(
            f"Ограничение частоты должно быть от 1 до {MAX_RATE_LIMIT} запросов в минуту"
        )

    prefix = secrets.token_hex(PREFIX_LENGTH // 2)
    secret = secrets.token_urlsafe(SECRET_LENGTH)
    raw = f"{prefix}.{secret}"

    with session_scope() as session:
        row = ApiKey(
            name=clean_name,
            prefix=prefix,
            key_hash=_hash(raw),
            scope=scope,
            rate_limit=rate_limit,
        )
        session.add(row)
        session.flush()
        view = _view(row)

    logger.info("F73: создан ключ API «%s» (%s…, %s)", clean_name, prefix, scope)
    return view, raw


def authenticate(raw: str | None) -> ApiKeyView | None:
    """Найти ключ по предъявленному значению. `None` — не подошёл.

    Причина отказа НЕ различается: «нет такого ключа» и «ключ отозван» для
    вызывающего одно и то же, а разница помогала бы перебирать.
    """
    if not raw or "." not in raw:
        return None
    prefix = raw.split(".", 1)[0]
    if len(prefix) != PREFIX_LENGTH:
        return None

    with session_scope() as session:
        row = session.query(ApiKey).filter(ApiKey.prefix == prefix).first()
        if row is None or not row.is_active:
            return None
        # Сравнение в постоянном времени: обычное `==` выходит на первом
        # несовпавшем символе и позволяет подбирать хэш побайтно.
        if not hmac.compare_digest(row.key_hash, _hash(raw)):
            return None
        row.last_used_at = _utcnow()
        return _view(row)


def list_keys() -> list[ApiKeyView]:
    with session_scope() as session:
        rows = session.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
        return [_view(row) for row in rows]


def revoke(key_id: int) -> bool:
    """Отозвать ключ. Строка остаётся: журнал должен объяснять, чем ходили.

    Удалять её значило бы стереть след использования вместе с самим ключом —
    ровно тогда, когда он понадобился для разбора.
    """
    with session_scope() as session:
        row = session.get(ApiKey, key_id)
        if row is None or not row.is_active:
            return False
        row.is_active = False
        row.revoked_at = _utcnow()
        logger.info("F73: ключ %s… отозван", row.prefix)
        return True


# --- ограничение частоты ---

_WINDOW_SECONDS = 60.0
_hits: dict[str, deque[float]] = {}


def check_rate_limit(view: ApiKeyView, *, now: float | None = None) -> tuple[bool, int]:
    """Уложился ли запрос в предел. `(можно, через сколько секунд можно)`.

    Скользящее окно, а не «сброс каждую минуту»: при сбросе по часам можно
    отправить двойной предел на стыке минут — половину в конце одной,
    половину в начале следующей.
    """
    moment = now if now is not None else time.monotonic()
    window = _hits.setdefault(view.prefix, deque())
    while window and moment - window[0] >= _WINDOW_SECONDS:
        window.popleft()

    if len(window) >= view.rate_limit:
        retry_after = int(_WINDOW_SECONDS - (moment - window[0])) + 1
        return False, max(1, retry_after)

    window.append(moment)
    return True, 0


def reset_rate_limits() -> None:
    """Сбросить счётчики. Только для тестов и перезапуска процесса."""
    _hits.clear()

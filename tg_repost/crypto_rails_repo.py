"""Настроенные способы приёма крипты и выбор нужного (F70).

ВЫБОР ИДЁТ ПО ЦЕПОЧКЕ: товар → его группа → способ группы → способ по
умолчанию. Так владелец получает то, что просил, — «в этой группе один
кошелёк, в той другой», — а товары общего каталога продолжают работать без
всякой привязки.

КЛЮЧИ ПРОВАЙДЕРОВ ШИФРУЮТСЯ мастер-ключом админки, как токены ботов. Токен
CryptoBot — это доступ к деньгам: открытым в базе он уезжает вместе с
первым же бэкапом.

НАРУЖУ КЛЮЧ НЕ ОТДАЁТСЯ НИКОГДА. `RailView` его не содержит вовсе, а не
маскирует: то, чего в объекте нет, невозможно случайно вывести в шаблон.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tg_repost import crypto
from tg_repost.crypto_rails import KINDS, KIND_TON_DIRECT
from tg_repost.db.models import CryptoRail, Product, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


class InvalidRail(ValueError):
    """Способ приёма не прошёл проверку."""


@dataclass(frozen=True)
class RailView:
    """Описание способа БЕЗ ключа — см. docstring модуля."""

    id: int
    name: str
    kind: str
    public_address: str | None
    is_active: bool
    is_default: bool
    created_at: datetime


def _view(row: CryptoRail) -> RailView:
    return RailView(
        id=row.id, name=row.name, kind=row.kind,
        public_address=row.public_address, is_active=row.is_active,
        is_default=row.is_default, created_at=row.created_at,
    )


def _master_key() -> str:
    from tg_repost.webui.settings_store import ensure_master_key

    return ensure_master_key()


def save(
    *,
    rail_id: int | None = None,
    name: str,
    kind: str,
    credential: str = "",
    is_active: bool = True,
    is_default: bool = False,
) -> int:
    """Создать или обновить способ. Пустой `credential` при правке — оставить.

    Пустой ключ означает «не меняли», а не «стереть»: форма не показывает
    сохранённый ключ (его нельзя показать), и трактовать пустое поле как
    очистку значило бы ломать способ при каждой правке названия.
    """
    clean_name = name.strip()
    if not clean_name:
        raise InvalidRail("Название не может быть пустым")
    if kind not in KINDS:
        raise InvalidRail(f"Неизвестный способ приёма: {kind}")

    secret = credential.strip()
    with session_scope() as session:
        row = session.get(CryptoRail, rail_id) if rail_id is not None else None
        if row is None and not secret:
            raise InvalidRail(
                "Нужен токен провайдера или адрес кошелька"
            )
        if row is None:
            row = CryptoRail(name=clean_name, kind=kind, credential_encrypted="")
            session.add(row)
        row.name = clean_name
        row.kind = kind
        if secret:
            row.credential_encrypted = crypto.encrypt(secret, _master_key())
            # Для прямого перевода адрес — не секрет: владелец сверяется по
            # нему с кошельком, и прятать его значит мешать себе же.
            row.public_address = secret if kind == KIND_TON_DIRECT else None
        row.is_active = is_active
        session.flush()

        if is_default:
            # «Ровно один по умолчанию» держим кодом: в SQL это выражается
            # только триггером, а он на SQLite и Postgres пишется по-разному.
            session.query(CryptoRail).filter(CryptoRail.id != row.id).update(
                {CryptoRail.is_default: False}, synchronize_session=False,
            )
        row.is_default = is_default
        return row.id


def get(rail_id: int) -> RailView | None:
    with session_scope() as session:
        row = session.get(CryptoRail, rail_id)
        return _view(row) if row is not None else None


def list_all() -> list[RailView]:
    with session_scope() as session:
        rows = session.query(CryptoRail).order_by(CryptoRail.id.asc()).all()
        return [_view(row) for row in rows]


def delete(rail_id: int) -> bool:
    """Удалить способ и отвязать его от групп.

    Отвязка обязательна: группа со ссылкой на удалённый кошелёк выглядела бы
    настроенной, а платить было бы некуда.
    """
    with session_scope() as session:
        row = session.get(CryptoRail, rail_id)
        if row is None:
            return False
        session.query(TargetGroup).filter(
            TargetGroup.crypto_rail_id == rail_id,
        ).update({TargetGroup.crypto_rail_id: None}, synchronize_session=False)
        session.delete(row)
        return True


def bind_to_group(chat_id: int, rail_id: int | None) -> bool:
    """Назначить группе способ приёма. `None` — вернуть к умолчанию."""
    with session_scope() as session:
        row = (
            session.query(TargetGroup)
            .filter(TargetGroup.chat_id == chat_id)
            .first()
        )
        if row is None:
            return False
        if rail_id is not None and session.get(CryptoRail, rail_id) is None:
            return False
        row.crypto_rail_id = rail_id
        return True


def rail_for_product(product_id: int) -> RailView | None:
    """Чем платить за этот товар. Цепочка описана в docstring модуля."""
    with session_scope() as session:
        product = session.get(Product, product_id)
        if product is None:
            return None
        rail_id: int | None = None
        if product.chat_id is not None:
            group = (
                session.query(TargetGroup)
                .filter(TargetGroup.chat_id == product.chat_id)
                .first()
            )
            rail_id = group.crypto_rail_id if group is not None else None

        row = session.get(CryptoRail, rail_id) if rail_id is not None else None
        if row is None or not row.is_active:
            row = (
                session.query(CryptoRail)
                .filter(
                    CryptoRail.is_default.is_(True),
                    CryptoRail.is_active.is_(True),
                )
                .first()
            )
        return _view(row) if row is not None else None


def build(rail_id: int):  # noqa: ANN201 — тип адаптера объявлен протоколом
    """Собрать рабочий адаптер: расшифровать ключ и отдать объект."""
    from tg_repost.crypto_rails.adapters import build_rail

    with session_scope() as session:
        row = session.get(CryptoRail, rail_id)
        if row is None:
            raise InvalidRail("Способ приёма не найден")
        kind, encrypted = row.kind, row.credential_encrypted

    try:
        credential = crypto.decrypt(encrypted, _master_key())
    except Exception as exc:  # noqa: BLE001
        # Не только `InvalidToken`: повреждённая на уровне байт запись даёт
        # `binascii.Error`/`UnicodeEncodeError`, а вызывающий код ждёт
        # `InvalidRail` — иначе владелец получает 500 вместо объяснения на
        # странице приёма оплаты.
        raise InvalidRail(
            "Ключ не расшифровывается текущим мастер-ключом — его сменили "
            "после сохранения?"
        ) from exc
    return build_rail(kind, credential)

"""Атрибуция подписчиков: кто по какой ссылке пришёл и остался ли (F41).

Telegram САМ сообщает использованную инвайт-ссылку в апдейтах `chat_member` и
`chat_join_request` — до F41 эти данные доходили до наших хендлеров и молча
выбрасывались. Здесь они сохраняются и превращаются в ответ на главный вопрос
рекламы: «сколько людей принесло размещение и сколько из них осталось».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost.db.models import InviteLink, MemberOrigin
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite отдаёт naive-datetime — приводим к UTC-aware, иначе сравнение
    с `_utcnow()` падает с `can't compare offset-naive and offset-aware`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class OriginStats:
    """Итог по одной инвайт-ссылке (или по «без ссылки»)."""

    invite_link: str | None
    invite_name: str | None
    joined: int  # всего пришло по ней
    still_here: int  # из них сейчас в чате
    left: int  # ушли
    retention_7d: float | None  # доля оставшихся среди тех, кто вступил >7д назад
    retention_30d: float | None
    cost: float | None = None
    cost_currency: str = "RUB"

    @property
    def cpa(self) -> float | None:
        """Цена привлечённого подписчика. Считается по ОСТАВШИМСЯ, а не по
        пришедшим: платить за того, кто вступил и сразу вышел, смысла нет."""
        if self.cost is None or self.still_here <= 0:
            return None
        return round(self.cost / self.still_here, 2)


def record_join(
    chat_id: int, user_id: int,
    invite_link: str | None = None, invite_name: str | None = None,
) -> None:
    """Записать вступление. Апсерт по паре (чат, участник): повторное
    вступление после ухода перезаписывает источник — интересен АКТУАЛЬНЫЙ, а не
    вся история метаний. `invite_link=None` — пришёл не по нашей ссылке."""
    with session_scope() as session:
        existing = (
            session.query(MemberOrigin)
            .filter(MemberOrigin.chat_id == chat_id, MemberOrigin.user_id == user_id)
            .one_or_none()
        )
        if existing is not None:
            existing.invite_link = invite_link
            existing.invite_name = invite_name
            existing.joined_at = _utcnow()
            existing.left_at = None  # вернулся — снова с нами
            return
        session.add(
            MemberOrigin(
                chat_id=chat_id, user_id=user_id,
                invite_link=invite_link, invite_name=invite_name,
            )
        )


def record_leave(chat_id: int, user_id: int) -> bool:
    """Отметить уход. False — про такого участника мы ничего не знали (вступил
    до появления F41 или до того, как бота сделали админом): не выдумываем
    запись задним числом, иначе исказим статистику ссылок."""
    with session_scope() as session:
        existing = (
            session.query(MemberOrigin)
            .filter(MemberOrigin.chat_id == chat_id, MemberOrigin.user_id == user_id)
            .one_or_none()
        )
        if existing is None:
            return False
        existing.left_at = _utcnow()
        return True


def _retention(rows: list[MemberOrigin], days: int, now: datetime) -> float | None:
    """Доля оставшихся среди тех, кто вступил РАНЬШЕ чем `days` назад.

    Свежие вступления исключаются намеренно: человек, пришедший час назад,
    ещё физически не мог «прожить неделю», и его учёт занижал бы retention.
    None — таких «созревших» записей ещё нет, показывать нечего.
    """
    cutoff = now - timedelta(days=days)
    mature = [r for r in rows if _aware(r.joined_at) <= cutoff]
    if not mature:
        return None
    stayed = sum(
        1 for r in mature
        if r.left_at is None or _aware(r.left_at) - _aware(r.joined_at) >= timedelta(days=days)
    )
    return round(stayed / len(mature), 3)


def origin_stats(chat_id: int | None = None) -> list[OriginStats]:
    """Статистика по источникам вступления. Сортировка: сначала те, кто привёл
    больше народу; «без ссылки» — всегда последним, это не кампания."""
    now = _utcnow()
    with session_scope() as session:
        query = session.query(MemberOrigin)
        if chat_id is not None:
            query = query.filter(MemberOrigin.chat_id == chat_id)
        rows = query.all()

        links = {link.invite_link: link for link in session.query(InviteLink).all()}

        grouped: dict[str | None, list[MemberOrigin]] = {}
        for row in rows:
            grouped.setdefault(row.invite_link, []).append(row)

        result: list[OriginStats] = []
        for link_url, members in grouped.items():
            link = links.get(link_url) if link_url else None
            still_here = sum(1 for m in members if m.left_at is None)
            result.append(
                OriginStats(
                    invite_link=link_url,
                    # Имя из справочника ссылок свежее, чем сохранённое на
                    # момент вступления, но если ссылку отозвали и удалили —
                    # выручает сохранённое.
                    invite_name=(link.name if link is not None else None)
                    or next((m.invite_name for m in members if m.invite_name), None),
                    joined=len(members),
                    still_here=still_here,
                    left=len(members) - still_here,
                    retention_7d=_retention(members, 7, now),
                    retention_30d=_retention(members, 30, now),
                    cost=link.cost if link is not None else None,
                    cost_currency=link.cost_currency if link is not None else "RUB",
                )
            )

    result.sort(key=lambda s: (s.invite_link is None, -s.joined))
    return result

"""Реферальная программа (F42): кто кого привёл и кому это засчитано.

Главное здесь — АНТИНАКРУТКА. Без неё механика мгновенно превращается в ферму
мультиаккаунтов: завёл десять аккаунтов, прошёл по своей ссылке, собрал
награды. Поэтому реферал засчитывается не по факту перехода, а когда
приглашённый ПРОЖИЛ в группе N дней И написал хотя бы одно сообщение.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tg_repost.db.models import Referral, UserActivity
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Очки за подтверждённого реферала. Заметно дороже квиза (10): привести живого
# человека полезнее для канала, чем ответить на один вопрос.
POINTS_PER_REFERRAL = 50


@dataclass(frozen=True)
class ReferralStats:
    invited: int  # всего перешло по ссылке
    joined: int  # из них вступило в группу
    confirmed: int  # засчитано (прожили срок и написали)

    @property
    def points_earned(self) -> int:
        return self.confirmed * POINTS_PER_REFERRAL


def build_referral_payload(user_id: int) -> str:
    """Payload для персональной ссылки `t.me/<bot>?start=<payload>`."""
    return f"ref_{user_id}"


def register_referral(inviter_user_id: int, invited_user_id: int, chat_id: int) -> bool:
    """Записать переход по реферальной ссылке. False — не записали.

    Отказы (осознанные, не ошибки):
    * сам себя — очевидная накрутка;
    * приглашённый уже кем-то приведён — первый, кто привёл, тот и привёл,
      иначе началась бы гонка «перебей чужого реферала».
    """
    if inviter_user_id == invited_user_id:
        logger.info("Реферал отклонён: %s пригласил сам себя", inviter_user_id)
        return False
    with session_scope() as session:
        existing = (
            session.query(Referral)
            .filter(Referral.invited_user_id == invited_user_id)
            .one_or_none()
        )
        if existing is not None:
            return False
        session.add(
            Referral(
                inviter_user_id=inviter_user_id, invited_user_id=invited_user_id,
                chat_id=chat_id,
            )
        )
    return True


def mark_joined(invited_user_id: int) -> bool:
    """Отметить, что приглашённый вступил в группу (первое из двух условий)."""
    with session_scope() as session:
        row = (
            session.query(Referral)
            .filter(Referral.invited_user_id == invited_user_id)
            .one_or_none()
        )
        if row is None or row.joined_at is not None:
            return False
        row.joined_at = datetime.now(timezone.utc)
        return True


def mark_first_message(invited_user_id: int) -> bool:
    """Отметить первое сообщение приглашённого (второе из двух условий).

    Именно оно отделяет живого человека от мультиаккаунта, зашедшего ради
    награды: вступить может кто угодно, а писать в группу боты-однодневки не
    станут.
    """
    with session_scope() as session:
        row = (
            session.query(Referral)
            .filter(Referral.invited_user_id == invited_user_id)
            .one_or_none()
        )
        if row is None or row.first_message_at is not None:
            return False
        row.first_message_at = datetime.now(timezone.utc)
        return True


def confirm_matured_referrals(min_days: int) -> int:
    """Засчитать рефералов, выдержавших срок, и начислить очки пригласившим.

    Зовётся периодической джобой. Условия все три: вступил, написал, прожил
    `min_days` с момента вступления. Возвращает число засчитанных.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, min_days))
    confirmed = 0
    with session_scope() as session:
        rows = (
            session.query(Referral)
            .filter(
                Referral.confirmed_at.is_(None),
                Referral.joined_at.isnot(None),
                Referral.first_message_at.isnot(None),
                Referral.joined_at <= cutoff,
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            row.confirmed_at = now
            activity = (
                session.query(UserActivity)
                .filter(
                    UserActivity.chat_id == row.chat_id,
                    UserActivity.user_id == row.inviter_user_id,
                )
                .one_or_none()
            )
            if activity is None:
                # Пригласивший мог ни разу не отвечать на викторины — заводим
                # ему запись явными нулями (default=0 срабатывает лишь на
                # INSERT, а мы прибавляем до flush).
                activity = UserActivity(
                    chat_id=row.chat_id, user_id=row.inviter_user_id, points=0,
                    correct_answers=0, total_answers=0, streak_days=0,
                )
                session.add(activity)
            activity.points += POINTS_PER_REFERRAL
            activity.updated_at = now
            confirmed += 1
            logger.info(
                "Реферал засчитан: %s привёл %s (+%d очков)",
                row.inviter_user_id, row.invited_user_id, POINTS_PER_REFERRAL,
            )
    return confirmed


def stats_for(inviter_user_id: int, chat_id: int | None = None) -> ReferralStats:
    """Сводка по пригласившему: сколько перешло / вступило / засчитано."""
    with session_scope() as session:
        query = session.query(Referral).filter(Referral.inviter_user_id == inviter_user_id)
        if chat_id is not None:
            query = query.filter(Referral.chat_id == chat_id)
        rows = query.all()
        return ReferralStats(
            invited=len(rows),
            joined=sum(1 for r in rows if r.joined_at is not None),
            confirmed=sum(1 for r in rows if r.confirmed_at is not None),
        )


def top_inviters(chat_id: int, limit: int = 10) -> list[tuple[int, int]]:
    """Лидерборд рефереров: (user_id, число ЗАСЧИТАННЫХ). Считаем именно
    подтверждённых — иначе первое место займёт тот, кто нагнал мультиаккаунтов."""
    with session_scope() as session:
        rows = (
            session.query(Referral)
            .filter(Referral.chat_id == chat_id, Referral.confirmed_at.isnot(None))
            .all()
        )
    counts: dict[int, int] = {}
    for row in rows:
        counts[row.inviter_user_id] = counts.get(row.inviter_user_id, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]

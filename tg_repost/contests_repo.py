"""Конкурсы и розыгрыши (F44) с ВОСПРОИЗВОДИМЫМ розыгрышем.

Прозрачность — не украшение, а условие работоспособности механики: если
аудитория не верит, что победителя не выбрали «своим», конкурс не вовлекает, а
раздражает. Поэтому:

1. `draw_seed` генерируется при СОЗДАНИИ конкурса и публикуется вместе с
   условиями — до того, как известен состав участников. Организатор физически
   не может подобрать seed под нужного победителя.
2. Участники сортируются детерминированно (по user_id), а не в порядке БД.
3. Победители выбираются `random.Random(seed)` — то есть при тех же входных
   данных результат повторяется у кого угодно.
4. Протокол (список участников + победители + seed) сохраняется и публикуется.

Имея seed, список и описание алгоритма, любой желающий проверяет результат
сам. Именно это и делает конкурс честным в глазах аудитории, а не обещание.
"""

from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from tg_repost.db.models import (
    Contest,
    ContestEntry,
    Referral,
    UserActivity,
    parse_chat_ids_csv,
)
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Описание алгоритма — публикуется вместе с протоколом, чтобы проверка не
# требовала читать наш исходник.
DRAW_ALGORITHM = (
    "участники сортируются по возрастанию user_id, затем "
    "random.Random(seed).sample() выбирает победителей"
)


@dataclass(frozen=True)
class EligibilityResult:
    """Проходит ли участник по условиям, и если нет — чего не хватает."""

    ok: bool
    missing: list[str]


@dataclass(frozen=True)
class ContestView:
    id: int
    chat_id: int
    title: str
    prize: str
    winners_count: int
    ends_at: datetime
    draw_seed: str
    require_subscribed_chat_ids: list[int]
    require_min_points: int
    require_min_referrals: int


def create_contest(
    *, chat_id: int, title: str, prize: str, winners_count: int, ends_at: datetime,
    require_subscribed_chat_ids: list[int] | None = None,
    require_min_points: int = 0, require_min_referrals: int = 0,
) -> int | None:
    """Создать конкурс. Seed рождается ЗДЕСЬ — до того, как появился хоть один
    участник: подобрать его под нужного победителя невозможно даже теоретически."""
    if winners_count < 1 or not title.strip() or not prize.strip():
        return None
    seed = secrets.token_hex(16)
    with session_scope() as session:
        contest = Contest(
            chat_id=chat_id, title=title.strip(), prize=prize.strip(),
            winners_count=winners_count, ends_at=ends_at, draw_seed=seed,
            require_subscribed_chat_ids=(
                ",".join(str(c) for c in require_subscribed_chat_ids)
                if require_subscribed_chat_ids else None
            ),
            require_min_points=max(0, require_min_points),
            require_min_referrals=max(0, require_min_referrals),
        )
        session.add(contest)
        session.flush()
        return contest.id


def get_contest(contest_id: int) -> ContestView | None:
    with session_scope() as session:
        row = session.get(Contest, contest_id)
        if row is None:
            return None
        return ContestView(
            id=row.id, chat_id=row.chat_id, title=row.title, prize=row.prize,
            winners_count=row.winners_count, ends_at=row.ends_at, draw_seed=row.draw_seed,
            require_subscribed_chat_ids=parse_chat_ids_csv(row.require_subscribed_chat_ids),
            require_min_points=row.require_min_points,
            require_min_referrals=row.require_min_referrals,
        )


def check_local_conditions(contest: ContestView, user_id: int) -> EligibilityResult:
    """Проверить условия, которые видны из БД (очки и рефералы).

    Подписка на каналы проверяется отдельно, через Bot API — здесь её нет
    намеренно: этот модуль не должен знать про Telegram.
    """
    missing: list[str] = []
    with session_scope() as session:
        if contest.require_min_points > 0:
            activity = (
                session.query(UserActivity)
                .filter(
                    UserActivity.chat_id == contest.chat_id,
                    UserActivity.user_id == user_id,
                )
                .one_or_none()
            )
            points = activity.points if activity else 0
            if points < contest.require_min_points:
                missing.append(
                    f"нужно минимум {contest.require_min_points} очков (у тебя {points})",
                )
        if contest.require_min_referrals > 0:
            confirmed = (
                session.query(Referral)
                .filter(
                    Referral.inviter_user_id == user_id,
                    Referral.chat_id == contest.chat_id,
                    Referral.confirmed_at.isnot(None),
                )
                .count()
            )
            if confirmed < contest.require_min_referrals:
                missing.append(
                    f"нужно минимум {contest.require_min_referrals} приглашённых "
                    f"(у тебя {confirmed})",
                )
    return EligibilityResult(ok=not missing, missing=missing)


def join_contest(
    contest_id: int, user_id: int,
    username: str | None = None, full_name: str | None = None,
) -> bool:
    """Записать участника. False — конкурс не найден, уже закончился или
    человек уже записан."""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        contest = session.get(Contest, contest_id)
        if contest is None or contest.drawn_at is not None:
            return False
        ends_at = contest.ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ends_at <= now:
            return False
        exists = (
            session.query(ContestEntry)
            .filter(
                ContestEntry.contest_id == contest_id,
                ContestEntry.user_id == user_id,
            )
            .one_or_none()
        )
        if exists is not None:
            return False
        session.add(
            ContestEntry(
                contest_id=contest_id, user_id=user_id,
                username=username, full_name=full_name,
            )
        )
    return True


def pick_winners(seed: str, participant_ids: list[int], winners_count: int) -> list[int]:
    """Выбрать победителей ВОСПРОИЗВОДИМО.

    Чистая функция без БД — именно она и есть «алгоритм», который мы публикуем:
    любой может вызвать её с тем же seed и списком и получить тот же результат.
    Сортировка обязательна: порядок строк в БД не воспроизводим, а без него
    один и тот же seed давал бы разных победителей.
    """
    ordered = sorted(set(participant_ids))
    if not ordered:
        return []
    count = min(winners_count, len(ordered))
    # Псевдослучайный генератор здесь ОБЯЗАТЕЛЕН, а не недосмотр: крипто-ГСЧ
    # невоспроизводим, а значит результат нельзя перепроверить — вся ценность
    # прозрачности пропала бы. Непредсказуемость обеспечивает не генератор, а
    # сам seed: он берётся из `secrets.token_hex` при создании конкурса, до
    # появления участников, и публикуется заранее. Подобрать его под нужного
    # победителя нельзя.
    return random.Random(seed).sample(ordered, count)  # nosec B311


def draw_contest(contest_id: int, eligible_user_ids: list[int] | None = None) -> dict | None:
    """Провести розыгрыш и сохранить протокол. None — нечего разыгрывать.

    `eligible_user_ids` — список тех, кто ПОВТОРНО прошёл проверку условий уже
    на момент розыгрыша (подписку проверяет вызывающий через Bot API). Так
    нельзя выполнить условие, записаться и тут же отписаться от канала.
    None — проверять нечего, участвуют все записавшиеся.
    """
    with session_scope() as session:
        contest = session.get(Contest, contest_id)
        if contest is None or contest.drawn_at is not None:
            return None
        entries = (
            session.query(ContestEntry)
            .filter(ContestEntry.contest_id == contest_id)
            .all()
        )
        participants = [e.user_id for e in entries]
        if eligible_user_ids is not None:
            allowed = set(eligible_user_ids)
            participants = [uid for uid in participants if uid in allowed]
        if not participants:
            logger.info("Конкурс %s: участников нет, розыгрыш не проводится", contest_id)
            return None

        winners = pick_winners(contest.draw_seed, participants, contest.winners_count)
        for entry in entries:
            entry.is_winner = entry.user_id in winners

        protocol = {
            "seed": contest.draw_seed,
            "algorithm": DRAW_ALGORITHM,
            # Именно тот список и в том порядке, который видел алгоритм — без
            # него проверить результат невозможно.
            "participants": sorted(set(participants)),
            "winners": winners,
        }
        contest.draw_protocol = json.dumps(protocol, ensure_ascii=False)
        contest.drawn_at = datetime.now(timezone.utc)
        logger.info("Конкурс %s разыгран: победители %s", contest_id, winners)
        return protocol


def list_entries(contest_id: int) -> list[ContestEntry]:
    with session_scope() as session:
        return (
            session.query(ContestEntry)
            .filter(ContestEntry.contest_id == contest_id)
            .order_by(ContestEntry.joined_at)
            .all()
        )


def due_contests() -> list[ContestView]:
    """Конкурсы, у которых вышел срок и розыгрыш ещё не проводился."""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        rows = (
            session.query(Contest)
            .filter(Contest.drawn_at.is_(None), Contest.ends_at <= now)
            .all()
        )
        return [
            ContestView(
                id=r.id, chat_id=r.chat_id, title=r.title, prize=r.prize,
                winners_count=r.winners_count, ends_at=r.ends_at, draw_seed=r.draw_seed,
                require_subscribed_chat_ids=parse_chat_ids_csv(r.require_subscribed_chat_ids),
                require_min_points=r.require_min_points,
                require_min_referrals=r.require_min_referrals,
            )
            for r in rows
        ]


def list_contests(chat_id: int | None = None) -> list[Contest]:
    with session_scope() as session:
        query = session.query(Contest)
        if chat_id is not None:
            query = query.filter(Contest.chat_id == chat_id)
        return query.order_by(Contest.created_at.desc()).all()

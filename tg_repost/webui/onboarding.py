"""Первые шаги: что осталось настроить, чтобы система заработала.

ЗАЧЕМ. До этого на главной висело одно предупреждение «система не
настроена». Оно верное и бесполезное: не говорит ни что именно не задано, ни
куда идти, ни что случится, если пропустить. Владелец, зайдя в админку
впервые, сказал прямо: «ничего не понятно».

ШАГИ ВЫЧИСЛЯЮТСЯ, А НЕ ПЕРЕЧИСЛЯЮТСЯ. Список, написанный руками, разойдётся
с системой на первой же фиче и начнёт врать — а врущий чеклист хуже, чем его
отсутствие: по нему всё сделано, а ничего не работает.

ПОРЯДОК — ПО ЗАВИСИМОСТЯМ, А НЕ ПО ВАЖНОСТИ. Источники бессмысленны без
Telethon, публикация — без целевой группы. Человек идёт сверху вниз и на
каждом шаге получает работающий кусок, а не собирает всё, чтобы проверить в
конце.

ОБЯЗАТЕЛЬНОЕ ОТДЕЛЕНО ОТ ЖЕЛАТЕЛЬНОГО. Guardian и Engage — отдельные боты со
своими токенами; без них ядро работает полностью. Смешать их с обязательными
шагами значит заставить человека заводить трёх ботов, чтобы опубликовать
один пост.
"""

from __future__ import annotations

from dataclasses import dataclass


# Порядок шагов, доступный БЕЗ обращения к базе. Нужен проверке полноты
# переводов: та собирает свой список на импорте, когда базы может не быть
# вовсе, а лезть в неё ради перечня ключей — лишняя связность.
STEP_KEYS: tuple[str, ...] = (
    "telegram_api",
    "telethon_session",
    "bot_token",
    "owner_id",
    "ai_key",
    "sources",
    "targets",
    "guardian",
    "engage",
)


@dataclass(frozen=True)
class Step:
    key: str
    done: bool
    href: str
    # Обязателен ли для работы ядра: сбор → рерайт → модерация → публикация.
    required: bool = True


def _has_sources() -> bool:
    from tg_repost.db.models import Source
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        return session.query(Source.id).first() is not None


def _has_targets() -> bool:
    from tg_repost.db.models import TargetGroup
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        return (
            session.query(TargetGroup.id)
            .filter(TargetGroup.is_active.is_(True))
            .first()
            is not None
        )


def _secret_present(key: str) -> bool:
    """Задан ли секрет. Проверяется НАЛИЧИЕ, а не значение.

    Расшифровывать ради галочки незачем: непустая строка означает, что
    владелец что-то ввёл, а верен ли токен — покажет первый же запрос к
    Telegram, и врать об этом чеклист не должен.
    """
    from tg_repost.db.models import Secret
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        row = session.query(Secret).filter(Secret.key == key).one_or_none()
        return row is not None and bool(row.encrypted_value)


def steps() -> list[Step]:
    """Текущее состояние настройки, по порядку."""
    from tg_repost.config import get_settings

    settings = get_settings()

    return [
        # Без этого Telethon не поднимется, и собирать посты будет нечем.
        Step("telegram_api", bool(settings.tg_api_id and settings.tg_api_hash), "/settings"),
        Step("telethon_session", _secret_present("tg_session_string"), "/components"),
        # Бот модерации: через него владелец одобряет посты и в него же
        # система пишет о сбоях.
        Step("bot_token", _secret_present("tg_bot_token"), "/settings"),
        Step("owner_id", bool(settings.tg_owner_user_id), "/settings"),
        # Рерайт — сердце системы: без ключа ИИ посты не переписываются.
        Step("ai_key", _secret_present("openai_api_key"), "/settings"),
        Step("sources", _has_sources(), "/sources"),
        Step("targets", _has_targets(), "/targets"),
        # Дальше — необязательное. Ядро без этого работает целиком.
        Step("guardian", _secret_present("guardian_bot_token"), "/settings", required=False),
        Step("engage", _secret_present("engage_bot_token"), "/settings", required=False),
    ]


def summary() -> dict:
    """Сводка для главной: сколько сделано и что следующее.

    `next_step` — ПЕРВЫЙ невыполненный обязательный шаг. Именно один, а не
    список: человеку нужно знать, что делать сейчас, а не сколько всего
    предстоит.
    """
    all_steps = steps()
    required = [s for s in all_steps if s.required]
    done = [s for s in required if s.done]
    pending = [s for s in required if not s.done]

    return {
        "steps": all_steps,
        "done_count": len(done),
        "total_count": len(required),
        "is_ready": not pending,
        "next_step": pending[0] if pending else None,
    }

"""Фабрика сессий SQLAlchemy для Guardian — отдельная БД от репост-бота
(своя alembic-цепочка, свой файл по умолчанию), тот же паттерн, что
`tg_repost.db.session` (см. комментарии там про StaticPool/":memory:")."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _get_database_url() -> str:
    load_dotenv()  # idempotent — не перезаписывает уже выставленные os.environ
    return os.environ.get("GUARDIAN_DATABASE_URL", "sqlite:///guardian.db")


_database_url = _get_database_url()

# timeout=15 (сек) — этот файл реально пишется ДВУМЯ независимыми ОС-
# процессами одновременно (guardian и tg_repost, см. webui/guardian_routes.py
# про кросс-пакетную запись сюда прямо из процесса tg_repost) — явный запас
# сверх дефолтных 5с sqlite3 на случай всплеска одновременных записей
# (найдено на аудите; см. тот же комментарий в tg_repost/db/session.py).
_connect_args = (
    {"check_same_thread": False, "timeout": 15} if _database_url.startswith("sqlite") else {}
)

_engine_kwargs: dict = {
    "echo": False,
    "future": True,
    "connect_args": _connect_args,
}
if ":memory:" in _database_url:
    _engine_kwargs["poolclass"] = StaticPool

engine = create_engine(_database_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Транзакционный контекст: commit при успехе, rollback при ошибке."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

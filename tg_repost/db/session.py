"""Фабрика сессий SQLAlchemy.

На MVP используется синхронный engine (SQLite). Работа с БД из async-кода
выполняется через короткие синхронные транзакции внутри
`run_in_executor`-обёртки или напрямую — операции быстрые и локальные.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tg_repost.config import get_settings

_settings = get_settings()

# check_same_thread=False — чтобы SQLite-соединение можно было использовать
# из разных задач event loop / executor-потоков.
_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    _settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
)

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

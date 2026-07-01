"""Фабрика сессий SQLAlchemy.

На MVP используется синхронный engine (SQLite). Работа с БД из async-кода
выполняется через короткие синхронные транзакции внутри
`run_in_executor`-обёртки или напрямую — операции быстрые и локальные.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _get_database_url() -> str:
    """Прочитать DATABASE_URL напрямую из окружения/.env, БЕЗ `config.Settings`.

    Намеренно: `config.py` (Фаза 5) сам читает БД для оверлея настроек из
    веб-админки (таблица `app_settings`), что создало бы циклический импорт
    `config → db.session → config`. `database_url` и так не входит в список
    живо-перезагружаемых настроек (engine создаётся один раз при импорте) —
    поэтому читать его в обход полного `Settings`-конвейера не теряет
    функциональности.
    """
    load_dotenv()  # idempotent — не перезаписывает уже выставленные os.environ
    return os.environ.get("DATABASE_URL", "sqlite:///tg_repost.db")


_database_url = _get_database_url()

# check_same_thread=False — чтобы SQLite-соединение можно было использовать
# из разных задач event loop / executor-потоков.
_connect_args = (
    {"check_same_thread": False} if _database_url.startswith("sqlite") else {}
)

_engine_kwargs: dict = {
    "echo": False,
    "future": True,
    "connect_args": _connect_args,
}
if ":memory:" in _database_url:
    # По умолчанию SQLAlchemy использует SingletonThreadPool для sqlite
    # ":memory:" — одно соединение НА ПОТОК. Для ":memory:" БД каждое
    # отдельное соединение — это своя, полностью изолированная база: новый
    # поток видит ПУСТУЮ схему, даже если основной поток уже создал все
    # таблицы. Тесты через `fastapi.testclient.TestClient` гоняют
    # ASGI-приложение в отдельном потоке через anyio-портал — с
    # SingletonThreadPool эти запросы попадали бы в БД без единой таблицы
    # (найдено при добавлении интеграционных тестов, аудит Фазы 5).
    # `StaticPool` — ОДНО реальное соединение на всех, вне зависимости от
    # потока (thread-safety уже обеспечена `check_same_thread=False` выше) —
    # официально рекомендуемый паттерн для тестирования FastAPI+SQLite
    # ":memory:" именно по этой причине. В проде `database_url` — файл, не
    # ":memory:", так что это не меняет поведение вне тестов.
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

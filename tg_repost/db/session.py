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
# из разных задач event loop / executor-потоков. timeout=15 (сек, sqlite3
# DBAPI ждёт освобождения блокировки перед `OperationalError: database is
# locked`, дефолт — 5с) — этот файл реально пишется ДВУМЯ независимыми ОС-
# процессами одновременно (tg_repost и guardian, см. webui/guardian_routes.py
# про кросс-пакетную запись в guardian.db прямо из этого процесса) — явный
# запас на случай всплеска одновременных записей (найдено на аудите).
_connect_args = (
    {"check_same_thread": False, "timeout": 15} if _database_url.startswith("sqlite") else {}
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


if _database_url.startswith("sqlite") and ":memory:" not in _database_url:
    from sqlalchemy import event

    event.listens_for(engine, "connect")(
        lambda dbapi_connection, _record: apply_sqlite_pragmas(dbapi_connection)
    )


def apply_sqlite_pragmas(dbapi_connection) -> None:
    """WAL и разумные ожидания блокировки — на каждое соединение.

    ЗАЧЕМ WAL. Файл базы пишут ДВА независимых процесса: `tg_repost` и
    `engage` (у них общая БД — викторина делается из поста, реферальная
    ссылка это InviteLink). В режиме по умолчанию (`delete`) пишущий берёт
    исключительную блокировку на ВСЮ базу, а читающие ждут и через
    несколько секунд получают «database is locked». Измерено на стенде:
    режим был `delete`. Проявилось бы это в худший момент — на рассылке,
    когда очередь пишет пачками, а человек в это же время жмёт кнопку
    сценария. В WAL читатели не ждут писателя вовсе.

    Режим задаётся ОДИН раз и остаётся в самом файле базы, но выставляем
    на каждом соединении намеренно: так новый файл (первый запуск, тесты,
    восстановление из бэкапа) получает его сразу, а не «когда-нибудь».

    `synchronous=NORMAL` — штатный спутник WAL: fsync на checkpoint, а не
    на каждую транзакцию. Потерять при этом можно только последние
    транзакции при отключении питания, а не целостность базы.

    `busy_timeout` дублирует `timeout` из connect_args намеренно: тот
    действует на соединения через DBAPI, а PRAGMA — на всё, включая
    служебные подключения.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
    finally:
        cursor.close()


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

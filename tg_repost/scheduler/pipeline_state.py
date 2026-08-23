"""Чем занят пайплайн прямо сейчас — для дашборда (найдено 2026-08-23).

ЗАЧЕМ. Когда такт идёт дольше своего интервала, APScheduler пишет в лог
«maximum number of running instances reached» и пропускает следующий запуск.
Это единственный признак затора, и он не говорит НИ ЧЕГО: ни что делается, ни
как давно, ни сколько ждёт очередь. Владелец видит одно — посты ловятся,
дальше тишина.

Замер на стенде: такт шёл больше часа. При таймауте провайдера 180 с и двух
повторах ОДИН вызов модели занимает до девяти минут, а на пост их шесть —
получается до 54 минут на пост, и это не поломка, а арифметика настроек.
Понять это по логу было нельзя.

ПОЧЕМУ В ПАМЯТИ, А НЕ В БАЗЕ. Это сведения о текущем процессе, живут ровно
столько же, сколько он сам, и писать их в базу каждые полминуты значило бы
лишний износ базы ради данных, которые после перезапуска всё равно неверны.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class TickState:
    """Что известно про такт пайплайна."""

    running: bool
    started_at: datetime | None
    current_post_id: int | None
    last_duration_seconds: float | None
    last_finished_at: datetime | None

    @property
    def running_seconds(self) -> float | None:
        if not self.running or self.started_at is None:
            return None
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


_lock = threading.Lock()
_started_at: datetime | None = None
_current_post_id: int | None = None
_last_duration: float | None = None
_last_finished_at: datetime | None = None


def tick_started() -> None:
    global _started_at, _current_post_id
    with _lock:
        _started_at = datetime.now(timezone.utc)
        _current_post_id = None


def post_started(post_id: int) -> None:
    """Какой пост сейчас в работе — чтобы на дашборде было видно, что затор
    именно на нём, а не «где-то»."""
    global _current_post_id
    with _lock:
        _current_post_id = post_id


def record_tick(duration_seconds: float) -> None:
    global _started_at, _current_post_id, _last_duration, _last_finished_at
    with _lock:
        _started_at = None
        _current_post_id = None
        _last_duration = duration_seconds
        _last_finished_at = datetime.now(timezone.utc)


def current() -> TickState:
    with _lock:
        return TickState(
            running=_started_at is not None,
            started_at=_started_at,
            current_post_id=_current_post_id,
            last_duration_seconds=_last_duration,
            last_finished_at=_last_finished_at,
        )


def reset() -> None:
    """Забыть всё — для тестов: состояние общее на процесс, и без сброса один
    тест видел бы такт, запущенный другим."""
    global _started_at, _current_post_id, _last_duration, _last_finished_at
    with _lock:
        _started_at = None
        _current_post_id = None
        _last_duration = None
        _last_finished_at = None

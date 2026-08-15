"""Детектор накрутки по кривой роста (F60).

На этих цифрах человек решает, платить ли за размещение, — поэтому тесты в
основном про ЛОЖНЫЕ СРАБАТЫВАНИЯ. Детектор, который кричит на любой всплеск,
приучает не смотреть на предупреждения, и настоящую накрутку тоже
пропустят.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import fraud_detector
from tg_repost.db.models import ChannelGrowthSnapshot, Post, PostStat
from tg_repost.db.session import session_scope

CHAT = -100909090


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostStat).delete()
            session.query(Post).delete()
            session.query(ChannelGrowthSnapshot).delete()

    _wipe()
    yield
    _wipe()


def _series(*counts: int) -> list[tuple[datetime, int]]:
    base = _utcnow() - timedelta(days=len(counts))
    return [(base + timedelta(days=i), value) for i, value in enumerate(counts)]


def _store(*counts: int) -> None:
    base = _utcnow() - timedelta(days=len(counts))
    with session_scope() as session:
        for i, value in enumerate(counts):
            session.add(
                ChannelGrowthSnapshot(
                    chat_id=CHAT, subscriber_count=value,
                    captured_at=base + timedelta(days=i),
                )
            )


# --- «пила» ---


def test_sawtooth_is_detected():
    """Пришло много и почти столько же ушло — так выглядит снятая накрутка."""
    finding = fraud_detector.detect_sawtooth(
        _series(1000, 1010, 1500, 1120, 1100, 1105)
    )

    assert finding is not None
    assert finding.code == "sawtooth"
    assert "+490" in finding.detail


def test_steady_growth_is_not_sawtooth():
    """Ровный рост — это просто рост."""
    assert fraud_detector.detect_sawtooth(
        _series(1000, 1050, 1100, 1160, 1210, 1270)
    ) is None


def test_spike_that_stays_is_not_sawtooth():
    """ГЛАВНЫЙ ТЕСТ ПРОТИВ ЛОЖНЫХ СРАБАТЫВАНИЙ.

    Виральная публикация тоже даёт резкий приход. Разница в том, что эти
    люди остаются — и обвинять владельца в накрутке за удачный пост
    недопустимо.
    """
    assert fraud_detector.detect_sawtooth(
        _series(1000, 1010, 1500, 1495, 1510, 1530)
    ) is None


def test_small_fluctuation_is_ignored():
    """Колебания в пару процентов — обычная жизнь канала."""
    assert fraud_detector.detect_sawtooth(
        _series(1000, 1020, 1005, 1015, 1000, 1010)
    ) is None


def test_partial_dropback_below_threshold_is_ignored():
    """Ушла малая часть пришедших — это нормальный отсев, не пила."""
    assert fraud_detector.detect_sawtooth(
        _series(1000, 1010, 1500, 1450, 1440, 1445)
    ) is None


def test_too_short_series_gives_nothing():
    assert fraud_detector.detect_sawtooth(_series(1000, 1500)) is None


def test_drop_outside_window_is_not_linked_to_the_spike():
    """Отток через две недели после всплеска — не «пила».

    Иначе любой всплеск рано или поздно «подтвердится» естественным оттоком.
    """
    assert fraud_detector.detect_sawtooth(
        _series(1000, 1500, 1500, 1500, 1500, 1500, 1100)
    ) is None


# --- рост без охватов ---


def test_growth_without_reach_is_detected():
    """Живой подписчик хоть иногда открывает канал."""
    finding = fraud_detector.detect_growth_without_reach(
        subs_first=1000, subs_last=1400, views_first=500, views_last=480,
    )

    assert finding is not None
    assert finding.code == "growth_without_reach"


def test_growth_with_reach_is_fine():
    assert fraud_detector.detect_growth_without_reach(
        subs_first=1000, subs_last=1400, views_first=500, views_last=700,
    ) is None


def test_small_growth_is_not_judged():
    """На росте в пару процентов охваты могут и не сдвинуться — это шум."""
    assert fraud_detector.detect_growth_without_reach(
        subs_first=1000, subs_last=1030, views_first=500, views_last=495,
    ) is None


def test_missing_views_gives_no_verdict():
    """Нет данных об охватах — нет и обвинения.

    Промолчать честнее, чем назвать накруткой то, чего мы не измеряли.
    """
    assert fraud_detector.detect_growth_without_reach(
        subs_first=1000, subs_last=1400, views_first=None, views_last=None,
    ) is None


def test_zero_baseline_does_not_divide_by_zero():
    assert fraud_detector.detect_growth_without_reach(
        subs_first=0, subs_last=100, views_first=0, views_last=0,
    ) is None


# --- отчёт целиком ---


def test_not_enough_snapshots_is_reported_honestly():
    """По трём точкам форму кривой не увидеть, и делать вид, что увидели,
    нельзя."""
    _store(1000, 1100, 1200)

    report = fraud_detector.analyze(CHAT)

    assert report.enough_data is False
    assert report.looks_suspicious is False


def test_clean_channel_has_no_findings():
    _store(1000, 1020, 1040, 1060, 1080, 1100, 1120)

    report = fraud_detector.analyze(CHAT)

    assert report.enough_data is True
    assert report.findings == ()


def test_sawtooth_channel_is_flagged():
    _store(1000, 1010, 1600, 1120, 1110, 1115, 1120)

    report = fraud_detector.analyze(CHAT)

    assert report.looks_suspicious is True
    assert any(f.code == "sawtooth" for f in report.findings)


def test_other_channel_snapshots_are_ignored():
    _store(1000, 1010, 1600, 1120, 1110, 1115, 1120)
    with session_scope() as session:
        session.add(
            ChannelGrowthSnapshot(
                chat_id=-100111, subscriber_count=5, captured_at=_utcnow(),
            )
        )

    report = fraud_detector.analyze(CHAT)

    assert report.snapshots == 7

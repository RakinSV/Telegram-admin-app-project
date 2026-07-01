"""Тесты распределения источников между Telethon-клиентами (F26)."""

import pytest

from tg_repost.telegram.listener import partition_sources


def test_partition_sources_single_client_gets_everything():
    assert partition_sources(["a", "b", "c"], 1) == [["a", "b", "c"]]


def test_partition_sources_round_robin_even_split():
    result = partition_sources(["a", "b", "c", "d"], 2)
    assert result == [["a", "c"], ["b", "d"]]


def test_partition_sources_round_robin_uneven_split():
    result = partition_sources(["a", "b", "c"], 2)
    assert result == [["a", "c"], ["b"]]


def test_partition_sources_more_clients_than_sources():
    result = partition_sources(["a"], 3)
    assert result == [["a"], [], []]


def test_partition_sources_empty_list():
    assert partition_sources([], 3) == [[], [], []]


def test_partition_sources_preserves_all_sources_exactly_once():
    sources = [f"chan{i}" for i in range(17)]
    result = partition_sources(sources, 4)
    flattened = sorted(u for part in result for u in part)
    assert flattened == sorted(sources)


def test_partition_sources_rejects_zero_partitions():
    with pytest.raises(ValueError):
        partition_sources(["a"], 0)


def test_partition_sources_rejects_negative_partitions():
    with pytest.raises(ValueError):
        partition_sources(["a"], -1)

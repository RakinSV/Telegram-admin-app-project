"""Тесты семантического дубль-чека (F13): упаковка вектора и косинус."""

import math

from tg_repost.dedup.semantic import (
    cosine_similarity,
    pack_embedding,
    unpack_embedding,
)


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.5, 3.14, 0.0]
    restored = unpack_embedding(pack_embedding(vec))
    assert len(restored) == len(vec)
    for a, b in zip(vec, restored):
        assert math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def test_cosine_identical_is_one():
    vec = [1.0, 2.0, 3.0]
    assert math.isclose(cosine_similarity(vec, vec), 1.0, abs_tol=1e-9)


def test_cosine_orthogonal_is_zero():
    assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)


def test_cosine_opposite_is_minus_one():
    assert math.isclose(cosine_similarity([1.0, 1.0], [-1.0, -1.0]), -1.0, abs_tol=1e-9)


def test_cosine_zero_vector_safe():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_mismatched_length_safe():
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_cosine_near_duplicate_above_threshold():
    a = [0.9, 0.1, 0.2]
    b = [0.91, 0.09, 0.21]
    assert cosine_similarity(a, b) > 0.99

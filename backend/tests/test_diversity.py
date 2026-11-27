"""Varied passages (MMR): a question asking two things finds passages for both."""

import math
import random

from app.services import diversity


def _around(center, noise, rng):
    return [x + rng.gauss(0, noise) for x in center]


def _clusters():
    rng = random.Random(2)
    a = [rng.gauss(0, 1) for _ in range(64)]
    b = [rng.gauss(0, 1) for _ in range(64)]
    vectors = [_around(a, 0.65, rng) for _ in range(20)] + [_around(b, 0.65, rng) for _ in range(6)]
    relevance = [0.62 - 0.004 * i for i in range(20)] + [0.45 - 0.004 * i for i in range(6)]
    return relevance, vectors


def test_off_keeps_the_most_relevant():
    relevance, vectors = _clusters()
    assert diversity.select(relevance, vectors, 8, "off") == list(range(8))


def test_second_topic_gets_passages():
    relevance, vectors = _clusters()
    for level in ("normal", "high"):
        keep = diversity.select(relevance, vectors, 8, level)
        assert len(keep) == 8 and keep[0] == 0                 # the best passage always stays first
        assert any(i >= 20 for i in keep), level                # the second topic is represented
        assert keep == sorted(keep, key=lambda i: relevance[i], reverse=True)  # returned by relevance
    high = sum(i >= 20 for i in diversity.select(relevance, vectors, 8, "high"))
    normal = sum(i >= 20 for i in diversity.select(relevance, vectors, 8, "normal"))
    assert high >= normal


def test_few_candidates_and_missing_vectors():
    assert diversity.select([0.5, 0.4], [None, None], 8, "normal") == [0, 1]
    keep = diversity.select([0.9, 0.8, 0.7], [[1.0, 0.0], None, [0.0, 1.0]], 2, "high")
    assert keep[0] == 0 and len(keep) == 2


def test_pool_size():
    assert diversity.pool_size(8, "off") == 8
    assert diversity.pool_size(8, "normal") == 32 and diversity.pool_size(3, "high") == 24


def test_speed_on_a_realistic_pool():
    import time
    rng = random.Random(1)
    vectors = [[rng.gauss(0, 1) for _ in range(1024)] for _ in range(64)]
    relevance = sorted((rng.random() for _ in range(64)), reverse=True)
    t = time.monotonic()
    diversity.select(relevance, vectors, 20, "high")
    assert time.monotonic() - t < 1.0
    assert math.isfinite(relevance[0])

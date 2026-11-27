"""Varied passages: Maximal Marginal Relevance (Carbonell & Goldstein, 1998).

The plain search keeps the passages closest to the question. When a question asks two things
("how do I handle CVE-X, and which hotel is near the centre?"), the stronger topic takes every
place and the other finds nothing. MMR picks passages one at a time: each next one must be close
to the question AND different from those already picked:

    next = argmax  lambda * sim(question, p)  -  (1 - lambda) * max sim(p, picked)

Deterministic, no model call, one parameter. lambda = 1 is the plain search; lower values give
more variety. Pure functions: no database, no index.
"""

import math

LEVELS = ("off", "normal", "high")
DEFAULT = "normal"
LAMBDA = {"normal": 0.7, "high": 0.5}   # "off": plain search
POOL_FACTOR = 4                          # candidates read from the index: limit x 4 ...
POOL_MIN = 24                            # ... and at least this many


def pool_size(limit: int, level: str) -> int:
    """How many candidates to read from the index for `limit` passages."""
    return limit if level not in LAMBDA else max(limit * POOL_FACTOR, POOL_MIN)


def _unit(v: list[float] | None) -> list[float] | None:
    if v is None:
        return None
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def select(relevance: list[float], vectors: list[list[float] | None], limit: int, level: str) -> list[int]:
    """Indexes of the passages to keep, in order of relevance.

    `relevance[i]`: similarity of candidate i to the question (the index score); `vectors[i]`: its
    embedding (None: no vector, treated as unlike every other). With level "off", or no more
    candidates than places, the most relevant ones are kept as before.
    """
    order = sorted(range(len(relevance)), key=lambda i: relevance[i], reverse=True)
    lam = LAMBDA.get(level)
    if lam is None or len(order) <= limit:
        return order[:limit]
    unit = [_unit(v) for v in vectors]
    redundancy = dict.fromkeys(order, 0.0)  # max similarity to the passages picked so far
    picked: list[int] = []
    rest = list(order)
    while rest and len(picked) < limit:
        best = max(rest, key=lambda i: lam * relevance[i] - (1 - lam) * redundancy[i])
        picked.append(best)
        rest.remove(best)
        if unit[best] is not None:  # only the new pick can raise a candidate's redundancy
            for i in rest:
                if unit[i] is not None:
                    sim = sum(x * y for x, y in zip(unit[i], unit[best], strict=False))
                    redundancy[i] = max(redundancy[i], sim)
    return sorted(picked, key=lambda i: relevance[i], reverse=True)

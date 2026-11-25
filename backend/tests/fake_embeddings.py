"""Deterministic bag-of-words embeddings, for tests and the local end-to-end run.

Not a language model: texts sharing words get similar vectors, which is enough to check that
indexing, filtering and ranking work. Also runnable as an OpenAI-compatible server:

    uvicorn tests.fake_embeddings:app --port 8090   ->  POST /v1/embeddings
"""

import hashlib
import math
import re

from fastapi import FastAPI

DIM = 256


def embed_one(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) < 3:
            continue
        h = int(hashlib.sha1(word.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]]:
    return [embed_one(t) for t in texts]


app = FastAPI()


@app.post("/v1/embeddings")
def embeddings(body: dict) -> dict:
    texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return {"object": "list", "model": body.get("model"),
            "data": [{"object": "embedding", "index": i, "embedding": embed_one(t)} for i, t in enumerate(texts)]}

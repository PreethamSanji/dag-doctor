"""Embeddings.

Two backends, selected by ``retrieval.embedder`` in config:

``hashing``
    A deterministic, dependency-free hashed bag-of-ngrams. It is not a semantic
    model, but it is offline, free, and identical on every machine - which is
    what keeps unit tests and CI deterministic and what makes an eval report
    reproducible without an embedding-provider account.

``voyage``
    Voyage AI's hosted embeddings (Anthropic's recommended embedding partner),
    used when ``VOYAGE_API_KEY`` is set. Better recall, costs money, needs network.

Swapping the embedder changes retrieval, which means it is an eval-gated change.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

import httpx

_WORD = re.compile(r"[A-Za-z0-9_./-]+")


class Embedder(Protocol):
    """Anything that turns text into a fixed-width vector."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    words = [w.casefold() for w in _WORD.findall(text)]
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
    return words + bigrams


def _bucket(token: str, dim: int) -> tuple[int, float]:
    """Hash a token to a bucket and a sign, so collisions cancel rather than pile up."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


class HashingEmbedder:
    """Deterministic hashed bag-of-ngrams with sublinear term frequency."""

    def __init__(self, dim: int = 512) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self.name = "hashing"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        counts: dict[str, int] = {}
        for token in _tokens(text):
            counts[token] = counts.get(token, 0) + 1
        vector = [0.0] * self.dim
        for token, count in counts.items():
            index, sign = _bucket(token, self.dim)
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class VoyageEmbedder:
    """Hosted embeddings via Voyage AI. Requires ``VOYAGE_API_KEY``."""

    ENDPOINT = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, model: str = "voyage-3", dim: int = 1024, timeout: float = 30.0) -> None:
        api_key = os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            raise RuntimeError("VOYAGE_API_KEY is not set; use the hashing embedder instead")
        self.name = f"voyage:{model}"
        self.dim = dim
        self._model = model
        self._client = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 128):
            batch = texts[start : start + 128]
            response = self._client.post(self.ENDPOINT, json={"model": self._model, "input": batch})
            response.raise_for_status()
            payload = response.json()
            vectors.extend(item["embedding"] for item in payload["data"])
        return vectors


def build_embedder(name: str, dim: int) -> Embedder:
    """Construct the embedder named in config."""
    if name == "hashing":
        return HashingEmbedder(dim=dim)
    if name == "voyage":
        return VoyageEmbedder(dim=dim)
    raise ValueError(f"unknown embedder: {name!r} (expected 'hashing' or 'voyage')")


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; both backends emit normalized or near-normalized vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

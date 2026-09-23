"""Pure scoped retrieval results and deterministic hybrid fusion."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    repository_id: UUID
    generation_id: UUID
    commit_sha: str
    embedding_space_version: str
    chunk_count: int = 1


@dataclass(frozen=True, slots=True)
class Candidate:
    path: str
    ordinal: int
    start_line: int
    end_line: int
    content: str
    language: str


def chunk_uuid(generation_id: UUID, path: str, ordinal: int) -> UUID:
    """Derive a stable wire ID from the immutable database chunk key."""
    return uuid5(generation_id, f"{path}\x00{ordinal}")


def fuse_candidates(
    vector: tuple[Candidate, ...], lexical: tuple[Candidate, ...], top_k: int
) -> tuple[tuple[Candidate, float], ...]:
    """Use RRF k=60; path and ordinal make ties reproducible."""
    scores: dict[tuple[str, int], float] = {}
    candidates: dict[tuple[str, int], Candidate] = {}
    for ranked in (vector[:50], lexical[:50]):
        seen: set[tuple[str, int]] = set()
        for rank, candidate in enumerate(ranked, 1):
            key = (candidate.path, candidate.ordinal)
            if key in seen:
                continue
            seen.add(key)
            candidates[key] = candidate
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    keys = sorted(scores, key=lambda key: (-scores[key], key[0], key[1]))[:top_k]
    return tuple((candidates[key], scores[key]) for key in keys)

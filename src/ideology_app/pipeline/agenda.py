"""The Party-balanced Agenda: which candidates ``generate_statements`` sees.

Pure and deterministic: no database, no LLM, no clock, no randomness and no
iteration over unordered sets. Depends only on ``pipeline.prompts``.

Every Party contributes the same number of candidates (the quota), whatever the
length of its manifesto; a Party with fewer unique candidates than the quota
contributes all it has and nothing is invented for it. Within a Party, picks go
round-robin over the topics its own manifesto treats most. The union is sorted
by ``(topic, text)``, so the reduce prompt carries no Party id, name or order.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import ceil
from typing import Any

from ideology_app.pipeline.prompts import TOPICS, StatementDraft

AGENDA_VERSION = "v1"
# The most candidates any Party contributes (keeps the reduce input focused).
PARTY_QUOTA_MAX = 24

_TOPIC_INDEX = {topic: index for index, topic in enumerate(TOPICS)}


@dataclass(frozen=True)
class Agenda:
    """The balanced candidates for ``generate_statements`` and their audit report."""

    candidates: tuple[StatementDraft, ...]  # union of picks, deduped, sorted by (topic, text)
    quota: int
    report: dict[str, Any]  # JSON-serialisable, stored in ``statement_selection["agenda"]``


@dataclass(frozen=True)
class _Unique:
    topic: str
    text: str
    chunk: int  # 0-based index among the Party's chunks where it first appeared
    rank: int  # index in that chunk's output


@dataclass
class _PartyInput:
    chunks: int = 0
    candidates: int = 0
    unique: list[_Unique] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)  # membership only


def _spread(unique: Sequence[_Unique], share: int) -> list[_Unique]:
    """Round-robin ``share`` picks over the Party's topics (its own emphasis first)."""
    by_topic: dict[str, list[_Unique]] = {}
    for item in unique:
        by_topic.setdefault(item.topic, []).append(item)

    def topic_key(topic: str) -> tuple[int, int, int, int]:
        items = by_topic[topic]
        first = min((i.chunk, i.rank) for i in items)
        return (-len(items), first[0], first[1], _TOPIC_INDEX[topic])

    ordered = [
        sorted(by_topic[topic], key=lambda i: (i.rank, i.chunk))
        for topic in sorted(by_topic, key=topic_key)
    ]
    picks: list[_Unique] = []
    round_index = 0
    while len(picks) < share:
        for items in ordered:
            if round_index < len(items):
                picks.append(items[round_index])
                if len(picks) == share:
                    break
        round_index += 1
    return picks


def balance_candidates(
    per_chunk: Sequence[tuple[int, Sequence[StatementDraft]]], pool_max: int
) -> Agenda:
    """Choose the same number of candidates from every Party.

    ``per_chunk`` is ``(party_id, candidates of that chunk)`` in chunk order.
    Rule (``AGENDA_VERSION`` v1):

    1. Per Party, its unique ``(topic, text)`` in first-seen order, each with
       the chunk (0-based among the Party's chunks) and rank (index in that
       chunk's output) where it first appeared; ``n_p`` is their count.
    2. ``P`` is the number of Parties with ``n_p >= 1`` and
       ``quota = max(ceil(pool_max / P), min(PARTY_QUOTA_MAX, min n_p))``.
       Each Party contributes ``min(n_p, quota)``.
    3. Within a Party, topics are ordered by candidate count (most first), then
       first appearance ``(chunk, rank)``, then ``TOPICS`` order; within a
       topic by ``(rank, chunk)``. Picks go round-robin over those topics.
    4. The picks of all Parties are deduplicated and sorted by ``(topic, text)``.

    The report lists every Party seen in ``per_chunk``, in Party-id order.
    """
    parties: dict[int, _PartyInput] = {}
    for party_id, candidates in per_chunk:
        party = parties.setdefault(party_id, _PartyInput())
        for rank, candidate in enumerate(candidates):
            party.candidates += 1
            key = (candidate.topic, candidate.text)
            if key not in party.seen:
                party.seen.add(key)
                party.unique.append(_Unique(candidate.topic, candidate.text, party.chunks, rank))
        party.chunks += 1

    counts = [len(p.unique) for p in parties.values() if p.unique]
    if counts:
        floor = ceil(pool_max / len(counts))
        quota = max(floor, min(PARTY_QUOTA_MAX, min(counts)))
    else:
        floor = 0
        quota = 0

    picked: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for party_id in sorted(parties):
        party = parties[party_id]
        unique = party.unique
        picks = _spread(unique, min(len(unique), quota))
        picked.update((p.topic, p.text) for p in picks)
        rows.append(
            {
                "party_id": party_id,
                "chunks": party.chunks,
                "candidates": party.candidates,
                "unique": len(unique),
                "picked": len(picks),
            }
        )

    lines = sorted(picked)
    report: dict[str, Any] = {
        "version": AGENDA_VERSION,
        "pool_max": pool_max,
        "floor": floor,
        "quota_max": PARTY_QUOTA_MAX,
        "quota": quota,
        "lines": len(lines),
        "parties": rows,
    }
    return Agenda(
        candidates=tuple(StatementDraft(topic=topic, text=text) for topic, text in lines),
        quota=quota,
        report=report,
    )


__all__ = ["AGENDA_VERSION", "PARTY_QUOTA_MAX", "Agenda", "balance_candidates"]

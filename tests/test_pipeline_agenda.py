"""The Party-balanced Agenda (pipeline-balanced-statements, scenarios 1-4)."""

from collections.abc import Sequence
from typing import Any

import pytest
from pipeline_fixtures import PARTIES, fake_provider, offline_guard

from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.pipeline import (
    AGENDA_VERSION,
    NO_CANDIDATES_REASON,
    PARTY_QUOTA_MAX,
    TOPICS,
    Chunk,
    GenerationError,
    StatementDraft,
    Usage,
    balance_candidates,
    generate_statements,
    request_hash,
)
from ideology_app.pipeline.generation import reduce_request


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


PerChunk = list[tuple[int, list[StatementDraft]]]


def draft(text: str, topic: str = "economy") -> StatementDraft:
    return StatementDraft(text=text, topic=topic)


def party_chunks(party_id: int, sizes: Sequence[int], tag: str | None = None) -> PerChunk:
    """One Party's chunk outputs with distinct candidates (``sizes`` per chunk)."""
    tag = tag or "abcdefghijklmnopqrstuvwxyz"[party_id]
    out: PerChunk = []
    for chunk, size in enumerate(sizes):
        out.append(
            (
                party_id,
                [
                    draft(
                        f"Propuesta {tag} fragmento {chunk} número {rank}.",
                        TOPICS[(chunk * 12 + rank) % len(TOPICS)],
                    )
                    for rank in range(size)
                ],
            )
        )
    return out


def flat(n: int) -> list[int]:
    """Chunk sizes of 12 (the last one shorter) summing to ``n``."""
    sizes = [12] * (n // 12)
    if n % 12:
        sizes.append(n % 12)
    return sizes


# Run 1 shape: unique candidates and chunks per Party (PP .. BNG).
RUN1_UNIQUE = (72, 216, 60, 228, 144, 108, 12, 48, 47)
RUN1_CHUNKS = (6, 19, 5, 19, 12, 9, 1, 4, 4)


def split(n: int, chunks: int) -> list[int]:
    """``n`` candidates over ``chunks`` chunks, as evenly as possible."""
    base, extra = divmod(n, chunks)
    return [base + 1] * extra + [base] * (chunks - extra)


def run1_per_chunk() -> PerChunk:
    per_chunk: PerChunk = []
    for party_id, (unique, chunks) in enumerate(zip(RUN1_UNIQUE, RUN1_CHUNKS), start=1):
        sizes = split(unique, chunks)
        assert max(sizes) <= 12
        per_chunk.extend(party_chunks(party_id, sizes))
    return per_chunk


def picks_of(agenda_lines: Sequence[StatementDraft], per_chunk: PerChunk, party_id: int) -> set:
    own = {(c.topic, c.text) for p, cs in per_chunk if p == party_id for c in cs}
    return {(c.topic, c.text) for c in agenda_lines} & own


# Scenario 1: equal quota


def test_run1_shape_gives_quota_12_and_108_lines() -> None:
    per_chunk = run1_per_chunk()
    assert [sum(1 for p, _ in per_chunk if p == i) for i in range(1, 10)] == list(RUN1_CHUNKS)
    agenda = balance_candidates(per_chunk, pool_max=60)
    assert agenda.quota == max(7, min(PARTY_QUOTA_MAX, 12)) == 12
    assert len(agenda.candidates) == 108
    for party_id in range(1, 10):
        assert len(picks_of(agenda.candidates, per_chunk, party_id)) == 12
    assert agenda.report == {
        "version": AGENDA_VERSION,
        "pool_max": 60,
        "floor": 7,
        "quota_max": 24,
        "quota": 12,
        "lines": 108,
        "parties": [
            {
                "party_id": i,
                "chunks": RUN1_CHUNKS[i - 1],
                "candidates": RUN1_UNIQUE[i - 1],
                "unique": RUN1_UNIQUE[i - 1],
                "picked": 12,
            }
            for i in range(1, 10)
        ],
    }


def test_two_large_parties_get_the_floor() -> None:
    per_chunk = party_chunks(1, flat(100)) + party_chunks(2, flat(100))
    agenda = balance_candidates(per_chunk, pool_max=60)
    assert agenda.quota == max(30, 24) == 30
    assert [p["picked"] for p in agenda.report["parties"]] == [30, 30]
    assert agenda.report["lines"] == 60


def test_three_parties_with_a_short_one() -> None:
    per_chunk = party_chunks(1, flat(36)) + party_chunks(2, flat(24)) + party_chunks(3, flat(12))
    agenda = balance_candidates(per_chunk, pool_max=60)
    assert agenda.quota == max(20, 12) == 20
    assert [p["picked"] for p in agenda.report["parties"]] == [20, 20, 12]
    assert len(agenda.candidates) == 52


def test_quota_is_capped_at_party_quota_max() -> None:
    per_chunk = [x for i in range(1, 10) for x in party_chunks(i, flat(200))]
    agenda = balance_candidates(per_chunk, pool_max=60)
    assert agenda.quota == PARTY_QUOTA_MAX == 24
    assert len(agenda.candidates) == 9 * 24


# Scenario 2: shortfall, nothing invented


def test_party_with_zero_candidates_is_listed_and_not_counted() -> None:
    per_chunk = party_chunks(1, flat(30)) + [(2, []), (2, [])] + party_chunks(3, flat(30))
    agenda = balance_candidates(per_chunk, pool_max=60)
    # P = 2 (Party 2 has none): floor 30, quota max(30, 24) = 30.
    assert agenda.report["floor"] == 30
    assert agenda.quota == 30
    rows = {p["party_id"]: p for p in agenda.report["parties"]}
    assert rows[2] == {"party_id": 2, "chunks": 2, "candidates": 0, "unique": 0, "picked": 0}
    assert rows[1]["picked"] == rows[3]["picked"] == 30


def test_short_party_contributes_all_it_has_and_no_others() -> None:
    per_chunk = party_chunks(1, flat(50)) + party_chunks(2, [3])
    agenda = balance_candidates(per_chunk, pool_max=60)
    assert agenda.quota == 30
    assert picks_of(agenda.candidates, per_chunk, 2) == {
        (c.topic, c.text) for c in per_chunk[-1][1]
    }
    every = {(c.topic, c.text) for _, cs in per_chunk for c in cs}
    assert {(c.topic, c.text) for c in agenda.candidates} <= every


def test_every_party_empty_gives_an_empty_agenda() -> None:
    agenda = balance_candidates([(1, []), (2, [])], pool_max=60)
    assert agenda.candidates == ()
    assert agenda.quota == 0
    assert [p["picked"] for p in agenda.report["parties"]] == [0, 0]


def test_every_party_empty_raises_before_the_reduce_call() -> None:
    provider = fake_provider(statement_candidates={"candidates": []})
    chunks = [Chunk(1, 1, "uno"), Chunk(2, 2, "dos")]
    with pytest.raises(GenerationError, match=NO_CANDIDATES_REASON):
        generate_statements(provider, chunks, Usage())
    assert [c.task for c in provider.calls] == ["statement_candidates"] * 2


def test_duplicates_within_a_party_count_once_and_across_parties_merge() -> None:
    same = [draft("Común.", "housing"), draft("Común.", "housing"), draft("Solo uno.", "health")]
    per_chunk: PerChunk = [(1, same), (2, [draft("Común.", "housing")])]
    # P = 2, floor 2, quota max(2, 1) = 2: Party 1 gives both, Party 2 its one.
    agenda = balance_candidates(per_chunk, pool_max=4)
    rows = agenda.report["parties"]
    assert (rows[0]["candidates"], rows[0]["unique"]) == (3, 2)
    assert [(c.topic, c.text) for c in agenda.candidates] == [
        ("health", "Solo uno."),
        ("housing", "Común."),
    ]
    assert agenda.report["lines"] == 2


# Scenario 3: even spread over the Party's own topics


SPREAD_PARTY = [
    (1, [draft("A", "housing"), draft("B", "health"), draft("C", "housing"), draft("D", "economy")]),
    (1, [draft("E", "health"), draft("F", "economy"), draft("G", "housing"), draft("H", "taxation")]),
]
# Topic order: housing (3), health (2, first at chunk 0 rank 1), economy (2, first
# at chunk 0 rank 3), taxation (1). Within a topic by (rank, chunk): housing A, C,
# G; health E, B; economy F, D. Round robin: A E F H, then C B D, then G.
SPREAD_ORDER = ["A", "E", "F", "H", "C", "B", "D", "G"]


@pytest.mark.parametrize("share", range(1, 9))
def test_round_robin_over_topics_by_party_emphasis(share: int) -> None:
    # Party 2 sets the quota: share = min(24, n_2) with pool_max 1.
    other = (2, [draft(f"Otra {i}.", "pensions") for i in range(share)])
    agenda = balance_candidates([*SPREAD_PARTY, other], pool_max=1)
    assert agenda.quota == share
    picked = {c.text for c in agenda.candidates if c.topic != "pensions"}
    assert picked == set(SPREAD_ORDER[:share])


def test_topic_ties_break_by_first_appearance() -> None:
    # economy and health both have 1 candidate; health appears first.
    party = [(1, [draft("H1", "health"), draft("E1", "economy")])]
    other = (2, [draft("Otra.", "pensions")])
    agenda = balance_candidates([*party, other], pool_max=1)
    assert {c.text for c in agenda.candidates} == {"H1", "Otra."}


# Scenario 4: deterministic and Party-symmetric


def test_same_outputs_give_a_byte_identical_reduce_request() -> None:
    first = reduce_request(balance_candidates(run1_per_chunk(), 60).candidates)
    second = reduce_request(balance_candidates(run1_per_chunk(), 60).candidates)
    assert request_hash("fake", "m", first) == request_hash("fake", "m", second)


def _relabel(per_chunk: PerChunk, mapping: dict[int, int]) -> PerChunk:
    return [(mapping[p], cs) for p, cs in per_chunk]


@pytest.mark.parametrize(
    "mapping",
    [
        {1: 9, 2: 8, 3: 7, 4: 6, 5: 5, 6: 4, 7: 3, 8: 2, 9: 1},
        {1: 3, 2: 1, 3: 2, 4: 5, 5: 4, 6: 9, 7: 6, 8: 7, 9: 8},
    ],
    ids=["reversed", "shuffled"],
)
def test_permuting_party_ids_leaves_the_request_identical(mapping: dict[int, int]) -> None:
    base = run1_per_chunk()
    # Keep chunk order grouped by Party id, as build_document_chunks does.
    permuted = sorted(_relabel(base, mapping), key=lambda item: item[0])
    a = balance_candidates(base, 60)
    b = balance_candidates(permuted, 60)
    assert request_hash("fake", "m", reduce_request(a.candidates)) == request_hash(
        "fake", "m", reduce_request(b.candidates)
    )
    rows_a = {mapping[r["party_id"]]: r for r in a.report["parties"]}
    for row in b.report["parties"]:
        assert {**rows_a[row["party_id"]], "party_id": row["party_id"]} == row
    strip = lambda r: {k: v for k, v in r.items() if k != "parties"}  # noqa: E731
    assert strip(a.report) == strip(b.report)


def _per_chunk_fake(outputs: dict[str, list[StatementDraft]]) -> FakeProvider:
    """A fake that answers each chunk (found by its unique text) with its outputs."""

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        for key, drafts in outputs.items():
            if key in request.prompt:
                return {"candidates": [d.model_dump() for d in drafts]}
        raise AssertionError("unknown chunk")

    return fake_provider(statement_candidates=_respond)


def test_generation_feeds_the_agenda_to_the_reduce_without_party_labels() -> None:
    per_chunk = run1_per_chunk()
    chunks: list[Chunk] = []
    outputs: dict[str, list[StatementDraft]] = {}
    for index, (party_id, drafts) in enumerate(per_chunk):
        text = f"[página 1]\nFragmento ‹{index:03d}›"
        chunks.append(Chunk(party_id=party_id, document_id=party_id, text=text))
        outputs[f"‹{index:03d}›"] = drafts
    provider = _per_chunk_fake(outputs)
    usage = Usage()
    pool = generate_statements(provider, chunks, usage)

    assert usage.calls == len(chunks) + 1 == 80  # the map + reduce formula
    reduce = provider.calls[-1]
    assert reduce.task == "generate_statements"
    assert reduce.prompt.count("\n- [") == 108
    assert reduce.prompt == reduce_request(pool.agenda.candidates).prompt
    assert pool.agenda.report["quota"] == 12
    assert [p["picked"] for p in pool.agenda.report["parties"]] == [12] * 9
    for name, short in PARTIES:
        assert name not in reduce.system + reduce.prompt
        assert short not in reduce.system + reduce.prompt
    assert "party" not in reduce.prompt.lower() and "partido" not in reduce.prompt.lower()

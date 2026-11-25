"""Conflict entries of the Ingestion Ledger (proposal-conflicts scenarios 1, 2, 5, 7, 8, 10).

Pure tests: bundles in ``tmp_path``, no database and no LLM. Checks are
recorded through ``record_conflict_check_in_dir`` as ``conflicts detect`` does.

- ``P`` runs in 28 and 31 and lists ``a.md`` (all) and ``b.md`` (28): one overlap in 28.
- ``Q`` runs in 08 and 28 with ``q1.md`` (08) and ``q2.md`` (28): disjoint, no overlap.
- ``R`` lists only ``r.md``; ``S`` lists ``s1.md`` and ``s2.md``, and ``s2.md`` is discarded.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from bundle_factory import CandidatureSpec, DocumentSpec, write_bundle, write_bundle_v2

from ideology_app import ingestion_ledger as ledgers
from ideology_app.ingestion_ledger import (
    LEDGER_NAME,
    NOT_CANONICAL,
    ConflictCheck,
    ConflictStatus,
    Contradiction,
    LedgerError,
    Phase4Blocked,
)
from ideology_app.source_bundle import read_bundle

P = CandidatureSpec("P", "Partido P", ["28", "31"])
Q = CandidatureSpec("Q", "Partido Q", ["08", "28"])
R = CandidatureSpec("R", "Partido R", ["01"])
S = CandidatureSpec("S", "Partido S", ["02"])
DOC_A = DocumentSpec("a.md", "P", ["Programa nacional de P."], ["P"])
DOC_B = DocumentSpec("b.md", "P", ["Programa regional de P."], ["P"], ["28"])
DOC_Q1 = DocumentSpec("q1.md", "Q", ["Programa de Q en 08."], ["Q"], ["08"])
DOC_Q2 = DocumentSpec("q2.md", "Q", ["Programa de Q en 28."], ["Q"], ["28"])
DOC_R = DocumentSpec("r.md", "R", ["Programa de R."], ["R"])
DOC_S1 = DocumentSpec("s1.md", "S", ["Programa de S."], ["S"])
DOC_S2 = DocumentSpec("s2.md", "S", ["Anexo de S."], ["S"])
PARTIES = [P, Q, R, S]
DOCUMENTS = [DOC_A, DOC_B, DOC_Q1, DOC_Q2, DOC_R, DOC_S1, DOC_S2]
COUNTS = {"a.md": 40, "b.md": 7, "q1.md": 3, "q2.md": 3, "r.md": 3, "s1.md": 3}
CHECK = ConflictCheck("fake", "fake-model", "v1", 2)
FLAGGED = [Contradiction((40, 7), "housing", "A baja el alquiler y B lo congela.")]


def write(root: Path, documents: list[DocumentSpec] = DOCUMENTS, parties=PARTIES) -> Path:
    return write_bundle_v2(root / "data" / "elections", parties, documents)


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return write(tmp_path)


def _hash(directory: Path, file: str) -> str:
    return ledgers.listed_document(read_bundle(directory), file).text.content_hash


def _ready(directory: Path, counts: dict[str, int] = COUNTS) -> None:
    """Review every document kept (s2.md discarded) and record the counts (N = 3)."""
    ledgers.update_in_dir(directory, min_proposals=3)
    for document in read_bundle(directory).documents:
        if document.file == "s2.md":
            ledgers.review_in_dir(directory, "s2.md", decision="discarded", reason="incomplete")
        else:
            ledgers.review_in_dir(directory, document.file, decision="kept")
    for file, count in counts.items():
        ledgers.record_extraction_in_dir(
            directory, file, content_hash=_hash(directory, file), validated_proposals=count
        )


def _record(directory: Path, contradictions=(), check: ConflictCheck = CHECK, party: str = "P",
            files=("a.md", "b.md")) -> tuple[ledgers.Ledger, list[str]]:
    _, ledger, lines = ledgers.record_conflict_check_in_dir(
        directory,
        party,
        list(files),
        content_hashes=[_hash(directory, f) for f in files],
        check=check,
        contradictions=list(contradictions),
    )
    return ledger, lines


def _decide(directory: Path, prevails: str = "a.md", over: str = "b.md",
            reason: str = "El programa nacional manda.") -> tuple[ledgers.Ledger, list[str]]:
    _, ledger, lines = ledgers.decide_conflict_in_dir(
        directory, "P", prevails=prevails, over=over, reason=reason
    )
    return ledger, lines


def _entry(directory: Path) -> ledgers.ConflictEntry:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return ledger.conflict("P", ["b.md", "a.md"])


# --- Scenario 1: overlap derivation --------------------------------------------------------


def test_overlap_derivation(directory: Path, tmp_path: Path) -> None:
    ledgers.update_in_dir(directory, min_proposals=3)
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    _, ledger, lines = ledgers.review_in_dir(directory, "b.md", decision="kept")
    assert lines == [
        "Document b.md: kept",
        "Party P: candidature_declared -> manifesto_reviewed",
        "Conflict P a.md + b.md (28): added (unchecked)",
    ]
    _ready(directory)
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert ledger.conflicts == (
        ledgers.ConflictEntry(
            "P", ("a.md", "b.md"), (_hash(directory, "a.md"), _hash(directory, "b.md")), ("28",)
        ),
    )
    obj = json.loads((directory / LEDGER_NAME).read_bytes())
    assert obj["format"] == 2
    assert list(obj["conflicts"][0]) == [
        "party", "files", "content_hashes", "constituencies", "joint", "check",
        "contradictions", "status", "prevails", "reason",
    ]
    assert obj["conflicts"][0]["status"] == "unchecked"

    # Reordering [[documents]] keeps the entry (files sorted by name).
    write(tmp_path, [DOC_B, DOC_A, DOC_Q1, DOC_Q2, DOC_R, DOC_S1, DOC_S2])
    _, reordered, lines = ledgers.update_in_dir(directory)
    assert reordered.conflicts == ledger.conflicts
    assert lines == ["Ledger: entries reordered to follow election.toml"]


def test_three_documents_give_every_intersecting_pair(tmp_path: Path) -> None:
    doc_c = DocumentSpec("c.md", "P", ["Tercer programa."], ["P"], ["31"])
    directory = write(tmp_path, [DOC_B, DOC_A, doc_c])
    ledgers.update_in_dir(directory)
    for file in ("a.md", "b.md", "c.md"):
        ledgers.review_in_dir(directory, file, decision="kept")
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert [(c.files, c.constituencies) for c in ledger.conflicts] == [
        (("a.md", "b.md"), ("28",)),
        (("a.md", "c.md"), ("31",)),
    ]


# --- Scenario 2: the gate ---------------------------------------------------------------------


def test_unchecked_and_pending_block_the_gate(directory: Path) -> None:
    _ready(directory)
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == (
        f'conflict pending: P: a.md + b.md (28): not checked; run "ideology conflicts detect '
        f'{directory}"',
    )
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert ledgers.pending_conflicts(ledger) == (
        'P: a.md + b.md (28): not checked; run "ideology conflicts detect DIR"',
    )

    ledger, lines = _record(directory, FLAGGED)
    assert lines == [
        "Conflict P a.md + b.md: checked (1 contradictions, 2 calls)",
        "Conflict P a.md + b.md: unchecked -> pending",
    ]
    assert ledgers.pending_conflicts(ledger) == (
        'P: a.md + b.md (28): 1 contradictions; run "ideology conflicts decide DIR P '
        '--prevails FILE --over FILE --reason TEXT"',
    )
    with pytest.raises(Phase4Blocked):
        ledgers.require_phase4_ready(directory)

    ledger, lines = _decide(directory)
    assert lines == [
        "Conflict P a.md + b.md: a.md prevails over b.md (El programa nacional manda.)",
        "Conflict P a.md + b.md: pending -> decided",
    ]
    entry = ledger.conflicts[0]
    assert (entry.status, entry.prevails, entry.reason, entry.loser) == (
        ConflictStatus.DECIDED, "a.md", "El programa nacional manda.", "b.md"
    )
    assert ledgers.require_phase4_ready(directory) == ledger


def test_no_contradiction_opens_the_gate(directory: Path) -> None:
    _ready(directory)
    ledger, lines = _record(directory)
    assert lines[-1] == "Conflict P a.md + b.md: unchecked -> no_contradiction"
    assert ledger.conflicts[0].status is ConflictStatus.NO_CONTRADICTION
    assert ledger.conflicts[0].check == CHECK
    assert ledgers.require_phase4_ready(directory) == ledger


def test_an_excluded_party_does_not_block(directory: Path) -> None:
    _ready(directory, {**COUNTS, "a.md": 1, "b.md": 1})  # P: 2 < 3
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert ledger.party("P").reason is ledgers.ExclusionReason.TOO_FEW_PROPOSALS
    assert ledger.conflicts[0].status is ConflictStatus.UNCHECKED
    assert ledgers.pending_conflicts(ledger) == ()
    assert ledgers.require_phase4_ready(directory) == ledger


# --- Scenario 5: joint manifesto ------------------------------------------------------------


def _joint(tmp_path: Path, *joint: str) -> Path:
    docs = [
        DocumentSpec(d.file, d.party, d.pages, d.parties, d.constituencies,
                     joint_for=["P"] if d.file in joint else None)
        for d in DOCUMENTS
    ]
    return write(tmp_path, docs)


def test_joint_manifesto_prevails_without_an_operator_step(tmp_path: Path) -> None:
    directory = _joint(tmp_path, "b.md")
    _ready(directory)
    assert _entry(directory).joint == "b.md"
    assert _entry(directory).status is ConflictStatus.UNCHECKED
    with pytest.raises(Phase4Blocked):
        ledgers.require_phase4_ready(directory)

    ledger, lines = _record(directory, FLAGGED)
    entry = ledger.conflicts[0]
    assert lines[-1] == "Conflict P a.md + b.md: unchecked -> joint_manifesto"
    assert (entry.status, entry.prevails, entry.reason, entry.loser) == (
        ConflictStatus.JOINT_MANIFESTO, "b.md", None, "a.md"
    )
    assert ledgers.require_phase4_ready(directory) == ledger
    before = (directory / LEDGER_NAME).read_bytes()
    with pytest.raises(LedgerError, match="the joint manifesto b.md prevails automatically"):
        _decide(directory)
    assert (directory / LEDGER_NAME).read_bytes() == before


def test_both_joint_goes_to_the_operator(tmp_path: Path) -> None:
    directory = _joint(tmp_path, "a.md", "b.md")
    _ready(directory)
    ledger, _ = _record(directory, FLAGGED)
    assert (ledger.conflicts[0].joint, ledger.conflicts[0].status) == (None, ConflictStatus.PENDING)


def test_marking_a_joint_manifesto_clears_a_decision(directory: Path, tmp_path: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    _decide(directory)
    _joint(tmp_path, "b.md")
    _, ledger, lines = ledgers.update_in_dir(directory)
    assert lines == [
        "Conflict P a.md + b.md: decision cleared (joint manifesto b.md prevails)",
        "Conflict P a.md + b.md: joint manifesto none -> b.md",
        "Conflict P a.md + b.md: decided -> joint_manifesto",
    ]
    assert (ledger.conflicts[0].prevails, ledger.conflicts[0].reason) == ("b.md", None)
    assert ledger.conflicts[0].check == CHECK


# --- Scenario 7: refusals ---------------------------------------------------------------------


def test_decide_refusals_leave_the_ledger_byte_identical(directory: Path, tmp_path: Path) -> None:
    _ready(directory)
    path = directory / LEDGER_NAME
    before = path.read_bytes()

    def refused(match: str, **kwargs: Any) -> None:
        args = {"prevails": "a.md", "over": "b.md", "reason": "Motivo."} | kwargs
        party = args.pop("party", "P")
        with pytest.raises(LedgerError, match=match):
            ledgers.decide_conflict_in_dir(directory, party, **args)
        assert path.read_bytes() == current

    current = before
    refused("is not checked yet")
    _record(directory)
    current = path.read_bytes()
    refused("has no contradiction")

    path.write_bytes(before)
    _record(directory, FLAGGED)
    current = path.read_bytes()
    refused("party 'Z' is not in election.toml", party="Z")
    refused("party Q has no overlap between q1.md and q2.md", party="Q", prevails="q1.md",
            over="q2.md")
    refused("party P has no overlap between a.md and r.md", over="r.md")
    refused("two different files", over="a.md")
    refused("reason must not be empty", reason="  ")
    refused("reason must be a single line", reason="una\nlínea")
    refused("reason must be at most 500", reason="x" * 501)
    refused("a decision needs a reason", reason=None)

    write(tmp_path, [DOC_A, DOC_B, DOC_Q1, DOC_Q2, DOC_R, DOC_S1])  # s2.md removed
    (directory / "s2.md").unlink()
    refused(r"ingestion ledger is out of date: Document s2.md: removed")


def test_decide_refuses_a_missing_ledger_and_a_format_1_bundle(directory: Path, tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="no ingestion ledger yet"):
        ledgers.decide_conflict_in_dir(directory, "P", prevails="a.md", over="b.md", reason="x")
    assert not (directory / LEDGER_NAME).exists()
    legacy = write_bundle(tmp_path / "legacy")
    with pytest.raises(LedgerError, match="needs a format-2 election.toml"):
        ledgers.decide_conflict_in_dir(legacy, "PP", prevails="a.md", over="b.md", reason="x")


def test_re_deciding_overwrites(directory: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    _decide(directory)
    ledger, lines = _decide(directory, "b.md", "a.md", "El regional es más reciente.")
    assert lines == [
        "Conflict P a.md + b.md: b.md prevails over a.md (El regional es más reciente.) "
        "(was a.md: El programa nacional manda.)"
    ]
    assert (ledger.conflicts[0].prevails, ledger.conflicts[0].loser) == ("b.md", "a.md")
    assert _decide(directory, "b.md", "a.md", " El regional es más reciente. ")[1] == []


def test_record_check_refusals(directory: Path) -> None:
    _ready(directory)
    path = directory / LEDGER_NAME
    before = path.read_bytes()
    hashes = [_hash(directory, "a.md"), _hash(directory, "b.md")]

    def refused(match: str, **kwargs: Any) -> None:
        args: dict[str, Any] = {
            "party": "P", "files": ["a.md", "b.md"], "content_hashes": hashes,
            "check": CHECK, "contradictions": FLAGGED,
        } | kwargs
        with pytest.raises(LedgerError, match=match):
            ledgers.record_conflict_check_in_dir(
                directory, args.pop("party"), args.pop("files"), **args
            )
        assert path.read_bytes() == before

    refused("content hashes are stale", content_hashes=[hashes[0], "0" * 64])
    refused("files must be sorted", files=["b.md", "a.md"])
    refused("party P has no overlap between a.md and r.md", files=["a.md", "r.md"])
    refused("Proposal ordinal 41 of a.md must be between 1 and 40",
            contradictions=[Contradiction((41, 1), "housing", "x")])
    refused("Proposal ordinal 0 of b.md", contradictions=[Contradiction((1, 0), "housing", "x")])
    refused("unknown category 'weather'", contradictions=[Contradiction((1, 1), "weather", "x")])
    refused("explanation must be a single line",
            contradictions=[Contradiction((1, 1), "housing", "a\nb")])
    refused("listed twice", contradictions=[Contradiction((1, 1), "housing", "x")] * 2)
    refused("check calls must be an integer", check=ConflictCheck("fake", "m", "v1", -1))
    refused("check model must be a non-empty string", check=ConflictCheck("fake", "", "v1", 1))

    _record(directory, FLAGGED)
    assert _record(directory, FLAGGED)[1] == []
    with pytest.raises(LedgerError, match="is already checked"):
        _record(directory)


def test_record_check_needs_both_counts(tmp_path: Path) -> None:
    directory = write(tmp_path)
    _ready(directory, {k: v for k, v in COUNTS.items() if k != "b.md"})
    with pytest.raises(LedgerError, match="document b.md has no validated Proposal count"):
        _record(directory)


# --- Scenario 8: staleness ------------------------------------------------------------------


def test_changed_content_clears_check_and_decision(directory: Path, tmp_path: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    _decide(directory)
    changed = DocumentSpec("b.md", "P", ["Programa regional de P, versión 2."], ["P"], ["28"])
    write(tmp_path, [DOC_A, changed, DOC_Q1, DOC_Q2, DOC_R, DOC_S1, DOC_S2])

    _, ledger, lines = ledgers.update_in_dir(directory)

    assert lines == [
        "Document b.md: review cleared (content changed)",
        "Document b.md: proposals cleared (content changed)",
        "Conflict P a.md + b.md: check cleared (content changed)",
        "Conflict P a.md + b.md: decision cleared (content changed)",
        "Party P: proposals_extracted (47 proposals) -> candidature_declared",
        "Conflict P a.md + b.md: removed (no longer an overlap)",
    ]
    assert ledger.conflicts == ()
    # The re-reviewed file overlaps again, unchecked.
    _, ledger, lines = ledgers.review_in_dir(directory, "b.md", decision="kept")
    assert lines[-1] == "Conflict P a.md + b.md (28): added (unchecked)"
    assert ledger.conflicts[0].check is None
    assert ledger.conflicts[0].content_hashes[1] == _hash(directory, "b.md")


def test_changed_constituencies_keep_check_and_decision(directory: Path, tmp_path: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    _decide(directory)
    wider = DocumentSpec("b.md", "P", DOC_B.pages, ["P"], ["28", "31"])
    write(tmp_path, [DOC_A, wider, DOC_Q1, DOC_Q2, DOC_R, DOC_S1, DOC_S2])

    _, ledger, lines = ledgers.update_in_dir(directory)

    assert lines == ["Conflict P a.md + b.md: constituencies 28 -> 28, 31"]
    entry = ledger.conflicts[0]
    assert (entry.constituencies, entry.status, entry.check) == (
        ("28", "31"), ConflictStatus.DECIDED, CHECK
    )


def test_discarding_a_document_removes_its_overlap(directory: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    _, ledger, lines = ledgers.review_in_dir(
        directory, "b.md", decision="discarded", reason="incomplete"
    )
    assert lines[-1] == "Conflict P a.md + b.md: removed (no longer an overlap)"
    assert ledger.conflicts == ()


def test_out_of_date_conflict_is_a_ledger_problem(directory: Path, tmp_path: Path) -> None:
    _ready(directory)
    _record(directory, FLAGGED)
    wider = DocumentSpec("b.md", "P", DOC_B.pages, ["P"], ["28", "31"])
    write(tmp_path, [DOC_A, wider, DOC_Q1, DOC_Q2, DOC_R, DOC_S1, DOC_S2])
    assert ledgers.ledger_problems(read_bundle(directory)) == [
        "ingestion ledger is out of date: Conflict P a.md + b.md: constituencies 28 -> 28, 31; "
        f'run "ideology ingestion update {directory}"'
    ]


# --- Scenario 10: ledger format ---------------------------------------------------------------


def _canonical(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def test_format_1_ledger_is_read_and_upgraded(directory: Path) -> None:
    ledgers.update_in_dir(directory, min_proposals=3)
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    path = directory / LEDGER_NAME
    obj = json.loads(path.read_bytes())
    obj["format"] = 1
    path.write_bytes(_canonical(obj))

    ledger = ledgers.read_ledger(directory)
    assert ledger is not None and ledger.format == 1 and ledger.conflicts == ()
    assert ledgers.render_ledger(ledger) == path.read_bytes()
    bundle = read_bundle(directory)
    assert ledgers.ledger_problems(bundle) == [
        f'ingestion ledger is out of date: Ledger: format 1 -> 2; run "ideology ingestion '
        f'update {directory}"'
    ]
    with pytest.raises(LedgerError, match="out of date: Ledger: format 1 -> 2"):
        ledgers.decide_conflict_in_dir(directory, "P", prevails="a.md", over="b.md", reason="x")

    _, upgraded, lines = ledgers.update_in_dir(directory)
    assert lines == ["Ledger: format 1 -> 2"]
    assert upgraded.format == 2
    assert json.loads(path.read_bytes())["format"] == 2

    # A format-1 ledger with both of P's documents kept gains the overlap.
    ledgers.review_in_dir(directory, "b.md", decision="kept")
    obj = json.loads(path.read_bytes())
    obj["format"], obj["conflicts"] = 1, []
    path.write_bytes(_canonical(obj))
    _, _, lines = ledgers.update_in_dir(directory)
    assert lines == ["Ledger: format 1 -> 2", "Conflict P a.md + b.md (28): added (unchecked)"]

    obj["conflicts"] = [{"party": "P"}]
    path.write_bytes(_canonical(obj))
    with pytest.raises(LedgerError, match="conflicts: must be empty in ledger format 1"):
        ledgers.read_ledger(directory)


def _decided_obj(directory: Path) -> dict:
    _ready(directory)
    _record(directory, FLAGGED + [Contradiction((1, 2), "economy", "Otra.")])
    _decide(directory)
    return json.loads((directory / LEDGER_NAME).read_bytes())


_DELETE = object()

INVALID = [
    ("party", "Z", "conflicts[0].party: unknown party 'Z'"),
    ("party", "Q", "conflicts[0].files[0]: 'a.md' is not a document of Q"),
    ("files", ["b.md", "a.md"], "conflicts[0].files: must be two different files sorted"),
    ("files", ["a.md"], "conflicts[0].files: must be a list of two file names"),
    ("files", ["a.md", "z.md"], "conflicts[0].files[1]: 'z.md' is not in documents"),
    ("content_hashes", ["0" * 64, "1" * 64], "conflicts[0].content_hashes[0]: is not the"),
    ("content_hashes", ["x", "y"], "conflicts[0].content_hashes[0]: invalid content hash 'x'"),
    ("constituencies", [], "conflicts[0].constituencies: must be a non-empty sorted list"),
    ("constituencies", ["31", "28"], "conflicts[0].constituencies: must be a non-empty sorted"),
    ("constituencies", ["2"], "conflicts[0].constituencies: must be a non-empty sorted"),
    ("joint", "r.md", "conflicts[0].joint: must be null or one of the files"),
    ("status", "pending", "conflicts[0].status: must be decided, not pending"),
    ("status", "done", "conflicts[0].status: unknown conflict status 'done'"),
    ("check", None, "conflicts[0].contradictions: must be empty without a check"),
    ("check.calls", -1, "conflicts[0].check.calls: must be >= 0"),
    ("check.model", "", "conflicts[0].check.model: must be a non-empty string"),
    ("check.extra", 1, "conflicts[0].check: unknown key 'extra'"),
    ("contradictions.0.proposals", [41, 1],
     "conflicts[0].contradictions[0].proposals[0]: must be between 1 and 40"),
    ("contradictions.0.proposals", [1, 8],
     "conflicts[0].contradictions[0].proposals[1]: must be between 1 and 7"),
    ("contradictions.0.proposals", [1], "conflicts[0].contradictions[0].proposals: must be a"),
    ("contradictions.0.category", "weather",
     "conflicts[0].contradictions[0].category: unknown category 'weather'"),
    ("contradictions.0.explanation", "a\nb",
     "conflicts[0].contradictions[0].explanation: must be a single line"),
    ("contradictions.0.explanation", None,
     "conflicts[0].contradictions[0].explanation: must be a string"),
    ("contradictions.1.proposals", [1, 2],
     "conflicts[0].contradictions: must be sorted by proposals, without a duplicate pair"),
    ("prevails", "r.md", "conflicts[0].prevails: must be one of the files"),
    ("reason", "", "conflicts[0].reason: reason must not be empty"),
    ("extra", 1, "conflicts[0]: unknown key 'extra'"),
    ("reason", _DELETE, "conflicts[0]: missing key 'reason'"),
]


def _edit(obj: dict, path: str, value: object) -> None:
    target: Any = obj["conflicts"][0]
    *parents, last = path.split(".")
    for part in parents:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is _DELETE:
        del target[last]
    else:
        target[last] = value


@pytest.mark.parametrize(("path", "value", "message"), INVALID, ids=[i[2][:50] for i in INVALID])
def test_reader_refuses_a_hand_edited_entry(
    directory: Path, path: str, value: object, message: str
) -> None:
    obj = _decided_obj(directory)
    _edit(obj, path, value)
    (directory / LEDGER_NAME).write_bytes(_canonical(obj))
    with pytest.raises(LedgerError) as error:
        ledgers.read_ledger(directory)
    assert str(error.value).startswith(f"{directory / LEDGER_NAME}: {message}"), str(error.value)


def test_reader_refuses_status_and_decision_mismatches(directory: Path) -> None:
    obj = _decided_obj(directory)
    path = directory / LEDGER_NAME
    def refused(message: str, **changes: Any) -> None:
        edited = json.loads(json.dumps(obj))
        edited["conflicts"][0].update(changes)
        path.write_bytes(_canonical(edited))
        with pytest.raises(LedgerError, match=message):
            ledgers.read_ledger(directory)

    refused("reason: is required when the status is decided", reason=None)
    refused("status: must be pending, not decided", prevails=None, reason=None)
    refused("status: must be joint_manifesto, not decided", joint="b.md")
    refused("prevails: must be the joint manifesto", joint="b.md", status="joint_manifesto",
            reason=None)
    refused("reason: must be null for joint_manifesto", joint="b.md", status="joint_manifesto",
            prevails="b.md")
    refused("status: must be no_contradiction, not decided", contradictions=[])
    refused("status: must be unchecked, not decided", check=None, contradictions=[])
    duplicate = json.loads(json.dumps(obj))
    duplicate["conflicts"].append(duplicate["conflicts"][0])
    path.write_bytes(_canonical(duplicate))
    with pytest.raises(LedgerError, match=r"conflicts\[1\]: duplicate overlap P a.md \+ b.md"):
        ledgers.read_ledger(directory)


def test_reader_refuses_non_canonical_conflict_bytes(directory: Path) -> None:
    obj = _decided_obj(directory)
    path = directory / LEDGER_NAME
    canonical = path.read_bytes()
    assert canonical == _canonical(obj)
    path.write_bytes(canonical.replace(b'"status": "decided"', b'"status":  "decided"'))
    with pytest.raises(LedgerError, match=NOT_CANONICAL.split(" (")[0]):
        ledgers.read_ledger(directory)


def test_a_hand_edited_status_change_is_out_of_date(directory: Path) -> None:
    """A valid but stale entry (a reordered conflict list) is out of date, not invalid."""
    obj = _decided_obj(directory)
    obj["conflicts"][0]["constituencies"] = ["28", "31"]
    (directory / LEDGER_NAME).write_bytes(_canonical(obj))
    assert ledgers.ledger_problems(read_bundle(directory)) == [
        "ingestion ledger is out of date: Conflict P a.md + b.md: constituencies 28, 31 -> 28; "
        f'run "ideology ingestion update {directory}"'
    ]

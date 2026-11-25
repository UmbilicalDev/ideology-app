"""``ingestion_ledger`` (ingestion-ledger): transitions, read validation and the gate.

Pure tests: bundles are written in ``tmp_path`` with ``bundle_factory``; no
database and no LLM. Party ``A`` lists ``a.md``; ``B`` shares ``a.md`` (D1) and
has ``b.md``; ``C`` lists no document.
"""

import json
from pathlib import Path

import pytest
from bundle_factory import CandidatureSpec, DocumentSpec, write_bundle, write_bundle_v2

from ideology_app import ingestion_ledger as ledgers
from ideology_app.ingestion_ledger import (
    DEFAULT_MIN_PROPOSALS,
    LEDGER_NAME,
    NOT_CANONICAL,
    ExclusionReason,
    LedgerError,
    Phase,
    Phase4Blocked,
    ReviewDecision,
)
from ideology_app.source_bundle import Bundle, read_bundle

PARTY_A = CandidatureSpec("A", "Partido A", "all")
PARTY_B = CandidatureSpec("B", "Partido B", ["28"])
PARTY_C = CandidatureSpec("C", "Partido C", ["08"])
DOC_A = DocumentSpec("a.md", "A", ["Programa de A.", ""], ["A", "B"])
DOC_B = DocumentSpec("b.md", "B", ["Programa de B."], ["B"])
DOC_C = DocumentSpec("c.md", "C", ["Programa de C."], ["C"])
PARTIES = [PARTY_A, PARTY_B, PARTY_C]
DOCUMENTS = [DOC_A, DOC_B]


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return write_bundle_v2(tmp_path / "data" / "elections", PARTIES, DOCUMENTS)


def _bundle(directory: Path) -> Bundle:
    return read_bundle(directory)


def _phases(ledger: ledgers.Ledger) -> dict[str, tuple[str, str | None, int | None]]:
    return {
        p.short_name: (p.phase.value, p.reason.value if p.reason else None, p.proposals)
        for p in ledger.parties
    }


def _hash(directory: Path, file: str) -> str:
    return ledgers.listed_document(_bundle(directory), file).text.content_hash


def _extracted(directory: Path, a: int = 20, b: int = 15) -> None:
    """Review both documents kept and record their counts through the public interface."""
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    ledgers.review_in_dir(directory, "b.md", decision="kept")
    _stub_extraction(directory, {"a.md": a, "b.md": b})


def _stub_extraction(directory: Path, counts: dict[str, int]) -> list[ledgers.PartyEntry]:
    """What ``proposal-extraction`` will do: read the kept documents from the ledger
    and record each one's count once per ``content_hash``."""
    bundle = read_bundle(directory)
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    affected: list[ledgers.PartyEntry] = []
    for entry in ledger.documents:
        if entry.review is None or entry.review.decision is not ReviewDecision.KEPT:
            continue
        assert ledgers.listed_document(bundle, entry.file).text.content_hash == entry.content_hash
        affected.extend(
            ledgers.record_extraction_in_dir(
                directory,
                entry.file,
                content_hash=entry.content_hash,
                validated_proposals=counts[entry.file],
            )
        )
    return affected


# --- Scenario 1: create -------------------------------------------------------------


def test_update_creates_the_ledger_with_every_party_pending(directory: Path) -> None:
    bundle, ledger, lines = ledgers.update_in_dir(directory)

    path = directory / LEDGER_NAME
    assert lines == [f"Created ingestion ledger {path} (N = 30)"]
    assert ledger.min_proposals == DEFAULT_MIN_PROPOSALS == 30
    assert _phases(ledger) == {
        "A": ("candidature_declared", None, None),
        "B": ("candidature_declared", None, None),
        "C": ("candidature_declared", None, None),
    }
    assert [(d.file, d.parties, d.review, d.proposals) for d in ledger.documents] == [
        ("a.md", ("A", "B"), None, None),
        ("b.md", ("B",), None, None),
    ]
    assert ledger.documents[0].content_hash == _hash(directory, "a.md")
    assert path.read_bytes() == ledgers.render_ledger(ledger)
    assert ledgers.read_ledger(directory) == ledger
    assert [ledgers.next_step(bundle, ledger, s) for s in "ABC"] == [
        "review a.md",
        "review a.md, b.md",
        'list a manifesto in [[documents]] or record "ingestion no-manifesto"',
    ]
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == (
        "party A: candidature_declared (next: review a.md)",
        "party B: candidature_declared (next: review a.md, b.md)",
        'party C: candidature_declared (next: list a manifesto in [[documents]] or record '
        '"ingestion no-manifesto")',
    )


def test_canonical_bytes_and_a_second_update_is_a_no_op(directory: Path) -> None:
    _, ledger, _ = ledgers.update_in_dir(directory)
    data = (directory / LEDGER_NAME).read_bytes()
    obj = json.loads(data)

    assert data == (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert list(obj) == ["format", "election", "min_proposals", "parties", "documents",
                         "conflicts"]
    assert list(obj["parties"][0]) == ["short_name", "phase", "reason", "note", "proposals"]
    assert list(obj["documents"][0]) == ["file", "content_hash", "parties", "review",
                                         "proposals"]
    assert obj["format"] == 1 and obj["election"] == directory.name and obj["conflicts"] == []

    _, again, lines = ledgers.update_in_dir(directory)
    assert lines == []
    assert again == ledger
    assert (directory / LEDGER_NAME).read_bytes() == data


def test_update_with_min_proposals_at_creation_and_later(directory: Path) -> None:
    _, ledger, lines = ledgers.update_in_dir(directory, min_proposals=25)
    assert ledger.min_proposals == 25
    assert lines[0].endswith("(N = 25)")
    _, ledger, lines = ledgers.update_in_dir(directory, min_proposals=40)
    assert lines == ["N: 25 -> 40"]
    for bad in (0, 1001, True, 2.5):
        with pytest.raises(LedgerError, match="min_proposals must be an integer between 1 and"):
            ledgers.update_in_dir(directory, min_proposals=bad)  # type: ignore[arg-type]


def test_format_1_bundles_are_refused(tmp_path: Path) -> None:
    legacy = write_bundle(tmp_path / "data" / "elections")
    (legacy / LEDGER_NAME).write_text("not json", encoding="utf-8")
    message = "the Ingestion Ledger needs a format-2 election.toml"
    bundle = read_bundle(legacy)

    for call in (
        lambda: ledgers.update_in_dir(legacy),
        lambda: ledgers.reconcile(bundle, None),
        lambda: ledgers.review_document(bundle, None, "pp.md", decision="kept"),
        lambda: ledgers.set_no_manifesto(bundle, None, "PP"),
        lambda: ledgers.record_extraction(
            bundle, None, "pp.md", content_hash="0" * 64, validated_proposals=1
        ),
        lambda: ledgers.require_phase4_ready(legacy),
        lambda: ledgers.party_states(bundle, None),
    ):
        with pytest.raises(LedgerError, match=message):
            call()
    # The stray file of a format-1 bundle is never read by the checks.
    assert ledgers.ledger_problems(bundle) == []
    assert (legacy / LEDGER_NAME).read_text(encoding="utf-8") == "not json"


# --- Scenarios 2 and 3: review, shared document, partial discard ---------------------


def test_keeping_a_shared_document_applies_to_every_party(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    bundle, ledger, lines = ledgers.review_in_dir(directory, "a.md", decision="kept")

    assert lines == ["Document a.md: kept", "Party A: candidature_declared -> manifesto_reviewed"]
    assert _phases(ledger)["A"] == ("manifesto_reviewed", None, None)
    assert _phases(ledger)["B"] == ("candidature_declared", None, None)
    assert ledgers.next_step(bundle, ledger, "B") == "review b.md"
    assert ledgers.next_step(bundle, ledger, "A") == "extract Proposals from a.md"


def test_partial_discard_goes_on_and_full_discard_excludes(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    _, ledger, lines = ledgers.review_in_dir(
        directory, "b.md", decision="discarded", reason="incomplete", note=" Faltan páginas "
    )

    assert lines == [
        "Document b.md: discarded (incomplete)",
        "Party B: candidature_declared -> manifesto_reviewed",
    ]
    assert _phases(ledger)["B"] == ("manifesto_reviewed", None, None)
    b_entry = ledger.document("b.md")
    assert b_entry.review == ledgers.Review(
        ReviewDecision.DISCARDED, ledgers.DiscardReason.INCOMPLETE, "Faltan páginas"
    )
    assert (b_entry.file, b_entry.parties, b_entry.proposals) == ("b.md", ("B",), None)
    assert b_entry.content_hash == _hash(directory, "b.md")

    _, ledger, lines = ledgers.review_in_dir(
        directory, "a.md", decision="discarded", reason="not_a_manifesto"
    )
    assert lines == [
        "Document a.md: discarded (not_a_manifesto) (was kept)",
        "Party A: manifesto_reviewed -> excluded (discarded_at_review)",
        "Party B: manifesto_reviewed -> excluded (discarded_at_review)",
    ]
    assert _phases(ledger)["A"] == ("excluded", "discarded_at_review", None)
    assert _phases(ledger)["B"] == ("excluded", "discarded_at_review", None)


def test_review_refusals_leave_the_file_unchanged(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    before = (directory / LEDGER_NAME).read_bytes()

    with pytest.raises(LedgerError, match="a discarded document needs a reason"):
        ledgers.review_in_dir(directory, "a.md", decision="discarded")
    with pytest.raises(LedgerError, match="'z.md' is not listed in election.toml"):
        ledgers.review_in_dir(directory, "z.md", decision="kept")
    with pytest.raises(LedgerError, match="a kept document takes no discard reason"):
        ledgers.review_in_dir(directory, "a.md", decision="kept", reason="incomplete")
    with pytest.raises(LedgerError, match="unknown discard reason 'bad'"):
        ledgers.review_in_dir(directory, "a.md", decision="discarded", reason="bad")
    with pytest.raises(LedgerError, match="unknown review decision 'maybe'"):
        ledgers.review_in_dir(directory, "a.md", decision="maybe")
    for note, problem in (
        ("", "must not be empty"),
        ("una\nlínea", "single line"),
        ("x" * 501, "at most 500"),
    ):
        with pytest.raises(LedgerError, match=problem):
            ledgers.review_in_dir(directory, "a.md", decision="kept", note=note)

    assert (directory / LEDGER_NAME).read_bytes() == before


def test_review_works_without_a_ledger_and_re_review_overwrites(directory: Path) -> None:
    _, _, lines = ledgers.review_in_dir(directory, "a.md", decision="kept")
    assert lines[0].startswith("Created ingestion ledger")
    assert lines[1:] == ["Document a.md: kept", "Party A: candidature_declared -> manifesto_reviewed"]
    _, _, lines = ledgers.review_in_dir(directory, "a.md", decision="kept")
    assert lines == []


# --- Scenario 4: no manifesto ---------------------------------------------------------


def test_no_manifesto_is_recorded_refused_and_cleared(directory: Path, tmp_path: Path) -> None:
    ledgers.update_in_dir(directory)
    _, ledger, lines = ledgers.no_manifesto_in_dir(directory, "C", note="Sin programa a 26/11")

    assert lines == [
        "Party C: no_manifesto recorded",
        "Party C: candidature_declared -> excluded (no_manifesto)",
    ]
    assert ledger.party("C") == ledgers.PartyEntry(
        "C", Phase.EXCLUDED, ExclusionReason.NO_MANIFESTO, "Sin programa a 26/11"
    )
    with pytest.raises(LedgerError, match=r"party A lists documents \(a.md\)"):
        ledgers.no_manifesto_in_dir(directory, "A")
    with pytest.raises(LedgerError, match="party 'Z' is not in election.toml"):
        ledgers.no_manifesto_in_dir(directory, "Z")

    write_bundle_v2(tmp_path / "data" / "elections", PARTIES, [DOC_A, DOC_B, DOC_C])
    _, ledger, lines = ledgers.update_in_dir(directory)
    assert lines == [
        "Document c.md: added",
        "Party C: no_manifesto cleared (documents listed: c.md)",
        "Party C: excluded (no_manifesto) -> candidature_declared",
    ]
    assert ledger.party("C") == ledgers.PartyEntry("C", Phase.CANDIDATURE_DECLARED)


def test_no_manifesto_undo(directory: Path) -> None:
    ledgers.no_manifesto_in_dir(directory, "C")
    _, ledger, lines = ledgers.no_manifesto_in_dir(directory, "C", undo=True)
    assert lines == [
        "Party C: no_manifesto removed",
        "Party C: excluded (no_manifesto) -> candidature_declared",
    ]
    assert ledger.party("C").phase is Phase.CANDIDATURE_DECLARED
    with pytest.raises(LedgerError, match="no no_manifesto exclusion to undo"):
        ledgers.no_manifesto_in_dir(directory, "C", undo=True)


# --- Scenario 5: the phase-3 interface through a stub ----------------------------------


def test_extraction_stub_sums_kept_documents_against_n(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    ledgers.review_in_dir(directory, "b.md", decision="kept")

    affected = _stub_extraction(directory, {"a.md": 20, "b.md": 15})

    assert [(p.short_name, p.phase.value) for p in affected] == [
        ("A", "excluded"), ("B", "manifesto_reviewed"),  # after a.md: b.md not yet counted
        ("B", "proposals_extracted"),
    ]
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert _phases(ledger) == {
        "A": ("excluded", "too_few_proposals", 20),
        "B": ("proposals_extracted", None, 35),
        "C": ("candidature_declared", None, None),
    }
    assert [d.proposals for d in ledger.documents] == [20, 15]

    _, ledger, lines = ledgers.update_in_dir(directory, min_proposals=20)
    assert lines == [
        "N: 30 -> 20",
        "Party A: excluded (too_few_proposals, 20 < 30) -> proposals_extracted (20 proposals)",
    ]
    assert _phases(ledger)["A"] == ("proposals_extracted", None, 20)


def test_partly_discarded_party_counts_only_kept_documents(directory: Path) -> None:
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    ledgers.review_in_dir(directory, "b.md", decision="discarded", reason="no_text_layer")
    _stub_extraction(directory, {"a.md": 31})
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    assert _phases(ledger)["B"] == ("proposals_extracted", None, 31)
    assert ledger.document("b.md").proposals is None


def test_record_extraction_refusals(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision="kept")
    ledgers.review_in_dir(directory, "b.md", decision="discarded", reason="incomplete")
    before = (directory / LEDGER_NAME).read_bytes()
    a_hash = _hash(directory, "a.md")

    def record(file: str, content_hash: str, count: object) -> None:
        ledgers.record_extraction_in_dir(
            directory, file, content_hash=content_hash, validated_proposals=count  # type: ignore[arg-type]
        )

    with pytest.raises(LedgerError, match="is stale"):
        record("a.md", "0" * 64, 10)
    with pytest.raises(LedgerError, match="'z.md' is not listed"):
        record("z.md", a_hash, 10)
    with pytest.raises(LedgerError, match=r"b.md is discarded \(incomplete\)"):
        record("b.md", _hash(directory, "b.md"), 10)
    for bad in (-1, True, 3.0, "7"):
        with pytest.raises(LedgerError, match="validated_proposals must be"):
            record("a.md", a_hash, bad)
    assert (directory / LEDGER_NAME).read_bytes() == before

    ledgers.review_in_dir(directory, "a.md", decision="kept")
    write_bundle_v2(directory.parent, PARTIES, DOCUMENTS)  # same bytes
    ledgers.update_in_dir(directory)
    record("a.md", a_hash, 10)
    _, ledger, lines = ledgers.update_in_dir(directory)
    assert lines == []
    bundle = read_bundle(directory)
    ledger, lines = ledgers.record_extraction(
        bundle, ledger, "a.md", content_hash=a_hash, validated_proposals=12
    )
    assert lines == [
        "Document a.md: 12 validated proposals (was 10)",
        "Party A: excluded (too_few_proposals, 10 < 30) -> excluded (too_few_proposals, 12 < 30)",
        "Party B: excluded (too_few_proposals, 10 < 30) -> excluded (too_few_proposals, 12 < 30)",
    ]


def test_unreviewed_document_is_refused_for_extraction(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    with pytest.raises(LedgerError, match="a.md is not reviewed"):
        ledgers.record_extraction_in_dir(
            directory, "a.md", content_hash=_hash(directory, "a.md"), validated_proposals=1
        )


def test_discarding_clears_the_count(directory: Path) -> None:
    _extracted(directory)
    _, ledger, lines = ledgers.review_in_dir(
        directory, "b.md", decision="discarded", reason="incomplete"
    )
    assert lines == [
        "Document b.md: discarded (incomplete) (was kept)",
        "Document b.md: proposals cleared (discarded)",
        "Party B: proposals_extracted (35 proposals) -> excluded (too_few_proposals, 20 < 30)",
    ]
    assert ledger.document("b.md").proposals is None


# --- Scenario 6: changed content ------------------------------------------------------


def test_changed_file_voids_its_review_and_count(directory: Path, tmp_path: Path) -> None:
    _extracted(directory, a=40, b=15)
    changed = DocumentSpec("a.md", "A", ["Programa de A, versión 2."], ["A", "B"])
    write_bundle_v2(tmp_path / "data" / "elections", PARTIES, [changed, DOC_B])
    bundle = read_bundle(directory)

    problems = ledgers.ledger_problems(bundle)
    assert problems == [
        "ingestion ledger is out of date: Document a.md: review cleared (content changed) "
        f'(+3 more); run "ideology ingestion update {directory}"'
    ]
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers[0] == problems[0]

    _, ledger, lines = ledgers.update_in_dir(directory)
    assert lines == [
        "Document a.md: review cleared (content changed)",
        "Document a.md: proposals cleared (content changed)",
        "Party A: proposals_extracted (40 proposals) -> candidature_declared",
        "Party B: proposals_extracted (55 proposals) -> candidature_declared",
    ]
    assert ledger.document("a.md").content_hash == bundle.documents[0].text.content_hash
    assert ledgers.ledger_problems(bundle) == []


def test_removed_party_and_document_and_changed_parties(directory: Path, tmp_path: Path) -> None:
    _extracted(directory)
    doc_a = DocumentSpec("a.md", "A", DOC_A.pages, ["A"])
    party_d = CandidatureSpec("D", "Partido D", ["01"])
    write_bundle_v2(tmp_path / "data" / "elections", [PARTY_A, PARTY_C, party_d], [doc_a])
    (directory / "b.md").unlink()

    _, ledger, lines = ledgers.update_in_dir(directory)

    assert lines == [
        "Party D: added",
        "Party B: removed (not in election.toml)",
        "Document a.md: parties A, B -> A",
        "Document b.md: removed (not in election.toml)",
    ]
    assert [p.short_name for p in ledger.parties] == ["A", "C", "D"]
    assert [d.file for d in ledger.documents] == ["a.md"]


def test_reordered_manifest_is_reported(directory: Path, tmp_path: Path) -> None:
    ledgers.update_in_dir(directory)
    write_bundle_v2(tmp_path / "data" / "elections", [PARTY_B, PARTY_A, PARTY_C], DOCUMENTS)
    _, ledger, lines = ledgers.update_in_dir(directory)
    assert lines == ["Ledger: entries reordered to follow election.toml"]
    assert [p.short_name for p in ledger.parties] == ["B", "A", "C"]


def test_a_hand_edited_phase_is_out_of_date(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    path = directory / LEDGER_NAME
    obj = json.loads(path.read_bytes())
    obj["parties"][0].update(phase="proposals_extracted", proposals=99)
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode())

    assert ledgers.ledger_problems(read_bundle(directory)) == [
        "ingestion ledger is out of date: Party A: proposals_extracted (99 proposals) -> "
        f'candidature_declared; run "ideology ingestion update {directory}"'
    ]


# --- Scenario 7: the gate --------------------------------------------------------------


def test_gate_passes_when_every_party_is_extracted_or_excluded(directory: Path) -> None:
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers[0] == (
        f'no ingestion ledger yet; run "ideology ingestion update {directory}"'
    )

    _extracted(directory, a=20, b=15)
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == (
        'party C: candidature_declared (next: list a manifesto in [[documents]] or record '
        '"ingestion no-manifesto")',
    )
    assert str(blocked.value).startswith("phase 4 is blocked: party C")

    ledgers.no_manifesto_in_dir(directory, "C")
    ledger = ledgers.require_phase4_ready(directory)
    assert _phases(ledger) == {
        "A": ("excluded", "too_few_proposals", 20),
        "B": ("proposals_extracted", None, 35),
        "C": ("excluded", "no_manifesto", None),
    }
    assert ledgers.pending_conflicts(ledger) == ()
    assert ledgers.phase4_blockers(read_bundle(directory), ledger) == []
    assert ledgers.party_states(read_bundle(directory), ledger) == ledger.parties


def test_gate_blocks_on_pending_conflicts(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _extracted(directory, a=30, b=1)
    ledgers.no_manifesto_in_dir(directory, "C")
    ledgers.require_phase4_ready(directory)

    monkeypatch.setattr(ledgers, "pending_conflicts", lambda ledger: ("a.md p. 3 vs b.md p. 1",))
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == ("conflict pending: a.md p. 3 vs b.md p. 1",)


def test_gate_blocks_on_an_invalid_ledger(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    (directory / LEDGER_NAME).write_text("{}\n", encoding="utf-8")
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == (f"{directory / LEDGER_NAME}: $: missing key 'format'",)


def test_party_states_without_a_ledger(directory: Path) -> None:
    states = ledgers.party_states(read_bundle(directory), None)
    assert [(p.short_name, p.phase) for p in states] == [
        ("A", Phase.CANDIDATURE_DECLARED),
        ("B", Phase.CANDIDATURE_DECLARED),
        ("C", Phase.CANDIDATURE_DECLARED),
    ]
    assert not (directory / LEDGER_NAME).exists()


# --- Scenario 8: read validation ----------------------------------------------------------


def _valid_obj(directory: Path) -> dict:
    """A: proposals_extracted (40), B: proposals_extracted (40, b.md discarded), C: no_manifesto."""
    _extracted(directory, a=40, b=15)
    ledgers.no_manifesto_in_dir(directory, "C", note="Sin programa")
    ledgers.review_in_dir(directory, "b.md", decision="discarded", reason="incomplete")
    return json.loads((directory / LEDGER_NAME).read_bytes())


def _write(directory: Path, obj: object) -> None:
    (directory / LEDGER_NAME).write_bytes(
        (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _edit(obj: dict, path: str, value: object) -> None:
    target = obj
    *parents, last = path.split(".")
    for part in parents:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is _DELETE:
        del target[last]
    else:
        target[last] = value


_DELETE = object()

INVALID = [
    ("format", 2, "format: unsupported ledger format 2 (expected 1)"),
    ("format", True, "format: unsupported ledger format True (expected 1)"),
    ("election", "es-general-2019-11-10",
     "election: 'es-general-2019-11-10' is not this bundle's election"),
    ("min_proposals", 0, "min_proposals: must be between 1 and 1000"),
    ("min_proposals", True, "min_proposals: must be an integer"),
    ("min_proposals", 30.0, "min_proposals: must be an integer"),
    ("extra", 1, "$: unknown key 'extra'"),
    ("conflicts", _DELETE, "$: missing key 'conflicts'"),
    ("conflicts", [{"a": 1}], "conflicts: must be empty in ledger format 1"),
    ("parties", {}, "parties: must be a list"),
    ("parties.1.phase", "done", "parties[1].phase: unknown phase 'done'"),
    ("parties.1.extra", None, "parties[1]: unknown key 'extra'"),
    ("parties.1.note", _DELETE, "parties[1]: missing key 'note'"),
    ("parties.0.phase", "excluded", "parties[0].reason: is required when the phase is excluded"),
    ("parties.1.reason", "no_manifesto",
     "parties[1].reason: must be null when the phase is proposals_extracted"),
    ("parties.0.reason", "gone", "parties[0].reason: unknown exclusion reason 'gone'"),
    ("parties.0.note", "nota", "parties[0].note: is only allowed with reason no_manifesto"),
    ("parties.2.note", "", "parties[2].note: note must not be empty"),
    ("parties.2.note", "a\tb", "parties[2].note: note must be a single line"),
    ("parties.1.proposals", True, "parties[1].proposals: must be an integer"),
    ("parties.1.proposals", -1, "parties[1].proposals: must be >= 0"),
    ("parties.1.proposals", None,
     "parties[1].proposals: is required for proposals_extracted and too_few_proposals"),
    ("parties.2.proposals", 3,
     "parties[2].proposals: must be null unless proposals_extracted or too_few_proposals"),
    ("parties.1.short_name", "A", "parties[1].short_name: duplicate short name 'A'"),
    ("parties.1.short_name", "", "parties[1].short_name: must be a non-empty string"),
    ("documents.0.file", "A.MD", "documents[0].file: invalid file name 'A.MD'"),
    ("documents.1.file", "a.md", "documents[1].file: duplicate file 'a.md'"),
    ("documents.0.content_hash", "abc", "documents[0].content_hash: must be 64 lowercase hex"),
    ("documents.0.parties", [], "documents[0].parties: must be a non-empty list"),
    ("documents.0.parties", ["A", "A"], "documents[0].parties: has a duplicate short name"),
    ("documents.0.review.decision", "maybe", "documents[0].review.decision: unknown decision"),
    ("documents.0.review.reason", "incomplete",
     "documents[0].review.reason: must be null when the decision is kept"),
    ("documents.1.review.reason", None,
     "documents[1].review.reason: is required when the decision is discarded"),
    ("documents.1.review.reason", "typo",
     "documents[1].review.reason: unknown discard reason 'typo'"),
    ("documents.1.proposals", 5, "documents[1].proposals: must be null unless the review is kept"),
    ("documents.0.proposals", False, "documents[0].proposals: must be an integer"),
    ("documents.0.review", [], "documents[0].review: must be an object"),
]


@pytest.mark.parametrize(("path", "value", "message"), INVALID, ids=[i[2][:40] for i in INVALID])
def test_read_refuses_a_hand_edited_file(
    directory: Path, path: str, value: object, message: str
) -> None:
    obj = _valid_obj(directory)
    _edit(obj, path, value)
    _write(directory, obj)

    with pytest.raises(LedgerError) as error:
        ledgers.read_ledger(directory)
    assert str(error.value).startswith(f"{directory / LEDGER_NAME}: {message}")


def test_read_refuses_non_canonical_bytes(directory: Path) -> None:
    obj = _valid_obj(directory)
    path = directory / LEDGER_NAME
    canonical = path.read_bytes()
    lines = canonical.count(b"\n")
    for data, where in (
        (json.dumps(obj, indent=4).encode() + b"\n", "line 2"),
        (canonical[:-1], f"line {lines}"),
        (canonical.replace(b'"format": 1,', b'"format": 1 ,'), "line 2"),
    ):
        path.write_bytes(data)
        with pytest.raises(LedgerError) as error:
            ledgers.read_ledger(directory)
        assert str(error.value) == f"{path}: {where}: {NOT_CANONICAL}"


def test_read_refuses_reordered_keys_and_bad_json(directory: Path) -> None:
    obj = _valid_obj(directory)
    path = directory / LEDGER_NAME
    reordered = {"election": obj["election"], **{k: v for k, v in obj.items() if k != "election"}}
    _write(directory, reordered)
    with pytest.raises(LedgerError, match="line 2: not in canonical form"):
        ledgers.read_ledger(directory)

    path.write_bytes(b'{"format": 1,\n')
    with pytest.raises(LedgerError, match="line 2: invalid JSON"):
        ledgers.read_ledger(directory)
    path.write_bytes(b"\xff")
    with pytest.raises(LedgerError, match="line 1: invalid UTF-8"):
        ledgers.read_ledger(directory)
    path.write_bytes(b'{"format": NaN}\n')
    with pytest.raises(LedgerError, match="invalid JSON: NaN is not allowed"):
        ledgers.read_ledger(directory)
    path.write_bytes(b"[]\n")
    with pytest.raises(LedgerError, match=r"\$: must be an object"):
        ledgers.read_ledger(directory)


def test_read_refuses_a_large_file_and_a_directory(directory: Path) -> None:
    path = directory / LEDGER_NAME
    path.write_bytes(b" " * (ledgers.MAX_LEDGER_BYTES + 1))
    with pytest.raises(LedgerError, match="file: is larger than 5242880 bytes"):
        ledgers.read_ledger(directory)
    path.unlink()
    path.mkdir()
    with pytest.raises(LedgerError, match="file: must be a regular file"):
        ledgers.read_ledger(directory)


def test_write_commands_refuse_to_overwrite_an_invalid_file(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    path = directory / LEDGER_NAME
    path.write_bytes(path.read_bytes().replace(b"  ", b"   ", 1))
    edited = path.read_bytes()

    for call in (
        lambda: ledgers.update_in_dir(directory),
        lambda: ledgers.review_in_dir(directory, "a.md", decision="kept"),
        lambda: ledgers.no_manifesto_in_dir(directory, "C"),
        lambda: ledgers.record_extraction_in_dir(
            directory, "a.md", content_hash=_hash(directory, "a.md"), validated_proposals=1
        ),
    ):
        with pytest.raises(LedgerError, match=NOT_CANONICAL.split(" (")[0]):
            call()
    assert path.read_bytes() == edited
    assert ledgers.ledger_problems(read_bundle(directory)) == [
        f"{path}: line 2: {NOT_CANONICAL}"
    ]


def test_bundle_still_reads_with_a_ledger_and_no_temp_file_is_left(directory: Path) -> None:
    _extracted(directory)
    assert read_bundle(directory).slug == directory.name
    assert sorted(p.name for p in directory.iterdir()) == [
        "a.md", "b.md", "election.toml", LEDGER_NAME
    ]

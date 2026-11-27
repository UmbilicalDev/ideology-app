"""dev-dataset: the fictional seed (S1, S3, S5-S8), its content and the scripted provider.

One session seed (``conftest.dev_seed``) is read by most tests; S3 seeds twice
more (one through the CLI, with a hostile environment) and S5 fails a reseed
of a copy. Sockets are blocked and no real LLM runs.
"""

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from dev_dataset_fixtures import bundle_files, sha256, snapshot
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ideology_app import dev_dataset, ingestion_ledger as ledgers, llm, shared_db
from ideology_app.cli import main
from ideology_app.config import ValidationSettings
from ideology_app.db import make_engine
from ideology_app.dev_dataset import content, guard, logos, provider
from ideology_app.dev_dataset.dump import SEED_INSTANT, dump_sha256
from ideology_app.llm import LLMOutputError, LLMProviderError
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    Party,
    PipelineRun,
    PipelineRunStatus,
    Proposal,
    Statement,
    StatementRewording,
)
from ideology_app.pipeline.v2.prompts import (
    DraftInput,
    draft_request,
    position_request,
    rewording_request,
)
from ideology_app.proposals.conflict_prompts import conflict_request
from ideology_app.proposals.extraction import build_chunks
from ideology_app.proposals.prompts import proposal_request
from ideology_app.source_bundle import read_bundle

# Realised numbers (README "Datos de desarrollo").
POOL = 56
N_TYPICAL = 43
N_GALICIA = 45
N_CATALONIA = 42
N_BARCELONA = 52
N_CEUTA = 14
CATEGORIES = 16


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def engine(dev_seed: Any) -> Iterator[Engine]:
    engine = make_engine(shared_db.read_only_url(dev_seed.database))
    try:
        yield engine
    finally:
        engine.dispose()


def _party_ids(session: Session) -> dict[str, int]:
    return {p.short_name: p.id for p in session.scalars(select(Party))}


# --- S7: content -------------------------------------------------------------------


def test_content_is_self_consistent() -> None:
    assert content.check() == []
    assert len(content.STATEMENTS) == POOL
    assert len({s.category for s in content.STATEMENTS}) == CATEGORIES


def test_rendered_bundle_reads_back(tmp_path: Path) -> None:
    from ideology_app.dev_dataset import bundle

    directory = bundle.render(tmp_path)
    loaded = read_bundle(directory)
    assert loaded.slug == content.SLUG == "es-general-2031-05-18"
    assert [p.short_name for p in loaded.parties] == [p.short_name for p in content.PARTIES]
    assert loaded.party("ZAFIRO").logo is None
    assert [d.file for d in loaded.documents] == [d.file for d in content.DOCUMENTS]
    assert loaded.documents[0].text.pages[0].startswith(content.disclaimer("Partido Cuarzo"))


def test_manifest_lists_codes_in_ine_order() -> None:
    from ideology_app.dev_dataset import bundle

    for line in bundle.manifest_text().splitlines():
        if line.startswith("constituencies = ["):
            codes = json.loads(line.removeprefix("constituencies = "))
            assert codes == sorted(codes)


def test_logos_are_small_passive_svg() -> None:
    from ideology_app.party_logos import check_logo

    seen: set[bytes] = set()
    for party in content.PARTIES:
        if party.logo_colour is None:
            continue
        data = logos.svg(party)
        assert len(data) <= 1024
        assert b"<text" not in data and b'viewBox="0 0 64 64"' in data
        assert check_logo(data).media_type == "image/svg+xml"
        seen.add(data)
    assert len(seen) == 9


def test_dev_provider_is_not_registered() -> None:
    assert all("dev" not in name for name in llm.PROVIDERS)
    assert provider.build_provider().name == "fake"
    assert provider.build_provider().model == "dev-dataset-1"


# --- Scripted provider (D2), on requests from the real builders -----------------------


def test_extraction_returns_every_measure_on_its_page() -> None:
    document = content.DOCUMENTS_BY_FILE["cuarzo.md"]
    (chunk,) = build_chunks(document.page_texts())
    items = provider.extraction(proposal_request(chunk))["proposals"]
    expected = [(m.text, page.number) for page in document.pages for m in page.measures]
    assert [(i["text"], i["page"]) for i in items] == expected


def test_extraction_ignores_the_context_page() -> None:
    document = content.DOCUMENTS_BY_FILE["cuarzo.md"]
    chunks = build_chunks(document.page_texts(), max_chars=3000)
    assert chunks[0].context_page is not None
    items = provider.extraction(proposal_request(chunks[0]))["proposals"]
    assert {i["page"] for i in items} == set(chunks[0].pages)


def test_conflict_check_matches_either_order() -> None:
    conflict = content.CONFLICTS[1]
    other = content.measure_for("onix", "peajes-autovias").text
    forward = conflict_request(conflict.category, [other, conflict.texts[0]], [conflict.texts[1]])
    backward = conflict_request(conflict.category, [conflict.texts[1]], [conflict.texts[0]])
    assert provider.conflict_check(forward)["contradictions"] == [
        {"a": 2, "b": 1, "explanation": conflict.explanation}
    ]
    assert provider.conflict_check(backward)["contradictions"][0]["a"] == 1
    none = conflict_request(conflict.category, [other], [conflict.texts[1]])
    assert provider.conflict_check(none) == {"contradictions": []}


def test_drafts_cite_the_listed_proposals_with_a_stance() -> None:
    cuarzo = content.measure_for("cuarzo", "teletrabajo")
    jade = content.measure_for("jade", "teletrabajo")
    other = content.measure_for("cuarzo", "jornada-35")
    request = draft_request(
        "employment",
        [DraftInput(other.text, other.tags), DraftInput(cuarzo.text), DraftInput(jade.text)],
        [],
        ValidationSettings(),
    )
    drafted = provider.statement_drafts(request)
    by_text = {d["text"]: d["sources"] for d in drafted["statements"]}
    assert by_text == {
        content.STATEMENTS_BY_KEY["jornada-35"].text: [1],
        content.STATEMENTS_BY_KEY["teletrabajo"].text: [2, 3],
    }
    assert drafted["additions"] == []


def test_positions_use_the_common_value_and_refuse_mixed_signs() -> None:
    statement = content.STATEMENTS_BY_KEY["redes-edad"]
    jade = content.measure_for("jade", "redes-edad").text
    turquesa = content.measure_for("turquesa", "redes-edad").text
    answer = provider.proposal_positions(position_request("science_digital", [statement.text], [turquesa]))
    assert answer == {"positions": [{"statement": 1, "value": 1, "evidence": [1]}]}
    with pytest.raises(LLMOutputError, match="mixed stances"):
        provider.proposal_positions(
            position_request("science_digital", [statement.text], [jade, turquesa])
        )


def test_rewording_verdict_is_scripted() -> None:
    statement = content.STATEMENTS_BY_KEY[content.REWORDING.statement]
    verdict = provider.rewording_check(
        rewording_request(statement.text, statement.note, content.REWORDING.text)
    )
    assert verdict["equivalent"] is True
    with pytest.raises(LLMOutputError):
        provider.rewording_check(rewording_request(statement.text, statement.note, "Otra cosa."))


# --- S1: every case is present ------------------------------------------------------------


def test_election_parties_and_candidatures_match_the_table(engine: Engine) -> None:
    with Session(engine) as session:
        (election,) = session.scalars(select(Election)).all()
        assert (election.country, election.date.isoformat(), election.name) == (
            "ES", "2031-05-18", content.ELECTION_NAME
        )
        assert election.status is ElectionStatus.ACTIVE
        parties = session.scalars(select(Party).order_by(Party.id)).all()
        assert [(p.short_name, p.name) for p in parties] == [
            (p.short_name, p.name) for p in content.PARTIES
        ]
        assert {p.short_name for p in parties if p.logo_sha256 is None} == {"ZAFIRO"}
        assert all(p.logo_media_type == "image/svg+xml" for p in parties if p.logo_sha256)
        version = session.scalars(select(DatasetVersion)).one()
        rows = session.execute(
            select(Party.short_name, DatasetVersionCandidature.constituency_code)
            .join(Party, Party.id == DatasetVersionCandidature.party_id)
            .where(DatasetVersionCandidature.dataset_version_id == version.id)
        ).all()
    codes: dict[str, set[str]] = {}
    for short_name, code in rows:
        codes.setdefault(short_name, set()).add(code)
    for party in content.PARTIES:
        assert codes[party.short_name] == set(party.codes()), party.short_name
    assert len(codes["CUARZO"]) == 52 and len(codes["JADE"]) == 46
    assert len(codes["ONIX"]) == 47 and len(codes["ZAFIRO"]) == 50


def test_excluded_reasons_ledger_and_set_aside(dev_seed: Any, engine: Engine) -> None:
    with Session(engine) as session:
        ids = _party_ids(session)
        reasons = dict(
            session.execute(
                select(DatasetVersionCandidature.party_id, DatasetVersionCandidature.excluded_reason)
                .where(DatasetVersionCandidature.excluded_reason.is_not(None))
                .distinct()
            ).all()
        )
        assert reasons == {
            ids["MICA"]: "too_few_proposals",
            ids["GRAFITO"]: "no_manifesto",
            ids["PIZARRA"]: "discarded_at_review",
        }
        aside = session.scalars(
            select(Proposal).where(
                Proposal.text == content.measure_for("onix", "cercanias-gestion").text
            )
        ).one()
        holders = set(
            session.scalars(
                select(DatasetVersionProposal.party_id).where(
                    DatasetVersionProposal.proposal_id == aside.id
                )
            )
        )
        assert ids["ONIX"] in holders and ids["ONIX-CAT"] not in holders
    ledger = ledgers.read_ledger(dev_seed.bundle)
    assert ledger is not None
    turquesa = ledger.conflict("TURQUESA", ["jade.md", "turquesa.md"])
    onix_cat = ledger.conflict("ONIX-CAT", ["onix.md", "onix-cat.md"])
    assert turquesa.status is ledgers.ConflictStatus.JOINT_MANIFESTO
    assert turquesa.prevails == "turquesa.md" and len(turquesa.contradictions) >= 1
    assert onix_cat.status is ledgers.ConflictStatus.DECIDED
    assert onix_cat.prevails == "onix-cat.md" and onix_cat.reason == content.DECISION.reason
    assert len(onix_cat.contradictions) >= 1
    assert ledger.party("GRAFITO").note == content.GRAFITO_NOTE


def test_run_version_rewording_and_constituencies(engine: Engine) -> None:
    with Session(engine) as session:
        (run,) = session.scalars(select(PipelineRun)).all()
        assert run.status is PipelineRunStatus.PASSED
        assert (run.llm_provider, run.llm_model) == ("fake", "dev-dataset-1")
        version = session.scalars(select(DatasetVersion)).one()
        assert version.status is DatasetVersionStatus.PUBLISHED
        assert session.scalar(select(func.count()).select_from(Statement)) == POOL
        (rewording,) = session.scalars(select(StatementRewording)).all()
        assert rewording.ai_text == content.STATEMENTS_BY_KEY[content.REWORDING.statement].text
        report = run.statement_selection["rewordings"]["entries"]
        assert [e["status"] for e in report] == ["applied"]
        rows = {
            r.constituency_code: r
            for r in session.scalars(select(DatasetVersionConstituency))
        }
    assert len(rows) == 52
    assert not rows["52"].available
    assert rows["52"].unavailable_reason == "fewer_than_two_parties"
    assert sum(r.available for r in rows.values()) == 51
    counts = {code: r.valid_statement_count for code, r in rows.items()}
    galicia, catalonia = ("15", "27", "32", "36"), ("17", "25", "43")
    for code, n in counts.items():
        if code in galicia:
            assert n == N_GALICIA
        elif code in catalonia:
            assert n == N_CATALONIA
        elif code == "08":
            assert n == N_BARCELONA
        elif code == "51":
            assert n == N_CEUTA
        elif code != "52":
            assert n == N_TYPICAL, code
    assert 41 <= N_TYPICAL <= 49 and N_TYPICAL % 5
    assert 50 <= N_BARCELONA <= 59 and N_BARCELONA % 5
    assert 10 <= N_CEUTA <= 19 and N_GALICIA != N_TYPICAL
    assert rows["51"].offered_lengths == [N_CEUTA]
    assert rows["08"].offered_lengths == [20, 30, 40, 50]


def test_timestamps_are_fixed(engine: Engine) -> None:
    with Session(engine) as session:
        run = session.scalars(select(PipelineRun)).one()
        assert run.created_at.replace(tzinfo=None) == SEED_INSTANT.replace(tzinfo=None)


def test_ledger_and_database_match_the_bundle(dev_seed: Any, engine: Engine) -> None:
    from ideology_app.bundle_import import check_against_bundle

    loaded = read_bundle(dev_seed.bundle)
    assert ledgers.ledger_problems(loaded) == []
    with Session(engine) as session:
        assert check_against_bundle(session, loaded) == []


# --- S6: fictional only --------------------------------------------------------------------

DENYLIST = (
    "PP", "PSOE", "PSC", "Vox", "Sumar", "Podemos", "ERC", "Esquerra", "Junts", "PNV", "EAJ",
    "Bildu", "BNG", "Coalición Canaria", "CC", "UPN", "PACMA", "Ciudadanos", "Cs", "IU",
    "Izquierda Unida", "Más País", "Más Madrid", "Compromís", "CUP", "Teruel Existe",
    "Nueva Canarias", "PRC", "Foro", "Geroa Bai", "SALF", "Se Acabó La Fiesta",
    "Partido Popular", "Partido Socialista", "Partido Animalista",
)


def _denied(text: str) -> list[str]:
    found: list[str] = []
    for entry in DENYLIST:
        acronym = entry.isupper() or entry == "Cs"
        pattern = re.compile(
            rf"(?<!\w){re.escape(entry)}(?!\w)", 0 if acronym else re.IGNORECASE
        )
        if pattern.search(text):
            found.append(entry)
    return found


def test_denylist_matches_whole_words() -> None:
    assert _denied("Votó al Partido Popular y al PSOE.") == ["PSOE", "Partido Popular"]
    assert _denied("Los ciudadanos podemos sumar.") == ["Sumar", "Podemos", "Ciudadanos"]
    assert _denied("PPE, cc y CSIC, programa, foros") == []


def test_no_real_party_name_in_any_rendered_text(dev_seed: Any) -> None:
    texts = [data.decode("utf-8") for name, data in bundle_files(dev_seed.bundle).items()]
    texts += [p.short_name + " " + p.name for p in content.PARTIES]
    texts += [f"{s.text} {s.note}" for s in content.STATEMENTS]
    texts += [c.explanation for c in content.CONFLICTS]
    texts += [content.DECISION.reason, content.REWORDING.text, content.REWORDING.reason]
    texts += [content.REWORDING.explanation, content.GRAFITO_NOTE, content.PIZARRA_NOTE]
    assert [(t[:60], _denied(t)) for t in texts if _denied(t)] == []


# --- S3 + S8: deterministic, and the CLI output ---------------------------------------------


def test_two_seeds_are_identical_and_reseed_is_stable(
    dev_seed: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "99")
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "1")
    url = f"sqlite:///{tmp_path}/other/place.db"
    result = CliRunner().invoke(main, ["--database-url", url, "dev", "seed"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == f"Database: {tmp_path}/other/place.db"
    assert lines[1] == f"Bundle: {tmp_path}/other/place-bundle/{content.SLUG}"
    assert lines[2] == f"Election 1: {content.ELECTION_NAME}"
    assert lines[3] == "Pipeline run 1: passed; dataset version 1 published"
    assert lines[4] == f"Pool: {POOL} statements"
    assert lines[5] == "Constituencies: 51 available, 1 unavailable"
    assert lines[6] == (
        f"Statements per Constituency: 08 {N_BARCELONA}, 28 {N_TYPICAL}, 15 {N_GALICIA}, "
        f"51 {N_CEUTA}"
    )
    assert lines[7] == f"Dump SHA-256: {dev_seed.dump_sha256}"
    assert "--port 8002" in lines[-1]
    assert dump_sha256(tmp_path / "other" / "place.db") == dev_seed.dump_sha256
    assert bundle_files(tmp_path / "other" / "place-bundle" / content.SLUG) == bundle_files(
        dev_seed.bundle
    )
    again = dev_dataset.seed(url)
    assert again.dump_sha256 == dev_seed.dump_sha256
    assert sorted(p.name for p in (tmp_path / "other").iterdir()) == ["place-bundle", "place.db"]


# --- S5: a failed reseed leaves the previous data ---------------------------------------------


def test_failed_reseed_keeps_the_previous_data(
    dev_seed: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "data" / "dev"
    directory.mkdir(parents=True)
    shutil.copy(dev_seed.database, directory / "dev.db")
    shutil.copytree(dev_seed.bundle.parent, directory / "dev-bundle")
    before = snapshot(tmp_path)

    original = provider.build_provider

    def _failing() -> Any:
        def _raise(request: Any) -> dict[str, Any]:
            raise LLMProviderError("provider overloaded (529)")

        scripted = original()
        scripted.responses["proposal_positions"] = _raise
        return scripted

    monkeypatch.setattr(provider, "build_provider", _failing)
    result = CliRunner().invoke(main, ["dev", "seed"])
    assert result.exit_code == 1
    assert "Error: dev seed failed at self-check" in result.output
    assert "previous data is untouched" in result.output
    assert snapshot(tmp_path) == before
    assert not (directory / ".dev-seed-tmp").exists()


def test_default_target_is_data_dev(tmp_path: Path) -> None:
    target = guard.check_target(None)
    assert target.database == tmp_path / "data" / "dev" / "dev.db"
    assert target.bundle == tmp_path / "data" / "dev" / "dev-bundle" / content.SLUG
    assert snapshot(tmp_path) == {}


def test_bundle_json_ledger_is_canonical(dev_seed: Any) -> None:
    data = (dev_seed.bundle / "ingestion-ledger.json").read_bytes()
    assert json.loads(data)["election"] == content.SLUG
    assert sha256(dev_seed.bundle / "ingestion-ledger.json")


def test_canonical_statement_ignores_constraint_order() -> None:
    from ideology_app.dev_dataset.dump import canonical_statement

    first = "CREATE TABLE t (\n\tid INTEGER NOT NULL, \n\tCONSTRAINT a CHECK (id > 0), \n\tPRIMARY KEY (id)\n);"
    second = "CREATE TABLE t (\n\tid INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT a CHECK (id > 0)\n);"
    assert canonical_statement(first) == canonical_statement(second)
    assert canonical_statement("INSERT INTO t VALUES(1);") == "INSERT INTO t VALUES(1);"

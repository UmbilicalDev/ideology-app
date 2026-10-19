"""``ideology pipeline run|list|statements|positions|validate|checks`` with the fake provider.

pipeline-generate-statements Scenario 7, pipeline-extract-positions Scenario 10,
validation-evidence-quotes Scenario 7, validation-party-coverage Scenario 5 and
validation-questionnaire-shape Scenario 5 and auto-publish-dataset-version
Scenario 8.
"""

from typing import Any

import pytest
from click.testing import CliRunner, Result
from pipeline_fixtures import (
    PAGES,
    chunk_pages,
    default_responses,
    fake_provider,
    findings_response,
    offline_guard,
    positions_response,
    seed_election,
    statements_payload,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.config import GenerationMode
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.models import (
    PartyPosition,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentStatus,
)
from ideology_app.pipeline import execute_run, queue_run
from ideology_app.pipeline import runs as runs_module

RUN_HEADER = (
    "id\tstatus\tprovider\tmodel\tmode\tdataset_version\tstatements\t"
    "llm_calls\tinput_tokens\toutput_tokens\tfailure_reason"
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def seeded(db_url: str) -> None:
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        seed_election(engine)
    finally:
        engine.dispose()


@pytest.fixture
def use_fake(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


def run_count(db_url: str) -> int:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            return s.scalar(select(func.count()).select_from(PipelineRun)) or 0
    finally:
        engine.dispose()


def test_run_list_and_statements(run, seeded, use_fake) -> None:
    provider = use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Pipeline run 1: passed (dataset version 1, 30 statements, 60 party positions)\n"
        "Published dataset version 1 for election 1\n"
    )
    assert len(provider.calls) == 7

    listed = run("pipeline", "list", "--election", "1")
    assert listed.exit_code == 0, listed.output
    lines = listed.output.splitlines()
    assert lines[0] == RUN_HEADER
    assert len(lines) == 2
    row = lines[1].split("\t")
    in_tokens = sum(len(f"{c.system} {c.prompt}".split()) for c in provider.calls)
    assert row[:9] == [
        "1", "passed", "fake", "fake-model", "precomputed", "1", "30", "7", str(in_tokens)
    ]
    assert int(row[9]) > 0
    assert row[10] == ""

    statements = run("pipeline", "statements", "--dataset-version", "1")
    assert statements.exit_code == 0, statements.output
    lines = statements.output.splitlines()
    assert lines[0] == "position\ttopic\ttext"
    expected = statements_payload()["statements"]
    assert lines[1:] == [f"{i}\t{e['topic']}\t{e['text']}" for i, e in enumerate(expected, 1)]


def test_live_generation_mode_is_recorded(run, seeded, use_fake, monkeypatch) -> None:
    use_fake(fake_provider())
    monkeypatch.setenv("GENERATION_MODE", "live")
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[4] == "live"


def test_failed_run_is_committed_and_reported(run, seeded, use_fake) -> None:
    use_fake(fake_provider(statement_candidates={"candidates": []}))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: pipeline run 1 failed: "
        "no statement candidates were found in the source documents\n"
    )
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "failed"
    assert row[5:8] == ["", "", "2"]
    assert row[10] == "no statement candidates were found in the source documents"


def test_provider_is_closed(run, seeded, use_fake) -> None:
    closed: list[bool] = []

    class ClosingFake(FakeProvider):
        def close(self) -> None:
            closed.append(True)

    provider = ClosingFake(default_responses())
    use_fake(provider)
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    assert closed == [True]


def test_fake_from_config_has_no_responses_and_fails(run, seeded, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: pipeline run 1 failed: "
        "FakeProvider has no response for task 'statement_candidates'\n"
    )
    assert len(run("pipeline", "list", "--election", "1").output.splitlines()) == 2


def test_anthropic_without_key_fails_the_run_offline(run, seeded, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 failed: ANTHROPIC_API_KEY is not set\n"
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1:5] == ["failed", "anthropic", "claude-sonnet-5-5", "precomputed"]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("LLM_PROVIDER", "Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, fake\n"),
        (
            "GENERATION_MODE",
            "Error: Invalid GENERATION_MODE 'bogus'; supported values: precomputed, live\n",
        ),
    ],
)
def test_bad_config_creates_no_run(run, seeded, db_url, monkeypatch, name, message) -> None:
    monkeypatch.setenv(name, "bogus")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == message
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("pipeline", "run", "--election", "9"), "Error: election 9 not found\n"),
        (("pipeline", "list", "--election", "9"), "Error: election 9 not found\n"),
        (
            ("pipeline", "statements", "--dataset-version", "9"),
            "Error: dataset version 9 not found\n",
        ),
        (
            ("pipeline", "positions", "--dataset-version", "9"),
            "Error: dataset version 9 not found\n",
        ),
        (("pipeline", "validate", "--run", "9"), "Error: pipeline run 9 not found\n"),
        (("pipeline", "checks", "--run", "9"), "Error: pipeline run 9 not found\n"),
    ],
    ids=["run", "list", "statements", "positions", "validate", "checks"],
)
def test_not_found(run, seeded, use_fake, db_url, args, message) -> None:
    provider = use_fake(fake_provider())

    result = run(*args)

    assert result.exit_code == 1
    assert result.stderr == message
    assert provider.calls == []
    assert run_count(db_url) == 0


def test_election_without_parsed_documents(run, use_fake, db_url) -> None:
    use_fake(fake_provider())
    for args in (
        ("db", "upgrade"),
        ("election", "create", "--country", "ES", "--type", "general",
         "--date", "2023-07-23", "--name", "Generales 2023"),
    ):
        assert run(*args).exit_code == 0

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == "Error: election 1 has no parsed source documents\n"
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    "revision",
    [None, "0001", "0002", "0003", "0004", "0005"],
    ids=["not-migrated", "at-0001", "at-0002", "at-0003", "at-0004", "at-0005"],
)
@pytest.mark.parametrize(
    "args",
    [
        ("pipeline", "run", "--election", "1"),
        ("pipeline", "list", "--election", "1"),
        ("pipeline", "statements", "--dataset-version", "1"),
        ("pipeline", "positions", "--dataset-version", "1"),
        ("pipeline", "validate", "--run", "1"),
        ("pipeline", "checks", "--run", "1"),
    ],
    ids=["run", "list", "statements", "positions", "validate", "checks"],
)
def test_requires_current_schema(
    db_url: str, use_fake, revision: str | None, args: tuple[str, ...]
) -> None:
    provider = use_fake(fake_provider())
    if revision:
        run_migrations(db_url, revision)

    result = CliRunner().invoke(main, ["--database-url", db_url, *args])

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert provider.calls == []


def test_real_provider_seam_uses_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "m1")
    provider: Any = cli._provider()
    assert isinstance(provider, FakeProvider)
    assert (provider.name, provider.model) == ("fake", "m1")


def test_failing_generate_call_reports_reason(run, seeded, use_fake) -> None:
    def _boom(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMProviderError("APIConnectionError")

    use_fake(fake_provider(generate_statements=_boom))
    result = run("pipeline", "run", "--election", "1")
    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 failed: APIConnectionError\n"


# pipeline-extract-positions Scenario 10: ``pipeline positions``

POSITIONS_HEADER = "statement\tparty\tvalue\tdocument\tpage\turl\tquote"


def test_positions_lists_every_statement_party_pair(
    run, seeded, use_fake, monkeypatch
) -> None:
    # Sparse on purpose (no fill), so ``no_stance`` rows exist; coverage is not
    # checked. Statements 3..30 have no stance, so the run fails on
    # statement_separation and keeps its Dataset Version.
    use_fake(fake_provider(party_positions=positions_response()))
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "0")
    failed = run("pipeline", "run", "--election", "1")
    assert failed.exit_code == 1
    assert "validation failed: statement_separation;" in failed.stderr

    result = run("pipeline", "positions", "--dataset-version", "1")

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == POSITIONS_HEADER
    assert len(lines) == 61
    assert lines[1:5] == [
        f"1\t1\t1\t1\t1\t\t{PAGES[1][0]}",
        f"1\t2\t-1\t2\t1\t\t{PAGES[2][0]}",
        f"2\t1\t1\t1\t2\t\t{PAGES[1][1]}",
        f"2\t2\t-1\t2\t2\t\t{PAGES[2][1]}",
    ]
    assert lines[5:7] == ["3\t1\tno_stance\t\t\t\t", "3\t2\tno_stance\t\t\t\t"]
    assert [line.split("\t")[:2] for line in lines[1:]] == [
        [str(n), str(p)] for n in range(1, 31) for p in (1, 2)
    ]

    party = run("pipeline", "positions", "--dataset-version", "1", "--party", "2")
    assert party.exit_code == 0, party.output
    rows = party.output.splitlines()
    assert rows[0] == POSITIONS_HEADER
    assert len(rows) == 31
    assert all(row.split("\t")[1] == "2" for row in rows[1:])


def test_positions_show_negative_values_urls_and_one_line_quotes(
    run, seeded, use_fake, db_url
) -> None:
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                update(SourceDocument)
                .where(SourceDocument.id == 2)
                .values(origin=SourceDocumentOrigin.URL, source_url="https://example.org/p.pdf")
            )
    finally:
        engine.dispose()
    quote = "Bajaremos\tel IVA\n\n  de la luz."
    use_fake(
        fake_provider(
            position_findings={
                "findings": [{"statement": 2, "value": -2, "quote": quote, "page": 2}]
            },
            party_positions={"positions": [{"statement": 2, "value": -2, "evidence": 1}]},
        )
    )
    # The quote is on no page, so the run fails Validation but keeps its positions.
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = run("pipeline", "positions", "--dataset-version", "1", "--party", "2")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[2] == (
        "2\t2\t-2\t2\t2\thttps://example.org/p.pdf\tBajaremos el IVA de la luz."
    )
    # Display only: the stored quote is unchanged.
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            stored = s.scalars(
                select(PartyPosition.evidence_quote).where(PartyPosition.value.is_not(None))
            ).all()
    finally:
        engine.dispose()
    assert stored == [quote, quote]


@pytest.mark.parametrize("party", ["9", "3"], ids=["unknown", "other-election"])
def test_positions_unknown_party(run, seeded, use_fake, party) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    assert run(
        "election", "create", "--country", "ES", "--type", "general",
        "--date", "2019-11-10", "--name", "Generales 2019",
    ).exit_code == 0
    added = run("party", "add", "--election", "2", "--name", "Otro", "--short-name", "OT")
    assert added.exit_code == 0

    result = run("pipeline", "positions", "--dataset-version", "1", "--party", party)

    assert result.exit_code == 1
    assert result.stderr == f"Error: party {party} not found\n"


# validation-evidence-quotes Scenario 7: ``pipeline run`` / ``validate`` / ``checks``

CHECKS_HEADER = "check\tresult\tstatement\tparty\tmessage"
INVENTED = "Bajaremos el IVA de los libros al cero por ciento."
FAILED_RUN_1 = (
    'Error: pipeline run 1 failed: validation failed: evidence_quotes; '
    'see "ideology pipeline checks --run 1"\n'
)
COVERAGE_FAILED_RUN_1 = (
    'Error: pipeline run 1 failed: validation failed: party_coverage, statement_separation; '
    'see "ideology pipeline checks --run 1"\n'
)
SEPARATION_FAILED_RUN_1 = (
    'Error: pipeline run 1 failed: validation failed: statement_separation; '
    'see "ideology pipeline checks --run 1"\n'
)
# validation-questionnaire-shape: the default fake's 30 distinct Statements
# over 18 topics pass the three checks appended after statement_separation.
SHAPE_PASSED_ROWS = [
    "statement_uniqueness\tpassed\t\t\t",
    "statement_count\tpassed\t\t\t",
    "topic_spread\tpassed\t\t\t",
]
PASSED_CHECKS = (
    f"{CHECKS_HEADER}\n"
    "evidence_quotes\tpassed\t\t\t\n"
    "party_coverage\tpassed\t\t\t\n"
    "statement_separation\tpassed\t\t\t\n"
    + "".join(f"{row}\n" for row in SHAPE_PASSED_ROWS)
)
PARTY2_ZERO = (
    "party_coverage\tfailed\t\t2\t"
    "party 2 has positions on 0 of 30 statements (0%); minimum is 70%"
)
# Party 2 without stances: no Statement separates the two Parties.
ONLY_PARTY1_ROWS = [
    f"statement_separation\tfailed\t{n}\t\t"
    f"statement {n} does not separate parties: only party 1 has a stance (value 1)"
    for n in range(1, 31)
]


def _invented_for_party2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2 cites an invented quote for Statement 1 only (real Statement 2 first).

    The invented finding keeps Party 2's default value (-1), so the Statements
    still separate the Parties.
    """
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    kept = [f for f in real["findings"] if f["statement"] != 1]
    return {"findings": [*kept, {"statement": 1, "value": -1, "quote": INVENTED, "page": 1}]}


def _fail_party2_document(db_url: str) -> None:
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                update(SourceDocument)
                .where(SourceDocument.id == 2)
                .values(status=SourceDocumentStatus.FAILED)
            )
    finally:
        engine.dispose()


def _validating_run(db_url: str, provider: FakeProvider) -> None:
    """Leave run 1 in ``validating``, as before this feature or after a crash."""
    engine = make_engine(db_url)
    try:
        with session_scope(engine) as session:
            run_id = queue_run(
                session,
                1,
                llm_provider=provider.name,
                llm_model=provider.model,
                generation_mode=GenerationMode.PRECOMPUTED,
            ).id
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
            execute_run(engine, run_id, provider)
    finally:
        engine.dispose()


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if a command resolves an LLM provider or reads LLM settings."""

    def _boom() -> FakeProvider:
        raise AssertionError("pipeline validate/checks must not need a provider")

    monkeypatch.setattr(cli, "_provider", _boom)
    monkeypatch.setenv("LLM_PROVIDER", "bogus")


def test_checks_of_a_passed_run(run, seeded, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0

    result = run("pipeline", "checks", "--run", "1")

    assert result.exit_code == 0, result.output
    assert result.output == PASSED_CHECKS


def test_run_failing_validation_is_committed_and_reported(run, seeded, use_fake) -> None:
    use_fake(fake_provider(position_findings=_invented_for_party2))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FAILED_RUN_1
    listed = run("pipeline", "list", "--election", "1").output.splitlines()
    assert len(listed) == 2
    row = listed[1].split("\t")
    assert row[1] == "failed"
    assert row[5:7] == ["1", "30"]
    assert row[10] == "validation failed: evidence_quotes"

    checks = run("pipeline", "checks", "--run", "1")
    assert checks.exit_code == 0, checks.output
    assert checks.output == (
        f"{CHECKS_HEADER}\n"
        "evidence_quotes\tfailed\t1\t2\tquote not found in source document 2\n"
        "party_coverage\tpassed\t\t\t\n"
        "statement_separation\tpassed\t\t\t\n"
        + "".join(f"{row}\n" for row in SHAPE_PASSED_ROWS)
    )
    # The failed run keeps its candidate Dataset Version.
    positions = run("pipeline", "positions", "--dataset-version", "1", "--party", "2")
    assert positions.exit_code == 0
    assert f"1\t2\t-1\t2\t1\t\t{INVENTED}" in positions.output.splitlines()


def test_checks_list_one_row_per_entry(run, seeded, use_fake) -> None:
    def _all_invented(request: LLMRequest[Any]) -> dict[str, Any]:
        return {
            "findings": [
                {"statement": page, "value": -1, "quote": f"Inventada\t{page}.", "page": page}
                for page, _ in chunk_pages(request)
            ]
        }

    # Sparse (no fill): each Party covers 2 of 30 Statements with value -1, so
    # all three checks fail.
    use_fake(
        fake_provider(position_findings=_all_invented, party_positions=positions_response())
    )
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = run("pipeline", "checks", "--run", "1")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        CHECKS_HEADER,
        "evidence_quotes\tfailed\t1\t1\tquote not found in source document 1",
        "evidence_quotes\tfailed\t1\t2\tquote not found in source document 2",
        "evidence_quotes\tfailed\t2\t1\tquote not found in source document 1",
        "evidence_quotes\tfailed\t2\t2\tquote not found in source document 2",
        "party_coverage\tfailed\t\t1\t"
        "party 1 has positions on 2 of 30 statements (6%); minimum is 70%",
        "party_coverage\tfailed\t\t2\t"
        "party 2 has positions on 2 of 30 statements (6%); minimum is 70%",
        "statement_separation\tfailed\t1\t\t"
        "statement 1 does not separate parties: all 2 parties with a stance have value -1",
        "statement_separation\tfailed\t2\t\t"
        "statement 2 does not separate parties: all 2 parties with a stance have value -1",
        *(
            f"statement_separation\tfailed\t{n}\t\t"
            f"statement {n} does not separate parties: no party has a stance"
            for n in range(3, 31)
        ),
        *SHAPE_PASSED_ROWS,
    ]


def test_checks_of_a_run_that_was_not_validated(run, seeded, use_fake) -> None:
    use_fake(fake_provider(statement_candidates={"candidates": []}))
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = run("pipeline", "checks", "--run", "1")

    assert result.exit_code == 0
    assert result.output == f"{CHECKS_HEADER}\n"


def test_validate_a_run_left_in_validating(run, seeded, db_url, no_provider) -> None:
    _validating_run(db_url, fake_provider())
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "validating"
    assert run("pipeline", "checks", "--run", "1").output == f"{CHECKS_HEADER}\n"

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Pipeline run 1: passed\nPublished dataset version 1 for election 1\n"
    )
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "passed"
    assert run("pipeline", "checks", "--run", "1").output == PASSED_CHECKS


def test_validate_a_failing_run_left_in_validating(run, seeded, db_url, no_provider) -> None:
    _validating_run(db_url, fake_provider(position_findings=_invented_for_party2))

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FAILED_RUN_1
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[10]) == ("failed", "validation failed: evidence_quotes")


def test_validate_rejects_a_run_that_is_not_validating(run, seeded, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 is passed, expected validating\n"
    assert run("pipeline", "checks", "--run", "1").output.count("evidence_quotes") == 1


# validation-party-coverage Scenario 5: threshold config and coverage failures


def test_coverage_failure_is_committed_and_reported(run, seeded, use_fake, db_url) -> None:
    _fail_party2_document(db_url)
    use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == COVERAGE_FAILED_RUN_1
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[5], row[6], row[10]) == (
        "failed", "1", "30", "validation failed: party_coverage, statement_separation"
    )
    checks = run("pipeline", "checks", "--run", "1")
    assert checks.exit_code == 0, checks.output
    # Coverage names Party 2 once; separation names every Statement (intended).
    assert checks.output.splitlines() == [
        CHECKS_HEADER,
        "evidence_quotes\tpassed\t\t\t",
        PARTY2_ZERO,
        *ONLY_PARTY1_ROWS,
        *SHAPE_PASSED_ROWS,
    ]
    # The failed run keeps its candidate Dataset Version and every Party Position.
    positions = run("pipeline", "positions", "--dataset-version", "1")
    assert len(positions.output.splitlines()) == 61


def test_configured_threshold_is_used_by_pipeline_run(
    run, seeded, use_fake, db_url, monkeypatch
) -> None:
    _fail_party2_document(db_url)
    use_fake(fake_provider())
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", " 0 ")

    result = run("pipeline", "run", "--election", "1")

    # With 0% coverage passes; Party 2 without stances still fails separation.
    assert result.exit_code == 1
    assert result.stderr == SEPARATION_FAILED_RUN_1
    assert run("pipeline", "checks", "--run", "1").output.splitlines() == [
        CHECKS_HEADER,
        "evidence_quotes\tpassed\t\t\t",
        "party_coverage\tpassed\t\t\t",
        *ONLY_PARTY1_ROWS,
        *SHAPE_PASSED_ROWS,
    ]


@pytest.mark.parametrize("raw", ["abc", "0.7", "70%", "-1", "101"])
def test_invalid_threshold_creates_no_run(
    run, seeded, use_fake, db_url, monkeypatch, raw
) -> None:
    provider = use_fake(fake_provider())
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", raw)

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        f"Error: Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT '{raw}'; "
        "expected an integer from 0 to 100\n"
    )
    assert run_count(db_url) == 0
    assert provider.calls == []


def test_validate_with_invalid_threshold_leaves_the_run_validating(
    run, seeded, db_url, no_provider, monkeypatch
) -> None:
    _validating_run(db_url, fake_provider())
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "abc")

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT 'abc'; "
        "expected an integer from 0 to 100\n"
    )
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "validating"
    assert run("pipeline", "checks", "--run", "1").output == f"{CHECKS_HEADER}\n"


def test_validate_uses_the_configured_threshold(
    run, seeded, db_url, no_provider, monkeypatch
) -> None:
    _fail_party2_document(db_url)
    _validating_run(db_url, fake_provider())

    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "0")
    result = run("pipeline", "validate", "--run", "1")

    # With 0% coverage passes; Party 2 without stances still fails separation.
    assert result.exit_code == 1
    assert result.stderr == SEPARATION_FAILED_RUN_1
    assert run("pipeline", "checks", "--run", "1").output.splitlines()[2] == (
        "party_coverage\tpassed\t\t\t"
    )


def test_validate_reports_a_coverage_failure(run, seeded, db_url, no_provider) -> None:
    _fail_party2_document(db_url)
    _validating_run(db_url, fake_provider())

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == COVERAGE_FAILED_RUN_1
    assert run("pipeline", "checks", "--run", "1").output.splitlines()[2] == PARTY2_ZERO
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            stored = s.get(PipelineRun, 1)
            assert stored is not None and stored.status is PipelineRunStatus.FAILED
    finally:
        engine.dispose()


# validation-statement-separation Scenario 5: ``pipeline run`` / ``validate`` / ``checks``

EQUAL_ON_2_ROW = (
    "statement_separation\tfailed\t2\t\t"
    "statement 2 does not separate parties: all 2 parties with a stance have value 1"
)


def _party2_agrees_on_statement2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2's page-2 finding (Statement 2) takes value 1, equal to Party 1's."""
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    return {
        "findings": [
            f | {"value": 1} if f["statement"] == 2 else f for f in real["findings"]
        ]
    }


def test_separation_failure_is_committed_and_reported(run, seeded, use_fake) -> None:
    use_fake(fake_provider(position_findings=_party2_agrees_on_statement2))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == SEPARATION_FAILED_RUN_1
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[5], row[6], row[10]) == (
        "failed", "1", "30", "validation failed: statement_separation"
    )
    checks = run("pipeline", "checks", "--run", "1")
    assert checks.exit_code == 0, checks.output
    assert checks.output.splitlines() == [
        CHECKS_HEADER,
        "evidence_quotes\tpassed\t\t\t",
        "party_coverage\tpassed\t\t\t",
        EQUAL_ON_2_ROW,
        *SHAPE_PASSED_ROWS,
    ]
    # The failed run keeps its candidate Dataset Version and every Party Position.
    positions = run("pipeline", "positions", "--dataset-version", "1").output.splitlines()
    assert len(positions) == 61
    assert positions[3:5] == [
        f"2\t1\t1\t1\t2\t\t{PAGES[1][1]}",
        f"2\t2\t1\t2\t2\t\t{PAGES[2][1]}",
    ]


def test_validate_reports_a_separation_failure(run, seeded, db_url, no_provider) -> None:
    _validating_run(db_url, fake_provider(position_findings=_party2_agrees_on_statement2))

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == SEPARATION_FAILED_RUN_1
    assert run("pipeline", "checks", "--run", "1").output.splitlines()[1:] == [
        "evidence_quotes\tpassed\t\t\t",
        "party_coverage\tpassed\t\t\t",
        EQUAL_ON_2_ROW,
        *SHAPE_PASSED_ROWS,
    ]


# validation-questionnaire-shape Scenario 5: ``pipeline run`` / ``validate`` / ``checks``

COUNT_FAILED_RUN_1 = (
    'Error: pipeline run 1 failed: validation failed: statement_count; '
    'see "ideology pipeline checks --run 1"\n'
)
COUNT_20_ROW = "statement_count\tfailed\t\t\tquestionnaire has 20 statements; expected 25 to 35"


def test_default_run_prints_six_passed_checks(run, seeded, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0

    result = run("pipeline", "checks", "--run", "1")

    assert result.exit_code == 0, result.output
    assert result.output == PASSED_CHECKS
    assert len(result.output.splitlines()) == 7


def test_count_failure_is_committed_and_reported(run, seeded, use_fake) -> None:
    use_fake(fake_provider(generate_statements=statements_payload(20)))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == COUNT_FAILED_RUN_1
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[5], row[6], row[10]) == (
        "failed", "1", "20", "validation failed: statement_count"
    )
    assert run("pipeline", "checks", "--run", "1").output.splitlines() == [
        CHECKS_HEADER,
        "evidence_quotes\tpassed\t\t\t",
        "party_coverage\tpassed\t\t\t",
        "statement_separation\tpassed\t\t\t",
        "statement_uniqueness\tpassed\t\t\t",
        COUNT_20_ROW,
        "topic_spread\tpassed\t\t\t",
    ]
    # The failed run keeps its candidate Dataset Version and its 20 Statements.
    statements = run("pipeline", "statements", "--dataset-version", "1").output.splitlines()
    assert len(statements) == 21


def test_configured_statement_range_is_used_by_pipeline_run(
    run, seeded, use_fake, monkeypatch
) -> None:
    use_fake(fake_provider(generate_statements=statements_payload(20)))
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "20")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert "statement_count\tpassed" in run("pipeline", "checks", "--run", "1").output


def test_duplicate_and_topic_failures_are_named(run, seeded, use_fake) -> None:
    use_fake(
        fake_provider(
            generate_statements=statements_payload(topic=("economy", 15), duplicate=(2, 5))
        )
    )

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: pipeline run 1 failed: validation failed: statement_uniqueness, topic_spread; "
        'see "ideology pipeline checks --run 1"\n'
    )
    assert run("pipeline", "checks", "--run", "1").output.splitlines()[4:] == [
        "statement_uniqueness\tfailed\t5\t\tstatement 5 duplicates statement 2",
        "statement_count\tpassed\t\t\t",
        "topic_spread\tfailed\t\t\t"
        "topic economy has 15 of 30 statements (50%); maximum is 30%",
    ]


@pytest.mark.parametrize(
    ("name", "raw", "message"),
    [
        (
            "VALIDATION_MAX_TOPIC_SHARE_PERCENT",
            "abc",
            "Invalid VALIDATION_MAX_TOPIC_SHARE_PERCENT 'abc'; expected an integer from 0 to 100",
        ),
        (
            "VALIDATION_MIN_STATEMENTS",
            "2.5",
            "Invalid VALIDATION_MIN_STATEMENTS '2.5'; expected a positive integer",
        ),
        (
            "VALIDATION_MIN_STATEMENTS",
            "40",
            "Invalid statement count range: VALIDATION_MIN_STATEMENTS (40) is greater than "
            "VALIDATION_MAX_STATEMENTS (35)",
        ),
    ],
)
def test_invalid_shape_setting_creates_no_run(
    run, seeded, use_fake, db_url, monkeypatch, name, raw, message
) -> None:
    provider = use_fake(fake_provider())
    monkeypatch.setenv(name, raw)

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == f"Error: {message}\n"
    assert run_count(db_url) == 0
    assert provider.calls == []


def test_validate_with_invalid_topic_share_leaves_the_run_validating(
    run, seeded, db_url, no_provider, monkeypatch
) -> None:
    _validating_run(db_url, fake_provider())
    monkeypatch.setenv("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "abc")

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: Invalid VALIDATION_MAX_TOPIC_SHARE_PERCENT 'abc'; "
        "expected an integer from 0 to 100\n"
    )
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "validating"
    assert run("pipeline", "checks", "--run", "1").output == f"{CHECKS_HEADER}\n"


def test_validate_reports_a_count_failure(run, seeded, db_url, no_provider) -> None:
    _validating_run(db_url, fake_provider(generate_statements=statements_payload(20)))

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == COUNT_FAILED_RUN_1
    assert COUNT_20_ROW in run("pipeline", "checks", "--run", "1").output.splitlines()


# auto-publish-dataset-version Scenario 8: the publish line


PASSED_RUN = (
    "Pipeline run {run}: passed (dataset version {version}, 30 statements, "
    "60 party positions)\n"
)


def _election_status(run) -> str:
    lines = run("election", "list").output.splitlines()
    assert lines[0] == "id\tcountry\ttype\tdate\tstatus\tname"
    return lines[1].split("\t")[4]


def test_run_publishes_then_supersedes(run, seeded, use_fake) -> None:
    assert _election_status(run) == "draft"
    use_fake(fake_provider())

    first = run("pipeline", "run", "--election", "1")

    assert first.exit_code == 0, first.output
    assert first.output == (
        PASSED_RUN.format(run=1, version=1) + "Published dataset version 1 for election 1\n"
    )
    assert _election_status(run) == "active"
    statements_before = run("pipeline", "statements", "--dataset-version", "1").output
    positions_before = run("pipeline", "positions", "--dataset-version", "1").output

    use_fake(fake_provider())
    second = run("pipeline", "run", "--election", "1")

    assert second.exit_code == 0, second.output
    assert second.output == PASSED_RUN.format(run=2, version=2) + (
        "Published dataset version 2 for election 1 (superseded dataset version 1)\n"
    )
    assert _election_status(run) == "active"
    # The superseded version stays readable, unchanged.
    statements = run("pipeline", "statements", "--dataset-version", "1")
    positions = run("pipeline", "positions", "--dataset-version", "1")
    assert (statements.exit_code, positions.exit_code) == (0, 0)
    assert statements.output == statements_before
    assert positions.output == positions_before
    assert len(positions.output.splitlines()) == 61


def test_failing_run_after_a_publish_keeps_its_output(run, seeded, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    use_fake(fake_provider(position_findings=_invented_for_party2))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FAILED_RUN_1.replace("run 1", "run 2").replace("--run 1", "--run 2")
    assert _election_status(run) == "active"


def test_failing_first_run_leaves_the_election_draft(run, seeded, use_fake) -> None:
    use_fake(fake_provider(position_findings=_invented_for_party2))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == FAILED_RUN_1
    assert _election_status(run) == "draft"


def test_validate_an_older_run_after_a_newer_one_published(
    run, seeded, db_url, use_fake
) -> None:
    _validating_run(db_url, fake_provider())
    use_fake(fake_provider())
    newer = run("pipeline", "run", "--election", "1")
    assert newer.exit_code == 0, newer.output
    assert newer.output == (
        PASSED_RUN.format(run=2, version=2) + "Published dataset version 2 for election 1\n"
    )

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Pipeline run 1: passed\n"
        "Not published: dataset version 2 of newer pipeline run 2 is published for election 1\n"
    )
    listed = run("pipeline", "list", "--election", "1").output.splitlines()[1:]
    rows = [line.split("\t") for line in listed]
    assert [(r[0], r[1], r[5]) for r in rows] == [("1", "passed", "1"), ("2", "passed", "2")]


def test_validate_supersedes_an_older_published_run(run, seeded, db_url, use_fake) -> None:
    _validating_run(db_url, fake_provider())
    engine = make_engine(db_url)
    try:
        with session_scope(engine) as session:
            run2 = queue_run(
                session,
                1,
                llm_provider="fake",
                llm_model="fake-model",
                generation_mode=GenerationMode.PRECOMPUTED,
            ).id
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
            execute_run(engine, run2, fake_provider())
    finally:
        engine.dispose()
    assert run("pipeline", "validate", "--run", "1").output == (
        "Pipeline run 1: passed\nPublished dataset version 1 for election 1\n"
    )

    result = run("pipeline", "validate", "--run", "2")

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Pipeline run 2: passed\n"
        "Published dataset version 2 for election 1 (superseded dataset version 1)\n"
    )

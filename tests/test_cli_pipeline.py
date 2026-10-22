"""``ideology pipeline run|list|statements|positions|validate|checks`` with the fake provider.

pipeline-generate-statements Scenario 7, pipeline-extract-positions Scenario 10,
validation-evidence-quotes Scenario 7, validation-party-coverage Scenario 5 and
validation-questionnaire-shape Scenario 5, auto-publish-dataset-version
Scenario 8 and pipeline-coverage-selection (``--reuse-from``).
"""

import subprocess
from typing import Any

import pytest
from click.testing import CliRunner, Result
from pipeline_fixtures import (
    PAGES,
    chunk_pages,
    default_responses,
    fake_provider,
    findings_response,
    invent_quote_after_extraction,
    offline_guard,
    positions_response,
    seed_election,
    statements_payload,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.config import GenerationMode, ValidationSettings
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest, claude_code_provider
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
        "Pipeline run 1: passed (dataset version 1, 35 statements, 70 party positions)\n"
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
        "1", "passed", "fake", "fake-model", "precomputed", "1", "35", "7", str(in_tokens)
    ]
    assert int(row[9]) > 0
    assert row[10] == ""

    statements = run("pipeline", "statements", "--dataset-version", "1")
    assert statements.exit_code == 0, statements.output
    lines = statements.output.splitlines()
    assert lines[0] == "position\ttopic\ttext"
    # The selection keeps pool Statements 1..35 of the 50-Statement pool.
    expected = statements_payload()["statements"][:35]
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


def test_claude_code_cli_missing_creates_no_run(run, seeded, db_url, monkeypatch) -> None:
    """llm-provider-claude-code Scenario 8: the preflight fails before any write."""
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setenv("LLM_CLAUDE_CODE_BIN", "/nonexistent/claude")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: Claude Code CLI '/nonexistent/claude' not found on PATH; "
        "install it or set LLM_CLAUDE_CODE_BIN\n"
    )
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (1, '{"loggedIn": false, "authMethod": "none"}'),
        (0, '{"loggedIn": true, "authMethod": "api_key"}'),
    ],
    ids=["not-logged-in", "api-key"],
)
def test_claude_code_not_logged_in_creates_no_run(
    run, seeded, db_url, monkeypatch, returncode, stdout
) -> None:
    """llm-provider-claude-code Scenario 8: a failed ``claude auth status`` writes nothing."""
    calls: list[list[str]] = []

    def fake_cli(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setattr(claude_code_provider, "find_cli", lambda name: "/fake/bin/claude")
    monkeypatch.setattr(claude_code_provider, "run_cli", fake_cli)

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: Claude Code is ")
    assert calls == [["/fake/bin/claude", "auth", "status", "--json"]]
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    "name", ["LLM_CLAUDE_CODE_TIMEOUT_SECONDS", "LLM_CLAUDE_CODE_MAX_WAIT_HOURS"]
)
def test_claude_code_bad_setting_creates_no_run(run, seeded, db_url, monkeypatch, name) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setenv(name, "0")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == f"Error: Invalid {name} '0'; expected a positive integer\n"
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("LLM_PROVIDER", "Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, claude_code, fake\n"),
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
    # checked. Statements 3..25 have no stance (the selection fills up to 25
    # with them), so the run fails on statement_separation and keeps its
    # Dataset Version.
    use_fake(fake_provider(party_positions=positions_response()))
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "0")
    failed = run("pipeline", "run", "--election", "1")
    assert failed.exit_code == 1
    assert "validation failed: statement_separation;" in failed.stderr

    result = run("pipeline", "positions", "--dataset-version", "1")

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == POSITIONS_HEADER
    assert len(lines) == 51
    assert lines[1:5] == [
        f"1\t1\t1\t1\t1\t\t{PAGES[1][0]}",
        f"1\t2\t-1\t2\t1\t\t{PAGES[2][0]}",
        f"2\t1\t1\t1\t2\t\t{PAGES[1][1]}",
        f"2\t2\t-1\t2\t2\t\t{PAGES[2][1]}",
    ]
    assert lines[5:7] == ["3\t1\tno_stance\t\t\t\t", "3\t2\tno_stance\t\t\t\t"]
    assert [line.split("\t")[:2] for line in lines[1:]] == [
        [str(n), str(p)] for n in range(1, 26) for p in (1, 2)
    ]

    party = run("pipeline", "positions", "--dataset-version", "1", "--party", "2")
    assert party.exit_code == 0, party.output
    rows = party.output.splitlines()
    assert rows[0] == POSITIONS_HEADER
    assert len(rows) == 26
    assert all(row.split("\t")[1] == "2" for row in rows[1:])


def test_positions_show_negative_values_urls_and_one_line_quotes(
    run, seeded, use_fake, db_url, monkeypatch
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
            party_positions={"positions": [{"statement": 2, "value": -2, "evidence": 1}]},
        )
    )
    # Extraction would discard a quote that is on no page (pipeline-verified-
    # findings), so it is put in after extraction for both Parties.
    for party_id in (1, 2):
        invent_quote_after_extraction(
            monkeypatch, quote, party_id=party_id, statement=2, value=-2, page=2
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
# validation-questionnaire-shape: the default fake's 35 distinct Statements
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
    "party 2 has positions on 0 of 25 statements (0%); minimum is 50%"
)
# Party 2 without stances: no Statement separates the two Parties, so the
# selection keeps min_statements (25) of them.
ONLY_PARTY1_ROWS = [
    f"statement_separation\tfailed\t{n}\t\t"
    f"statement {n} does not separate parties: only party 1 has a stance (value 1)"
    for n in range(1, 26)
]


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


def _validating_run(
    db_url: str, provider: FakeProvider, settings: ValidationSettings | None = None
) -> None:
    """Leave run 1 in ``validating``, as before this feature or after a crash.

    ``settings`` bounds the selected Statement count (default 25..35); another
    range stands for a run generated with other thresholds.
    """
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
            execute_run(engine, run_id, provider, settings or ValidationSettings())
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


def test_run_failing_validation_is_committed_and_reported(
    run, seeded, use_fake, monkeypatch
) -> None:
    # The invented quote bypasses the extraction check (pipeline-verified-findings).
    invent_quote_after_extraction(monkeypatch, INVENTED)
    use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FAILED_RUN_1
    listed = run("pipeline", "list", "--election", "1").output.splitlines()
    assert len(listed) == 2
    row = listed[1].split("\t")
    assert row[1] == "failed"
    assert row[5:7] == ["1", "35"]
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


def test_checks_list_one_row_per_entry(run, seeded, use_fake, monkeypatch) -> None:
    # Every stance gets an invented quote after extraction (extraction itself
    # would discard them, pipeline-verified-findings).
    for party_id in (1, 2):
        for statement in (1, 2):
            invent_quote_after_extraction(
                monkeypatch,
                f"Inventada\t{statement}.",
                party_id=party_id,
                statement=statement,
                page=statement,
            )

    # Sparse (no fill): no Statement separates, so the selection keeps 25; each
    # Party covers 2 of them with value -1, so all three checks fail.
    use_fake(fake_provider(party_positions=positions_response()))
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
        "party 1 has positions on 2 of 25 statements (8%); minimum is 50%",
        "party_coverage\tfailed\t\t2\t"
        "party 2 has positions on 2 of 25 statements (8%); minimum is 50%",
        "statement_separation\tfailed\t1\t\t"
        "statement 1 does not separate parties: all 2 parties with a stance have value -1",
        "statement_separation\tfailed\t2\t\t"
        "statement 2 does not separate parties: all 2 parties with a stance have value -1",
        *(
            f"statement_separation\tfailed\t{n}\t\t"
            f"statement {n} does not separate parties: no party has a stance"
            for n in range(3, 26)
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


def test_validate_a_failing_run_left_in_validating(
    run, seeded, db_url, no_provider, monkeypatch
) -> None:
    invent_quote_after_extraction(monkeypatch, INVENTED)
    _validating_run(db_url, fake_provider())

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
        "failed", "1", "25", "validation failed: party_coverage, statement_separation"
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
    assert len(positions.output.splitlines()) == 51


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


# The selection drops a non-separating Statement while separating ones are
# left, so these runs keep the whole 50-Statement pool (min = max = 50).
WHOLE_POOL = ValidationSettings(min_statements=50, max_statements=50)


def _whole_pool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "50")
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "50")


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


def test_separation_failure_is_committed_and_reported(
    run, seeded, use_fake, monkeypatch
) -> None:
    _whole_pool_env(monkeypatch)
    use_fake(fake_provider(position_findings=_party2_agrees_on_statement2))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == SEPARATION_FAILED_RUN_1
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[5], row[6], row[10]) == (
        "failed", "1", "50", "validation failed: statement_separation"
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
    assert len(positions) == 101
    assert positions[3:5] == [
        f"2\t1\t1\t1\t2\t\t{PAGES[1][1]}",
        f"2\t2\t1\t2\t2\t\t{PAGES[2][1]}",
    ]


def test_validate_reports_a_separation_failure(
    run, seeded, db_url, no_provider, monkeypatch
) -> None:
    _validating_run(
        db_url, fake_provider(position_findings=_party2_agrees_on_statement2), WHOLE_POOL
    )
    _whole_pool_env(monkeypatch)

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


TWENTY = ValidationSettings(min_statements=20, max_statements=20)


def test_count_failure_is_committed_and_reported(run, seeded, db_url, no_provider) -> None:
    # The selection keeps the count inside the run's range, so the run is
    # generated and selected with a range of 20..20 and then validated with
    # the defaults.
    _validating_run(db_url, fake_provider(), TWENTY)

    result = run("pipeline", "validate", "--run", "1")

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


def test_out_of_range_count_fails_pipeline_run_at_generation(run, seeded, use_fake) -> None:
    use_fake(fake_provider(generate_statements=statements_payload(20)))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    reason = (
        "FakeProvider response for task 'generate_statements' does not match "
        "StatementSet: 1 validation error(s)"
    )
    assert result.stderr == f"Error: pipeline run 1 failed: {reason}\n"
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert (row[1], row[5], row[6], row[10]) == ("failed", "", "", reason)
    assert run("pipeline", "checks", "--run", "1").output == f"{CHECKS_HEADER}\n"


def test_configured_statement_range_is_used_by_pipeline_run(
    run, seeded, use_fake, monkeypatch
) -> None:
    use_fake(fake_provider())
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "20")
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "20")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert "20 statements, 40 party positions" in result.output
    assert "statement_count\tpassed" in run("pipeline", "checks", "--run", "1").output


def test_duplicate_and_topic_share_are_left_out_by_the_selection(
    run, seeded, use_fake
) -> None:
    # pipeline-coverage-selection: the later duplicate (pool 5) is left out and
    # economy is capped at 7 picks, so both checks pass. The run-level failures
    # of these checks are covered in test_validation_runs.py.
    use_fake(
        fake_provider(
            generate_statements=statements_payload(topic=("economy", 15), duplicate=(2, 5))
        )
    )

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert run("pipeline", "checks", "--run", "1").output.splitlines()[4:] == SHAPE_PASSED_ROWS
    statements = run("pipeline", "statements", "--dataset-version", "1").output.splitlines()
    assert sum(line.split("\t")[1] == "economy" for line in statements[1:]) == 7


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
    _validating_run(db_url, fake_provider(), TWENTY)

    result = run("pipeline", "validate", "--run", "1")

    assert result.exit_code == 1
    assert result.stderr == COUNT_FAILED_RUN_1
    assert COUNT_20_ROW in run("pipeline", "checks", "--run", "1").output.splitlines()


# auto-publish-dataset-version Scenario 8: the publish line


PASSED_RUN = (
    "Pipeline run {run}: passed (dataset version {version}, 35 statements, "
    "70 party positions)\n"
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
    assert len(positions.output.splitlines()) == 71


def test_failing_run_after_a_publish_keeps_its_output(
    run, seeded, use_fake, monkeypatch
) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    invent_quote_after_extraction(monkeypatch, INVENTED)
    use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FAILED_RUN_1.replace("run 1", "run 2").replace("--run 1", "--run 2")
    assert _election_status(run) == "active"


def test_failing_first_run_leaves_the_election_draft(
    run, seeded, use_fake, monkeypatch
) -> None:
    invent_quote_after_extraction(monkeypatch, INVENTED)
    use_fake(fake_provider())

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


# pipeline-coverage-selection: ``pipeline run --reuse-from``


def test_cli_reuse_from_prints_and_reuses(run, seeded, db_url, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    # --resume-from still refuses a run with a Dataset Version.
    refused = run("pipeline", "run", "--election", "1", "--resume-from", "1")
    assert refused.exit_code == 1
    assert "already has dataset version 1" in refused.stderr
    assert run_count(db_url) == 1

    provider = use_fake(fake_provider())
    result = run("pipeline", "run", "--election", "1", "--reuse-from", "1")

    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        "Pipeline run 2: reusing identical calls of run 1 (7 recorded calls)\n"
    )
    assert provider.calls == []
    report = run("pipeline", "report", "--run", "2").output
    assert "resumed_from: 1\n" in report
    assert "reused_calls: 7\n" in report


def test_reuse_from_refuses_an_unknown_run(run, seeded, db_url, use_fake) -> None:
    use_fake(fake_provider())
    result = run("pipeline", "run", "--election", "1", "--reuse-from", "99")
    assert result.exit_code == 1
    assert "pipeline run 99 not found" in result.stderr
    assert run_count(db_url) == 0


def test_reuse_from_and_resume_from_are_exclusive(run, seeded, db_url, use_fake) -> None:
    provider = use_fake(fake_provider())
    result = run(
        "pipeline", "run", "--election", "1", "--resume-from", "1", "--reuse-from", "1"
    )
    assert result.exit_code == 2
    assert "pass at most one of --resume-from or --reuse-from" in result.output
    assert run_count(db_url) == 0
    assert provider.calls == []


def test_reuse_from_still_runs_the_unfinished_guard(run, seeded, db_url, use_fake) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    # Run 2 stops after three recorded calls: an unfinished run.
    stopping = fake_provider(position_findings=_raise_provider_error)
    use_fake(stopping)
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    use_fake(fake_provider())
    result = run("pipeline", "run", "--election", "1", "--reuse-from", "1")

    # On this (non-shared) database the guard warns; the shared one refuses
    # (tests/test_shared_db.py).
    assert result.exit_code == 0, result.output
    assert (
        "Warning: election 1 has an unfinished run 2 (failed, 3 recorded calls); "
        "resume it with --resume-from 2, or pass --fresh to start from zero"
    ) in result.stderr
    fresh = run("pipeline", "run", "--election", "1", "--reuse-from", "1", "--fresh")
    assert fresh.exit_code == 0, fresh.output
    assert "Warning" not in fresh.stderr


def _raise_provider_error(request: LLMRequest[Any]) -> dict[str, Any]:
    raise LLMProviderError("usage limit beyond max wait")

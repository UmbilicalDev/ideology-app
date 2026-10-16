from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from ideology_app.cli import NOT_INITIALISED, _safe_url, main

CREATE_2023 = [
    "election", "create", "--country", "es", "--type", "general",
    "--date", "2023-07-23", "--name", "Elecciones generales 2023",
]


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def migrated(run) -> None:
    result = run("db", "upgrade")
    assert result.exit_code == 0, result.output


def test_db_upgrade_creates_schema_and_is_repeatable(run, tmp_path: Path) -> None:
    first = run("db", "upgrade")
    second = run("db", "upgrade")

    assert first.exit_code == 0, first.output
    assert first.output.strip() == f"Database at sqlite:///{tmp_path}/test.db is at head"
    assert second.exit_code == 0
    assert (tmp_path / "test.db").exists()


def test_safe_url_hides_password() -> None:
    assert _safe_url("postgresql://user:secret@db/x") == "postgresql://user:***@db/x"


@pytest.mark.parametrize("url", ["nonsense", "postgresql+nosuchdriver://user:secret@db/x"])
def test_unusable_database_url_is_a_clean_error(url: str) -> None:
    result = CliRunner().invoke(main, ["--database-url", url, "election", "list"])

    assert result.exit_code == 1
    assert result.output.startswith("Error: invalid database URL")
    assert "secret" not in result.output


def test_missing_driver_is_a_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str) -> None:
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr("ideology_app.cli.make_engine", fail)

    result = CliRunner().invoke(main, ["--database-url", "postgresql://db/x", "db", "upgrade"])

    assert result.exit_code == 1
    assert result.output == "Error: database driver not installed: No module named 'psycopg'\n"


@pytest.mark.usefixtures("migrated")
def test_create_and_list_election_with_parties(run) -> None:
    created = run(*CREATE_2023)
    sumar = run("party", "add", "--election", "1", "--name", "Sumar", "--short-name", "SUMAR")
    pp = run("party", "add", "--election", "1", "--name", "Partido Popular", "--short-name", "PP")

    assert (created.exit_code, created.output) == (0, "Created election 1\n")
    assert (sumar.exit_code, sumar.output) == (0, "Created party 1\n")
    assert (pp.exit_code, pp.output) == (0, "Created party 2\n")

    elections = run("election", "list")
    assert elections.exit_code == 0
    assert elections.output.splitlines() == [
        "id\tcountry\ttype\tdate\tstatus\tname",
        "1\tES\tgeneral\t2023-07-23\tdraft\tElecciones generales 2023",
    ]

    parties = run("party", "list", "--election", "1")
    assert parties.exit_code == 0
    assert parties.output.splitlines() == [
        "id\tshort_name\tname",
        "1\tSUMAR\tSumar",
        "2\tPP\tPartido Popular",
    ]


@pytest.mark.usefixtures("migrated")
def test_empty_lists_print_only_the_header(run) -> None:
    assert run("election", "list").output == "id\tcountry\ttype\tdate\tstatus\tname\n"
    run(*CREATE_2023)
    assert run("party", "list", "--election", "1").output == "id\tshort_name\tname\n"


@pytest.mark.usefixtures("migrated")
@pytest.mark.parametrize(
    ("option", "value", "field"),
    [
        ("--country", "ESP", "country"),
        ("--country", "1A", "country"),
        ("--type", "regional", "type"),
        ("--name", "  ", "name"),
    ],
)
def test_invalid_election_input_exits_1(run, option: str, value: str, field: str) -> None:
    args = list(CREATE_2023)
    args[args.index(option) + 1] = value

    result = run(*args)

    assert result.exit_code == 1
    assert result.output.startswith("Error: ") and field in result.output
    assert run("election", "list").output.count("\n") == 1


@pytest.mark.usefixtures("migrated")
def test_malformed_date_is_a_click_usage_error(run) -> None:
    args = list(CREATE_2023)
    args[args.index("--date") + 1] = "23/07/2023"

    result = run(*args)

    assert result.exit_code == 2
    assert "--date" in result.output
    assert run("election", "list").output.count("\n") == 1


@pytest.mark.usefixtures("migrated")
@pytest.mark.parametrize(("name", "short_name"), [("", "X"), ("X", " ")])
def test_invalid_party_input_exits_1(run, name: str, short_name: str) -> None:
    run(*CREATE_2023)

    result = run("party", "add", "--election", "1", "--name", name, "--short-name", short_name)

    assert result.exit_code == 1
    assert result.output.startswith("Error: ")
    assert run("party", "list", "--election", "1").output.count("\n") == 1


@pytest.mark.usefixtures("migrated")
def test_duplicates_and_unknown_election_exit_1(run) -> None:
    run(*CREATE_2023)
    run("party", "add", "--election", "1", "--name", "Sumar", "--short-name", "SUMAR")

    dup_election = run(*CREATE_2023)
    dup_name = run("party", "add", "--election", "1", "--name", "Sumar", "--short-name", "S2")
    dup_short = run("party", "add", "--election", "1", "--name", "Other", "--short-name", "SUMAR")
    missing = run("party", "add", "--election", "999", "--name", "Sumar", "--short-name", "SUMAR")
    missing_list = run("party", "list", "--election", "999")

    for result in (dup_election, dup_name, dup_short):
        assert result.exit_code == 1
        assert "already exists" in result.output
    for result in (missing, missing_list):
        assert result.exit_code == 1
        assert result.output == "Error: election 999 not found\n"
    assert run("election", "list").output.count("\n") == 2
    assert run("party", "list", "--election", "1").output.count("\n") == 2

    other = run(
        "election", "create", "--country", "ES", "--type", "general",
        "--date", "2019-11-10", "--name", "Elecciones generales 2019",
    )
    same_name = run("party", "add", "--election", "2", "--name", "Sumar", "--short-name", "SUMAR")
    assert other.exit_code == 0 and same_name.exit_code == 0


@pytest.mark.parametrize(
    "args",
    [
        ["election", "list"],
        CREATE_2023,
        ["party", "add", "--election", "1", "--name", "Sumar", "--short-name", "SUMAR"],
        ["party", "list", "--election", "1"],
    ],
    ids=["election-list", "election-create", "party-add", "party-list"],
)
def test_unmigrated_database_is_reported(run, args: list[str]) -> None:
    result = run(*args)

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
    assert result.exception is None or isinstance(result.exception, SystemExit)

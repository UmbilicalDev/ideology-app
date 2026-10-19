"""Checks ``statement_uniqueness``, ``statement_count`` and ``topic_spread`` on plain data.

validation-questionnaire-shape Scenarios 1-4, the registry tuple and purity.
No database, LLM or network. Run-level and CLI cases (Scenario 5) live in
``test_validation_runs.py`` and ``test_cli_pipeline.py``.
"""

from collections.abc import Sequence

import pytest
from pipeline_fixtures import offline_guard

from ideology_app.config import (
    DEFAULT_MAX_STATEMENTS,
    DEFAULT_MAX_TOPIC_SHARE_PERCENT,
    DEFAULT_MIN_STATEMENTS,
    ConfigError,
    ValidationSettings,
    validation_settings,
)
from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PARTY_COVERAGE,
    STATEMENT_COUNT,
    STATEMENT_SEPARATION,
    STATEMENT_UNIQUENESS,
    TOPIC_SPREAD,
    ReportEntry,
    StatementRow,
    ValidationInput,
)
from ideology_app.validation.statement_count import check_statement_count
from ideology_app.validation.statement_uniqueness import check_statement_uniqueness
from ideology_app.validation.topic_spread import check_topic_spread


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def rows(texts: Sequence[str], topics: Sequence[str] | None = None) -> tuple[StatementRow, ...]:
    """Statements at positions 1..n with ids 101..100+n (topic ``economy`` by default)."""
    topics = topics or ["economy"] * len(texts)
    return tuple(
        StatementRow(id=100 + n, position=n, text=text, topic=topic)
        for n, (text, topic) in enumerate(zip(texts, topics, strict=True), start=1)
    )


def distinct(count: int) -> list[str]:
    return [
        f"Afirmación {n}: el Estado debe actuar en el ámbito {n}." for n in range(1, count + 1)
    ]


def data(
    statements: tuple[StatementRow, ...], settings: ValidationSettings | None = None
) -> ValidationInput:
    return ValidationInput(
        statements=statements,
        positions=(),
        party_ids=(1, 2),
        settings=settings or ValidationSettings(),
    )


def counted(count: int, settings: ValidationSettings | None = None) -> ValidationInput:
    topics = [f"topic{n % 18}" for n in range(count)]
    return data(rows(distinct(count), topics), settings)


def spread(topics: Sequence[str], settings: ValidationSettings | None = None) -> ValidationInput:
    return data(rows(distinct(len(topics)), topics), settings)


# Registry


def test_registry_appends_the_three_checks_in_order() -> None:
    assert CHECKS == (
        EVIDENCE_QUOTES,
        PARTY_COVERAGE,
        STATEMENT_SEPARATION,
        STATEMENT_UNIQUENESS,
        STATEMENT_COUNT,
        TOPIC_SPREAD,
    )
    assert [c.name for c in CHECKS[3:]] == [
        "statement_uniqueness", "statement_count", "topic_spread"
    ]
    assert STATEMENT_UNIQUENESS.run is check_statement_uniqueness
    assert STATEMENT_COUNT.run is check_statement_count
    assert TOPIC_SPREAD.run is check_topic_spread


def test_checks_are_pure_and_deterministic() -> None:
    texts = [*distinct(10), "afirmación 1: el estado debe actuar en el ámbito 1"]
    sample = data(rows(texts, ["economy"] * 6 + ["health"] * 5))
    before = sample
    for check in (STATEMENT_UNIQUENESS, STATEMENT_COUNT, TOPIC_SPREAD):
        first = check.run(sample)
        assert first == check.run(sample)
        assert first  # every check fails on this sample
    assert sample == before


# Scenario 1: Statement count


def test_twenty_statements_give_one_run_level_entry() -> None:
    result = STATEMENT_COUNT.run(counted(20))
    assert result == [ReportEntry("questionnaire has 20 statements; expected 25 to 35")]
    assert (result[0].statement_id, result[0].party_id) == (None, None)


@pytest.mark.parametrize("count", [24, 36, 1, 60])
def test_counts_outside_the_default_range_fail(count: int) -> None:
    assert STATEMENT_COUNT.run(counted(count)) == [
        ReportEntry(f"questionnaire has {count} statements; expected 25 to 35")
    ]


@pytest.mark.parametrize("count", [25, 30, 35])
def test_counts_inside_the_default_range_pass(count: int) -> None:
    assert STATEMENT_COUNT.run(counted(count)) == []


def test_zero_statements_fail_the_count() -> None:
    assert STATEMENT_COUNT.run(data(())) == [
        ReportEntry("questionnaire has 0 statements; expected 25 to 35")
    ]


def test_custom_range_is_read_from_settings() -> None:
    settings = ValidationSettings(min_statements=10, max_statements=20)
    assert STATEMENT_COUNT.run(counted(20, settings)) == []
    assert STATEMENT_COUNT.run(counted(10, settings)) == []
    assert STATEMENT_COUNT.run(counted(21, settings)) == [
        ReportEntry("questionnaire has 21 statements; expected 10 to 20")
    ]
    assert STATEMENT_COUNT.run(counted(9, settings)) == [
        ReportEntry("questionnaire has 9 statements; expected 10 to 20")
    ]


def test_single_value_range_accepts_only_that_count() -> None:
    settings = ValidationSettings(min_statements=30, max_statements=30)
    assert STATEMENT_COUNT.run(counted(30, settings)) == []
    for count in (29, 31):
        assert STATEMENT_COUNT.run(counted(count, settings)) == [
            ReportEntry(f"questionnaire has {count} statements; expected 30 to 30")
        ]


# Scenario 2: duplicates


def test_duplicate_names_the_later_statement_and_the_first() -> None:
    texts = distinct(6)
    texts[4] = texts[1]
    result = STATEMENT_UNIQUENESS.run(data(rows(texts)))
    assert result == [ReportEntry("statement 5 duplicates statement 2", statement_id=105)]
    assert result[0].party_id is None


@pytest.mark.parametrize(
    "variant",
    [
        "el estado debe subir el iva",
        "El  Estado debe subir el IVA",
        "EL ESTADO DEBE SUBIR EL IVA!",
        "Él Estado débe subir el IVA.",
        "  El Estado debe subir el IVA.  ",
        "El Estado debe subir el I.V.A.",
    ],
)
def test_case_accents_whitespace_and_punctuation_are_ignored(variant: str) -> None:
    texts = ["El Estado debe subir el IVA.", "Otra afirmación.", variant]
    assert STATEMENT_UNIQUENESS.run(data(rows(texts))) == [
        ReportEntry("statement 3 duplicates statement 1", statement_id=103)
    ]


def test_spec_example_three_variants_are_all_duplicates() -> None:
    texts = [
        "El Estado debe subir el IVA.",
        "el estado debe subir el iva",
        "El  Estado debe subir el IVA",
    ]
    assert STATEMENT_UNIQUENESS.run(data(rows(texts))) == [
        ReportEntry("statement 2 duplicates statement 1", statement_id=102),
        ReportEntry("statement 3 duplicates statement 1", statement_id=103),
    ]


def test_same_text_with_different_topics_is_a_duplicate() -> None:
    statements = rows(["Subir el IVA.", "Subir el IVA."], ["economy", "taxation"])
    assert STATEMENT_UNIQUENESS.run(data(statements)) == [
        ReportEntry("statement 2 duplicates statement 1", statement_id=102)
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("El Estado debe subir el IVA.", "El Estado debe bajar el IVA."),
        ("Subir el IVA al 21 %.", "Subir el IVA al 22 %."),
        ("El Estado debe subir el IVA.", "El IVA debe subir el Estado."),
    ],
)
def test_one_word_one_digit_or_word_order_difference_is_not_a_duplicate(
    first: str, second: str
) -> None:
    assert STATEMENT_UNIQUENESS.run(data(rows([first, second]))) == []


def test_three_copies_give_two_entries_in_statement_order() -> None:
    texts = distinct(10)
    texts[3] = texts[0]
    texts[8] = texts[0]
    assert STATEMENT_UNIQUENESS.run(data(rows(texts))) == [
        ReportEntry("statement 4 duplicates statement 1", statement_id=104),
        ReportEntry("statement 9 duplicates statement 1", statement_id=109),
    ]


def test_two_duplicate_groups_are_reported_in_statement_order() -> None:
    texts = distinct(6)
    texts[3] = texts[1]
    texts[4] = texts[0]
    assert STATEMENT_UNIQUENESS.run(data(rows(texts))) == [
        ReportEntry("statement 4 duplicates statement 2", statement_id=104),
        ReportEntry("statement 5 duplicates statement 1", statement_id=105),
    ]


def test_zero_or_one_statement_has_no_duplicates() -> None:
    assert STATEMENT_UNIQUENESS.run(data(())) == []
    assert STATEMENT_UNIQUENESS.run(data(rows(["Única."]))) == []


def test_distinct_statements_pass() -> None:
    assert STATEMENT_UNIQUENESS.run(counted(30)) == []


# Scenario 3: topic spread


def test_half_on_one_topic_gives_one_run_level_entry() -> None:
    topics = ["economy"] * 15 + [f"topic{n}" for n in range(15)]
    result = TOPIC_SPREAD.run(spread(topics))
    assert result == [
        ReportEntry("topic economy has 15 of 30 statements (50%); maximum is 30%")
    ]
    assert (result[0].statement_id, result[0].party_id) == (None, None)


def test_exactly_the_maximum_passes() -> None:
    topics = ["economy"] * 9 + [f"topic{n}" for n in range(21)]
    assert TOPIC_SPREAD.run(spread(topics)) == []


def test_one_above_the_maximum_fails_with_the_ceiling_percent() -> None:
    topics = ["economy"] * 10 + [f"topic{n}" for n in range(20)]
    assert TOPIC_SPREAD.run(spread(topics)) == [
        ReportEntry("topic economy has 10 of 30 statements (34%); maximum is 30%")
    ]


def test_eight_of_thirty_passes() -> None:
    topics = ["economy"] * 8 + [f"topic{n}" for n in range(22)]
    assert TOPIC_SPREAD.run(spread(topics)) == []


def test_two_offending_topics_in_order_of_first_appearance() -> None:
    topics = ["health"] + ["economy"] * 10 + ["health"] * 9 + [f"topic{n}" for n in range(10)]
    assert TOPIC_SPREAD.run(spread(topics)) == [
        ReportEntry("topic health has 10 of 30 statements (34%); maximum is 30%"),
        ReportEntry("topic economy has 10 of 30 statements (34%); maximum is 30%"),
    ]


def test_zero_statements_report_nothing() -> None:
    assert TOPIC_SPREAD.run(data(())) == []


def test_share_100_accepts_a_single_topic() -> None:
    settings = ValidationSettings(max_topic_share_percent=100)
    assert TOPIC_SPREAD.run(spread(["economy"] * 30, settings)) == []


def test_share_0_fails_every_topic_present() -> None:
    settings = ValidationSettings(max_topic_share_percent=0)
    assert TOPIC_SPREAD.run(spread(["economy", "health", "economy"], settings)) == [
        ReportEntry("topic economy has 2 of 3 statements (67%); maximum is 0%"),
        ReportEntry("topic health has 1 of 3 statements (34%); maximum is 0%"),
    ]


def test_default_fake_spread_passes() -> None:
    assert TOPIC_SPREAD.run(counted(30)) == []


# Scenario 4: settings and configuration


def test_settings_defaults() -> None:
    settings = ValidationSettings()
    assert (
        settings.min_party_coverage_percent,
        settings.min_statements,
        settings.max_statements,
        settings.max_topic_share_percent,
    ) == (70, 25, 35, 30)
    assert (DEFAULT_MIN_STATEMENTS, DEFAULT_MAX_STATEMENTS, DEFAULT_MAX_TOPIC_SHARE_PERCENT) == (
        25, 35, 30
    )


@pytest.mark.parametrize("field", ["min_statements", "max_statements"])
@pytest.mark.parametrize("value", [0, -1, 2.5, "30", True, None])
def test_settings_reject_bad_counts(field: str, value: object) -> None:
    kwargs: dict[str, object] = {"min_statements": 1, "max_statements": 100, field: value}
    with pytest.raises(ValueError, match="integer of at least 1"):
        ValidationSettings(**kwargs)  # type: ignore[arg-type]


def test_settings_reject_min_above_max() -> None:
    with pytest.raises(ValueError, match="min_statements must not be greater than max_statements"):
        ValidationSettings(min_statements=31, max_statements=30)
    with pytest.raises(ValueError):
        ValidationSettings(min_statements=40)


@pytest.mark.parametrize("value", [-1, 101, 30.0, "30", True, None])
def test_settings_reject_bad_topic_share(value: object) -> None:
    with pytest.raises(ValueError, match="^max_topic_share_percent must be an integer from 0 to"):
        ValidationSettings(max_topic_share_percent=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, 100])
def test_settings_accept_topic_share_bounds(value: int) -> None:
    assert ValidationSettings(max_topic_share_percent=value).max_topic_share_percent == value


def test_env_unset_gives_defaults() -> None:
    assert validation_settings() == ValidationSettings()


@pytest.mark.parametrize(
    ("name", "raw", "field", "expected"),
    [
        ("VALIDATION_MIN_STATEMENTS", "", "min_statements", 25),
        ("VALIDATION_MIN_STATEMENTS", "   ", "min_statements", 25),
        ("VALIDATION_MIN_STATEMENTS", " 28 ", "min_statements", 28),
        ("VALIDATION_MIN_STATEMENTS", "1", "min_statements", 1),
        ("VALIDATION_MAX_STATEMENTS", " 28 ", "max_statements", 28),
        ("VALIDATION_MAX_STATEMENTS", "60", "max_statements", 60),
        ("VALIDATION_MAX_STATEMENTS", "", "max_statements", 35),
        ("VALIDATION_MAX_TOPIC_SHARE_PERCENT", " 28 ", "max_topic_share_percent", 28),
        ("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "0", "max_topic_share_percent", 0),
        ("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "100", "max_topic_share_percent", 100),
        ("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "", "max_topic_share_percent", 30),
    ],
)
def test_env_values_are_read(
    monkeypatch: pytest.MonkeyPatch, name: str, raw: str, field: str, expected: int
) -> None:
    monkeypatch.setenv(name, raw)
    assert getattr(validation_settings(), field) == expected


@pytest.mark.parametrize("name", ["VALIDATION_MIN_STATEMENTS", "VALIDATION_MAX_STATEMENTS"])
@pytest.mark.parametrize("raw", ["0", "-1", "2.5", "abc", "+5", "30%", "٣٠"])
def test_invalid_count_env_raises(monkeypatch: pytest.MonkeyPatch, name: str, raw: str) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == f"Invalid {name} {raw!r}; expected a positive integer"


@pytest.mark.parametrize("raw", ["abc", "0.3", "30%", "-1", "101", "+5"])
def test_invalid_topic_share_env_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VALIDATION_MAX_TOPIC_SHARE_PERCENT", raw)
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == (
        f"Invalid VALIDATION_MAX_TOPIC_SHARE_PERCENT {raw!r}; expected an integer from 0 to 100"
    )


def test_min_above_default_max_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "40")
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == (
        "Invalid statement count range: VALIDATION_MIN_STATEMENTS (40) is greater than "
        "VALIDATION_MAX_STATEMENTS (35)"
    )


def test_max_below_default_min_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "20")
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == (
        "Invalid statement count range: VALIDATION_MIN_STATEMENTS (25) is greater than "
        "VALIDATION_MAX_STATEMENTS (20)"
    )


def test_custom_range_and_share_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "10")
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "10")
    monkeypatch.setenv("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "50")
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "60")
    assert validation_settings() == ValidationSettings(
        min_party_coverage_percent=60,
        min_statements=10,
        max_statements=10,
        max_topic_share_percent=50,
    )


@pytest.mark.parametrize(
    ("env", "expected_start"),
    [
        # coverage before min
        (
            {"VALIDATION_MIN_PARTY_COVERAGE_PERCENT": "x", "VALIDATION_MIN_STATEMENTS": "x"},
            "Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT",
        ),
        # min before max
        (
            {"VALIDATION_MIN_STATEMENTS": "x", "VALIDATION_MAX_STATEMENTS": "x"},
            "Invalid VALIDATION_MIN_STATEMENTS",
        ),
        # max before range
        (
            {"VALIDATION_MIN_STATEMENTS": "40", "VALIDATION_MAX_STATEMENTS": "x"},
            "Invalid VALIDATION_MAX_STATEMENTS",
        ),
        # range before share
        (
            {"VALIDATION_MIN_STATEMENTS": "40", "VALIDATION_MAX_TOPIC_SHARE_PERCENT": "x"},
            "Invalid statement count range",
        ),
        # coverage before share
        (
            {
                "VALIDATION_MIN_PARTY_COVERAGE_PERCENT": "x",
                "VALIDATION_MAX_TOPIC_SHARE_PERCENT": "x",
            },
            "Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT",
        ),
    ],
)
def test_first_error_wins_in_documented_order(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected_start: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value).startswith(expected_start)

"""``config.source_refetch_interval`` (live-mode-url-refetch Scenario 4)."""

import datetime as dt

import pytest

from ideology_app import config
from ideology_app.config import ConfigError, source_refetch_interval

VAR = "SOURCE_REFETCH_INTERVAL_HOURS"


@pytest.mark.parametrize("raw", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_default_interval_is_six_hours(monkeypatch: pytest.MonkeyPatch, raw: str | None) -> None:
    if raw is None:
        monkeypatch.delenv(VAR, raising=False)
    else:
        monkeypatch.setenv(VAR, raw)

    assert source_refetch_interval() == dt.timedelta(hours=6)
    assert config.DEFAULT_SOURCE_REFETCH_INTERVAL_HOURS == 6


@pytest.mark.parametrize(("raw", "hours"), [("1", 1), (" 12 ", 12), ("168", 168)])
def test_interval_in_whole_hours(monkeypatch: pytest.MonkeyPatch, raw: str, hours: int) -> None:
    monkeypatch.setenv(VAR, raw)

    assert source_refetch_interval() == dt.timedelta(hours=hours)


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "6h", "+6", "seis", "٦"])
def test_invalid_interval_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(VAR, raw)

    with pytest.raises(ConfigError) as info:
        source_refetch_interval()
    assert str(info.value) == f"Invalid {VAR} {raw!r}; expected a positive integer"


# llm-provider-claude-code: ``claude_code_settings`` and the default model

CLAUDE_CODE_VARS = (
    "LLM_CLAUDE_CODE_BIN",
    "LLM_CLAUDE_CODE_TIMEOUT_SECONDS",
    "LLM_CLAUDE_CODE_MAX_WAIT_HOURS",
)


@pytest.fixture
def _no_claude_code_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*CLAUDE_CODE_VARS, "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("_no_claude_code_env")
def test_claude_code_settings_defaults() -> None:
    assert config.claude_code_settings() == config.ClaudeCodeSettings(
        bin="claude", timeout_seconds=900, max_wait_hours=48
    )


@pytest.mark.usefixtures("_no_claude_code_env")
def test_claude_code_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CLAUDE_CODE_BIN", " /opt/claude/bin/claude ")
    monkeypatch.setenv("LLM_CLAUDE_CODE_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LLM_CLAUDE_CODE_MAX_WAIT_HOURS", " 1 ")

    assert config.claude_code_settings() == config.ClaudeCodeSettings(
        bin="/opt/claude/bin/claude", timeout_seconds=60, max_wait_hours=1
    )


@pytest.mark.usefixtures("_no_claude_code_env")
@pytest.mark.parametrize(
    "name", ["LLM_CLAUDE_CODE_TIMEOUT_SECONDS", "LLM_CLAUDE_CODE_MAX_WAIT_HOURS"]
)
@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "2h", "+3"])
def test_claude_code_settings_invalid(monkeypatch: pytest.MonkeyPatch, name: str, raw: str) -> None:
    monkeypatch.setenv(name, raw)

    with pytest.raises(ConfigError) as info:
        config.claude_code_settings()
    assert str(info.value) == f"Invalid {name} {raw!r}; expected a positive integer"


@pytest.mark.usefixtures("_no_claude_code_env")
def test_claude_code_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "Claude_Code")

    assert config.llm_settings() == config.LLMSettings(
        provider="claude_code", model="claude-sonnet-4-6"
    )
    monkeypatch.setenv("LLM_MODEL", "sonnet")
    assert config.llm_settings().model == "sonnet"


# pipeline-statement-priority-tiers, scenario 12: questionnaire lengths and the
# minimum Parties with a side.

_VALIDATION_VARS = (
    "VALIDATION_MIN_PARTY_COVERAGE_PERCENT",
    "VALIDATION_MIN_STATEMENTS",
    "VALIDATION_MAX_STATEMENTS",
    "VALIDATION_MAX_TOPIC_SHARE_PERCENT",
    "VALIDATION_CONTEXT_NOTE_MIN_CHARS",
    "VALIDATION_CONTEXT_NOTE_MAX_CHARS",
    "VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS",
    "VALIDATION_QUESTIONNAIRE_LENGTHS",
    "VALIDATION_MIN_STATEMENT_PARTIES",
)
LENGTHS = "VALIDATION_QUESTIONNAIRE_LENGTHS"
MIN_PARTIES = "VALIDATION_MIN_STATEMENT_PARTIES"


@pytest.fixture
def _no_validation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VALIDATION_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("_no_validation_env")
def test_priority_tier_defaults() -> None:
    settings = config.validation_settings()
    assert (settings.min_statements, settings.max_statements) == (35, 40)
    assert settings.questionnaire_lengths == (15, 30) == config.DEFAULT_QUESTIONNAIRE_LENGTHS
    assert settings.min_statement_parties == 3 == config.DEFAULT_MIN_STATEMENT_PARTIES
    assert config.ValidationSettings() == settings


@pytest.mark.usefixtures("_no_validation_env")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", (15, 30)),
        ("   ", (15, 30)),
        ("15,30", (15, 30)),
        (" 10 , 20 ", (10, 20)),
        ("34", (34,)),
        ("1,2,3", (1, 2, 3)),
        ("none", ()),
        ("NONE", ()),
        (" None ", ()),
    ],
)
def test_questionnaire_lengths_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: tuple[int, ...]
) -> None:
    monkeypatch.setenv(LENGTHS, raw)
    assert config.validation_settings().questionnaire_lengths == expected


@pytest.mark.usefixtures("_no_validation_env")
@pytest.mark.parametrize(
    "raw",
    ["15,15", "30,15", "0", "0,15", "15,35", "35", "40", "-15", "+15", "15.0", "15,,30",
     "15,", ",15", "quince", "15;30", "١٥"],
)
def test_invalid_questionnaire_lengths_raise(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(LENGTHS, raw)
    with pytest.raises(ConfigError) as info:
        config.validation_settings()
    assert str(info.value) == (
        f"Invalid {LENGTHS} {raw!r}; expected increasing positive integers below "
        "VALIDATION_MIN_STATEMENTS (35), or none"
    )


@pytest.mark.usefixtures("_no_validation_env")
def test_lengths_are_checked_against_the_configured_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "20")
    monkeypatch.setenv(LENGTHS, "10,20")
    with pytest.raises(ConfigError, match=r"below VALIDATION_MIN_STATEMENTS \(20\)"):
        config.validation_settings()
    monkeypatch.setenv(LENGTHS, "10,19")
    assert config.validation_settings().questionnaire_lengths == (10, 19)
    # The default lengths are never dropped silently: they must fit too.
    monkeypatch.delenv(LENGTHS)
    with pytest.raises(ConfigError) as info:
        config.validation_settings()
    assert str(info.value) == (
        f"Invalid {LENGTHS}: the default 15,30 is not below VALIDATION_MIN_STATEMENTS (20); "
        "set lower lengths or none"
    )


@pytest.mark.usefixtures("_no_validation_env")
@pytest.mark.parametrize(("raw", "expected"), [("", 3), ("1", 1), (" 5 ", 5), ("12", 12)])
def test_min_statement_parties_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    monkeypatch.setenv(MIN_PARTIES, raw)
    assert config.validation_settings().min_statement_parties == expected


@pytest.mark.usefixtures("_no_validation_env")
@pytest.mark.parametrize("raw", ["0", "-1", "2.5", "+3", "tres"])
def test_invalid_min_statement_parties_raise(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(MIN_PARTIES, raw)
    with pytest.raises(ConfigError) as info:
        config.validation_settings()
    assert str(info.value) == f"Invalid {MIN_PARTIES} {raw!r}; expected a positive integer"


@pytest.mark.usefixtures("_no_validation_env")
def test_lengths_are_checked_before_min_parties(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LENGTHS, "x")
    monkeypatch.setenv(MIN_PARTIES, "x")
    with pytest.raises(ConfigError, match=f"^Invalid {LENGTHS}"):
        config.validation_settings()
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS", ",")
    with pytest.raises(ConfigError, match="^Invalid VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS"):
        config.validation_settings()


@pytest.mark.parametrize(
    "lengths",
    [(15, 15), (30, 15), (0,), (15, 35), (35,), [15, 30], (15.0,), (True,), ("15",), None],
)
def test_settings_reject_bad_lengths(lengths: object) -> None:
    with pytest.raises(ValueError, match="^questionnaire_lengths must be"):
        config.ValidationSettings(questionnaire_lengths=lengths)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, -1, 2.5, True, "3", None])
def test_settings_reject_bad_min_statement_parties(value: object) -> None:
    with pytest.raises(ValueError, match="^min_statement_parties must be"):
        config.ValidationSettings(min_statement_parties=value)  # type: ignore[arg-type]


def test_settings_accept_no_shorter_length() -> None:
    assert config.ValidationSettings(questionnaire_lengths=()).questionnaire_lengths == ()
    assert config.ValidationSettings(questionnaire_lengths=(34,)).questionnaire_lengths == (34,)


# constituency-selection-validation: ``constituency_settings`` (K3, K4)

V2_VARS = ("VALIDATION_V2_MIN_STATEMENTS", "VALIDATION_V2_MIN_PARTY_SIDES")


def test_constituency_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in V2_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = config.constituency_settings()

    assert settings == config.ConstituencySettings(10, 5)
    assert (config.DEFAULT_V2_MIN_STATEMENTS, config.DEFAULT_V2_MIN_PARTY_SIDES) == (10, 5)
    # Kept apart from ValidationSettings, so legacy runs record what they recorded before.
    assert not set(config.ConstituencySettings.__dataclass_fields__) & set(
        config.ValidationSettings.__dataclass_fields__
    )


def test_constituency_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", " 20 ")
    monkeypatch.setenv("VALIDATION_V2_MIN_PARTY_SIDES", "1")

    assert config.constituency_settings() == config.ConstituencySettings(20, 1)


@pytest.mark.parametrize("name", V2_VARS)
@pytest.mark.parametrize("raw", ["0", "1.5", "x", "-3", "+2"])
def test_invalid_constituency_settings_raise(
    monkeypatch: pytest.MonkeyPatch, name: str, raw: str
) -> None:
    for other in V2_VARS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(name, raw)

    with pytest.raises(ConfigError) as info:
        config.constituency_settings()
    assert str(info.value) == f"Invalid {name} {raw!r}; expected a positive integer"


@pytest.mark.parametrize("values", [(0, 5), (10, 0), (True, 5), (10, 1.5)])
def test_constituency_settings_reject_bad_values(values: tuple[object, object]) -> None:
    with pytest.raises(ValueError):
        config.ConstituencySettings(*values)  # type: ignore[arg-type]

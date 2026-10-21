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

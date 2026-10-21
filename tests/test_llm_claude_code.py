"""``ClaudeCodeProvider`` (llm-provider-claude-code), fully offline.

The CLI is never started: every test injects a fake runner (or patches the
module seams), a fake clock and a fake sleep. The autouse guard replaces the
module's ``run_cli`` and ``find_cli`` seams with failing stubs, unsets the LLM
and Claude Code variables and blocks sockets.
"""

import datetime as dt
import json
import os
import socket
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from pydantic import BaseModel, Field

from ideology_app.config import ClaudeCodeSettings, LLMSettings, llm_settings
from ideology_app.llm import (
    PROVIDERS,
    ClaudeCodeProvider,
    LLMConfigError,
    LLMOutputError,
    LLMProviderError,
    LLMRequest,
    LLMResult,
    build_provider,
    claude_code_provider,
)
from ideology_app.llm.claude_code_provider import (
    TRANSIENT_BACKOFF,
    TRANSIENT_RETRIES,
    USAGE_LIMIT_FALLBACK_WAIT,
    USAGE_LIMIT_MARGIN,
    child_env,
    parse_reset_text,
)

GUARDED_ENV = (
    "ANTHROPIC_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "GENERATION_MODE",
    "LLM_CLAUDE_CODE_BIN",
    "LLM_CLAUDE_CODE_TIMEOUT_SECONDS",
    "LLM_CLAUDE_CODE_MAX_WAIT_HOURS",
)

BIN = "/fake/bin/claude"
MODEL = "claude-sonnet-4-6"
SECRET_PROMPT = "SECRET-PROMPT-MARKER manifesto text"
NOW = dt.datetime(2026, 10, 21, 11, 0, tzinfo=dt.UTC)  # 13:00 in Europe/Madrid (CEST)


@pytest.fixture(autouse=True)
def _offline_and_clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real CLI, key, LLM setting or socket can be reached."""
    for name in GUARDED_ENV:
        monkeypatch.delenv(name, raising=False)

    def _no_cli(*args: object, **kwargs: object) -> None:
        raise AssertionError("the real Claude Code CLI must not run in tests")

    monkeypatch.setattr(claude_code_provider, "run_cli", _no_cli)
    monkeypatch.setattr(claude_code_provider, "find_cli", _no_cli)

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is blocked in LLM tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class DemoOutput(BaseModel):
    answer: str
    items: list[str] = Field(max_length=3)


def demo_request(task: str = "demo", max_tokens: int = 4096) -> LLMRequest[DemoOutput]:
    return LLMRequest(
        task=task,
        system="You answer in JSON.",
        prompt=SECRET_PROMPT,
        schema=DemoOutput,
        max_tokens=max_tokens,
    )


# Envelope builders (shapes observed in Claude Code 2.1.110)


def init_message() -> dict[str, Any]:
    return {"type": "system", "subtype": "init", "model": MODEL, "tools": ["StructuredOutput"]}


def result_message(**fields: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 2,
        "result": "",
        "usage": {
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
        },
    }
    message.update(fields)
    return message


def success(output: Any = None, **usage: int) -> str:
    output = {"answer": "yes", "items": ["a"]} if output is None else output
    counts = {
        "input_tokens": 10,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 3000,
        "output_tokens": 40,
        **usage,
    }
    return json.dumps(
        [
            init_message(),
            {"type": "assistant", "message": {"content": []}},
            result_message(structured_output=output, usage=counts),
        ]
    )


def api_error(
    text: str,
    *,
    status: int | None = None,
    assistant_error: str | None = None,
    subtype: str = "success",
    rate_limit: dict[str, Any] | None = None,
) -> str:
    messages: list[dict[str, Any]] = [init_message()]
    if rate_limit is not None:
        messages.append({"type": "rate_limit_event", "rate_limit_info": rate_limit})
    assistant: dict[str, Any] = {"type": "assistant", "message": {"content": []}}
    if assistant_error is not None:
        assistant["error"] = assistant_error
    messages.append(assistant)
    fields: dict[str, Any] = {"subtype": subtype, "is_error": True, "result": text}
    if status is not None:
        fields["api_error_status"] = status
    messages.append(result_message(**fields))
    return json.dumps(messages)


def usage_limit(text: str = "You've hit your session limit", **kwargs: Any) -> str:
    return api_error(text, status=429, assistant_error="rate_limit", **kwargs)


Outcome = str | BaseException


class FakeRunner:
    """Returns (or raises) one scripted outcome per call and records each call."""

    def __init__(self, *outcomes: Outcome, returncode: int | None = None) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.returncode = returncode

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None,
        env: dict[str, str],
        cwd: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {
                "argv": list(argv),
                "input": input,
                "env": dict(env),
                "cwd": cwd,
                "cwd_listing": os.listdir(cwd),
                "timeout": timeout,
            }
        )
        if not self.outcomes:
            raise AssertionError("unexpected extra CLI call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if self.returncode is not None:
            code = self.returncode
        else:
            code = 1 if '"is_error": true' in outcome else 0
        return subprocess.CompletedProcess(list(argv), code, stdout=outcome, stderr="")


class FakeTime:
    """A controlled clock; ``sleep`` advances it."""

    def __init__(self, now: dt.datetime = NOW) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def clock(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


LOGGED_IN = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"})


def make_provider(
    *outcomes: Outcome,
    time: FakeTime | None = None,
    max_wait_hours: int = 48,
    returncode: int | None = None,
    auth_status: str = LOGGED_IN,
) -> tuple[ClaudeCodeProvider, FakeRunner, FakeTime, list[str]]:
    """A provider whose preflight sees ``auth_status``; then ``outcomes`` per call."""
    time = time or FakeTime()
    runner = FakeRunner(auth_status, *outcomes, returncode=returncode)
    logs: list[str] = []
    provider = ClaudeCodeProvider(
        MODEL,
        settings=ClaudeCodeSettings(bin="claude", timeout_seconds=900, max_wait_hours=max_wait_hours),
        runner=runner,
        which=lambda name: BIN,
        clock=time.clock,
        sleep=time.sleep,
        log=logs.append,
    )
    runner.calls.clear()  # drop the preflight call
    return provider, runner, time, logs


EXPECTED_SCHEMA = json.dumps(DemoOutput.model_json_schema())
EXPECTED_ARGV = [
    BIN,
    "-p",
    "--output-format",
    "json",
    "--verbose",
    "--model",
    MODEL,
    "--system-prompt",
    "You answer in JSON.",
    "--json-schema",
    EXPECTED_SCHEMA,
    "--tools",
    "",
    "--no-session-persistence",
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--disable-slash-commands",
]


# Scenario 1: registry


def test_registry_builds_claude_code_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    preflight = FakeRunner(LOGGED_IN)
    monkeypatch.setattr(claude_code_provider, "find_cli", lambda name: BIN)
    monkeypatch.setattr(claude_code_provider, "run_cli", preflight)

    settings = llm_settings()
    provider = build_provider(settings)

    assert settings == LLMSettings(provider="claude_code", model="claude-sonnet-4-6")
    assert isinstance(provider, ClaudeCodeProvider)
    assert provider.name == "claude_code"
    assert provider.model == "claude-sonnet-4-6"
    assert repr(provider) == "ClaudeCodeProvider(model='claude-sonnet-4-6')"
    assert [call["argv"] for call in preflight.calls] == [[BIN, "auth", "status", "--json"]]
    provider.close()


def test_registry_lists_three_providers() -> None:
    from ideology_app.config import DEFAULT_MODELS

    assert set(PROVIDERS) == set(DEFAULT_MODELS) == {"anthropic", "claude_code", "fake"}
    assert DEFAULT_MODELS["claude_code"] == "claude-sonnet-4-6"


# Scenario 2: invocation


def test_generate_runs_cli_once_with_exact_argv_stdin_cwd_env_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, runner, _, logs = make_provider(success())

    result = provider.generate(demo_request(max_tokens=8192))

    assert result == LLMResult(
        output=DemoOutput(answer="yes", items=["a"]),
        provider="claude_code",
        model=MODEL,
        input_tokens=10 + 200 + 3000,
        output_tokens=40,
    )
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["argv"] == EXPECTED_ARGV
    assert "--bare" not in call["argv"]
    assert call["input"] == SECRET_PROMPT
    assert SECRET_PROMPT not in call["argv"]
    assert call["timeout"] == 900
    assert call["cwd_listing"] == []  # a fresh empty directory...
    assert os.path.basename(call["cwd"]).startswith("ideology-claude-")
    assert not os.path.exists(call["cwd"])  # ...removed after the call
    assert call["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8192"
    assert logs == []


def test_child_env_strips_credentials_and_session_vars() -> None:
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/op",
        "ANTHROPIC_API_KEY": "dummy-not-a-key",
        "ANTHROPIC_AUTH_TOKEN": "dummy",
        "ANTHROPIC_BASE_URL": "http://proxy",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "sdk",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_SIMPLE": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-token",
        "CLAUDE_CONFIG_DIR": "/home/op/.claude",
    }

    env = child_env(4096, base)

    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/op",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-token",
        "CLAUDE_CONFIG_DIR": "/home/op/.claude",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_THINKING": "1",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
    }


def test_generate_passes_sanitised_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-key")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription-token")
    provider, runner, _, _ = make_provider(success())

    provider.generate(demo_request())

    env = runner.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDECODE" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-token"
    assert env["PATH"] == os.environ["PATH"]


def test_generate_accepts_non_verbose_result_object() -> None:
    envelope = result_message(
        structured_output={"answer": "ok", "items": []},
        usage={"input_tokens": 7, "output_tokens": 3},
    )
    provider, _, _, _ = make_provider(json.dumps(envelope))

    result = provider.generate(demo_request())

    assert result.output == DemoOutput(answer="ok", items=[])
    assert (result.input_tokens, result.output_tokens) == (7, 3)


def test_missing_or_bad_usage_counts_as_zero() -> None:
    envelope = result_message(
        structured_output={"answer": "ok", "items": []},
        usage={"input_tokens": "many", "output_tokens": True},
    )
    provider, _, _, _ = make_provider(json.dumps(envelope))

    result = provider.generate(demo_request())

    assert (result.input_tokens, result.output_tokens) == (0, 0)


# Scenario 3: schema mismatch


@pytest.mark.parametrize(
    "stdout",
    [
        success({"answer": "yes", "items": ["a", "b", "c", "d"]}),
        success({"answer": 3}),
        json.dumps([init_message(), result_message()]),  # no structured_output
        api_error(
            "Failed to provide valid structured output",
            subtype="error_max_structured_output_retries",
        ),
        api_error("Output limit reached", assistant_error="max_output_tokens"),
    ],
    ids=["too-many-items", "wrong-types", "missing", "max-structured-retries", "max-output-tokens"],
)
def test_schema_mismatch_raises_output_error(stdout: str) -> None:
    provider, runner, time, _ = make_provider(stdout)

    with pytest.raises(LLMOutputError) as info:
        provider.generate(demo_request("statement_candidates"))

    message = str(info.value)
    assert "'statement_candidates'" in message
    assert "DemoOutput" in message
    assert SECRET_PROMPT not in message
    assert len(runner.calls) == 1
    assert time.sleeps == []


# Scenario 4: usage limit, then success


def _assert_waited_until(time: FakeTime, target: dt.datetime) -> None:
    assert time.now == target
    assert time.sleeps and all(0 < s <= 60 for s in time.sleeps)


def _assert_retried_identically(runner: FakeRunner) -> None:
    assert len(runner.calls) == 2
    first, second = runner.calls
    assert first["argv"] == second["argv"] == EXPECTED_ARGV
    assert first["input"] == second["input"] == SECRET_PROMPT


def test_usage_limit_from_rate_limit_event_waits_then_retries() -> None:
    reset = NOW + dt.timedelta(hours=2)
    limited = usage_limit(
        "You've hit your session limit · resets 1pm (UTC)",
        rate_limit={
            "status": "rejected",
            "resetsAt": int(reset.timestamp()),
            "rateLimitType": "five_hour",
        },
    )
    provider, runner, time, logs = make_provider(limited, success())

    result = provider.generate(demo_request())

    assert result.output == DemoOutput(answer="yes", items=["a"])
    target = reset + USAGE_LIMIT_MARGIN
    _assert_waited_until(time, target)
    _assert_retried_identically(runner)
    assert logs == [
        "claude_code: usage limit reached (task demo); waiting until "
        f"{target.astimezone().isoformat(timespec='minutes')} before retrying (Ctrl-C to stop)"
    ]


def test_rate_limit_event_alone_is_a_usage_limit() -> None:
    reset = NOW + dt.timedelta(minutes=30)
    limited = api_error(
        "API Error: 429",
        status=429,
        rate_limit={"status": "rejected", "resetsAt": int(reset.timestamp())},
    )
    provider, runner, time, logs = make_provider(limited, success())

    provider.generate(demo_request())

    _assert_waited_until(time, reset + USAGE_LIMIT_MARGIN)
    _assert_retried_identically(runner)
    assert len(logs) == 1


@pytest.mark.parametrize(
    ("text", "reset"),
    [
        (
            "You've hit your session limit · resets 3pm (Europe/Madrid)",
            dt.datetime(2026, 10, 21, 13, 0, tzinfo=dt.UTC),
        ),
        (
            "You've hit your weekly limit · resets Oct 23, 3:30pm (Europe/Madrid)",
            dt.datetime(2026, 10, 23, 13, 30, tzinfo=dt.UTC),
        ),
        (
            "You're out of extra usage · resets 9am (Europe/Madrid)",  # already past: tomorrow
            dt.datetime(2026, 10, 22, 7, 0, tzinfo=dt.UTC),
        ),
    ],
    ids=["time-only", "date-and-time", "out-of-extra-usage-tomorrow"],
)
def test_usage_limit_reset_parsed_from_text(text: str, reset: dt.datetime) -> None:
    provider, runner, time, logs = make_provider(
        usage_limit(text), success(), max_wait_hours=72
    )

    provider.generate(demo_request())

    _assert_waited_until(time, reset + USAGE_LIMIT_MARGIN)
    _assert_retried_identically(runner)
    assert len(logs) == 1


@pytest.mark.parametrize(
    "text",
    [
        "You've hit your usage limit",
        "You've hit your limit · resets sometime soon",
        "You've hit your Opus limit · resets 3pm (Mars/Olympus_Mons)",
    ],
    ids=["missing", "unparsable", "unknown-zone"],
)
def test_usage_limit_without_reset_waits_fallback_and_probes(text: str) -> None:
    provider, runner, time, logs = make_provider(usage_limit(text), success())

    provider.generate(demo_request())

    _assert_waited_until(time, NOW + USAGE_LIMIT_FALLBACK_WAIT)
    _assert_retried_identically(runner)
    assert len(logs) == 1


def test_usage_limit_reset_in_the_past_waits_at_least_a_minute() -> None:
    reset = NOW - dt.timedelta(minutes=10)
    limited = usage_limit(rate_limit={"status": "rejected", "resetsAt": int(reset.timestamp())})
    provider, _, time, _ = make_provider(limited, success())

    provider.generate(demo_request())

    assert time.now == NOW + dt.timedelta(seconds=60)


def test_usage_limit_wait_is_measured_on_the_clock_not_by_sleeps() -> None:
    """If the machine sleeps, one sleep call may take far longer than asked."""

    class JumpyTime(FakeTime):
        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += dt.timedelta(minutes=50)

    time = JumpyTime()
    reset = NOW + dt.timedelta(hours=2)
    limited = usage_limit(rate_limit={"status": "rejected", "resetsAt": int(reset.timestamp())})
    provider, runner, _, _ = make_provider(limited, success(), time=time)

    provider.generate(demo_request())

    assert len(time.sleeps) == 3  # 50 + 50 + 50 min passes reset + 2 min
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("x · resets 3pm (Europe/Madrid)", dt.datetime(2026, 10, 21, 13, 0, tzinfo=dt.UTC)),
        ("x · resets 12am (UTC)", dt.datetime(2026, 10, 22, 0, 0, tzinfo=dt.UTC)),
        ("x · resets 12pm (UTC)", dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)),
        ("x · resets 11:05am (UTC)", dt.datetime(2026, 10, 21, 11, 5, tzinfo=dt.UTC)),
        ("x · resets 10:59am (UTC)", dt.datetime(2026, 10, 22, 10, 59, tzinfo=dt.UTC)),
        (
            "x · resets Jan 2, 2027, 3pm (Europe/Madrid)",
            dt.datetime(2027, 1, 2, 14, 0, tzinfo=dt.UTC),
        ),
        ("x · resets 13pm (UTC)", None),
        ("x · resets Foo 2, 3pm (UTC)", None),
        ("x · resets Feb 30, 3pm (UTC)", None),
        ("x resets 3pm (UTC)", None),
    ],
)
def test_parse_reset_text(text: str, expected: dt.datetime | None) -> None:
    assert parse_reset_text(text, NOW) == expected


# Scenario 5: wait budget


def test_reset_beyond_max_wait_fails_without_sleeping() -> None:
    reset = NOW + dt.timedelta(hours=3)
    limited = usage_limit(rate_limit={"status": "rejected", "resetsAt": int(reset.timestamp())})
    provider, runner, time, logs = make_provider(limited, max_wait_hours=1)

    with pytest.raises(LLMProviderError) as info:
        provider.generate(demo_request())

    message = str(info.value)
    assert f"resets at {reset.astimezone().isoformat(timespec='minutes')}" in message
    assert "beyond the configured maximum wait of 1 h" in message
    assert "LLM_CLAUDE_CODE_MAX_WAIT_HOURS" in message
    assert time.sleeps == []
    assert logs == []
    assert len(runner.calls) == 1


def test_cumulative_waits_beyond_max_wait_fail() -> None:
    limited = usage_limit("You've hit your usage limit")
    provider, runner, time, logs = make_provider(limited, limited, limited, max_wait_hours=1)

    with pytest.raises(LLMProviderError, match="beyond the configured maximum wait of 1 h"):
        provider.generate(demo_request())

    assert len(runner.calls) == 3
    assert time.now == NOW + 2 * USAGE_LIMIT_FALLBACK_WAIT  # two 30-minute waits, then stop
    assert len(logs) == 2


# Scenario 6: transient errors


TRANSIENT_OUTCOMES: list[Any] = [
    pytest.param(
        api_error(
            "API Error: Server is temporarily limiting requests (not your usage limit) · retry",
            status=429,
            assistant_error="rate_limit",
        ),
        id="429-not-your-usage-limit",
    ),
    *[
        pytest.param(api_error(f"API Error: {code}", status=code), id=f"http-{code}")
        for code in (500, 502, 503, 504, 529)
    ],
    pytest.param(api_error("API Error", assistant_error="server_error"), id="server-error"),
    pytest.param(subprocess.TimeoutExpired(["claude"], 900), id="timeout"),
]


@pytest.mark.parametrize("failure", TRANSIENT_OUTCOMES)
def test_transient_errors_retry_with_backoff_then_fail(failure: Outcome) -> None:
    provider, runner, time, logs = make_provider(*[failure] * (TRANSIENT_RETRIES + 1))

    with pytest.raises(LLMProviderError) as info:
        provider.generate(demo_request("party_positions"))

    assert "'party_positions'" in str(info.value)
    assert f"gave up after {TRANSIENT_RETRIES} retries" in str(info.value)
    assert len(runner.calls) == TRANSIENT_RETRIES + 1
    assert time.sleeps == [30, 120, 300] == list(TRANSIENT_BACKOFF)
    assert len(logs) == TRANSIENT_RETRIES
    assert all(call["argv"] == EXPECTED_ARGV for call in runner.calls)


@pytest.mark.parametrize("failure", TRANSIENT_OUTCOMES)
def test_transient_error_then_success_returns(failure: Outcome) -> None:
    provider, runner, time, logs = make_provider(failure, success())

    result = provider.generate(demo_request())

    assert result.output == DemoOutput(answer="yes", items=["a"])
    assert len(runner.calls) == 2
    assert time.sleeps == [30]
    assert len(logs) == 1 and "retry 1 of 3 in 30 s" in logs[0]


# Scenario 7: other errors


@pytest.mark.parametrize(
    "stdout",
    [
        api_error("Failed to authenticate. API Error: 401", status=401),
        api_error("API Error: 403 forbidden", status=403),
        api_error("Failed to authenticate", assistant_error="authentication_failed"),
    ],
    ids=["401", "403", "authentication_failed"],
)
def test_auth_failure_is_config_error_without_retry(stdout: str) -> None:
    provider, runner, time, _ = make_provider(stdout)

    with pytest.raises(LLMConfigError) as info:
        provider.generate(demo_request())

    assert "Claude Code is not logged in or its login expired; run `claude auth login`" in str(
        info.value
    )
    assert len(runner.calls) == 1
    assert time.sleeps == []


@pytest.mark.parametrize(
    "stdout",
    [
        "not json at all",
        json.dumps([init_message()]),
        json.dumps({"type": "assistant"}),
        json.dumps(42),
        api_error("Execution failed", subtype="error_during_execution"),
        api_error("Too many turns", subtype="error_max_turns"),
        api_error("Budget exceeded", subtype="error_max_budget_usd"),
        api_error("API Error: 400 bad request", status=400, assistant_error="invalid_request"),
        api_error("Credit balance is too low", assistant_error="billing_error"),
        api_error("Something odd", assistant_error="unknown"),
        api_error("Something new", subtype="error_from_the_future"),
    ],
    ids=[
        "non-json",
        "no-result",
        "dict-not-result",
        "scalar",
        "error_during_execution",
        "error_max_turns",
        "error_max_budget_usd",
        "invalid_request",
        "billing_error",
        "unknown",
        "unknown-subtype",
    ],
)
def test_other_errors_are_provider_errors_without_retry(stdout: str) -> None:
    provider, runner, time, logs = make_provider(stdout)

    with pytest.raises(LLMProviderError) as info:
        provider.generate(demo_request("generate_statements"))

    assert "'generate_statements'" in str(info.value)
    assert len(runner.calls) == 1
    assert time.sleeps == []
    assert logs == []


def test_error_message_has_details_but_no_prompt_env_or_long_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-key")
    long_text = "Credit balance is too low. " + "x" * 500
    provider, _, _, _ = make_provider(
        api_error(long_text, status=402, assistant_error="billing_error")
    )

    with pytest.raises(LLMProviderError) as info:
        provider.generate(demo_request("generate_statements"))

    message = str(info.value)
    assert "task 'generate_statements'" in message
    assert "subtype='success'" in message
    assert "api_error_status=402" in message
    assert "exit 1" in message
    assert "Credit balance is too low." in message
    assert "x" * 201 not in message
    assert len(message) < 400
    assert SECRET_PROMPT not in message
    assert "dummy-not-a-key" not in message


def test_non_json_stdout_reports_at_most_200_chars_of_stderr() -> None:
    class StderrRunner(FakeRunner):
        def __call__(self, argv, **kwargs):  # type: ignore[override]
            super().__call__(argv, **kwargs)
            return subprocess.CompletedProcess(list(argv), 2, stdout="", stderr="E" * 1000)

    runner = StderrRunner("")
    provider = ClaudeCodeProvider(
        MODEL,
        settings=ClaudeCodeSettings(),
        runner=_preflight_then(runner),
        which=lambda name: BIN,
        clock=FakeTime().clock,
        sleep=FakeTime().sleep,
        log=lambda line: None,
    )

    with pytest.raises(LLMProviderError) as info:
        provider.generate(demo_request())

    assert "exit 2" in str(info.value)
    assert "E" * 201 not in str(info.value)


def _preflight_then(runner: Callable[..., Any]) -> Callable[..., Any]:
    """Answer the preflight with LOGGED_IN, then delegate to ``runner``."""

    def _run(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if list(argv)[1:] == ["auth", "status", "--json"]:
            return subprocess.CompletedProcess(list(argv), 0, stdout=LOGGED_IN, stderr="")
        return runner(argv, **kwargs)

    return _run


def test_os_error_starting_cli_is_provider_error() -> None:
    provider, runner, _, _ = make_provider(FileNotFoundError("claude"))

    with pytest.raises(LLMProviderError, match="could not start: FileNotFoundError"):
        provider.generate(demo_request())
    assert len(runner.calls) == 1


# Ctrl-C keeps ending the run (runs.py records ``failed: interrupted``)


def test_keyboard_interrupt_during_usage_wait_propagates() -> None:
    class InterruptedTime(FakeTime):
        def sleep(self, seconds: float) -> None:
            raise KeyboardInterrupt

    provider, runner, _, _ = make_provider(usage_limit(), time=InterruptedTime())

    with pytest.raises(KeyboardInterrupt):
        provider.generate(demo_request())
    assert len(runner.calls) == 1


def test_keyboard_interrupt_during_cli_call_propagates() -> None:
    provider, _, _, _ = make_provider(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        provider.generate(demo_request())


# Scenario 8: preflight (CLI missing or not logged in)


def test_cli_not_found_is_config_error() -> None:
    with pytest.raises(LLMConfigError) as info:
        ClaudeCodeProvider(
            MODEL,
            settings=ClaudeCodeSettings(),
            runner=FakeRunner(),
            which=lambda name: None,
        )
    assert str(info.value) == (
        "Claude Code CLI 'claude' not found on PATH; install it or set LLM_CLAUDE_CODE_BIN"
    )


def test_preflight_runs_auth_status_in_temp_dir_with_sanitised_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-key")
    runner = FakeRunner(LOGGED_IN)

    ClaudeCodeProvider(
        MODEL, settings=ClaudeCodeSettings(), runner=runner, which=lambda name: BIN
    )

    (call,) = runner.calls
    assert call["argv"] == [BIN, "auth", "status", "--json"]
    assert call["input"] is None
    assert call["timeout"] == 30
    assert call["cwd_listing"] == []
    assert "ANTHROPIC_API_KEY" not in call["env"]


@pytest.mark.parametrize("method", ["claude.ai", "oauth_token"])
def test_preflight_accepts_subscription_logins(method: str) -> None:
    status = json.dumps({"loggedIn": True, "authMethod": method})
    provider, _, _, _ = make_provider(auth_status=status)
    assert provider.model == MODEL


@pytest.mark.parametrize(
    ("returncode", "stdout", "fragment"),
    [
        (1, json.dumps({"loggedIn": False}), "not logged in"),
        (0, json.dumps({"loggedIn": False, "authMethod": "claude.ai"}), "not logged in"),
        (0, "garbage", "Could not read"),
        (0, json.dumps([1, 2]), "not logged in"),
        (0, json.dumps({"loggedIn": True, "authMethod": "api_key"}), "'api_key', not a Claude"),
        (0, json.dumps({"loggedIn": True}), "'None', not a Claude"),
    ],
    ids=["exit-1", "logged-out", "unparsable", "not-an-object", "api-key", "no-method"],
)
def test_preflight_rejects(returncode: int, stdout: str, fragment: str) -> None:
    runner = FakeRunner(stdout, returncode=returncode)

    with pytest.raises(LLMConfigError) as info:
        ClaudeCodeProvider(
            MODEL, settings=ClaudeCodeSettings(), runner=runner, which=lambda name: BIN
        )
    assert fragment in str(info.value)


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired(["claude"], 30), PermissionError("denied")]
)
def test_preflight_cannot_run_is_config_error(failure: BaseException) -> None:
    with pytest.raises(LLMConfigError):
        ClaudeCodeProvider(
            MODEL, settings=ClaudeCodeSettings(), runner=FakeRunner(failure), which=lambda n: BIN
        )


def test_invalid_settings_raise_config_error_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CLAUDE_CODE_MAX_WAIT_HOURS", "forever")

    with pytest.raises(ValueError, match="LLM_CLAUDE_CODE_MAX_WAIT_HOURS"):
        ClaudeCodeProvider(MODEL)  # the guard's find_cli would fail if it were reached


# Scenario 9: offline guard


def test_guard_blocks_the_real_cli_and_sockets() -> None:
    with pytest.raises(AssertionError, match="must not run"):
        claude_code_provider.run_cli(["claude"], input=None, env={}, cwd=".", timeout=1)
    with pytest.raises(AssertionError, match="must not run"):
        claude_code_provider.find_cli("claude")
    with pytest.raises(AssertionError, match="network access is blocked"):
        socket.create_connection(("example.com", 443))
    assert all(name not in os.environ for name in GUARDED_ENV)

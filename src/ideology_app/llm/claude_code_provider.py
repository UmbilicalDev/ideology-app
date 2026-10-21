"""Claude Code adapter: each call runs the Operator's local ``claude -p`` CLI.

For local Operator use only (never a deployment or anything serving Voters):
the calls use the Operator's own Claude subscription, so no API key is read.
This is the only module that may spawn the ``claude`` CLI. Every call runs in a
fresh empty temporary directory with no tools, no settings, no MCP servers and
a child environment stripped of ``ANTHROPIC_*`` / ``CLAUDE*`` variables.

When the CLI reports the subscription usage limit, ``generate`` waits in-process
until the reported reset (plus a margin) and retries the identical call, up to
``LLM_CLAUDE_CODE_MAX_WAIT_HOURS`` in total. Transient errors are retried a few
times with backoff; anything else fails closed.

Tests replace the module-level seams ``run_cli`` and ``find_cli`` (or inject
``runner`` / ``which``) and never start the real CLI.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from ideology_app.config import ClaudeCodeSettings, claude_code_settings
from ideology_app.llm.base import (
    LLMConfigError,
    LLMOutputError,
    LLMProviderError,
    LLMRequest,
    LLMResult,
)

TRANSIENT_RETRIES = 3
TRANSIENT_BACKOFF: tuple[int, ...] = (30, 120, 300)  # seconds, one per retry
USAGE_LIMIT_MARGIN = dt.timedelta(minutes=2)
USAGE_LIMIT_FALLBACK_WAIT = dt.timedelta(minutes=30)
USAGE_LIMIT_MIN_WAIT = dt.timedelta(seconds=60)
SLEEP_SLICE_SECONDS = 60.0
PREFLIGHT_TIMEOUT_SECONDS = 30
DETAIL_MAX_CHARS = 200

SUBSCRIPTION_AUTH_METHODS = frozenset({"claude.ai", "oauth_token"})
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
AUTH_STATUSES = frozenset({401, 403})
USAGE_LIMIT_PREFIXES = ("You've hit your", "You're out of extra usage")
RESET_MARKER = " · resets "

# Environment variables kept although they match a stripped prefix.
ENV_KEEP = frozenset({"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"})
ENV_STRIP_PREFIXES = ("ANTHROPIC_", "CLAUDE")
ENV_SET = {
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_THINKING": "1",
}

NOT_LOGGED_IN = (
    "Claude Code is not logged in or its login expired; run `claude auth login`"
)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def run_cli(
    argv: Sequence[str],
    *,
    input: str | None,
    env: Mapping[str, str],
    cwd: str,
    timeout: float,
) -> "subprocess.CompletedProcess[str]":
    """Run the CLI once and capture its output (the seam tests replace)."""
    return subprocess.run(
        list(argv),
        input=input,
        env=dict(env),
        cwd=cwd,
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def find_cli(name: str) -> str | None:
    """Resolve the CLI on ``PATH`` (the seam tests replace)."""
    return shutil.which(name)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stderr_log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _clip(text: object) -> str:
    """At most ``DETAIL_MAX_CHARS`` characters of ``text`` on one line."""
    flat = " ".join(str(text).split())
    if len(flat) > DETAIL_MAX_CHARS:
        return flat[:DETAIL_MAX_CHARS] + "…"
    return flat


def child_env(max_tokens: int, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The CLI's environment: ``base`` (default ``os.environ``) minus credentials and
    session variables, plus the isolation switches. No value is read or logged."""
    source = os.environ if base is None else base
    env = {
        name: value
        for name, value in source.items()
        if name in ENV_KEEP or not name.startswith(ENV_STRIP_PREFIXES)
    }
    env.update(ENV_SET)
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
    return env


def build_argv(bin_path: str, model: str, request: LLMRequest[Any]) -> list[str]:
    """The exact CLI arguments for one call; the prompt goes on stdin."""
    return [
        bin_path,
        "-p",
        "--output-format",
        "json",
        "--verbose",
        "--model",
        model,
        "--system-prompt",
        request.system,
        "--json-schema",
        json.dumps(request.schema.model_json_schema()),
        "--tools",
        "",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
    ]


@dataclass
class Envelope:
    """The parts of the CLI's JSON output the provider reads."""

    result: dict[str, Any]
    rate_limits: list[dict[str, Any]] = field(default_factory=list)
    assistant_errors: list[str] = field(default_factory=list)

    @property
    def subtype(self) -> object:
        return self.result.get("subtype")

    @property
    def status(self) -> int | None:
        value = self.result.get("api_error_status")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def text(self) -> str:
        value = self.result.get("result")
        return value if isinstance(value, str) else ""

    @property
    def is_success(self) -> bool:
        return self.subtype == "success" and self.result.get("is_error") is False


def parse_envelope(stdout: str) -> Envelope | None:
    """Parse ``--output-format json`` output (a list with ``--verbose``, else the
    result object). ``None`` when it is not JSON or has no ``result`` element."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, dict):
        if data.get("type", "result") != "result":
            return None
        return Envelope(result=data)
    if not isinstance(data, list):
        return None
    messages = [m for m in data if isinstance(m, dict)]
    results = [m for m in messages if m.get("type") == "result"]
    if not results:
        return None
    rate_limits = [
        m["rate_limit_info"]
        for m in messages
        if m.get("type") == "rate_limit_event" and isinstance(m.get("rate_limit_info"), dict)
    ]
    errors = [
        m["error"]
        for m in messages
        if m.get("type") == "assistant" and isinstance(m.get("error"), str)
    ]
    return Envelope(result=results[-1], rate_limits=rate_limits, assistant_errors=errors)


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_RESET_RE = re.compile(
    r"(?:(?P<month>[A-Z][a-z]{2}) (?P<day>\d{1,2})(?:, (?P<year>\d{4}))?, )?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?P<ampm>am|pm) \((?P<zone>[^)]+)\)"
)


def parse_reset_text(text: str, now: dt.datetime) -> dt.datetime | None:
    """The reset time in a usage-limit message (``… · resets 3pm (Europe/Madrid)``,
    ``… · resets Oct 23, 3:30pm (Europe/Madrid)``), as an aware datetime, else ``None``.

    A time without a date is today in that zone, or tomorrow if already past.
    """
    _, marker, tail = text.partition(RESET_MARKER)
    if not marker:
        return None
    match = _RESET_RE.match(tail)
    if match is None:
        return None
    try:
        zone = ZoneInfo(match["zone"])
    except (ZoneInfoNotFoundError, ValueError):
        return None
    hour = int(match["hour"])
    minute = int(match["minute"] or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if match["ampm"] == "pm" else 0)
    local_now = now.astimezone(zone)
    try:
        if match["month"]:
            month = _MONTHS.get(match["month"])
            if month is None:
                return None
            year = int(match["year"]) if match["year"] else local_now.year
            return dt.datetime(year, month, int(match["day"]), hour, minute, tzinfo=zone)
        reset = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None
    if reset <= local_now:
        reset = dt.datetime.combine(
            reset.date() + dt.timedelta(days=1), reset.timetz()
        )
    return reset


def _is_usage_limit(envelope: Envelope) -> bool:
    if any(info.get("status") == "rejected" for info in envelope.rate_limits):
        return True
    return envelope.text.startswith(USAGE_LIMIT_PREFIXES)


def usage_limit_reset(envelope: Envelope, now: dt.datetime) -> dt.datetime | None:
    """When the usage limit resets: ``rate_limit_event.resetsAt`` first, else the text."""
    for info in reversed(envelope.rate_limits):
        resets_at = info.get("resetsAt")
        if info.get("status") == "rejected" and isinstance(resets_at, int | float):
            if isinstance(resets_at, bool):
                continue
            try:
                return dt.datetime.fromtimestamp(resets_at, dt.UTC)
            except (OverflowError, OSError, ValueError):
                break
    return parse_reset_text(envelope.text, now)


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class _Transient(Exception):
    """A failure worth retrying after a backoff."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _UsageLimit(Exception):
    """The subscription usage limit was reached; wait for the reset and retry."""

    def __init__(self, envelope: Envelope) -> None:
        super().__init__("usage limit")
        self.envelope = envelope


class ClaudeCodeProvider:
    """``LLMProvider`` backed by the local Claude Code CLI (``claude -p``)."""

    name = "claude_code"

    def __init__(
        self,
        model: str,
        *,
        settings: ClaudeCodeSettings | None = None,
        runner: Runner | None = None,
        which: Callable[[str], str | None] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.model = model
        self._settings = settings if settings is not None else claude_code_settings()
        self._runner = runner
        self._clock = clock or _now
        self._sleep = sleep
        self._log = log or _stderr_log
        lookup = which if which is not None else find_cli
        bin_path = lookup(self._settings.bin)
        if not bin_path:
            raise LLMConfigError(
                f"Claude Code CLI {self._settings.bin!r} not found on PATH; "
                "install it or set LLM_CLAUDE_CODE_BIN"
            )
        self._bin = bin_path
        self._preflight()

    def __repr__(self) -> str:
        return f"ClaudeCodeProvider(model={self.model!r})"

    def _run(
        self, argv: Sequence[str], *, input: str | None, env: Mapping[str, str], timeout: float
    ) -> "subprocess.CompletedProcess[str]":
        runner = self._runner if self._runner is not None else run_cli
        with tempfile.TemporaryDirectory(prefix="ideology-claude-") as cwd:
            return runner(argv, input=input, env=env, cwd=cwd, timeout=timeout)

    def _preflight(self) -> None:
        """Fail before any database write unless the CLI is logged in to a subscription."""
        try:
            completed = self._run(
                [self._bin, "auth", "status", "--json"],
                input=None,
                env=child_env(4096),
                timeout=PREFLIGHT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise LLMConfigError(
                f"`{self._settings.bin} auth status` timed out after "
                f"{PREFLIGHT_TIMEOUT_SECONDS} s"
            ) from None
        except OSError as exc:
            raise LLMConfigError(
                f"Could not run Claude Code CLI {self._settings.bin!r}: {type(exc).__name__}"
            ) from None
        if completed.returncode != 0:
            raise LLMConfigError(NOT_LOGGED_IN)
        try:
            status = json.loads(completed.stdout)
        except ValueError:
            raise LLMConfigError(
                "Could not read `claude auth status --json` output; " + NOT_LOGGED_IN
            ) from None
        if not isinstance(status, dict) or status.get("loggedIn") is not True:
            raise LLMConfigError(NOT_LOGGED_IN)
        method = status.get("authMethod")
        if method not in SUBSCRIPTION_AUTH_METHODS:
            raise LLMConfigError(
                f"Claude Code is authenticated with {_clip(method)!r}, not a Claude "
                "subscription (claude.ai); the claude_code provider must not bill the "
                "API. Run `claude auth login` with a Claude subscription"
            )

    def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        argv = build_argv(self._bin, self.model, request)
        transient_failures = 0
        waited = dt.timedelta(0)
        while True:
            try:
                return self._attempt(request, argv)
            except _Transient as exc:
                if transient_failures >= TRANSIENT_RETRIES:
                    raise LLMProviderError(
                        f"{exc.message}; gave up after {TRANSIENT_RETRIES} retries"
                    ) from None
                delay = TRANSIENT_BACKOFF[min(transient_failures, len(TRANSIENT_BACKOFF) - 1)]
                transient_failures += 1
                self._log(
                    f"claude_code: {exc.message}; retry {transient_failures} of "
                    f"{TRANSIENT_RETRIES} in {delay} s"
                )
                self._sleep(delay)
            except _UsageLimit as limit:
                waited += self._wait_for_reset(request, limit.envelope, waited)

    def _attempt[T: BaseModel](self, request: LLMRequest[T], argv: list[str]) -> LLMResult[T]:
        task = request.task
        try:
            completed = self._run(
                argv,
                input=request.prompt,
                env=child_env(request.max_tokens),
                timeout=self._settings.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise _Transient(
                f"Claude Code call for task {task!r} timed out after "
                f"{self._settings.timeout_seconds} s"
            ) from None
        except OSError as exc:
            raise LLMProviderError(
                f"Claude Code call for task {task!r} could not start: {type(exc).__name__}"
            ) from None
        envelope = parse_envelope(completed.stdout or "")
        if envelope is None:
            raise LLMProviderError(
                f"Claude Code call for task {task!r} returned no JSON result "
                f"(exit {completed.returncode}): {_clip(completed.stderr or '')}"
            )
        if envelope.is_success:
            return self._result(request, envelope)
        detail = (
            f"subtype={envelope.subtype!r}, api_error_status={envelope.status}, "
            f"exit {completed.returncode}: {_clip(envelope.text)}"
        )
        errors = set(envelope.assistant_errors)
        if _is_usage_limit(envelope):
            raise _UsageLimit(envelope)
        if envelope.status in AUTH_STATUSES or "authentication_failed" in errors:
            raise LLMConfigError(f"{NOT_LOGGED_IN} (task {task!r}; {detail})")
        if envelope.status in TRANSIENT_STATUSES or errors & {"server_error", "rate_limit"}:
            raise _Transient(f"Claude Code call for task {task!r} failed ({detail})")
        if (
            envelope.subtype == "error_max_structured_output_retries"
            or "max_output_tokens" in errors
        ):
            raise LLMOutputError(
                f"Claude Code output for task {task!r} does not match "
                f"{request.schema.__name__} ({detail})"
            )
        raise LLMProviderError(f"Claude Code call for task {task!r} failed ({detail})")

    def _result[T: BaseModel](self, request: LLMRequest[T], envelope: Envelope) -> LLMResult[T]:
        raw = envelope.result.get("structured_output")
        if raw is None:
            raise LLMOutputError(
                f"Claude Code returned no structured output for task {request.task!r} "
                f"(expected {request.schema.__name__})"
            )
        try:
            output = request.schema.model_validate(raw)
        except ValidationError as exc:
            raise LLMOutputError(
                f"Claude Code output for task {request.task!r} does not match "
                f"{request.schema.__name__}: {exc.error_count()} validation error(s)"
            ) from None
        usage = envelope.result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return LLMResult(
            output=output,
            provider=self.name,
            model=self.model,
            input_tokens=_int(usage.get("input_tokens"))
            + _int(usage.get("cache_creation_input_tokens"))
            + _int(usage.get("cache_read_input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
        )

    def _wait_for_reset(
        self, request: LLMRequest[Any], envelope: Envelope, waited: dt.timedelta
    ) -> dt.timedelta:
        """Sleep until the usage limit resets; return how long it actually waited."""
        start = self._clock()
        reset = usage_limit_reset(envelope, start)
        if reset is None:
            target = start + USAGE_LIMIT_FALLBACK_WAIT
            reset_label = "an unknown time"
        else:
            target = max(reset + USAGE_LIMIT_MARGIN, start + USAGE_LIMIT_MIN_WAIT)
            reset_label = reset.astimezone().isoformat(timespec="minutes")
        budget = dt.timedelta(hours=self._settings.max_wait_hours)
        if waited + (target - start) > budget:
            raise LLMProviderError(
                f"Claude Code usage limit for task {request.task!r} resets at "
                f"{reset_label}, beyond the configured maximum wait of "
                f"{self._settings.max_wait_hours} h (LLM_CLAUDE_CODE_MAX_WAIT_HOURS; "
                f"already waited {waited.total_seconds() / 3600:.1f} h)"
            )
        self._log(
            f"claude_code: usage limit reached (task {request.task}); waiting until "
            f"{target.astimezone().isoformat(timespec='minutes')} before retrying "
            "(Ctrl-C to stop)"
        )
        while (remaining := (target - self._clock()).total_seconds()) > 0:
            self._sleep(min(SLEEP_SLICE_SECONDS, remaining))
        return self._clock() - start

    def close(self) -> None:
        """Nothing to release: each call is its own process."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

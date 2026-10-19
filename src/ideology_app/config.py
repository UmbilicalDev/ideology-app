"""Runtime configuration read from the environment."""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///ideology.db"
DEFAULT_SOURCE_FILES_DIR = "source_files"

DEFAULT_LLM_PROVIDER = "anthropic"
# Default model per provider. Adding a provider adds one entry here.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5-5",
    "fake": "fake-model",
}


class ConfigError(ValueError):
    """A configuration value is missing or invalid."""


class GenerationMode(StrEnum):
    """When Statements and Party Positions are generated (see CONTEXT.md)."""

    PRECOMPUTED = "precomputed"
    LIVE = "live"


DEFAULT_GENERATION_MODE = GenerationMode.PRECOMPUTED

DEFAULT_MIN_PARTY_COVERAGE_PERCENT = 70
DEFAULT_MIN_STATEMENTS = 25
DEFAULT_MAX_STATEMENTS = 35
DEFAULT_MAX_TOPIC_SHARE_PERCENT = 30


@dataclass(frozen=True)
class LLMSettings:
    """Which LLM provider and model to use."""

    provider: str
    model: str


@dataclass(frozen=True)
class ValidationSettings:
    """Thresholds the Validation checks read (one value for the whole process).

    ``min_party_coverage_percent``: the minimum share (0..100) of a run's
    Statements on which every Party must have a position (check
    ``party_coverage``).
    ``min_statements`` / ``max_statements``: the inclusive range (each at least
    1, min not above max) for the number of Statements (check
    ``statement_count``).
    ``max_topic_share_percent``: the maximum share (0..100) of the Statements a
    single topic may have; a topic fails only when strictly above it (check
    ``topic_spread``).
    A later threshold check adds its field here.
    """

    min_party_coverage_percent: int = DEFAULT_MIN_PARTY_COVERAGE_PERCENT
    min_statements: int = DEFAULT_MIN_STATEMENTS
    max_statements: int = DEFAULT_MAX_STATEMENTS
    max_topic_share_percent: int = DEFAULT_MAX_TOPIC_SHARE_PERCENT

    def __post_init__(self) -> None:
        if not _is_int_in(self.min_party_coverage_percent, 0, 100):
            raise ValueError("min_party_coverage_percent must be an integer from 0 to 100")
        for name in ("min_statements", "max_statements"):
            if not _is_int_in(getattr(self, name), 1, None):
                raise ValueError(f"{name} must be an integer of at least 1")
        if self.min_statements > self.max_statements:
            raise ValueError("min_statements must not be greater than max_statements")
        if not _is_int_in(self.max_topic_share_percent, 0, 100):
            raise ValueError("max_topic_share_percent must be an integer from 0 to 100")


def _is_int_in(value: object, low: int, high: int | None) -> bool:
    """True when ``value`` is a non-``bool`` ``int`` in ``low..high`` (no upper bound if None)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= low and (high is None or value <= high)


def database_url() -> str:
    """Return ``DATABASE_URL`` if set, else a SQLite file in the current directory."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def source_files_dir() -> Path:
    """Return ``SOURCE_FILES_DIR`` if set, else ``source_files`` in the current directory."""
    return Path(os.environ.get("SOURCE_FILES_DIR") or DEFAULT_SOURCE_FILES_DIR)


def _env(name: str) -> str | None:
    """Return the trimmed value of ``name``, or ``None`` if unset or blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def generation_mode() -> GenerationMode:
    """Return ``GENERATION_MODE`` (case-insensitive), default ``precomputed``."""
    raw = _env("GENERATION_MODE")
    if raw is None:
        return DEFAULT_GENERATION_MODE
    try:
        return GenerationMode(raw.lower())
    except ValueError:
        supported = ", ".join(m.value for m in GenerationMode)
        raise ConfigError(
            f"Invalid GENERATION_MODE {raw!r}; supported values: {supported}"
        ) from None


def llm_settings() -> LLMSettings:
    """Return the provider (``LLM_PROVIDER``) and model (``LLM_MODEL``) to use.

    The provider is matched case-insensitively and defaults to ``anthropic``; the
    model defaults to the provider's entry in ``DEFAULT_MODELS``. The API key is
    not read here; the provider reads it lazily.
    """
    provider = (_env("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).lower()
    if provider not in DEFAULT_MODELS:
        supported = ", ".join(sorted(DEFAULT_MODELS))
        raise ConfigError(
            f"Invalid LLM_PROVIDER {provider!r}; supported values: {supported}"
        )
    model = _env("LLM_MODEL") or DEFAULT_MODELS[provider]
    return LLMSettings(provider=provider, model=model)


def _percent_env(name: str, default: int) -> int:
    """An integer from 0 to 100 read from ``name``, or ``default`` if unset or blank."""
    raw = _env(name)
    if raw is None:
        return default
    if not (raw.isascii() and raw.isdigit()) or int(raw) > 100:
        raise ConfigError(f"Invalid {name} {raw!r}; expected an integer from 0 to 100")
    return int(raw)


def _positive_int_env(name: str, default: int) -> int:
    """An integer of at least 1 read from ``name``, or ``default`` if unset or blank."""
    raw = _env(name)
    if raw is None:
        return default
    if not (raw.isascii() and raw.isdigit()) or int(raw) < 1:
        raise ConfigError(f"Invalid {name} {raw!r}; expected a positive integer")
    return int(raw)


def validation_settings() -> ValidationSettings:
    """Return the Validation thresholds from the environment.

    ``VALIDATION_MIN_PARTY_COVERAGE_PERCENT`` (default 70) and
    ``VALIDATION_MAX_TOPIC_SHARE_PERCENT`` (default 30) are integers from 0 to
    100; ``VALIDATION_MIN_STATEMENTS`` (default 25) and
    ``VALIDATION_MAX_STATEMENTS`` (default 35) are integers of at least 1, and
    the min must not be greater than the max. Anything else (decimals, ``%``,
    signs) raises ``ConfigError``. Variables are checked in this order:
    coverage, min, max, range, share; the first error wins.
    """
    coverage = _percent_env(
        "VALIDATION_MIN_PARTY_COVERAGE_PERCENT", DEFAULT_MIN_PARTY_COVERAGE_PERCENT
    )
    min_statements = _positive_int_env("VALIDATION_MIN_STATEMENTS", DEFAULT_MIN_STATEMENTS)
    max_statements = _positive_int_env("VALIDATION_MAX_STATEMENTS", DEFAULT_MAX_STATEMENTS)
    if min_statements > max_statements:
        raise ConfigError(
            "Invalid statement count range: "
            f"VALIDATION_MIN_STATEMENTS ({min_statements}) is greater than "
            f"VALIDATION_MAX_STATEMENTS ({max_statements})"
        )
    share = _percent_env("VALIDATION_MAX_TOPIC_SHARE_PERCENT", DEFAULT_MAX_TOPIC_SHARE_PERCENT)
    return ValidationSettings(
        min_party_coverage_percent=coverage,
        min_statements=min_statements,
        max_statements=max_statements,
        max_topic_share_percent=share,
    )

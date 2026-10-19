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
    ``party_coverage``). A later threshold check adds its field here.
    """

    min_party_coverage_percent: int = DEFAULT_MIN_PARTY_COVERAGE_PERCENT

    def __post_init__(self) -> None:
        value = self.min_party_coverage_percent
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("min_party_coverage_percent must be an integer from 0 to 100")


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


def validation_settings() -> ValidationSettings:
    """Return the Validation thresholds from the environment.

    ``VALIDATION_MIN_PARTY_COVERAGE_PERCENT`` is an integer from 0 to 100
    (default 70); anything else (decimals, ``%``, signs) raises ``ConfigError``.
    """
    raw = _env("VALIDATION_MIN_PARTY_COVERAGE_PERCENT")
    if raw is None:
        return ValidationSettings()
    if not (raw.isascii() and raw.isdigit()) or int(raw) > 100:
        raise ConfigError(
            f"Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT {raw!r}; "
            "expected an integer from 0 to 100"
        )
    return ValidationSettings(min_party_coverage_percent=int(raw))

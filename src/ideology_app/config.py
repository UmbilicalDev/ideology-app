"""Runtime configuration read from the environment."""

import datetime as dt
import logging
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///ideology.db"
DEFAULT_SOURCE_FILES_DIR = "source_files"
DEFAULT_WEB_DIST_DIR = "apps/web/dist"
DEFAULT_ELECTIONS_DATA_DIR = "data/elections"
# The anonymous Voter feedback store (feedback-api): its own SQLite file in the
# current directory, never the shared database. Ignored by git through *.db.
DEFAULT_FEEDBACK_DATABASE_URL = "sqlite:///feedback.db"
# The database committed to git and shared by every developer (shared-database).
# Relative to the current directory, like the other defaults; selected only
# through DATABASE_URL / --database-url (sqlite:///data/ideology.db).
SHARED_DATABASE_PATH = Path("data/ideology.db")

DEFAULT_LLM_PROVIDER = "anthropic"
# Default model per provider. Adding a provider adds one entry here.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5-5",
    # The full id the Claude Code CLI's ``sonnet`` alias resolves to (2.1.110).
    "claude_code": "claude-sonnet-4-6",
    "fake": "fake-model",
}


class ConfigError(ValueError):
    """A configuration value is missing or invalid."""


class GenerationMode(StrEnum):
    """When Statements and Party Positions are generated (see CONTEXT.md)."""

    PRECOMPUTED = "precomputed"
    LIVE = "live"


DEFAULT_GENERATION_MODE = GenerationMode.PRECOMPUTED

DEFAULT_MIN_PARTY_COVERAGE_PERCENT = 50
DEFAULT_MIN_STATEMENTS = 25
DEFAULT_MAX_STATEMENTS = 35
DEFAULT_MAX_TOPIC_SHARE_PERCENT = 30

# Context notes (pipeline-statement-clarity-context). The structural cap equals
# ``pipeline.prompts.CONTEXT_NOTE_SCHEMA_MAX`` and the ``statements.context_note``
# column width; the configured bounds must stay within it.
CONTEXT_NOTE_MAX_CHARS_LIMIT = 500
DEFAULT_CONTEXT_NOTE_MIN_CHARS = 30
DEFAULT_CONTEXT_NOTE_MAX_CHARS = 300
# Whole words (or consecutive words) a context note must not use; matched after
# folding case and accents (``validation.context_note``). A planner proposal for
# the team to review (docs/risks-and-open-questions.md).
DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS: tuple[str, ...] = (
    "injusto", "injusta", "injustos", "injustas",
    "polémico", "polémica", "polémicos", "polémicas",
    "controvertido", "controvertida", "controvertidos", "controvertidas",
    "represivo", "represiva", "represivos", "represivas",
    "abusivo", "abusiva", "abusivos", "abusivas",
    "desastroso", "desastrosa", "desastrosos", "desastrosas",
    "nefasto", "nefasta", "nefastos", "nefastas",
    "excelente", "excelentes",
    "beneficioso", "beneficiosa", "beneficiosos", "beneficiosas",
    "perjudicial", "perjudiciales",
    "acertado", "acertada", "acertados", "acertadas",
    "erróneo", "errónea", "erróneos", "erróneas",
    "fracaso", "fracasos",
    "exitoso", "exitosa", "exitosos", "exitosas",
    "necesario", "necesaria", "necesarios", "necesarias",
    "imprescindible", "imprescindibles",
    "radical", "radicales",
    "extremista", "extremistas",
    "populista", "populistas",
    "sectario", "sectaria",
    "afortunadamente", "lamentablemente", "desgraciadamente",
    "por desgracia", "por suerte",
)

DEFAULT_SOURCE_REFETCH_INTERVAL_HOURS = 6

DEFAULT_CLAUDE_CODE_BIN = "claude"
DEFAULT_CLAUDE_CODE_TIMEOUT_SECONDS = 900
DEFAULT_CLAUDE_CODE_MAX_WAIT_HOURS = 48


@dataclass(frozen=True)
class LLMSettings:
    """Which LLM provider and model to use."""

    provider: str
    model: str


@dataclass(frozen=True)
class ClaudeCodeSettings:
    """How the ``claude_code`` provider runs the local Claude Code CLI.

    ``bin``: the executable name or path (looked up on ``PATH``).
    ``timeout_seconds``: the limit for one CLI call.
    ``max_wait_hours``: the most a single ``generate`` may wait, in total, for
    the subscription usage limit to reset before it fails.
    """

    bin: str = DEFAULT_CLAUDE_CODE_BIN
    timeout_seconds: int = DEFAULT_CLAUDE_CODE_TIMEOUT_SECONDS
    max_wait_hours: int = DEFAULT_CLAUDE_CODE_MAX_WAIT_HOURS


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
    ``context_note_min_chars`` / ``context_note_max_chars``: the inclusive
    range for a Statement's context note, counted after trimming
    (``1 <= min <= max <= CONTEXT_NOTE_MAX_CHARS_LIMIT``); and
    ``context_note_evaluative_words``: the non-empty list of words or phrases,
    each with a letter or digit, a note must not use (check ``context_note``).
    A later threshold check adds its field here.
    """

    min_party_coverage_percent: int = DEFAULT_MIN_PARTY_COVERAGE_PERCENT
    min_statements: int = DEFAULT_MIN_STATEMENTS
    max_statements: int = DEFAULT_MAX_STATEMENTS
    max_topic_share_percent: int = DEFAULT_MAX_TOPIC_SHARE_PERCENT
    context_note_min_chars: int = DEFAULT_CONTEXT_NOTE_MIN_CHARS
    context_note_max_chars: int = DEFAULT_CONTEXT_NOTE_MAX_CHARS
    context_note_evaluative_words: tuple[str, ...] = DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS

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
        for name in ("context_note_min_chars", "context_note_max_chars"):
            if not _is_int_in(getattr(self, name), 1, CONTEXT_NOTE_MAX_CHARS_LIMIT):
                raise ValueError(
                    f"{name} must be an integer from 1 to {CONTEXT_NOTE_MAX_CHARS_LIMIT}"
                )
        if self.context_note_min_chars > self.context_note_max_chars:
            raise ValueError(
                "context_note_min_chars must not be greater than context_note_max_chars"
            )
        words = self.context_note_evaluative_words
        if (
            not isinstance(words, tuple)
            or not words
            or not all(isinstance(w, str) and _has_word_character(w) for w in words)
        ):
            raise ValueError(
                "context_note_evaluative_words must be a non-empty tuple of strings "
                "that each contain a letter or digit"
            )


def _has_word_character(value: str) -> bool:
    """True when ``value`` contains a letter or digit."""
    return any(ch.isalnum() for ch in value)


def _is_int_in(value: object, low: int, high: int | None) -> bool:
    """True when ``value`` is a non-``bool`` ``int`` in ``low..high`` (no upper bound if None)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= low and (high is None or value <= high)


def database_url() -> str:
    """Return ``DATABASE_URL`` if set, else a SQLite file in the current directory."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def feedback_database_url() -> str:
    """Return ``FEEDBACK_DATABASE_URL`` (trimmed) if set, else ``sqlite:///feedback.db``.

    The default file is relative to the current directory. The store must not be
    the shared or ``DATABASE_URL`` database (``feedback.store.check_separate``).
    """
    return _env("FEEDBACK_DATABASE_URL") or DEFAULT_FEEDBACK_DATABASE_URL


def admin_users_raw() -> str | None:
    """Return ``ADMIN_USERS`` (trimmed), or ``None`` when unset or blank (no Operator account).

    The Operator accounts for the admin page (feedback-admin), parsed by
    ``admin.accounts.parse_admin_users``. Never logged or echoed.
    """
    return _env("ADMIN_USERS")


def source_files_dir() -> Path:
    """Return ``SOURCE_FILES_DIR`` if set, else ``source_files`` in the current directory."""
    return Path(os.environ.get("SOURCE_FILES_DIR") or DEFAULT_SOURCE_FILES_DIR)


def elections_data_dir() -> Path:
    """Return ``ELECTIONS_DATA_DIR`` (trimmed) if set, else ``data/elections`` in the current directory.

    It holds one Source Text Bundle per Election, in ``<slug>/`` (see ``source_bundle``).
    """
    return Path(_env("ELECTIONS_DATA_DIR") or DEFAULT_ELECTIONS_DATA_DIR)


def _env(name: str) -> str | None:
    """Return the trimmed value of ``name``, or ``None`` if unset or blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def web_dist_dir() -> Path:
    """Return ``WEB_DIST_DIR`` (trimmed) if set, else ``apps/web/dist`` in the current directory.

    The directory holds the Vite build of ``apps/web`` that FastAPI serves.
    """
    return Path(_env("WEB_DIST_DIR") or DEFAULT_WEB_DIST_DIR)


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


def _bounded_int_env(name: str, default: int, high: int) -> int:
    """An integer from 1 to ``high`` read from ``name``, or ``default`` if unset or blank."""
    raw = _env(name)
    if raw is None:
        return default
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= high:
        raise ConfigError(f"Invalid {name} {raw!r}; expected an integer from 1 to {high}")
    return int(raw)


def _word_list_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """A comma-separated list of words read from ``name`` (each trimmed), or ``default``.

    Unset or blank means ``default``. Empty entries are dropped; an entry with
    no letter or digit, or a list left empty, raises ``ConfigError``.
    """
    raw = _env(name)
    if raw is None:
        return default
    words = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not words:
        raise ConfigError(f"Invalid {name}: expected a comma-separated list of words")
    for word in words:
        if not _has_word_character(word):
            raise ConfigError(f"Invalid {name}: entry {word!r} has no letter or digit")
    return words


def validation_settings() -> ValidationSettings:
    """Return the Validation thresholds from the environment.

    ``VALIDATION_MIN_PARTY_COVERAGE_PERCENT`` (default 50) and
    ``VALIDATION_MAX_TOPIC_SHARE_PERCENT`` (default 30) are integers from 0 to
    100; ``VALIDATION_MIN_STATEMENTS`` (default 25) and
    ``VALIDATION_MAX_STATEMENTS`` (default 35) are integers of at least 1, and
    the min must not be greater than the max. Anything else (decimals, ``%``,
    signs) raises ``ConfigError``. ``VALIDATION_CONTEXT_NOTE_MIN_CHARS``
    (default 30) and ``VALIDATION_CONTEXT_NOTE_MAX_CHARS`` (default 300) are
    integers from 1 to ``CONTEXT_NOTE_MAX_CHARS_LIMIT`` (500), min not above
    max; ``VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS`` is a comma-separated
    list that replaces the default list (unset or blank: the default).
    Variables are checked in this order: coverage, min, max, range, share,
    note min, note max, note range, words; the first error wins.
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
    note_min = _bounded_int_env(
        "VALIDATION_CONTEXT_NOTE_MIN_CHARS",
        DEFAULT_CONTEXT_NOTE_MIN_CHARS,
        CONTEXT_NOTE_MAX_CHARS_LIMIT,
    )
    note_max = _bounded_int_env(
        "VALIDATION_CONTEXT_NOTE_MAX_CHARS",
        DEFAULT_CONTEXT_NOTE_MAX_CHARS,
        CONTEXT_NOTE_MAX_CHARS_LIMIT,
    )
    if note_min > note_max:
        raise ConfigError(
            "Invalid context note length range: "
            f"VALIDATION_CONTEXT_NOTE_MIN_CHARS ({note_min}) is greater than "
            f"VALIDATION_CONTEXT_NOTE_MAX_CHARS ({note_max})"
        )
    words = _word_list_env(
        "VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS", DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS
    )
    return ValidationSettings(
        min_party_coverage_percent=coverage,
        min_statements=min_statements,
        max_statements=max_statements,
        max_topic_share_percent=share,
        context_note_min_chars=note_min,
        context_note_max_chars=note_max,
        context_note_evaluative_words=words,
    )


def source_refetch_interval() -> dt.timedelta:
    """How old a URL Source Document's last check must be before ``source refetch`` fetches it.

    ``SOURCE_REFETCH_INTERVAL_HOURS`` is a whole number of hours of at least 1
    (default 6); anything else (``0``, signs, decimals, units such as ``6h``)
    raises ``ConfigError``.
    """
    hours = _positive_int_env(
        "SOURCE_REFETCH_INTERVAL_HOURS", DEFAULT_SOURCE_REFETCH_INTERVAL_HOURS
    )
    return dt.timedelta(hours=hours)


def claude_code_settings() -> ClaudeCodeSettings:
    """Return the ``claude_code`` provider settings from the environment.

    ``LLM_CLAUDE_CODE_BIN`` (trimmed, default ``claude``),
    ``LLM_CLAUDE_CODE_TIMEOUT_SECONDS`` (default 900) and
    ``LLM_CLAUDE_CODE_MAX_WAIT_HOURS`` (default 48). The two numbers are ASCII
    digits of at least 1; anything else raises ``ConfigError``.
    """
    return ClaudeCodeSettings(
        bin=_env("LLM_CLAUDE_CODE_BIN") or DEFAULT_CLAUDE_CODE_BIN,
        timeout_seconds=_positive_int_env(
            "LLM_CLAUDE_CODE_TIMEOUT_SECONDS", DEFAULT_CLAUDE_CODE_TIMEOUT_SECONDS
        ),
        max_wait_hours=_positive_int_env(
            "LLM_CLAUDE_CODE_MAX_WAIT_HOURS", DEFAULT_CLAUDE_CODE_MAX_WAIT_HOURS
        ),
    )


# --- Legal notice (legal-privacy-page) ---------------------------------------
# The holders and contact details shown on /legal. Personal data: set only in
# the server environment, never in git, and never logged or echoed in errors.

LEGAL_MAX_HOLDERS = 10
LEGAL_MAX_NAME_CHARS = 120
LEGAL_MAX_EMAIL_CHARS = 254
LEGAL_MAX_ADDRESS_CHARS = 300

_LEGAL_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
# Documentation domains (RFC 2606): a value left from an example is refused.
_LEGAL_PLACEHOLDER_DOMAINS = ("example.com", "example.net", "example.org")
_DNI_RE = re.compile(r"^\d{8}[A-Z]$")
_NIE_RE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
# C0, DEL and C1 control characters.
_CONTROL_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f]")


@dataclass(frozen=True)
class LegalHolder:
    """One holder of the site: a natural person's name and, optionally, their NIF."""

    name: str
    nif: str | None = None


@dataclass(frozen=True)
class LegalNoticeSettings:
    """What ``GET /api/v1/legal-notice`` serves; empty when nothing is configured."""

    holders: tuple[LegalHolder, ...] = ()
    contact_email: str | None = None
    address: str | None = None


def _legal_text(name: str, raw: str | None) -> str | None:
    """``raw`` trimmed, ``None`` if blank; refuses control characters, ``<`` and ``>``."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if _CONTROL_RE.search(value) or "<" in value or ">" in value:
        raise ConfigError(f"Invalid {name}: control characters, '<' and '>' are not allowed")
    return value


def _valid_nif(value: str) -> bool:
    """A DNI (8 digits + letter) or NIE (X/Y/Z + 7 digits + letter) with its mod-23 letter."""
    if _DNI_RE.match(value):
        number = value[:8]
    elif _NIE_RE.match(value):
        number = str("XYZ".index(value[0])) + value[1:8]
    else:
        return False
    return _NIF_LETTERS[int(number) % 23] == value[-1]


def parse_legal_notice(
    holders: str | None,
    contact_email: str | None,
    nif: str | None = None,
    address: str | None = None,
) -> LegalNoticeSettings:
    """Parse the ``LEGAL_*`` values; unset or blank means "not configured".

    ``holders``: 1..10 names separated by ``;``, each 1..120 code points.
    ``contact_email``: at most 254 characters, ``alias@dominio``; the
    ``example.com/.net/.org`` domains are refused. ``nif`` (optional): needs
    ``holders``; one DNI or NIE per holder, in the same order, separated by
    ``;``, checked after upper-casing. ``address`` (optional): one line of
    1..300 code points. A malformed value raises ``ConfigError`` naming the
    variable, never the value.
    """
    holders_text = _legal_text("LEGAL_HOLDERS", holders)
    email = _legal_text("LEGAL_CONTACT_EMAIL", contact_email)
    nif_text = _legal_text("LEGAL_NIF", nif)
    address_text = _legal_text("LEGAL_ADDRESS", address)

    names: list[str] = []
    if holders_text is not None:
        names = [part.strip() for part in holders_text.split(";")]
        if len(names) > LEGAL_MAX_HOLDERS:
            raise ConfigError(f"Invalid LEGAL_HOLDERS: at most {LEGAL_MAX_HOLDERS} names")
        if any(not 1 <= len(name) <= LEGAL_MAX_NAME_CHARS for name in names):
            raise ConfigError(
                "Invalid LEGAL_HOLDERS: each name separated by ';' must have "
                f"1 to {LEGAL_MAX_NAME_CHARS} characters"
            )

    nifs: list[str | None] = [None] * len(names)
    if nif_text is not None:
        if not names:
            raise ConfigError("Invalid LEGAL_NIF: it needs LEGAL_HOLDERS")
        values = [part.strip().upper() for part in nif_text.split(";")]
        if len(values) != len(names):
            raise ConfigError("Invalid LEGAL_NIF: it needs one NIF per name in LEGAL_HOLDERS")
        if not all(_valid_nif(value) for value in values):
            raise ConfigError("Invalid LEGAL_NIF: each value must be a valid DNI or NIE")
        nifs = list(values)

    if email is not None:
        domain = email.rsplit("@", 1)[-1].lower()
        if (
            len(email) > LEGAL_MAX_EMAIL_CHARS
            or not _LEGAL_EMAIL_RE.match(email)
            or any(domain == d or domain.endswith("." + d) for d in _LEGAL_PLACEHOLDER_DOMAINS)
        ):
            raise ConfigError("Invalid LEGAL_CONTACT_EMAIL: expected an address like alias@dominio")

    if address_text is not None and len(address_text) > LEGAL_MAX_ADDRESS_CHARS:
        raise ConfigError(
            f"Invalid LEGAL_ADDRESS: at most {LEGAL_MAX_ADDRESS_CHARS} characters"
        )

    return LegalNoticeSettings(
        holders=tuple(LegalHolder(name=n, nif=v) for n, v in zip(names, nifs, strict=True)),
        contact_email=email,
        address=address_text,
    )


def legal_notice_settings() -> LegalNoticeSettings:
    """The legal notice from ``LEGAL_HOLDERS``, ``LEGAL_CONTACT_EMAIL``, ``LEGAL_NIF`` and ``LEGAL_ADDRESS``."""
    return parse_legal_notice(
        os.environ.get("LEGAL_HOLDERS"),
        os.environ.get("LEGAL_CONTACT_EMAIL"),
        os.environ.get("LEGAL_NIF"),
        os.environ.get("LEGAL_ADDRESS"),
    )


# --- Donation link (donate-buymeacoffee) --------------------------------------
# The project's Buy Me a Coffee profile, shown as a plain external link. Optional:
# unset, blank or invalid hides the link, and an invalid value never stops
# startup (it is not legal information). The same rule lives in
# packages/core/src/domain/donation.ts; the shared vectors keep them equal.

DONATION_URL_RE = re.compile(r"https://(www\.)?buymeacoffee\.com/[A-Za-z0-9_-]{1,64}")
DONATION_URL_WARNING = (
    "Ignoring DONATION_URL: expected https://www.buymeacoffee.com/<perfil> or "
    "https://buymeacoffee.com/<perfil>; the donation link stays hidden."
)

_config_logger = logging.getLogger("ideology_app.config")


def parse_donation_url(raw: str | None) -> str | None:
    """The trimmed ``DONATION_URL``, or ``None`` when unset, blank or invalid.

    Valid means a full match of ``DONATION_URL_RE``: lower-case ``https``
    scheme and host (with or without ``www.``), one path segment of 1..64
    ``A-Za-z0-9_-`` and nothing else. An invalid value logs one warning that
    never echoes the value.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if DONATION_URL_RE.fullmatch(value) is None:
        _config_logger.warning(DONATION_URL_WARNING)
        return None
    return value


def donation_url() -> str | None:
    """The donation link from ``DONATION_URL`` (see ``parse_donation_url``)."""
    return parse_donation_url(os.environ.get("DONATION_URL"))

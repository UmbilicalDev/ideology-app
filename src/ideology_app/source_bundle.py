"""Source Text Bundles: the committed text of an Election's manifestos.

A bundle is a directory ``<root>/<slug>/`` (``root`` is
``config.elections_data_dir()``, ``slug`` is ``election_slug(...)``) holding an
``election.toml`` manifest and one Source Text file (``<party>.md``) per Party.
A Source Text file is written only by ``ideology source extract`` and is never
edited: it holds YAML front matter and each page's text exactly as
``pdf_text.extract_pages`` returned it, under ``<!-- page N -->`` markers.
A Party may also declare a logo (``logo = "logos/<file>"``): an optional
``logos/`` directory holds exactly the declared logo files, checked by
``party_logos`` (PNG, WebP or SVG by content, at most 256 KiB).

Manifest format 1 lists one ``file`` per Party. Format 2
(constituencies-and-candidatures) adds ``[candidatures]`` (the BOE source),
each Party's ``constituencies`` (INE codes or ``"all"``) and ``[[documents]]``
(a file, the Parties it applies to and optionally its Constituencies); see
``docs/specs/constituencies-and-candidatures.md`` (Manifest Format 2).

This module is the only one that parses or serialises Source Text files. It is
pure: no database and no pypdf. Files are read and written as bytes; only
``"\\n"`` separates lines (``"\\r"``, form feeds and Unicode line separators are
page text). See ``docs/specs/source-text-bundle.md`` (File Format).
"""

import datetime as dt
import hashlib
import json
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ideology_app import config
from ideology_app.constituencies import CODES as CONSTITUENCY_CODES
from ideology_app.constituencies import CONSTITUENCIES, name_of
from ideology_app.elections import InvalidInputError
from ideology_app.models import Election, ElectionType
from ideology_app.party_logos import (
    EXTENSION_MEDIA_TYPES,
    InvalidLogoError,
    Logo,
    read_logo_file,
)

BUNDLE_FORMAT = 1
MANIFEST_FORMATS = (1, 2)
MANIFEST_NAME = "election.toml"
MAX_SOURCE_TEXT_BYTES = 50 * 1024 * 1024
NOT_CANONICAL = (
    'not in canonical form (files are written by "ideology source extract", never edited)'
)

_FRONT_MATTER_DELIMITER = "---"
_FRONT_KEYS = (
    "bundle_format",
    "party",
    "source_url",
    "pdf_sha256",
    "page_count",
    "extractor",
    "text_sha256",
)
_OPTIONAL_KEYS = frozenset({"source_url"})
_MARKER_PREFIX = "<!-- page"
_ESCAPED_MARKER_RE = re.compile(r"^\\*<!-- page")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")
LOGOS_DIR = "logos"
_LOGO_RE = re.compile(r"^logos/[a-z0-9][a-z0-9._-]*\.(png|webp|svg)$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_NAME_MAX = 200
_SHORT_NAME_MAX = 50
_BOM = b"\xef\xbb\xbf"

_MANIFEST_TOP_KEYS = frozenset({"format", "election", "parties"})
_MANIFEST_TOP_KEYS_V2 = ("format", "election", "candidatures", "parties")
_MANIFEST_ELECTION_KEYS = ("country", "type", "date", "name")
_MANIFEST_PARTY_KEYS = ("short_name", "name", "file")
_MANIFEST_PARTY_KEYS_V2 = ("short_name", "name", "constituencies")
_MANIFEST_PARTY_OPTIONAL_KEYS = frozenset({"logo"})
_MANIFEST_DOCUMENT_KEYS = ("file", "parties")
_MANIFEST_DOCUMENT_OPTIONAL_KEYS = frozenset({"constituencies", "joint_for"})
_FORMAT_PROBLEM = "format must be 1 or 2"
_CANDIDATURES_SOURCE_MAX = 500
_URL_MAX = 2048


class BundleError(InvalidInputError):
    """A Source Text file or a bundle is malformed. The message is ``<file>:<line>: <problem>``."""


def _error(name: str, line: int, problem: str) -> BundleError:
    return BundleError(f"{name}:{line}: {problem}")


def _marker(number: int) -> str:
    return f"<!-- page {number} -->"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SourceText:
    """A parsed Source Text file. ``content_hash`` is the SHA-256 of the whole file."""

    party: str
    source_url: str | None
    pdf_sha256: str
    page_count: int
    extractor: str
    pages: tuple[str, ...]
    content_hash: str


# --- Serialising ------------------------------------------------------------


def _escape_line(line: str) -> str:
    return "\\" + line if _ESCAPED_MARKER_RE.match(line) else line


def _serialise_body(pages: Sequence[str]) -> str:
    parts: list[str] = []
    for number, text in enumerate(pages, start=1):
        parts.append(_marker(number) + "\n")
        parts.append("\n".join(_escape_line(line) for line in text.split("\n")) + "\n")
    return "".join(parts)


def _encode(text: str, what: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise BundleError(f"{what} cannot be encoded as UTF-8: {exc.reason}") from None


def serialise_source_text(
    *,
    party: str,
    source_url: str | None,
    pdf_sha256: str,
    extractor: str,
    pages: Sequence[str],
) -> bytes:
    """Return the canonical bytes of a Source Text file for ``pages``.

    Raises BundleError when the values cannot form a valid file (no pages, no
    text on any page, a bad hash, empty strings).
    """
    if not isinstance(party, str) or not party.strip():
        raise BundleError("party must be a non-empty string")
    if source_url is not None and (not isinstance(source_url, str) or not source_url):
        raise BundleError("source_url must be a non-empty string when given")
    if not isinstance(pdf_sha256, str) or not _HEX64_RE.match(pdf_sha256):
        raise BundleError("pdf_sha256 must be 64 lowercase hex characters")
    if not isinstance(extractor, str) or not extractor.strip():
        raise BundleError("extractor must be a non-empty string")
    pages = list(pages)
    if not pages:
        raise BundleError("a source text needs at least one page")
    if not all(isinstance(text, str) for text in pages):
        raise BundleError("every page must be a string")
    if not any(text.strip() for text in pages):
        raise BundleError("no page has any text")

    body = _encode(_serialise_body(pages), "page text")
    values: list[tuple[str, Any]] = [
        ("bundle_format", BUNDLE_FORMAT),
        ("party", party),
        ("source_url", source_url),
        ("pdf_sha256", pdf_sha256),
        ("page_count", len(pages)),
        ("extractor", extractor),
        ("text_sha256", _sha256(body)),
    ]
    lines = [_FRONT_MATTER_DELIMITER]
    for key, value in values:
        if value is None:
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    lines.append(_FRONT_MATTER_DELIMITER)
    return ("\n".join(lines) + "\n").encode("ascii") + body


def _serialise(text: SourceText) -> bytes:
    return serialise_source_text(
        party=text.party,
        source_url=text.source_url,
        pdf_sha256=text.pdf_sha256,
        extractor=text.extractor,
        pages=text.pages,
    )


# --- Parsing ----------------------------------------------------------------


def _parse_front_value(name: str, line_no: int, key: str, raw: str) -> Any:
    try:
        value = json.loads(raw)
    except ValueError:
        raise _error(name, line_no, f"{key}: value {raw!r} is not valid JSON") from None
    if key in ("bundle_format", "page_count"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _error(name, line_no, f"{key} must be an integer")
        if key == "bundle_format" and value != BUNDLE_FORMAT:
            raise _error(
                name, line_no, f"bundle_format {value} is not supported (expected {BUNDLE_FORMAT})"
            )
        if key == "page_count" and value < 1:
            raise _error(name, line_no, "page_count must be at least 1")
        return value
    if not isinstance(value, str):
        raise _error(name, line_no, f"{key} must be a string")
    if key in ("pdf_sha256", "text_sha256") and not _HEX64_RE.match(value):
        raise _error(name, line_no, f"{key} must be 64 lowercase hex characters")
    if key in ("party", "extractor", "source_url") and not value.strip():
        raise _error(name, line_no, f"{key} must not be empty")
    return value


def _parse_front_matter(
    name: str, lines: list[str]
) -> tuple[dict[str, Any], dict[str, int], int]:
    """Return the front-matter values, their line numbers and the index of the first body line."""
    if not lines or lines[0] != _FRONT_MATTER_DELIMITER:
        raise _error(name, 1, "missing front matter (the file must start with '---')")
    values: dict[str, Any] = {}
    key_lines: dict[str, int] = {}
    index = 1
    expected = list(_FRONT_KEYS)
    while True:
        if index >= len(lines) - 1:  # the last element is what follows the final "\n"
            raise _error(name, index + 1, "front matter is not closed with '---'")
        line = lines[index]
        line_no = index + 1
        if line == _FRONT_MATTER_DELIMITER:
            missing = [key for key in expected if key not in _OPTIONAL_KEYS]
            if missing:
                raise _error(name, line_no, f"front matter is missing key {missing[0]!r}")
            return values, key_lines, index + 1
        key, sep, raw = line.partition(": ")
        if not sep:
            raise _error(name, line_no, f"front-matter line {line!r} is not 'key: value'")
        if key not in _FRONT_KEYS:
            raise _error(name, line_no, f"unknown front-matter key {key!r}")
        while expected and expected[0] != key and expected[0] in _OPTIONAL_KEYS:
            expected.pop(0)
        if not expected or expected[0] != key:
            if key in values:
                raise _error(name, line_no, f"front-matter key {key!r} is repeated")
            wanted = expected[0] if expected else "'---'"
            raise _error(
                name, line_no, f"front-matter key {key!r} is out of order (expected {wanted!r})"
            )
        expected.pop(0)
        values[key] = _parse_front_value(name, line_no, key, raw)
        key_lines[key] = line_no
        index += 1


def _parse_body(
    name: str, lines: list[str], first: int, page_count: int
) -> list[str]:
    """Return the page texts of the body lines ``lines[first:]``."""
    if lines[-1] != "":
        raise _error(name, len(lines), "the file does not end with a newline")
    body = lines[first:-1]
    if not body:
        raise _error(name, first + 1, "the body has no pages (expected '<!-- page 1 -->')")
    pages: list[list[str]] = []
    for offset, line in enumerate(body):
        line_no = first + offset + 1
        if line.startswith(_MARKER_PREFIX):
            expected = _marker(len(pages) + 1)
            if line != expected:
                raise _error(name, line_no, f"bad page marker {line!r} (expected {expected!r})")
            if pages and not pages[-1]:
                raise _error(name, line_no, f"page {len(pages)} has no text line")
            pages.append([])
            continue
        if not pages:
            raise _error(name, line_no, f"expected {_marker(1)!r}, found {line[:60]!r}")
        if _ESCAPED_MARKER_RE.match(line):
            line = line[1:]
        pages[-1].append(line)
    if not pages[-1]:
        raise _error(name, len(lines) - 1, f"page {len(pages)} has no text line")
    if len(pages) != page_count:
        raise _error(
            name, first + 1, f"page_count is {page_count} but the body has {len(pages)} pages"
        )
    return ["\n".join(page) for page in pages]


def _first_difference_line(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    index = next((i for i in range(limit) if a[i] != b[i]), limit)
    return a[:index].count(b"\n") + 1


def parse_source_text(data: bytes, *, name: str) -> SourceText:
    """Parse and check a Source Text file. Raises BundleError (``<name>:<line>: <problem>``).

    The checks: UTF-8 without a BOM, the front-matter keys in order, the page
    markers, ``page_count``, ``text_sha256``, text on at least one page, at
    most 50 MiB, and the canonical form (re-serialising gives ``data``).
    """
    if len(data) > MAX_SOURCE_TEXT_BYTES:
        raise _error(name, 1, f"file is larger than {MAX_SOURCE_TEXT_BYTES} bytes")
    if data.startswith(_BOM):
        raise _error(name, 1, "file starts with a byte order mark (BOM)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data[: exc.start].count(b"\n") + 1
        raise _error(name, line, f"invalid UTF-8 at byte {exc.start}") from None
    lines = text.split("\n")
    values, key_lines, first = _parse_front_matter(name, lines)
    body_bytes = "\n".join(lines[first:]).encode("utf-8")
    pages = _parse_body(name, lines, first, values["page_count"])
    if _sha256(body_bytes) != values["text_sha256"]:
        raise _error(
            name, key_lines["text_sha256"], "text_sha256 does not match the SHA-256 of the body"
        )
    if not any(page.strip() for page in pages):
        raise _error(name, first + 1, "no page has any text")

    parsed = SourceText(
        party=values["party"],
        source_url=values.get("source_url"),
        pdf_sha256=values["pdf_sha256"],
        page_count=values["page_count"],
        extractor=values["extractor"],
        pages=tuple(pages),
        content_hash=_sha256(data),
    )
    try:
        canonical = _serialise(parsed)
    except BundleError as exc:
        raise _error(name, 1, str(exc)) from None
    if canonical != data:
        raise _error(name, _first_difference_line(data, canonical), NOT_CANONICAL)
    return parsed


# --- Slugs and paths ----------------------------------------------------------


def election_slug(country: str, type: str | ElectionType, date: dt.date) -> str:
    """The bundle directory name of an Election, e.g. ``es-general-2023-07-23``."""
    type_value = type.value if isinstance(type, ElectionType) else type
    return f"{country.lower()}-{type_value}-{date.isoformat()}"


def election_slug_for(election: Election) -> str:
    return election_slug(election.country, election.type, election.date)


def bundle_dir_for(root: Path, election: Election) -> Path:
    """Where ``election``'s bundle lives under ``root`` (it may not exist)."""
    return Path(root) / election_slug_for(election)


def bundle_slug(election: Election, root: Path | None = None) -> str | None:
    """The slug of ``election`` when ``<root>/<slug>/election.toml`` exists, else ``None``.

    ``root`` defaults to ``config.elections_data_dir()``.
    """
    base = config.elections_data_dir() if root is None else Path(root)
    slug = election_slug_for(election)
    return slug if (base / slug / MANIFEST_NAME).is_file() else None


# --- Bundles ------------------------------------------------------------------


@dataclass(frozen=True)
class BundleLogo:
    """A Party's declared logo: its manifest path (``logos/<file>``) and checked bytes."""

    file: str
    logo: Logo


@dataclass(frozen=True)
class BundleParty:
    """A manifest Party (a candidature).

    ``file`` and ``text`` are set only in format 1 (one document per Party, a
    legacy convenience); new code reads ``Bundle.documents``.
    ``constituencies`` is set only in format 2: the sorted INE codes the Party
    runs in (``"all"`` expanded).
    """

    short_name: str
    name: str
    file: str | None = None
    text: SourceText | None = None
    logo: BundleLogo | None = None
    constituencies: tuple[str, ...] | None = None


@dataclass(frozen=True)
class BundleDocument:
    """A Source Text file and the Parties (and optionally Constituencies) it applies to.

    Format 1 derives one per Party (``parties=(short_name,)``, no
    ``constituencies``). ``constituencies`` is the declared scope, sorted, or
    ``None`` (every Constituency of each listed Party); see ``document_scope``.
    ``joint_for`` names the listed Parties for which this file is the
    coalition's own joint manifesto (format 2 only; ``proposal-conflicts``).
    """

    file: str
    text: SourceText
    parties: tuple[str, ...]
    constituencies: tuple[str, ...] | None = None
    joint_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidatureSource:
    """Where a format-2 manifest's candidatures come from (the BOE proclamation)."""

    source: str
    url: str | None = None


@dataclass(frozen=True)
class Bundle:
    """A fully checked bundle: nothing in it has to be validated again."""

    path: Path
    slug: str
    country: str
    type: ElectionType
    date: dt.date
    name: str
    parties: tuple[BundleParty, ...]
    format: int = 1
    candidatures: CandidatureSource | None = None
    documents: tuple[BundleDocument, ...] = ()

    def party(self, short_name: str) -> BundleParty:
        """The manifest Party with ``short_name``. Raises KeyError."""
        for entry in self.parties:
            if entry.short_name == short_name:
                return entry
        raise KeyError(short_name)


def document_scope(bundle: Bundle, document: BundleDocument, short_name: str) -> tuple[str, ...]:
    """The Constituencies ``document`` applies to for the Party ``short_name`` (D1).

    The document's declared Constituencies, or every Constituency of the
    Party when none are declared, intersected with the Party's
    Constituencies; sorted. Empty for a format-1 bundle (no candidatures).
    """
    party_codes = bundle.party(short_name).constituencies or ()
    if document.constituencies is None:
        return tuple(party_codes)
    declared = set(document.constituencies)
    return tuple(code for code in party_codes if code in declared)


class _ManifestLines:
    """Best-effort line numbers for manifest errors (tomllib gives none for values).

    Array-table indexes are counted per section: ``[[documents]]`` restarts at 0
    after ``[[parties]]``.
    """

    _KEY_RE = re.compile(r'^\s*"?([A-Za-z0-9_-]+)"?\s*=')

    def __init__(self, text: str) -> None:
        self._keys: dict[tuple[str, int, str], int] = {}
        self._tables: dict[tuple[str, int], int] = {}
        section, index = "", 0
        array_counts: dict[str, int] = {}
        for number, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip()
            header = line.split("#")[0].strip().strip("[]").strip()
            if line.startswith("[["):
                section = header
                index = array_counts.get(section, 0)
                array_counts[section] = index + 1
                self._tables.setdefault((section, index), number)
                continue
            if line.startswith("["):
                section, index = header, 0
                self._tables.setdefault((section, index), number)
                continue
            match = self._KEY_RE.match(raw)
            if match:
                self._keys.setdefault((section, index, match.group(1)), number)

    def of(self, section: str = "", index: int = 0, key: str | None = None) -> int:
        if key is not None and (section, index, key) in self._keys:
            return self._keys[(section, index, key)]
        return self._tables.get((section, index), 1)


def _check_keys(
    name: str,
    line: int,
    table: dict[str, Any],
    keys: Sequence[str] | frozenset[str],
    where: str,
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = sorted(set(table) - set(keys) - optional)
    if unknown:
        raise _error(name, line, f"unknown key {unknown[0]!r} in {where}")
    missing = [key for key in keys if key not in table]
    if missing:
        raise _error(name, line, f"missing key {missing[0]!r} in {where}")


def _text_value(
    name: str, line: int, value: Any, field: str, max_length: int
) -> str:
    if not isinstance(value, str):
        raise _error(name, line, f"{field} must be a string")
    if not value.strip():
        raise _error(name, line, f"{field} must not be empty")
    if value != value.strip():
        raise _error(name, line, f"{field} must not have leading or trailing whitespace")
    if len(value) > max_length:
        raise _error(name, line, f"{field} must be at most {max_length} characters")
    return value


@dataclass(frozen=True)
class _ManifestParty:
    short_name: str
    name: str
    file: str | None
    logo: str | None = None
    logo_line: int = 1
    constituencies: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _ManifestDocument:
    file: str
    parties: tuple[str, ...]
    constituencies: tuple[str, ...] | None
    line: int
    joint_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Manifest:
    format: int
    country: str
    type: ElectionType
    date: dt.date
    name: str
    parties: list[_ManifestParty]
    candidatures: CandidatureSource | None = None
    documents: list[_ManifestDocument] | None = None


def _check_file(name: str, line: int, file: Any) -> str:
    if not isinstance(file, str) or not _FILE_RE.match(file):
        raise _error(
            name,
            line,
            f"file {file!r} is invalid: expected a name like 'pp.md' "
            "(lower-case letters, digits, '.', '_', '-')",
        )
    return file


def _constituency_codes(name: str, line: int, value: Any, owner: str) -> tuple[str, ...]:
    """A ``constituencies`` value: ``"all"`` or a non-empty list of INE codes; sorted."""
    if value == "all":
        return tuple(code for code, _ in CONSTITUENCIES)
    if not isinstance(value, list):
        raise _error(
            name, line, 'constituencies must be "all" or a list of INE codes such as ["28"]'
        )
    if not value:
        raise _error(name, line, f"{owner} has no Constituencies")
    seen: set[str] = set()
    for code in value:
        if isinstance(code, bool) or isinstance(code, int):
            raise _error(name, line, f'Constituency {code!r} must be a string such as "28"')
        if not isinstance(code, str):
            raise _error(name, line, f'Constituency {code!r} must be a string such as "28"')
        if code not in CONSTITUENCY_CODES:
            raise _error(
                name,
                line,
                f"unknown Constituency {code!r} (expected an INE code 01..52; "
                'see "ideology constituency list")',
            )
        if code in seen:
            raise _error(name, line, f"duplicate Constituency {code!r}")
        seen.add(code)
    return tuple(sorted(seen))


def _read_election(name: str, lines: _ManifestLines, manifest: dict[str, Any]) -> tuple[
    str, ElectionType, dt.date, str
]:
    election = manifest["election"]
    if not isinstance(election, dict):
        raise _error(name, lines.of(key="election"), "[election] must be a table")
    _check_keys(name, lines.of("election"), election, _MANIFEST_ELECTION_KEYS, "[election]")
    country = election["country"]
    if not isinstance(country, str) or not _COUNTRY_RE.match(country):
        raise _error(
            name,
            lines.of("election", key="country"),
            f"country {country!r} is invalid: expected a two-letter upper-case code such as ES",
        )
    type_value = election["type"]
    try:
        election_type = ElectionType(type_value)
    except ValueError:
        allowed = ", ".join(t.value for t in ElectionType)
        raise _error(
            name,
            lines.of("election", key="type"),
            f"type {type_value!r} is invalid: expected one of {allowed}",
        ) from None
    date = election["date"]
    if not isinstance(date, dt.date) or isinstance(date, dt.datetime):
        raise _error(
            name, lines.of("election", key="date"), f"date {date!r} is invalid: expected a TOML date"
        )
    election_name = _text_value(
        name, lines.of("election", key="name"), election["name"], "election name", _NAME_MAX
    )
    return country, election_type, date, election_name


def _read_parties(
    name: str, lines: _ManifestLines, manifest: dict[str, Any], format: int
) -> list[_ManifestParty]:
    parties_raw = manifest["parties"]
    if not isinstance(parties_raw, list) or not parties_raw:
        raise _error(name, lines.of(key="parties"), "[[parties]] must list at least one party")
    keys = _MANIFEST_PARTY_KEYS if format == 1 else _MANIFEST_PARTY_KEYS_V2
    parties: list[_ManifestParty] = []
    seen: dict[str, set[str]] = {
        "short_name": set(), "name": set(), "file": set(), "logo": set()
    }
    for index, entry in enumerate(parties_raw):
        where = f"[[parties]] #{index + 1}"
        if not isinstance(entry, dict):
            raise _error(name, lines.of("parties", index), f"{where} must be a table")
        _check_keys(
            name, lines.of("parties", index), entry, keys, where,
            _MANIFEST_PARTY_OPTIONAL_KEYS,
        )
        short_name = _text_value(
            name, lines.of("parties", index, "short_name"), entry["short_name"],
            "short_name", _SHORT_NAME_MAX,
        )
        party_name = _text_value(
            name, lines.of("parties", index, "name"), entry["name"], "name", _NAME_MAX
        )
        file = (
            _check_file(name, lines.of("parties", index, "file"), entry["file"])
            if format == 1
            else None
        )
        constituencies = (
            _constituency_codes(
                name,
                lines.of("parties", index, "constituencies"),
                entry["constituencies"],
                f"party {short_name}",
            )
            if format == 2
            else None
        )
        logo = entry.get("logo")
        logo_line = lines.of("parties", index, "logo")
        if logo is not None and (not isinstance(logo, str) or not _LOGO_RE.match(logo)):
            raise _error(
                name,
                logo_line,
                f"logo {logo!r} is invalid: expected a path like 'logos/pp.svg' "
                "(lower-case letters, digits, '.', '_', '-'; .png, .webp or .svg)",
            )
        values: list[tuple[str, str]] = [("short_name", short_name), ("name", party_name)]
        if file is not None:
            values.append(("file", file))
        if logo is not None:
            values.append(("logo", logo))
        for field, value in values:
            if value in seen[field]:
                raise _error(
                    name, lines.of("parties", index, field), f"duplicate {field} {value!r}"
                )
            seen[field].add(value)
        parties.append(
            _ManifestParty(short_name, party_name, file, logo, logo_line, constituencies)
        )
    return parties


def _read_candidatures(
    name: str, lines: _ManifestLines, manifest: dict[str, Any]
) -> CandidatureSource:
    table = manifest["candidatures"]
    if not isinstance(table, dict):
        raise _error(name, lines.of(key="candidatures"), "[candidatures] must be a table")
    _check_keys(
        name, lines.of("candidatures"), table, ("source",), "[candidatures]",
        frozenset({"url"}),
    )
    source = _text_value(
        name, lines.of("candidatures", key="source"), table["source"],
        "candidatures source", _CANDIDATURES_SOURCE_MAX,
    )
    url = table.get("url")
    if url is not None:
        url = _text_value(
            name, lines.of("candidatures", key="url"), url, "candidatures url", _URL_MAX
        )
    return CandidatureSource(source, url)


def _joint_for(
    name: str, line: int, value: Any, file: str, short_names: list[str]
) -> tuple[str, ...]:
    """``joint_for``: a non-empty list of the document's own Parties, no duplicates."""
    if not isinstance(value, list) or not value:
        raise _error(
            name, line, f"document {file}: joint_for must be a non-empty list of short names"
        )
    joint: list[str] = []
    for short_name in value:
        if not isinstance(short_name, str):
            raise _error(
                name, line, f"document {file}: joint_for party {short_name!r} must be a string"
            )
        if short_name not in short_names:
            raise _error(
                name, line,
                f"document {file}: joint_for party {short_name!r} is not in its parties",
            )
        if short_name in joint:
            raise _error(name, line, f"document {file}: duplicate joint_for party {short_name!r}")
        joint.append(short_name)
    return tuple(joint)


def _read_documents(
    name: str, lines: _ManifestLines, manifest: dict[str, Any], parties: list[_ManifestParty]
) -> list[_ManifestDocument]:
    raw = manifest.get("documents", [])
    if not isinstance(raw, list):
        raise _error(name, lines.of(key="documents"), "[[documents]] must be a list of tables")
    by_short = {party.short_name: party for party in parties}
    documents: list[_ManifestDocument] = []
    files: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"[[documents]] #{index + 1}"
        line = lines.of("documents", index)
        if not isinstance(entry, dict):
            raise _error(name, line, f"{where} must be a table")
        _check_keys(
            name, line, entry, _MANIFEST_DOCUMENT_KEYS, where,
            _MANIFEST_DOCUMENT_OPTIONAL_KEYS,
        )
        file_line = lines.of("documents", index, "file")
        file = _check_file(name, file_line, entry["file"])
        if file in files:
            raise _error(name, file_line, f"duplicate file {file!r}")
        files.add(file)
        parties_line = lines.of("documents", index, "parties")
        listed = entry["parties"]
        if not isinstance(listed, list) or not listed:
            raise _error(
                name, parties_line, f"document {file}: parties must be a non-empty list of "
                "short names"
            )
        short_names: list[str] = []
        for short_name in listed:
            if not isinstance(short_name, str):
                raise _error(
                    name, parties_line, f"document {file}: party {short_name!r} must be a string"
                )
            if short_name not in by_short:
                raise _error(
                    name, parties_line,
                    f"document {file}: party {short_name!r} is not declared in [[parties]]",
                )
            if short_name in short_names:
                raise _error(
                    name, parties_line, f"document {file}: duplicate party {short_name!r}"
                )
            short_names.append(short_name)
        constituencies: tuple[str, ...] | None = None
        if "constituencies" in entry:
            scope_line = lines.of("documents", index, "constituencies")
            constituencies = _constituency_codes(
                name, scope_line, entry["constituencies"], f"document {file}"
            )
            run = set().union(*(by_short[s].constituencies or () for s in short_names))
            outside = [code for code in constituencies if code not in run]
            if outside:
                raise _error(
                    name, scope_line,
                    f"document {file}: Constituency {outside[0]} ({name_of(outside[0])}) is "
                    "not run by any of its parties",
                )
            declared = set(constituencies)
            for short_name in short_names:
                if not declared & set(by_short[short_name].constituencies or ()):
                    raise _error(
                        name, scope_line,
                        f"document {file}: party {short_name} runs in none of its "
                        "Constituencies",
                    )
        joint_for: tuple[str, ...] = ()
        if "joint_for" in entry:
            joint_for = _joint_for(
                name, lines.of("documents", index, "joint_for"), entry["joint_for"], file,
                short_names,
            )
        documents.append(
            _ManifestDocument(file, tuple(short_names), constituencies, line, joint_for)
        )
    return documents


def _read_manifest(directory: Path) -> _Manifest:
    path = directory / MANIFEST_NAME
    name = str(path)
    if not path.is_file():
        raise _error(name, 1, "manifest not found")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
        manifest = tomllib.loads(text)
    except UnicodeDecodeError as exc:
        raise _error(name, raw[: exc.start].count(b"\n") + 1, "invalid UTF-8") from None
    except tomllib.TOMLDecodeError as exc:
        line = getattr(exc, "lineno", None) or 1
        raise _error(name, line, f"invalid TOML: {exc}") from None
    lines = _ManifestLines(text)

    format_value = manifest.get("format")
    if "format" in manifest and (
        isinstance(format_value, bool) or format_value not in MANIFEST_FORMATS
    ):
        # A bad format is reported as such, whatever other keys the manifest has
        # (constituencies-and-candidatures validation: format 3 with format-2 keys).
        raise _error(name, lines.of(key="format"), _FORMAT_PROBLEM)
    if format_value != 2:
        # Format 1 (or a bad format): checked exactly as before format 2 existed.
        _check_keys(name, 1, manifest, _MANIFEST_TOP_KEYS, "the manifest")
        if isinstance(manifest["format"], bool) or manifest["format"] not in MANIFEST_FORMATS:
            raise _error(name, lines.of(key="format"), _FORMAT_PROBLEM)
        country, election_type, date, election_name = _read_election(name, lines, manifest)
        parties = _read_parties(name, lines, manifest, 1)
        return _Manifest(1, country, election_type, date, election_name, parties)

    _check_keys(
        name, 1, manifest, _MANIFEST_TOP_KEYS_V2, "the manifest", frozenset({"documents"})
    )
    country, election_type, date, election_name = _read_election(name, lines, manifest)
    candidatures = _read_candidatures(name, lines, manifest)
    parties = _read_parties(name, lines, manifest, 2)
    documents = _read_documents(name, lines, manifest, parties)
    return _Manifest(
        2, country, election_type, date, election_name, parties, candidatures, documents
    )


def _check_logos_dir(directory: Path, declared: set[str]) -> None:
    """``logos/`` (when present) is a directory of regular files, each one declared."""
    logos = directory / LOGOS_DIR
    if not logos.is_symlink() and not logos.exists():
        return
    if logos.is_symlink() or not logos.is_dir():
        raise _error(str(logos), 1, "logos must be a directory, not a link or a file")
    for child in sorted(logos.iterdir(), key=lambda p: p.name):
        if child.name.startswith("."):
            continue
        if child.is_symlink():
            raise _error(str(child), 1, "logo file must not be a symbolic link")
        if child.is_dir():
            raise _error(str(child), 1, "subdirectories are not allowed in logos/")
        if not child.is_file():
            raise _error(str(child), 1, "logo file is not a regular file")
        if f"{LOGOS_DIR}/{child.name}" not in declared:
            raise _error(str(child), 1, f"file is not declared as a logo in {MANIFEST_NAME}")


def _read_logo(directory: Path, manifest: str, entry: _ManifestParty) -> BundleLogo | None:
    if entry.logo is None:
        return None
    path = directory / entry.logo
    if not path.is_symlink() and not path.exists():
        raise _error(manifest, entry.logo_line, f"logo file {entry.logo!r} not found")
    try:
        logo = read_logo_file(path)
    except InvalidLogoError as exc:
        raise _error(str(path), 1, str(exc)) from None
    expected = EXTENSION_MEDIA_TYPES[Path(entry.logo).suffix]
    if logo.media_type != expected:
        raise _error(
            str(path),
            1,
            f"extension {Path(entry.logo).suffix} does not match its content ({logo.media_type})",
        )
    return BundleLogo(entry.logo, logo)


def _read_source_text(directory: Path, file: str) -> SourceText:
    file_path = directory / file
    file_name = str(file_path)
    if not file_path.is_file():
        raise _error(file_name, 1, f"file listed in {MANIFEST_NAME} not found")
    if file_path.stat().st_size > MAX_SOURCE_TEXT_BYTES:
        raise _error(file_name, 1, f"file is larger than {MAX_SOURCE_TEXT_BYTES} bytes")
    return parse_source_text(file_path.read_bytes(), name=file_name)


def read_bundle(path: Path) -> Bundle:
    """Read and fully check the bundle in ``path``. Raises BundleError.

    Checks the manifest (format 1 or 2), the directory name (the slug), that
    no ``*.pdf`` is anywhere under it, that every top-level ``*.md`` is listed
    and every listed file exists, and parses every Source Text file (whose
    ``party`` must equal its manifest ``short_name`` in format 1, or be one of
    the document's ``parties`` in format 2). Every declared logo is read and
    checked (``party_logos``; its extension must match its content), and
    ``logos/`` must hold only declared logo files (dotfiles are ignored).
    Nothing is written.
    """
    directory = Path(path)
    if not directory.is_dir():
        raise _error(str(directory), 1, "bundle directory not found")
    manifest_data = _read_manifest(directory)
    manifest_parties = manifest_data.parties
    manifest = str(directory / MANIFEST_NAME)

    slug = election_slug(manifest_data.country, manifest_data.type, manifest_data.date)
    actual = directory.resolve().name
    if actual != slug:
        raise _error(
            manifest, 1, f"bundle directory is named {actual!r}; expected {slug!r}"
        )
    pdfs = sorted(p for p in directory.rglob("*") if p.suffix.lower() == ".pdf")
    if pdfs:
        raise _error(str(pdfs[0]), 1, "PDF files must not be in a bundle")
    if manifest_data.format == 1:
        listed = {party.file for party in manifest_parties}
    else:
        listed = {document.file for document in manifest_data.documents or ()}
    unlisted = sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".md" and not p.name.startswith(".")
        and p.name not in listed
    )
    if unlisted:
        raise _error(
            str(directory / unlisted[0]), 1, f"file is not listed in {MANIFEST_NAME}"
        )

    _check_logos_dir(
        directory, {party.logo for party in manifest_parties if party.logo is not None}
    )

    if manifest_data.format == 1:
        parties: list[BundleParty] = []
        for entry in manifest_parties:
            assert entry.file is not None
            source_text = _read_source_text(directory, entry.file)
            if source_text.party != entry.short_name:
                raise _error(
                    str(directory / entry.file),
                    3,
                    f"party {source_text.party!r} does not match the manifest short_name "
                    f"{entry.short_name!r}",
                )
            logo = _read_logo(directory, manifest, entry)
            parties.append(
                BundleParty(entry.short_name, entry.name, entry.file, source_text, logo)
            )
        documents = tuple(
            BundleDocument(party.file, party.text, (party.short_name,))
            for party in parties
            if party.file is not None and party.text is not None
        )
        return Bundle(
            path=directory,
            slug=slug,
            country=manifest_data.country,
            type=manifest_data.type,
            date=manifest_data.date,
            name=manifest_data.name,
            parties=tuple(parties),
            format=1,
            documents=documents,
        )

    parties = [
        BundleParty(
            entry.short_name,
            entry.name,
            logo=_read_logo(directory, manifest, entry),
            constituencies=entry.constituencies,
        )
        for entry in manifest_parties
    ]
    read_documents: list[BundleDocument] = []
    hashes: dict[tuple[str, str], str] = {}
    for document in manifest_data.documents or ():
        source_text = _read_source_text(directory, document.file)
        if source_text.party not in document.parties:
            raise _error(
                str(directory / document.file),
                3,
                f"party {source_text.party!r} is not one of the document's parties in "
                f"{MANIFEST_NAME} ({', '.join(document.parties)})",
            )
        for short_name in document.parties:
            other = hashes.get((short_name, source_text.content_hash))
            if other is not None:
                raise _error(
                    manifest,
                    document.line,
                    f"documents {other} and {document.file} both list party {short_name} "
                    "and have the same content",
                )
            hashes[(short_name, source_text.content_hash)] = document.file
        read_documents.append(
            BundleDocument(
                document.file, source_text, document.parties, document.constituencies,
                document.joint_for,
            )
        )
    return Bundle(
        path=directory,
        slug=slug,
        country=manifest_data.country,
        type=manifest_data.type,
        date=manifest_data.date,
        name=manifest_data.name,
        parties=tuple(parties),
        format=2,
        candidatures=manifest_data.candidatures,
        documents=tuple(read_documents),
    )

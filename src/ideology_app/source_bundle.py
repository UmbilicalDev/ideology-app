"""Source Text Bundles: the committed text of an Election's manifestos.

A bundle is a directory ``<root>/<slug>/`` (``root`` is
``config.elections_data_dir()``, ``slug`` is ``election_slug(...)``) holding an
``election.toml`` manifest and one Source Text file (``<party>.md``) per Party.
A Source Text file is written only by ``ideology source extract`` and is never
edited: it holds YAML front matter and each page's text exactly as
``pdf_text.extract_pages`` returned it, under ``<!-- page N -->`` markers.

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
from ideology_app.elections import InvalidInputError
from ideology_app.models import Election, ElectionType

BUNDLE_FORMAT = 1
MANIFEST_FORMAT = 1
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
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_NAME_MAX = 200
_SHORT_NAME_MAX = 50
_BOM = b"\xef\xbb\xbf"

_MANIFEST_TOP_KEYS = frozenset({"format", "election", "parties"})
_MANIFEST_ELECTION_KEYS = ("country", "type", "date", "name")
_MANIFEST_PARTY_KEYS = ("short_name", "name", "file")


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
class BundleParty:
    short_name: str
    name: str
    file: str
    text: SourceText


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


class _ManifestLines:
    """Best-effort line numbers for manifest errors (tomllib gives none for values)."""

    _KEY_RE = re.compile(r'^\s*"?([A-Za-z0-9_-]+)"?\s*=')

    def __init__(self, text: str) -> None:
        self._keys: dict[tuple[str, int, str], int] = {}
        self._tables: dict[tuple[str, int], int] = {}
        section, index = "", 0
        party_count = 0
        for number, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip()
            header = line.split("#")[0].strip().strip("[]").strip()
            if line.startswith("[["):
                section, index = header, party_count
                party_count += 1
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
    name: str, line: int, table: dict[str, Any], keys: Sequence[str] | frozenset[str], where: str
) -> None:
    unknown = sorted(set(table) - set(keys))
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
    file: str


def _read_manifest(
    directory: Path,
) -> tuple[str, ElectionType, dt.date, str, list[_ManifestParty]]:
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

    _check_keys(name, 1, manifest, _MANIFEST_TOP_KEYS, "the manifest")
    if isinstance(manifest["format"], bool) or manifest["format"] != MANIFEST_FORMAT:
        raise _error(
            name, lines.of(key="format"), f"format must be {MANIFEST_FORMAT}"
        )

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

    parties_raw = manifest["parties"]
    if not isinstance(parties_raw, list) or not parties_raw:
        raise _error(name, lines.of(key="parties"), "[[parties]] must list at least one party")
    parties: list[_ManifestParty] = []
    seen: dict[str, set[str]] = {"short_name": set(), "name": set(), "file": set()}
    for index, entry in enumerate(parties_raw):
        where = f"[[parties]] #{index + 1}"
        if not isinstance(entry, dict):
            raise _error(name, lines.of("parties", index), f"{where} must be a table")
        _check_keys(name, lines.of("parties", index), entry, _MANIFEST_PARTY_KEYS, where)
        short_name = _text_value(
            name, lines.of("parties", index, "short_name"), entry["short_name"],
            "short_name", _SHORT_NAME_MAX,
        )
        party_name = _text_value(
            name, lines.of("parties", index, "name"), entry["name"], "name", _NAME_MAX
        )
        file = entry["file"]
        if not isinstance(file, str) or not _FILE_RE.match(file):
            raise _error(
                name,
                lines.of("parties", index, "file"),
                f"file {file!r} is invalid: expected a name like 'pp.md' "
                "(lower-case letters, digits, '.', '_', '-')",
            )
        for field, value in (("short_name", short_name), ("name", party_name), ("file", file)):
            if value in seen[field]:
                raise _error(
                    name, lines.of("parties", index, field), f"duplicate {field} {value!r}"
                )
            seen[field].add(value)
        parties.append(_ManifestParty(short_name, party_name, file))
    return country, election_type, date, election_name, parties


def read_bundle(path: Path) -> Bundle:
    """Read and fully check the bundle in ``path``. Raises BundleError.

    Checks the manifest, the directory name (the slug), that no ``*.pdf`` is
    anywhere under it, that every top-level ``*.md`` is listed and every
    listed file exists, and parses every Source Text file (whose ``party``
    must equal its manifest ``short_name``). Nothing is written.
    """
    directory = Path(path)
    if not directory.is_dir():
        raise _error(str(directory), 1, "bundle directory not found")
    country, election_type, date, election_name, manifest_parties = _read_manifest(directory)
    manifest = str(directory / MANIFEST_NAME)

    slug = election_slug(country, election_type, date)
    actual = directory.resolve().name
    if actual != slug:
        raise _error(
            manifest, 1, f"bundle directory is named {actual!r}; expected {slug!r}"
        )
    pdfs = sorted(p for p in directory.rglob("*") if p.suffix.lower() == ".pdf")
    if pdfs:
        raise _error(str(pdfs[0]), 1, "PDF files must not be in a bundle")
    listed = {party.file for party in manifest_parties}
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

    parties: list[BundleParty] = []
    for entry in manifest_parties:
        file_path = directory / entry.file
        file_name = str(file_path)
        if not file_path.is_file():
            raise _error(file_name, 1, f"file listed in {MANIFEST_NAME} not found")
        if file_path.stat().st_size > MAX_SOURCE_TEXT_BYTES:
            raise _error(file_name, 1, f"file is larger than {MAX_SOURCE_TEXT_BYTES} bytes")
        source_text = parse_source_text(file_path.read_bytes(), name=file_name)
        if source_text.party != entry.short_name:
            raise _error(
                file_name,
                3,
                f"party {source_text.party!r} does not match the manifest short_name "
                f"{entry.short_name!r}",
            )
        parties.append(BundleParty(entry.short_name, entry.name, entry.file, source_text))

    return Bundle(
        path=directory,
        slug=slug,
        country=country,
        type=election_type,
        date=date,
        name=election_name,
        parties=tuple(parties),
    )

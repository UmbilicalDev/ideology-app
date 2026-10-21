"""Source Text format and bundle reader (source-text-bundle Scenarios 3 and 8, slugs).

Also the read-only check of every committed bundle under ``data/elections/``.
"""

import dataclasses
import datetime as dt
import hashlib
import re
from pathlib import Path

import pytest
from bundle_factory import PP, PSOE, SLUG, manifest_text, write_bundle

from ideology_app import config
from ideology_app.models import Election, ElectionType
from ideology_app.source_bundle import (
    MANIFEST_NAME,
    NOT_CANONICAL,
    BundleError,
    bundle_dir_for,
    bundle_slug,
    election_slug,
    election_slug_for,
    parse_source_text,
    read_bundle,
    serialise_source_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_ROOT = REPO_ROOT / "data" / "elections"
PDF_SHA = "a" * 64


def _serialise(pages: list[str], source_url: str | None = None, party: str = "PP") -> bytes:
    return serialise_source_text(
        party=party, source_url=source_url, pdf_sha256=PDF_SHA, extractor="pypdf 9.9", pages=pages
    )


def _split(data: bytes) -> tuple[bytes, bytes]:
    """(front matter including the closing ``---\\n``, body)."""
    head, _, body = data.partition(b"\n---\n")
    return head + b"\n---\n", body


def _with_body(data: bytes, body: bytes) -> bytes:
    """Replace the body and fix ``text_sha256`` so only the body check can fail."""
    head, old_body = _split(data)
    new_hash = hashlib.sha256(body).hexdigest().encode()
    old_hash = hashlib.sha256(old_body).hexdigest().encode()
    return head.replace(old_hash, new_hash) + body


# --- Scenario 3: round trip --------------------------------------------------

ROUND_TRIP_PAGES = [
    ["texto"],
    ["", "texto"],
    ["\n", "a\n\n", "b"],
    ["línea uno\r\nlínea dos\r\n"],
    ["salto de página\x0c", " ", "acentos: áéíóú ñ ç €"],
    ["<!-- page 1 -->", "x\n<!-- page 2 -->\ny"],
    ["\\<!-- page", "\\\\<!-- page 3 -->\n\\x", "<!-- pagex"],
    ["espacios al final   \n  ", " separador ", "fin"],
]


@pytest.mark.parametrize("pages", ROUND_TRIP_PAGES)
def test_round_trip_is_byte_exact(pages: list[str]) -> None:
    data = _serialise(pages)
    parsed = parse_source_text(data, name="pp.md")

    assert list(parsed.pages) == pages
    assert parsed.page_count == len(pages)
    assert parsed.content_hash == hashlib.sha256(data).hexdigest()
    assert _serialise(list(parsed.pages)) == data


def test_layout_of_a_file() -> None:
    data = _serialise(
        ["uno", "", "<!-- page 2 -->\n\\<!-- page 9 -->"], source_url="https://e.org/p.pdf"
    )
    head, body = _split(data)
    assert head.decode().split("\n") == [
        "---",
        "bundle_format: 1",
        'party: "PP"',
        'source_url: "https://e.org/p.pdf"',
        f'pdf_sha256: "{PDF_SHA}"',
        "page_count: 3",
        'extractor: "pypdf 9.9"',
        f'text_sha256: "{hashlib.sha256(body).hexdigest()}"',
        "---",
        "",
    ]
    assert body == (
        b"<!-- page 1 -->\nuno\n"
        b"<!-- page 2 -->\n\n"
        b"<!-- page 3 -->\n\\<!-- page 2 -->\n\\\\<!-- page 9 -->\n"
    )


def test_without_url_the_line_is_absent() -> None:
    data = _serialise(["uno"])
    assert b"source_url" not in data
    assert parse_source_text(data, name="pp.md").source_url is None


def test_strings_are_json_ascii_escaped() -> None:
    data = _serialise(["uno"], party="EH Bildu ñ")
    assert b'party: "EH Bildu \\u00f1"' in data
    assert parse_source_text(data, name="x.md").party == "EH Bildu ñ"


@pytest.mark.parametrize(
    ("pages", "message"),
    [([], "at least one page"), (["", "  \n"], "no page has any text")],
)
def test_serialise_refuses_files_that_would_not_parse(pages: list[str], message: str) -> None:
    with pytest.raises(BundleError, match=message):
        _serialise(pages)


def test_serialise_refuses_lone_surrogates() -> None:
    with pytest.raises(BundleError, match="UTF-8"):
        _serialise(["a\ud800b"])


# --- Scenario 8: malformed Source Text files ---------------------------------

GOOD = _serialise(["uno", "", "tres\n"], source_url="https://e.org/p.pdf")


def _replace_line(data: bytes, old: bytes, new: bytes) -> bytes:
    assert old in data
    return data.replace(old, new, 1)


BAD_FILES: dict[str, tuple[bytes, int, str]] = {
    "no front matter": (_split(GOOD)[1], 1, "missing front matter"),
    "unclosed front matter": (b"---\nbundle_format: 1\n", 3, "not closed"),
    "unknown key": (
        _replace_line(GOOD, b"bundle_format: 1\n", b"bundle_format: 1\nauthor: \"x\"\n"),
        3,
        "unknown front-matter key 'author'",
    ),
    "reordered keys": (
        _replace_line(
            _replace_line(GOOD, b'party: "PP"\n', b""),
            b"page_count: 3\n",
            b'page_count: 3\nparty: "PP"\n',
        ),
        3,
        "out of order",
    ),
    "missing key": (
        _replace_line(GOOD, b'extractor: "pypdf 9.9"\n', b""),
        7,
        "out of order (expected 'extractor')",
    ),
    "missing last key": (
        re.sub(rb'text_sha256: "[0-9a-f]+"\n', b"", GOOD),
        8,
        "missing key 'text_sha256'",
    ),
    "not key value": (_replace_line(GOOD, b"page_count: 3", b"page_count=3"), 6, "not 'key: value'"),
    "bad JSON value": (_replace_line(GOOD, b'party: "PP"', b"party: PP"), 3, "not valid JSON"),
    "integer as string": (
        _replace_line(GOOD, b"page_count: 3", b'page_count: "3"'), 6, "must be an integer"
    ),
    "bool format": (
        _replace_line(GOOD, b"bundle_format: 1", b"bundle_format: true"), 2, "must be an integer"
    ),
    "unsupported format": (
        _replace_line(GOOD, b"bundle_format: 1", b"bundle_format: 2"), 2, "not supported"
    ),
    "bad pdf hash": (
        _replace_line(GOOD, PDF_SHA.encode(), b"A" * 64), 5, "64 lowercase hex"
    ),
    "page_count mismatch": (
        _replace_line(GOOD, b"page_count: 3", b"page_count: 4"), 10, "page_count is 4"
    ),
    "page_count zero": (
        _replace_line(GOOD, b"page_count: 3", b"page_count: 0"), 6, "at least 1"
    ),
    "text_sha256 mismatch": (
        _split(GOOD)[0] + _split(GOOD)[1].replace(b"uno", b"UNO"),
        8,
        "text_sha256 does not match",
    ),
    "skipped marker": (
        _with_body(GOOD, b"<!-- page 1 -->\nuno\n<!-- page 3 -->\n\n<!-- page 3 -->\ntres\n\n"),
        12,
        "bad page marker '<!-- page 3 -->' (expected '<!-- page 2 -->')",
    ),
    "bad marker": (
        _with_body(GOOD, b"<!-- page 1 -->\nuno\n<!-- page 2-->\n\n<!-- page 3 -->\ntres\n\n"),
        12,
        "bad page marker",
    ),
    "unescaped marker-like line": (
        _with_body(GOOD, b"<!-- page 1 -->\nuno\n<!-- pages -->\n<!-- page 2 -->\n\n"
                         b"<!-- page 3 -->\ntres\n\n"),
        12,
        "bad page marker '<!-- pages -->'",
    ),
    "body without marker": (
        _with_body(GOOD, b"uno\n<!-- page 1 -->\nuno\n"), 10, "expected '<!-- page 1 -->'"
    ),
    "missing final newline": (_serialise(["uno"])[:-1], 10, "does not end with a newline"),
    "invalid UTF-8": (
        _with_body(GOOD, b"<!-- page 1 -->\nuno \xff\n<!-- page 2 -->\n\n<!-- page 3 -->\ntres\n\n"),
        11,
        "invalid UTF-8",
    ),
    "BOM": (b"\xef\xbb\xbf" + GOOD, 1, "byte order mark"),
    "no text on any page": (
        _with_body(GOOD, b"<!-- page 1 -->\n \n<!-- page 2 -->\n\n<!-- page 3 -->\n\n\n"),
        10,
        "no page has any text",
    ),
    "page without a text line": (
        _with_body(GOOD, b"<!-- page 1 -->\nuno\n<!-- page 2 -->\n<!-- page 3 -->\ntres\n\n"),
        13,
        "page 2 has no text line",
    ),
    "not canonical (space after a value)": (
        _replace_line(GOOD, b"page_count: 3", b"page_count: 3 "), 6, NOT_CANONICAL
    ),
    "not canonical (non-ASCII in front matter)": (
        _replace_line(GOOD, b'"pypdf 9.9"', '"pypdf 9.9 ñ"'.encode()), 7, NOT_CANONICAL
    ),
}


@pytest.mark.parametrize("case", sorted(BAD_FILES))
def test_malformed_source_text_is_refused(case: str) -> None:
    data, line, message = BAD_FILES[case]
    with pytest.raises(BundleError) as caught:
        parse_source_text(data, name="dir/pp.md")
    text = str(caught.value)
    assert text.startswith(f"dir/pp.md:{line}: "), text
    assert message in text, text


def test_too_large_file_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ideology_app.source_bundle.MAX_SOURCE_TEXT_BYTES", len(GOOD) - 1)
    with pytest.raises(BundleError, match=r"^pp.md:1: file is larger than"):
        parse_source_text(GOOD, name="pp.md")


def test_body_helper_keeps_a_good_file_good() -> None:
    data = _with_body(GOOD, b"<!-- page 1 -->\nuno\n<!-- page 2 -->\n\n<!-- page 3 -->\ntres\n\n")
    assert data == GOOD
    assert parse_source_text(data, name="pp.md").pages == ("uno", "", "tres\n")


# --- Slugs and paths ----------------------------------------------------------


def _election() -> Election:
    return Election(
        country="ES", type=ElectionType.GENERAL, date=dt.date(2023, 7, 23), name="G"
    )


def test_election_slug() -> None:
    assert election_slug("ES", "general", dt.date(2023, 7, 23)) == SLUG
    assert election_slug("ES", ElectionType.GENERAL, dt.date(2023, 7, 23)) == SLUG
    assert election_slug_for(_election()) == SLUG


def test_bundle_dir_and_slug(tmp_path: Path) -> None:
    election = _election()
    assert bundle_dir_for(tmp_path, election) == tmp_path / SLUG
    assert bundle_slug(election, tmp_path) is None
    (tmp_path / SLUG).mkdir()
    assert bundle_slug(election, tmp_path) is None
    (tmp_path / SLUG / MANIFEST_NAME).write_text("format = 1\n")
    assert bundle_slug(election, tmp_path) == SLUG


def test_bundle_slug_defaults_to_the_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELECTIONS_DATA_DIR", raising=False)
    assert config.elections_data_dir() == Path("data/elections")
    write_bundle(tmp_path / "data" / "elections")  # tests run in tmp_path
    assert bundle_slug(_election()) == SLUG
    monkeypatch.setenv("ELECTIONS_DATA_DIR", str(tmp_path / "elsewhere"))
    assert config.elections_data_dir() == tmp_path / "elsewhere"
    assert bundle_slug(_election()) is None


# --- read_bundle ----------------------------------------------------------------


def test_read_bundle(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / ".DS_Store").write_bytes(b"\x00")
    (directory / ".notes.md").write_text("ignored")
    (directory / "README.txt").write_text("ignored")
    (directory / "sub").mkdir()
    (directory / "sub" / "x.md").write_text("ignored")

    bundle = read_bundle(directory)

    assert (bundle.slug, bundle.country, bundle.type, bundle.date, bundle.name) == (
        SLUG, "ES", ElectionType.GENERAL, dt.date(2023, 7, 23), "Elecciones generales 2023"
    )
    assert [(p.short_name, p.name, p.file) for p in bundle.parties] == [
        ("PP", "Partido Popular", "pp.md"),
        ("PSOE", "Partido Socialista Obrero Español", "psoe.md"),
    ]
    assert list(bundle.parties[0].text.pages) == list(PP.pages)
    assert bundle.parties[0].text.source_url == "https://example.org/pp.pdf"
    assert bundle.parties[1].text.source_url is None


def test_read_bundle_through_a_relative_dot_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = write_bundle(tmp_path)
    monkeypatch.chdir(directory)
    assert read_bundle(Path(".")).slug == SLUG


MANIFEST_ERRORS: dict[str, tuple[str, int, str]] = {
    "invalid TOML": (manifest_text([PP, PSOE]).replace("format = 1", "format = "), 1,
                     "invalid TOML"),
    "missing top key": (manifest_text([PP, PSOE]).replace("format = 1\n", ""), 1,
                        "missing key 'format'"),
    "unknown top key": ("extra = 1\n" + manifest_text([PP, PSOE]), 1, "unknown key 'extra'"),
    "bad format": (manifest_text([PP, PSOE]).replace("format = 1", "format = 2"), 1,
                   "format must be 1"),
    "unknown election key": (
        manifest_text([PP, PSOE]).replace('name = "Elecciones', 'seats = 350\nname = "Elecciones'),
        3, "unknown key 'seats' in [election]",
    ),
    "missing election key": (
        manifest_text([PP, PSOE]).replace('type = "general"\n', ""), 3,
        "missing key 'type' in [election]",
    ),
    "bad country": (manifest_text([PP, PSOE], country="es"), 4, "country 'es' is invalid"),
    "bad type": (manifest_text([PP, PSOE], type="local"), 5, "type 'local' is invalid"),
    "bad date": (
        manifest_text([PP, PSOE]).replace("date = 2023-07-23", 'date = "2023-07-23"'), 6,
        "date '2023-07-23' is invalid",
    ),
    "datetime is not a date": (
        manifest_text([PP, PSOE]).replace("date = 2023-07-23", "date = 2023-07-23T10:00:00"), 6,
        "is invalid: expected a TOML date",
    ),
    "empty name": (manifest_text([PP, PSOE], name=" "), 7, "election name must not be empty"),
    "padded name": (manifest_text([PP, PSOE], name=" G "), 7, "leading or trailing whitespace"),
    "no parties": ("parties = []\n" + manifest_text([]), 1, "at least one party"),
    "unknown party key": (
        manifest_text([PP, PSOE]).replace('file = "psoe.md"', 'file = "psoe.md"\nseats = 1'),
        14, "unknown key 'seats' in [[parties]] #2",
    ),
    "missing party key": (
        manifest_text([PP, PSOE]).replace('file = "psoe.md"\n', ""), 14,
        "missing key 'file' in [[parties]] #2",
    ),
    "duplicate short names": (
        manifest_text([PP, dataclasses.replace(PSOE, short_name="PP")]), 15,
        "duplicate short_name 'PP'",
    ),
    "duplicate names": (
        manifest_text([PP, dataclasses.replace(PSOE, name="Partido Popular")]), 16,
        "duplicate name 'Partido Popular'",
    ),
    "bad file name": (
        manifest_text([PP, dataclasses.replace(PSOE, file="../psoe.md")]), 17,
        "file '../psoe.md' is invalid",
    ),
}


@pytest.mark.parametrize("case", sorted(MANIFEST_ERRORS))
def test_malformed_manifest_is_refused(tmp_path: Path, case: str) -> None:
    manifest, line, message = MANIFEST_ERRORS[case]
    directory = write_bundle(tmp_path, manifest=manifest)
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    text = str(caught.value)
    assert text.startswith(f"{directory / MANIFEST_NAME}:{line}: "), text
    assert message in text, text


def test_missing_manifest(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / MANIFEST_NAME).unlink()
    with pytest.raises(BundleError, match="manifest not found"):
        read_bundle(directory)


def test_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="bundle directory not found"):
        read_bundle(tmp_path / SLUG)


def test_directory_name_must_be_the_slug(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path, slug="es-general-2023")
    with pytest.raises(BundleError, match="named 'es-general-2023'; expected 'es-general-2023-07-23'"):
        read_bundle(directory)


@pytest.mark.parametrize("where", ["manifesto.pdf", "sub/OLD.PDF"])
def test_a_pdf_anywhere_is_refused(tmp_path: Path, where: str) -> None:
    directory = write_bundle(tmp_path)
    (directory / where).parent.mkdir(exist_ok=True)
    (directory / where).write_bytes(b"%PDF-1.4")
    with pytest.raises(BundleError, match="PDF files must not be in a bundle"):
        read_bundle(directory)


def test_listed_file_missing(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / "psoe.md").unlink()
    with pytest.raises(BundleError, match=r"psoe.md:1: file listed in election.toml not found"):
        read_bundle(directory)


def test_unlisted_md_file(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / "upn.md").write_bytes(PP.content())
    with pytest.raises(BundleError, match=r"upn.md:1: file is not listed in election.toml"):
        read_bundle(directory)


def test_party_must_match_the_manifest(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / "psoe.md").write_bytes(dataclasses.replace(PSOE, short_name="PSC").content())
    with pytest.raises(BundleError, match=r"psoe.md:3: party 'PSC' does not match"):
        read_bundle(directory)


def test_a_bad_file_names_its_path(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / "psoe.md").write_bytes(PSOE.content()[:-1])
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    assert str(caught.value).startswith(f"{directory / 'psoe.md'}:")


# --- The committed bundles ---------------------------------------------------------


def _committed_bundles() -> list[Path]:
    return sorted(p for p in COMMITTED_ROOT.iterdir() if p.is_dir())


def test_every_committed_bundle_parses_and_is_canonical() -> None:
    bundles = _committed_bundles()
    assert bundles, "no committed bundle under data/elections/"
    for directory in bundles:
        bundle = read_bundle(directory)  # parses every file and checks the canonical form
        for party in bundle.parties:
            data = (directory / party.file).read_bytes()
            assert party.text.content_hash == hashlib.sha256(data).hexdigest()


def test_the_2023_bundle() -> None:
    bundle = read_bundle(COMMITTED_ROOT / SLUG)
    assert [p.short_name for p in bundle.parties] == [
        "PP", "PSOE", "VOX", "SUMAR", "ERC", "JUNTS", "EH Bildu", "EAJ-PNV", "BNG"
    ]
    assert [p.file for p in bundle.parties] == [
        "pp.md", "psoe.md", "vox.md", "sumar.md", "erc.md", "junts.md", "eh-bildu.md",
        "eaj-pnv.md", "bng.md",
    ]
    without_url = [p.short_name for p in bundle.parties if p.text.source_url is None]
    assert without_url == ["PSOE", "VOX"]
    assert {p.text.extractor for p in bundle.parties} == {"pypdf 6.21.1"}
    assert [p.text.page_count for p in bundle.parties] == [112, 272, 178, 182, 132, 151, 16, 52, 68]
    assert not list(COMMITTED_ROOT.parent.rglob("*.pdf"))
    assert not list(COMMITTED_ROOT.parent.rglob("*.PDF"))

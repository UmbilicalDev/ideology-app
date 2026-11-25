"""Source Text format and bundle reader (source-text-bundle Scenarios 3 and 8, slugs).

Also the read-only check of every committed bundle under ``data/elections/``.
"""

import dataclasses
import datetime as dt
import hashlib
import re
from pathlib import Path

import pytest
from bundle_factory import (
    BOE_SOURCE,
    BOE_URL,
    DOC_PSC,
    DOC_UPN,
    PP,
    PSOE,
    SLUG,
    V2_DOCUMENTS,
    V2_PARTIES,
    manifest_text,
    manifest_v2_text,
    write_bundle,
    write_bundle_v2,
)

from ideology_app import config
from ideology_app.models import Election, ElectionType
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.source_bundle import (
    MANIFEST_NAME,
    NOT_CANONICAL,
    BundleDocument,
    BundleError,
    CandidatureSource,
    document_scope,
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
    "bad format": (manifest_text([PP, PSOE]).replace("format = 1", "format = 3"), 1,
                   "format must be 1 or 2"),
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


# --- Manifest format 2 (constituencies-and-candidatures) ---------------------------

ALL_CODES = tuple(code for code, _ in CONSTITUENCIES)
CATALONIA = ("08", "17", "25", "43")


def test_format_1_derives_one_document_per_party(tmp_path: Path) -> None:
    bundle = read_bundle(write_bundle(tmp_path))
    assert bundle.format == 1 and bundle.candidatures is None
    assert bundle.documents == tuple(
        BundleDocument(p.file, p.text, (p.short_name,)) for p in bundle.parties
    )
    assert all(p.constituencies is None for p in bundle.parties)
    assert document_scope(bundle, bundle.documents[0], "PP") == ()


def test_read_format_2_bundle(tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)

    bundle = read_bundle(directory)

    assert bundle.format == 2
    assert bundle.candidatures == CandidatureSource(BOE_SOURCE, BOE_URL)
    assert [(p.short_name, p.file, p.text) for p in bundle.parties] == [
        (p.short_name, None, None) for p in V2_PARTIES
    ]
    pp, psoe, psc, upn, pacma = bundle.parties
    assert pp.constituencies == ALL_CODES
    assert psc.constituencies == CATALONIA  # sorted
    assert psoe.constituencies == tuple(c for c in ALL_CODES if c not in CATALONIA)
    assert (upn.constituencies, pacma.constituencies) == (("31",), ("28",))
    assert [(d.file, d.parties, d.constituencies) for d in bundle.documents] == [
        ("pp.md", ("PP", "UPN-PP"), None),
        ("upn.md", ("UPN-PP",), None),
        ("psoe.md", ("PSOE", "PSC"), None),
        ("psc.md", ("PSC",), ("08",)),
    ]
    doc_pp, doc_upn, doc_psoe, doc_psc = bundle.documents
    assert doc_pp.text.party == "PP" and list(doc_pp.text.pages) == list(PP.pages)
    # D1: declared scope (or the Party's Constituencies) intersected with the Party's.
    assert document_scope(bundle, doc_pp, "PP") == ALL_CODES
    assert document_scope(bundle, doc_pp, "UPN-PP") == ("31",)
    assert document_scope(bundle, doc_upn, "UPN-PP") == ("31",)
    assert document_scope(bundle, doc_psoe, "PSC") == CATALONIA
    assert document_scope(bundle, doc_psc, "PSC") == ("08",)


def test_format_2_without_documents_and_url(tmp_path: Path) -> None:
    manifest = manifest_v2_text(documents=[], url=None)
    bundle = read_bundle(write_bundle_v2(tmp_path, documents=[], manifest=manifest))
    assert bundle.documents == ()
    assert bundle.candidatures == CandidatureSource(BOE_SOURCE, None)


def test_document_scope_intersects_with_each_party(tmp_path: Path) -> None:
    doc = dataclasses.replace(DOC_PSC, parties=["PSC", "PSOE"], constituencies=["08", "28"])
    documents = [d for d in V2_DOCUMENTS if d.file != "psc.md"] + [doc]
    bundle = read_bundle(write_bundle_v2(tmp_path, documents=documents))
    shared = bundle.documents[-1]
    assert document_scope(bundle, shared, "PSC") == ("08",)
    assert document_scope(bundle, shared, "PSOE") == ("28",)


def _line_of(text: str, needle: str, occurrence: int = 1) -> int:
    lines = text.split("\n")
    found = [i + 1 for i, line in enumerate(lines) if needle in line]
    return found[occurrence - 1]


def _v2(replace: str = "", by: str = "", count: int = 1) -> str:
    text = manifest_v2_text()
    if replace:
        assert replace in text, replace
        text = text.replace(replace, by, count)
    return text


PACMA_CODES = 'constituencies = ["28"]'
PSC_SCOPE = 'constituencies = ["08"]'

V2_MANIFEST_ERRORS: dict[str, tuple[str, str | int, str]] = {
    # case: (manifest, needle for the expected line (or a line number), message)
    "unknown top key": ("extra = 1\n" + _v2(), 1, "unknown key 'extra' in the manifest"),
    "bad format with format-2 keys": (_v2("format = 2", "format = 3"), 1, "format must be 1 or 2"),
    "boolean format with format-2 keys": (_v2("format = 2", "format = true"), 1,
                                          "format must be 1 or 2"),
    "missing candidatures": (
        _v2(f'[candidatures]\nsource = "{BOE_SOURCE}"\nurl = "{BOE_URL}"\n'), 1,
        "missing key 'candidatures' in the manifest",
    ),
    "format-1 key in format 2": (
        _v2('short_name = "PACMA"', 'file = "pacma.md"\nshort_name = "PACMA"'),
        ("[[parties]]", 5), "unknown key 'file' in [[parties]] #5",
    ),
    "missing constituencies": (
        _v2(PACMA_CODES + "\n"), ("[[parties]]", 5), "missing key 'constituencies'",
    ),
    "integer code": (
        _v2(PACMA_CODES, "constituencies = [28]"), "constituencies = [28]",
        "Constituency 28 must be a string such as \"28\"",
    ),
    "unknown code": (
        _v2(PACMA_CODES, 'constituencies = ["53"]'), 'constituencies = ["53"]',
        "unknown Constituency '53' (expected an INE code 01..52; "
        'see "ideology constituency list")',
    ),
    "empty list": (
        _v2(PACMA_CODES, "constituencies = []"), "constituencies = []",
        "party PACMA has no Constituencies",
    ),
    "duplicate code": (
        _v2(PACMA_CODES, 'constituencies = ["28", "28"]'), 'constituencies = ["28", "28"]',
        "duplicate Constituency '28'",
    ),
    "not all": (
        _v2(PACMA_CODES, 'constituencies = "todas"'), 'constituencies = "todas"',
        'constituencies must be "all" or a list of INE codes',
    ),
    "empty source": (
        _v2(f'source = "{BOE_SOURCE}"', 'source = " "'), 'source = " "',
        "candidatures source must not be empty",
    ),
    "long source": (
        _v2(f'source = "{BOE_SOURCE}"', f'source = "{"x" * 501}"'), "x" * 501,
        "candidatures source must be at most 500 characters",
    ),
    "padded source": (
        _v2(f'source = "{BOE_SOURCE}"', 'source = " BOE"'), 'source = " BOE"',
        "leading or trailing whitespace",
    ),
    "missing source": (
        _v2(f'source = "{BOE_SOURCE}"\n'), "[candidatures]", "missing key 'source' in [candidatures]",
    ),
    "unknown candidatures key": (
        _v2(f'url = "{BOE_URL}"', f'url = "{BOE_URL}"\ndate = 2023-06-24'), "[candidatures]",
        "unknown key 'date' in [candidatures]",
    ),
    "url not a string": (
        _v2(f'url = "{BOE_URL}"', "url = 1"), "url = 1", "candidatures url must be a string",
    ),
    "candidatures not a table": (
        'candidatures = "BOE"\n'
        + _v2(f'[candidatures]\nsource = "{BOE_SOURCE}"\nurl = "{BOE_URL}"\n'), 1,
        "[candidatures] must be a table",
    ),
    "unknown document key": (
        _v2('file = "upn.md"', 'file = "upn.md"\nrole = "main"'), ('[[documents]]', 2),
        "unknown key 'role' in [[documents]] #2",
    ),
    "missing document parties": (
        _v2('parties = ["UPN-PP"]\n'), ('[[documents]]', 2),
        "missing key 'parties' in [[documents]] #2",
    ),
    "bad document file": (
        _v2('file = "upn.md"', 'file = "../upn.md"'), 'file = "../upn.md"',
        "file '../upn.md' is invalid",
    ),
    "duplicate document file": (
        _v2('file = "upn.md"', 'file = "pp.md"'), ('file = "pp.md"', 2),
        "duplicate file 'pp.md'",
    ),
    "empty document parties": (
        _v2('parties = ["UPN-PP"]', "parties = []"), "parties = []",
        "document upn.md: parties must be a non-empty list of short names",
    ),
    "undeclared document party": (
        _v2('parties = ["PSOE", "PSC"]', 'parties = ["PSOE", "VOX"]'), 'parties = ["PSOE", "VOX"]',
        "document psoe.md: party 'VOX' is not declared in [[parties]]",
    ),
    "duplicate document party": (
        _v2('parties = ["PSOE", "PSC"]', 'parties = ["PSOE", "PSOE"]'),
        'parties = ["PSOE", "PSOE"]', "document psoe.md: duplicate party 'PSOE'",
    ),
    "document party not a string": (
        _v2('parties = ["UPN-PP"]', "parties = [1]"), "parties = [1]",
        "document upn.md: party 1 must be a string",
    ),
    "document code outside its parties": (
        _v2(PSC_SCOPE, 'constituencies = ["28"]'), ('constituencies = ["28"]', 2),
        "document psc.md: Constituency 28 (Madrid) is not run by any of its parties",
    ),
    "document party with no code left": (
        _v2('parties = ["PSOE", "PSC"]', 'parties = ["PSOE", "PSC"]\nconstituencies = ["28"]'),
        ('constituencies = ["28"]', 2), "document psoe.md: party PSC runs in none of its",
    ),
    "document empty constituencies": (
        _v2(PSC_SCOPE, "constituencies = []"), "constituencies = []",
        "document psc.md has no Constituencies",
    ),
    "document unknown code": (
        _v2(PSC_SCOPE, 'constituencies = ["00"]'), 'constituencies = ["00"]',
        "unknown Constituency '00'",
    ),
}


@pytest.mark.parametrize("case", sorted(V2_MANIFEST_ERRORS))
def test_malformed_format_2_manifest_is_refused(tmp_path: Path, case: str) -> None:
    manifest, where, message = V2_MANIFEST_ERRORS[case]
    if isinstance(where, int):
        line = where
    elif isinstance(where, tuple):
        line = _line_of(manifest, *where)
    else:
        line = _line_of(manifest, where)
    directory = write_bundle_v2(tmp_path, manifest=manifest)
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    text = str(caught.value)
    assert text.startswith(f"{directory / MANIFEST_NAME}:{line}: "), text
    assert message in text, text


def test_format_2_key_in_format_1_is_unknown(tmp_path: Path) -> None:
    manifest = manifest_text([PP, PSOE]).replace(
        'file = "pp.md"', 'file = "pp.md"\nconstituencies = "all"'
    )
    directory = write_bundle(tmp_path, manifest=manifest)
    with pytest.raises(BundleError, match=r"election.toml:9: unknown key 'constituencies' in "
                                          r"\[\[parties\]\] #1"):
        read_bundle(directory)


def test_documents_table_is_not_a_list(tmp_path: Path) -> None:
    manifest = _v2().split("\n[[documents]]")[0].replace(
        "format = 2\n", 'format = 2\ndocuments = "pp.md"\n'
    )
    directory = write_bundle_v2(tmp_path, documents=[], manifest=manifest)
    with pytest.raises(BundleError, match=r"election.toml:2: \[\[documents\]\] must be a list"):
        read_bundle(directory)


def test_front_matter_party_must_be_a_document_party(tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    (directory / "psc.md").write_bytes(dataclasses.replace(DOC_PSC, party="PSOE").content())
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    assert str(caught.value) == (
        f"{directory / 'psc.md'}:3: party 'PSOE' is not one of the document's parties in "
        "election.toml (PSC)"
    )


def test_two_documents_of_a_party_must_differ(tmp_path: Path) -> None:
    copy = dataclasses.replace(DOC_UPN, file="upn2.md")
    documents = [*V2_DOCUMENTS, copy]
    directory = write_bundle_v2(tmp_path, documents=documents)
    (directory / "upn2.md").write_bytes((directory / "upn.md").read_bytes())
    manifest = (directory / MANIFEST_NAME).read_text(encoding="utf-8")
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    line = _line_of(manifest, "[[documents]]", 5)
    assert str(caught.value) == (
        f"{directory / MANIFEST_NAME}:{line}: documents upn.md and upn2.md both list party "
        "UPN-PP and have the same content"
    )


def test_format_2_unlisted_and_missing_files(tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    (directory / "pacma.md").write_bytes(DOC_UPN.content())
    with pytest.raises(BundleError, match=r"pacma.md:1: file is not listed in election.toml"):
        read_bundle(directory)
    (directory / "pacma.md").unlink()
    (directory / "upn.md").unlink()
    with pytest.raises(BundleError, match=r"upn.md:1: file listed in election.toml not found"):
        read_bundle(directory)

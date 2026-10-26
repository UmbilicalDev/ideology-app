"""party-logos-data: logo checks, bundle logos, import/check and ``party logo`` (Scenarios 2-6).

Every logo is generated in code (``tests/logo_factory.py``) and every bundle is
built in ``tmp_path``; nothing reads the committed logos or writes
``data/ideology.db``. The API side (Scenarios 7-9) is in ``test_public_api.py``.
"""

import dataclasses
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import PP, PSOE, SLUG, PartySpec, manifest_text, write_bundle
from click.testing import CliRunner, Result
from logo_factory import png, png_of_size, svg, webp
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app import elections
from ideology_app.bundle_import import check_against_bundle, import_bundle
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.db import make_engine, session_scope
from ideology_app.models import Party
from ideology_app.party_logos import (
    MAX_LOGO_BYTES,
    NOT_AN_IMAGE,
    PNG,
    SVG,
    WEBP,
    InvalidLogoError,
    LogoChange,
    check_logo,
    logo_url,
    logo_version,
    read_logo_file,
)
from ideology_app.source_bundle import MANIFEST_NAME, BundleError, read_bundle

SUMAR = PartySpec("SUMAR", "Sumar", "sumar.md", ["Propuestas sobre empleo y vivienda."])
PP_SVG = svg()
PSOE_PNG = png(2, 2)
PP_LOGO = dataclasses.replace(PP, logo=("logos/pp.svg", PP_SVG))
PSOE_LOGO = dataclasses.replace(PSOE, logo=("logos/psoe.png", PSOE_PNG))
PARTIES = (PP_LOGO, PSOE_LOGO, SUMAR)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    offline_guard(monkeypatch)
    monkeypatch.setenv("SOURCE_FILES_DIR", str(tmp_path / "stored"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- check_logo: accepted ---------------------------------------------------------


def test_png_webp_and_svg_are_recognised_by_content() -> None:
    for data, media_type in ((png(), PNG), (png(3, 5), PNG), (PP_SVG, SVG)):
        logo = check_logo(data)
        assert (logo.data, logo.media_type, logo.sha256) == (data, media_type, sha(data))
    for chunk in (b"VP8 ", b"VP8L", b"VP8X"):
        assert check_logo(webp(chunk)).media_type == WEBP


@pytest.mark.parametrize(
    "data",
    [
        b'<?xml version="1.0" encoding="UTF-8"?>\n' + svg(),
        b"\xef\xbb\xbf" + svg(),
        b"  \n" + svg(),
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n' + svg(),
        b"<!-- Generator: Adobe Illustrator -->\n" + svg(),
        svg('<defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="1" height="1"/>'),
        svg('<use href="#g"/><use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#g"/>'),
        svg('<image href="data:image/png;base64,iVBORw0KGgo="/>'),
        svg("<style>.a{fill:url(#g)} .b{fill:#fff}</style>"),
        svg('<rect style="fill: url( \'#g\' )" width="1" height="1"/>'),
    ],
    ids=[
        "xml-declaration", "bom", "leading-space", "external-doctype", "comment",
        "url-fragment", "href-fragments", "data-png-image", "style-element", "style-attribute",
    ],
)
def test_passive_svgs_are_accepted(data: bytes) -> None:
    assert check_logo(data).media_type == SVG


def test_exactly_the_maximum_size_is_accepted() -> None:
    data = png_of_size(MAX_LOGO_BYTES)
    assert len(data) == MAX_LOGO_BYTES
    assert check_logo(data).media_type == PNG


# --- check_logo: refused ----------------------------------------------------------

_BAD_IHDR = bytearray(png())
_BAD_IHDR[16:20] = b"\x00\x00\x00\x00"  # width 0
_BAD_WEBP_SIZE = bytearray(webp())
_BAD_WEBP_SIZE[4] ^= 1

REFUSED: dict[str, tuple[bytes, str]] = {
    "empty": (b"", "logo is empty"),
    "too large": (png_of_size(MAX_LOGO_BYTES + 1), f"logo is larger than {MAX_LOGO_BYTES} bytes"),
    "jpeg": (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64, NOT_AN_IMAGE),
    "gif": (b"GIF89a\x01\x00\x01\x00" + b"\x00" * 40, NOT_AN_IMAGE),
    "text": (b"hello", NOT_AN_IMAGE),
    "not utf-8": (b"<svg \xff>", NOT_AN_IMAGE),
    "malformed xml": (b'<svg xmlns="http://www.w3.org/2000/svg"><g></svg>', NOT_AN_IMAGE),
    "html root": (b"<html><body>x</body></html>", NOT_AN_IMAGE),
    "svg without namespace": (b'<svg viewBox="0 0 1 1"></svg>', NOT_AN_IMAGE),
    "png width 0": (bytes(_BAD_IHDR), NOT_AN_IMAGE),
    "png without IEND": (png()[:-12], NOT_AN_IMAGE),
    "webp wrong size": (bytes(_BAD_WEBP_SIZE), NOT_AN_IMAGE),
    "webp unknown chunk": (webp(b"ABCD"), NOT_AN_IMAGE),
    "script": (svg("<script>alert(1)</script>"), "must not contain <script>"),
    "namespaced script": (
        svg('<x:script xmlns:x="http://www.w3.org/2000/svg">1</x:script>'),
        "must not contain <script>",
    ),
    "foreignObject": (svg("<foreignObject><p>x</p></foreignObject>"), "<foreignObject>"),
    "onload": (svg(attrs='onload="alert(1)"'), "event handler attributes ('onload')"),
    "ONCLICK": (svg('<rect ONCLICK="x"/>'), "event handler attributes ('ONCLICK')"),
    "entity": (
        b'<!DOCTYPE svg [<!ENTITY a "aaaa">]>\n' + svg("<text>&a;</text>"),
        "must not declare entities",
    ),
    "internal subset": (
        b'<!DOCTYPE svg [<!ATTLIST svg x CDATA "1">]>\n' + svg(),
        "DOCTYPE internal subset",
    ),
    "xml-stylesheet": (
        b'<?xml-stylesheet href="https://evil.example/a.css"?>\n' + svg(),
        "<?xml-stylesheet",
    ),
    "external href": (svg('<image href="https://evil.example/a.png"/>'), "external reference"),
    "external xlink:href": (
        svg('<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="other.svg#a"/>'),
        "external reference 'other.svg#a'",
    ),
    "svg data uri": (svg('<image href="data:image/svg+xml;base64,PHN2Zz4="/>'), "external"),
    "css url": (svg("<style>.a{fill:url(https://evil.example/x)}</style>"), "external reference"),
    "css import": (svg("<style>@import 'https://evil.example/a.css';</style>"), "@import"),
    "attribute url": (svg('<rect fill="url(http://evil.example/#g)"/>'), "external reference"),
    "javascript url": (
        svg('<a href="#x"><set attributeName="href" to="java script:alert(1)"/></a>'),
        "javascript: URLs",
    ),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_logos(case: str) -> None:
    data, message = REFUSED[case]
    with pytest.raises(InvalidLogoError) as caught:
        check_logo(data)
    assert message in str(caught.value)


def test_logo_url_and_version() -> None:
    digest = sha(b"x")
    assert logo_version(digest) == digest[:16]
    assert logo_url(7, digest) == f"/api/v1/parties/7/logo?v={digest[:16]}"
    assert logo_url(7, None) is None


# --- read_logo_file -----------------------------------------------------------------


def test_read_logo_file(tmp_path: Path) -> None:
    good = tmp_path / "logo.bin"  # any extension: the content decides
    good.write_bytes(PSOE_PNG)
    assert read_logo_file(good).media_type == PNG

    link = tmp_path / "link.png"
    link.symlink_to(good)
    big = tmp_path / "big.png"
    big.write_bytes(png_of_size(MAX_LOGO_BYTES + 1))
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    for path, message in (
        (link, "must not be a symbolic link"),
        (tmp_path / "missing.png", "logo file not found"),
        (tmp_path, "not a regular file"),
        (big, "larger than"),
        (empty, "logo is empty"),
    ):
        with pytest.raises(InvalidLogoError, match=message):
            read_logo_file(path)


def test_size_is_checked_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(png_of_size(MAX_LOGO_BYTES + 1))
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("read before stat"))
    with pytest.raises(InvalidLogoError, match="larger than"):
        read_logo_file(big)


# --- set_party_logo / get_party_by_short_name ---------------------------------------


def test_set_party_logo_transitions(session: Session) -> None:
    election = elections.create_election(
        session, country="ES", type="general", date=dt.date(2023, 7, 23),
        name="G",
    )
    party = elections.add_party(session, election_id=election.id, name="Alfa", short_name="A")
    first, second = check_logo(PP_SVG), check_logo(PSOE_PNG)

    assert elections.set_party_logo(party, None) is LogoChange.NONE
    assert elections.set_party_logo(party, first) is LogoChange.SET
    assert (party.logo, party.logo_media_type, party.logo_sha256) == (PP_SVG, SVG, first.sha256)
    assert elections.set_party_logo(party, first) is LogoChange.UNCHANGED
    assert elections.set_party_logo(party, second) is LogoChange.REPLACED
    assert (party.logo, party.logo_media_type) == (PSOE_PNG, PNG)
    assert elections.set_party_logo(party, None) is LogoChange.REMOVED
    assert (party.logo, party.logo_media_type, party.logo_sha256) == (None, None, None)
    session.commit()

    assert elections.get_party_by_short_name(session, election.id, "A").id == party.id
    with pytest.raises(elections.NotFoundError, match="party 'B' not found in election 1"):
        elections.get_party_by_short_name(session, election.id, "B")
    with pytest.raises(elections.NotFoundError, match="election 9 not found"):
        elections.get_party_by_short_name(session, 9, "A")


def test_party_queries_do_not_load_the_logo_bytes(session: Session) -> None:
    election = elections.create_election(
        session, country="ES", type="general", date=dt.date(2023, 7, 23),
        name="G",
    )
    party = elections.add_party(session, election_id=election.id, name="Alfa", short_name="A")
    elections.set_party_logo(party, check_logo(PP_SVG))
    session.commit()
    session.expunge_all()

    loaded = session.scalars(sa.select(Party)).one()
    assert "logo" not in loaded.__dict__ and loaded.logo_sha256 == sha(PP_SVG)


# --- Bundle reader (Scenario 4) -----------------------------------------------------


def test_read_bundle_with_logos(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path, PARTIES)
    (directory / "logos" / ".DS_Store").write_bytes(b"junk")

    bundle = read_bundle(directory)

    pp, psoe, sumar = bundle.parties
    assert pp.logo is not None and psoe.logo is not None and sumar.logo is None
    assert (pp.logo.file, pp.logo.logo.media_type, pp.logo.logo.data) == (
        "logos/pp.svg", SVG, PP_SVG
    )
    assert (psoe.logo.file, psoe.logo.logo.media_type) == ("logos/psoe.png", PNG)


def _manifest_line(text: str, needle: str) -> int:
    return next(n for n, line in enumerate(text.split("\n"), start=1) if needle in line)


def _bundle_with(tmp_path: Path, pp_logo: tuple[str, bytes]) -> Path:
    return write_bundle(tmp_path, [dataclasses.replace(PP, logo=pp_logo), PSOE])


@pytest.mark.parametrize(
    ("pp_logo", "where", "message"),
    [
        (("logos/pp.png", b"\xff\xd8\xff\xe0" + b"\x00" * 60), "logos/pp.png", NOT_AN_IMAGE),
        (("logos/pp.png", png_of_size(MAX_LOGO_BYTES + 1)), "logos/pp.png", "larger than"),
        (("logos/pp.svg", svg("<script>1</script>")), "logos/pp.svg", "<script>"),
        (("logos/pp.svg", svg(attrs='onload="x"')), "logos/pp.svg", "event handler"),
        (
            ("logos/pp.svg", b'<!DOCTYPE svg [<!ENTITY a "b">]>' + svg()),
            "logos/pp.svg", "entities",
        ),
        (("logos/pp.png", PP_SVG), "logos/pp.png", "extension .png does not match its content"),
        (("logos/pp.webp", PSOE_PNG), "logos/pp.webp", "does not match its content (image/png)"),
    ],
    ids=["jpeg", "too-large", "script", "onload", "entity", "svg-as-png", "png-as-webp"],
)
def test_bad_logo_file_is_refused(
    tmp_path: Path, pp_logo: tuple[str, bytes], where: str, message: str
) -> None:
    directory = _bundle_with(tmp_path, pp_logo)
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    text = str(caught.value)
    assert text.startswith(f"{directory / where}:1: "), text
    assert message in text, text


@pytest.mark.parametrize(
    "path",
    ["pp.svg", "logos/../pp.svg", "logos/sub/pp.svg", "logos/PP.svg", "logos/pp.jpg",
     "logos/.pp.svg", "/logos/pp.svg"],
)
def test_bad_logo_path_is_refused(tmp_path: Path, path: str) -> None:
    manifest = manifest_text([PP, PSOE]).replace(
        'file = "pp.md"', f'file = "pp.md"\nlogo = "{path}"'
    )
    directory = write_bundle(tmp_path, manifest=manifest)
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    line = _manifest_line(manifest, "logo =")
    assert str(caught.value).startswith(f"{directory / MANIFEST_NAME}:{line}: ")
    assert f"logo {path!r} is invalid" in str(caught.value)


def test_logo_must_be_a_string(tmp_path: Path) -> None:
    manifest = manifest_text([PP, PSOE]).replace('file = "pp.md"', 'file = "pp.md"\nlogo = 1')
    directory = write_bundle(tmp_path, manifest=manifest)
    with pytest.raises(BundleError, match="logo 1 is invalid"):
        read_bundle(directory)


def test_duplicate_logo_path_is_refused(tmp_path: Path) -> None:
    parties = [PP_LOGO, dataclasses.replace(PSOE, logo=("logos/pp.svg", PP_SVG))]
    directory = write_bundle(tmp_path, parties)
    manifest = (directory / MANIFEST_NAME).read_text()
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    line = [n for n, text in enumerate(manifest.split("\n"), 1) if text.startswith("logo =")][1]
    assert str(caught.value) == (
        f"{directory / MANIFEST_NAME}:{line}: duplicate logo 'logos/pp.svg'"
    )


def test_missing_and_symlinked_logo_files(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path, [PP_LOGO, PSOE])
    (directory / "logos" / "pp.svg").unlink()
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    line = _manifest_line((directory / MANIFEST_NAME).read_text(), "logo =")
    assert str(caught.value) == (
        f"{directory / MANIFEST_NAME}:{line}: logo file 'logos/pp.svg' not found"
    )

    outside = tmp_path / "outside.svg"
    outside.write_bytes(PP_SVG)
    (directory / "logos" / "pp.svg").symlink_to(outside)
    with pytest.raises(BundleError, match="must not be a symbolic link"):
        read_bundle(directory)


@pytest.mark.parametrize("kind", ["unreferenced-file", "subdirectory", "logos-is-a-file"])
def test_logos_directory_holds_only_declared_files(tmp_path: Path, kind: str) -> None:
    directory = write_bundle(tmp_path, [PP_LOGO, PSOE])
    if kind == "unreferenced-file":
        (directory / "logos" / "vox.svg").write_bytes(PP_SVG)
        where, message = directory / "logos" / "vox.svg", "is not declared as a logo"
    elif kind == "subdirectory":
        (directory / "logos" / "old").mkdir()
        where, message = directory / "logos" / "old", "subdirectories are not allowed"
    else:
        directory = write_bundle(tmp_path / "b", [PP, PSOE])
        (directory / "logos").write_bytes(b"x")
        where, message = directory / "logos", "logos must be a directory"
    with pytest.raises(BundleError) as caught:
        read_bundle(directory)
    assert str(caught.value).startswith(f"{where}:1: ")
    assert message in str(caught.value)


def test_logos_directory_symlink_is_refused(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path / "b", [PP, PSOE])
    real = tmp_path / "real-logos"
    real.mkdir()
    (directory / "logos").symlink_to(real)
    with pytest.raises(BundleError, match="logos must be a directory, not a link"):
        read_bundle(directory)


def test_bundle_without_logos_directory_still_reads(tmp_path: Path) -> None:
    bundle = read_bundle(write_bundle(tmp_path))
    assert [p.logo for p in bundle.parties] == [None, None]


# --- CLI: import, check and party logo (Scenarios 2, 3, 4, 5, 6) --------------------


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def migrated(run) -> None:
    result = run("db", "upgrade")
    assert result.exit_code == 0, result.output


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return write_bundle(tmp_path / "data" / "elections", PARTIES)


TABLES = ("elections", "parties", "source_documents", "source_document_pages", "pipeline_runs")


def _snapshot(db_url: str) -> dict[str, list[tuple[Any, ...]]]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return {
                t: [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {t} ORDER BY 1"))]
                for t in TABLES
            }
    finally:
        engine.dispose()


def _logos(db_url: str) -> list[tuple[Any, ...]]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return [
                tuple(r)
                for r in conn.execute(
                    sa.text(
                        "SELECT short_name, logo, logo_media_type, logo_sha256 "
                        "FROM parties ORDER BY id"
                    )
                )
            ]
    finally:
        engine.dispose()


def test_import_stores_logos_and_is_idempotent(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Party PP: created (id 1); source document 1: added (3 pages)\n"
        f"Party PP (id 1): logo set (logos/pp.svg, image/svg+xml, {len(PP_SVG)} bytes)\n"
        "Party PSOE: created (id 2); source document 2: added (2 pages)\n"
        f"Party PSOE (id 2): logo set (logos/psoe.png, image/png, {len(PSOE_PNG)} bytes)\n"
        "Party SUMAR: created (id 3); source document 3: added (1 pages)\n"
        f"Imported election {SLUG} (id 1): 3 added, 0 replaced, 0 unchanged\n"
    )
    assert _logos(db_url) == [
        ("PP", PP_SVG, SVG, sha(PP_SVG)),
        ("PSOE", PSOE_PNG, PNG, sha(PSOE_PNG)),
        ("SUMAR", None, None, None),
    ]
    before = _snapshot(db_url)
    # Live mode: an unchanged bundle (logos included) queues nothing.
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    again = run("data", "import", str(bundle))

    assert again.exit_code == 0, again.output
    assert again.output == (
        "Party PP: exists (id 1); source document 1: unchanged\n"
        "Party PSOE: exists (id 2); source document 2: unchanged\n"
        "Party SUMAR: exists (id 3); source document 3: unchanged\n"
        f"Imported election {SLUG} (id 1): 0 added, 0 replaced, 3 unchanged\n"
    )
    assert _snapshot(db_url) == before
    assert run("data", "check", str(bundle)).exit_code == 0


def test_changed_and_removed_logos(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    new_svg = svg('<circle r="4" fill="#654321"/>')
    (bundle / "logos" / "pp.svg").write_bytes(new_svg)

    replaced = run("data", "import", str(bundle))

    assert replaced.exit_code == 0, replaced.output
    assert (
        f"Party PP (id 1): logo replaced (logos/pp.svg, image/svg+xml, {len(new_svg)} bytes)\n"
        in replaced.output
    )
    assert "PSOE (id 2): logo" not in replaced.output
    assert _logos(db_url)[0] == ("PP", new_svg, SVG, sha(new_svg))

    (bundle / "logos" / "pp.svg").unlink()
    (bundle / MANIFEST_NAME).write_text(
        manifest_text([PP, PSOE_LOGO, SUMAR]), encoding="utf-8"
    )
    removed = run("data", "import", str(bundle))

    assert removed.exit_code == 0, removed.output
    assert removed.output == (
        "Party PP: exists (id 1); source document 1: unchanged\n"
        "Party PP (id 1): logo removed\n"
        "Party PSOE: exists (id 2); source document 2: unchanged\n"
        "Party SUMAR: exists (id 3); source document 3: unchanged\n"
        f"Imported election {SLUG} (id 1): 0 added, 0 replaced, 3 unchanged\n"
    )
    assert _logos(db_url)[0] == ("PP", None, None, None)
    # A logo change never queues a run, even in live mode.
    assert _snapshot(db_url)["pipeline_runs"] == []


def test_logo_change_with_a_document_change(run, migrated, bundle: Path, db_url: str) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    psoe_v2 = dataclasses.replace(PSOE_LOGO, pages=["Nuevo."], logo=("logos/psoe.png", png(4, 4)))
    write_bundle(bundle.parent, [PP_LOGO, psoe_v2, SUMAR])

    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert (
        "Party PSOE: exists (id 2); source document 4: replaces source document 2 (1 pages)\n"
        f"Party PSOE (id 2): logo replaced (logos/psoe.png, image/png, {len(png(4, 4))} bytes)\n"
    ) in result.output


def test_parties_not_in_the_bundle_keep_their_logo(
    run, migrated, bundle: Path, db_url: str, tmp_path: Path
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    assert run("party", "add", "--election", "1", "--name", "Vox", "--short-name", "VOX").exit_code == 0
    logo = tmp_path / "vox.png"
    logo.write_bytes(png(1, 1, colour=9))
    assert run("party", "logo", "VOX", "--election", "1", "--file", str(logo)).exit_code == 0

    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert "Party VOX (id 4) is not in the bundle; left unchanged\n" in result.output
    assert _logos(db_url)[3][1] == png(1, 1, colour=9)


@pytest.mark.parametrize("command", ["import", "check"])
@pytest.mark.parametrize(
    "case", ["jpeg", "script", "unreferenced", "subdirectory", "missing", "symlink", "duplicate"]
)
def test_bad_bundle_logo_writes_nothing(
    run, migrated, bundle: Path, db_url: str, tmp_path: Path, command: str, case: str
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    logos = bundle / "logos"
    if case == "jpeg":
        (logos / "pp.svg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 60)
    elif case == "script":
        (logos / "pp.svg").write_bytes(svg("<script>1</script>"))
    elif case == "unreferenced":
        (logos / "vox.svg").write_bytes(PP_SVG)
    elif case == "subdirectory":
        (logos / "old").mkdir()
    elif case == "missing":
        (logos / "pp.svg").unlink()
    elif case == "symlink":
        target = tmp_path / "elsewhere.svg"
        target.write_bytes(svg('<circle r="1"/>'))
        (logos / "pp.svg").unlink()
        (logos / "pp.svg").symlink_to(target)
    else:
        (bundle / MANIFEST_NAME).write_text(
            manifest_text(
                [PP_LOGO, PSOE_LOGO, dataclasses.replace(SUMAR, logo=("logos/pp.svg", PP_SVG))]
            ),
            encoding="utf-8",
        )
    database = Path(db_url.removeprefix("sqlite:///"))
    before = database.read_bytes()

    result = run("data", command, str(bundle))

    assert result.exit_code == 1, result.output
    assert result.output.startswith("Error: "), result.output
    assert database.read_bytes() == before


def test_check_reports_each_logo_divergence(run, migrated, bundle: Path, db_url: str) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            # PP: stored bytes no longer match logo_sha256; PSOE: cleared; SUMAR: an undeclared logo.
            conn.execute(sa.text("UPDATE parties SET logo = X'00' WHERE short_name = 'PP'"))
            conn.execute(sa.text(
                "UPDATE parties SET logo = NULL, logo_media_type = NULL, logo_sha256 = NULL "
                "WHERE short_name = 'PSOE'"
            ))
            conn.execute(
                sa.text(
                    "UPDATE parties SET logo = :d, logo_media_type = 'image/png', logo_sha256 = :s "
                    "WHERE short_name = 'SUMAR'"
                ),
                {"d": PSOE_PNG, "s": sha(PSOE_PNG)},
            )
    finally:
        engine.dispose()

    result = run("data", "check", str(bundle))

    assert result.exit_code == 1
    assert result.output == (
        "Error: party PP (id 1): logo differs from logos/pp.svg\n"
        "Error: party PSOE (id 2): no logo, election.toml declares logos/psoe.png\n"
        "Error: party SUMAR (id 3): has a logo but election.toml declares none\n"
        f"Error: database does not match bundle {SLUG}: 3 problems\n"
    )


@pytest.mark.parametrize(
    "update",
    [
        "UPDATE parties SET logo_sha256 = :other WHERE short_name = 'PP'",
        "UPDATE parties SET logo_media_type = 'image/png' WHERE short_name = 'PP'",
        "UPDATE parties SET logo = :png, logo_media_type = 'image/png', logo_sha256 = :other "
        "WHERE short_name = 'PP'",
    ],
    ids=["sha256", "media-type", "other-logo"],
)
def test_check_against_bundle_compares_hash_and_media_type(
    migrated_engine: Engine, tmp_path: Path, update: str
) -> None:
    directory = write_bundle(tmp_path, PARTIES)
    bundle = read_bundle(directory)
    with session_scope(migrated_engine) as session:
        import_bundle(session, bundle)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text(update), {"other": sha(PSOE_PNG), "png": PSOE_PNG})
    with Session(migrated_engine) as session:
        assert check_against_bundle(session, bundle) == [
            "party PP (id 1): logo differs from logos/pp.svg"
        ]


def test_db_check_reports_a_logo_divergence(
    run, migrated, bundle: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    monkeypatch.setenv("ELECTIONS_DATA_DIR", str(bundle.parent))
    assert run("db", "check").output.endswith("Safe to commit: yes\n")
    logo = tmp_path / "other.png"
    logo.write_bytes(png(5, 5))
    assert run("party", "logo", "PP", "--election", "1", "--file", str(logo)).exit_code == 0

    result = run("db", "check")

    assert result.exit_code == 1
    assert f"Error: election 1 ({SLUG}): party PP (id 1): logo differs from logos/pp.svg\n" in (
        result.output
    )
    assert result.output.endswith("Safe to commit: no\n")


# --- party logo (Scenario 6) ----------------------------------------------------------


@pytest.fixture
def election(run, migrated) -> None:
    assert run("election", "create", "--country", "ES", "--type", "general",
               "--date", "2023-07-23", "--name", "G").exit_code == 0
    assert run("party", "add", "--election", "1", "--name", "Partido Popular",
               "--short-name", "PP").exit_code == 0


def test_party_logo_set_replace_and_clear(run, election, db_url: str, tmp_path: Path) -> None:
    logo = tmp_path / "logo.dat"  # any extension: the content decides
    logo.write_bytes(PSOE_PNG)

    result = run("party", "logo", "PP", "--election", "1", "--file", str(logo))

    assert result.exit_code == 0, result.output
    assert result.output == (
        f"Set logo of party PP (id 1): image/png, {len(PSOE_PNG)} bytes, "
        f"sha256 {sha(PSOE_PNG)[:12]}\n"
    )
    assert _logos(db_url) == [("PP", PSOE_PNG, PNG, sha(PSOE_PNG))]
    same = run("party", "logo", "PP", "--election", "1", "--file", str(logo))
    assert same.output == "Party PP (id 1) already has this logo; nothing changed\n"
    logo.write_bytes(PP_SVG)
    replaced = run("party", "logo", "PP", "--election", "1", "--file", str(logo))
    assert replaced.output.startswith("Set logo of party PP (id 1): image/svg+xml, ")
    assert _logos(db_url) == [("PP", PP_SVG, SVG, sha(PP_SVG))]

    cleared = run("party", "logo", "PP", "--election", "1", "--clear")
    assert cleared.exit_code == 0 and cleared.output == "Removed logo of party PP (id 1)\n"
    again = run("party", "logo", "PP", "--election", "1", "--clear")
    assert again.exit_code == 0
    assert again.output == "Party PP (id 1) has no logo; nothing changed\n"
    assert _logos(db_url) == [("PP", None, None, None)]


@pytest.mark.parametrize(
    "args", [[], ["--clear", "--file", "x.png"]], ids=["neither", "both"]
)
def test_party_logo_needs_exactly_one_action(run, election, args: list[str]) -> None:
    result = run("party", "logo", "PP", "--election", "1", *args)
    assert result.exit_code == 2
    assert "pass exactly one of --file or --clear" in result.output


def test_party_logo_errors(run, election, db_url: str, tmp_path: Path) -> None:
    good = tmp_path / "good.png"
    good.write_bytes(PSOE_PNG)
    bad = tmp_path / "bad.svg"
    bad.write_bytes(svg("<script>1</script>"))
    before = _logos(db_url)
    for args, message in (
        (["PP", "--election", "9", "--file", str(good)], "Error: election 9 not found\n"),
        (["VOX", "--election", "1", "--file", str(good)],
         "Error: party 'VOX' not found in election 1\n"),
        (["PP", "--election", "1", "--file", str(bad)],
         "Error: SVG logo must not contain <script>\n"),
        (["PP", "--election", "1", "--file", str(tmp_path / "missing.png")],
         "Error: logo file not found\n"),
    ):
        result = run("party", "logo", *args)
        assert result.exit_code == 1, result.output
        assert result.output == message
    assert _logos(db_url) == before


def test_party_logo_needs_a_migrated_database(run, tmp_path: Path) -> None:
    result = run("party", "logo", "PP", "--election", "1", "--clear")
    assert result.exit_code == 1
    assert NOT_INITIALISED in result.output


def test_party_logo_warns_for_a_bundle_election(
    run, migrated, bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    monkeypatch.setenv("ELECTIONS_DATA_DIR", str(bundle.parent))
    logo = tmp_path / "logo.png"
    logo.write_bytes(png(6, 6))

    result = run("party", "logo", "SUMAR", "--election", "1", "--file", str(logo))

    assert result.exit_code == 0, result.output
    assert result.stderr == (
        f'Warning: election 1 has a committed bundle ({SLUG}); "data check" will report '
        "this logo until election.toml declares it\n"
    )
    assert result.stdout.startswith("Set logo of party SUMAR (id 3): image/png, ")
    assert run("data", "check", str(bundle)).exit_code == 1


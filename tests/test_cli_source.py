import hashlib
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from pdf_factory import blank_pdf, make_text_pdf
from pipeline_fixtures import offline_guard

from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.db import run_migrations
from ideology_app.pdf_text import NO_TEXT_LAYER

HEADER = ["id", "origin", "status", "pages", "content_hash", "filename", "url", "failure_reason"]
TEXT_PAGES = ["Programa electoral\nSubir el salario mínimo.", "Página dos: educación."]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset GENERATION_MODE / LLM_* from the shell, so source add stays precomputed."""
    offline_guard(monkeypatch)


@pytest.fixture
def files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "stored"
    monkeypatch.setenv("SOURCE_FILES_DIR", str(path))
    return path


@pytest.fixture
def run(db_url: str, files_dir: Path):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def party(run) -> None:
    for args in (
        ("db", "upgrade"),
        ("election", "create", "--country", "ES", "--type", "general",
         "--date", "2023-07-23", "--name", "Generales 2023"),
        ("party", "add", "--election", "1", "--name", "Sumar", "--short-name", "SUMAR"),
        ("party", "add", "--election", "1", "--name", "Partido Popular", "--short-name", "PP"),
    ):
        result = run(*args)
        assert result.exit_code == 0, result.output


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "manifesto.pdf"
    path.write_bytes(make_text_pdf(TEXT_PAGES))
    return path


@pytest.fixture
def blank(tmp_path: Path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(blank_pdf(2))
    return path


def _list_rows(run, party_id: str = "1") -> list[list[str]]:
    result = run("source", "list", "--party", party_id)
    assert result.exit_code == 0, result.output
    return [line.split("\t") for line in result.output.splitlines()]


def test_add_text_pdf_is_parsed(run, party, text_pdf: Path, files_dir: Path) -> None:
    result = run("source", "add", "--party", "1", "--file", str(text_pdf))

    assert result.exit_code == 0, result.output
    assert result.output == "Created source document 1: parsed (2 pages)\n"
    digest = hashlib.sha256(text_pdf.read_bytes()).hexdigest()
    assert (files_dir / f"{digest}.pdf").read_bytes() == text_pdf.read_bytes()


def test_add_blank_pdf_fails_but_is_committed(run, party, blank: Path, files_dir: Path) -> None:
    result = run("source", "add", "--party", "1", "--file", str(blank))

    assert result.exit_code == 1
    assert result.stderr == f"Error: source document 1 failed: {NO_TEXT_LAYER}\n"
    assert result.stdout == ""
    digest = hashlib.sha256(blank.read_bytes()).hexdigest()
    assert _list_rows(run)[1] == ["1", "upload", "failed", "2", digest, "scan.pdf", "", NO_TEXT_LAYER]
    assert (files_dir / f"{digest}.pdf").exists()


def test_add_corrupt_pdf_fails(run, party, tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(make_text_pdf(TEXT_PAGES)[:400])

    result = run("source", "add", "--party", "1", "--file", str(path))

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: source document 1 failed: could not read PDF:")


@pytest.mark.parametrize(
    "name, data, message",
    [
        ("empty.pdf", b"", "is empty"),
        ("notes.pdf", b"plain text renamed\n", "is not a PDF"),
    ],
)
def test_add_rejects_bad_files(
    run, party, tmp_path: Path, files_dir: Path, name: str, data: bytes, message: str
) -> None:
    path = tmp_path / name
    path.write_bytes(data)

    result = run("source", "add", "--party", "1", "--file", str(path))

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert message in result.stderr and name in result.stderr
    assert _list_rows(run) == [
        HEADER
    ]
    assert not files_dir.exists()


def test_add_rejects_unknown_party(run, party, text_pdf: Path, files_dir: Path) -> None:
    result = run("source", "add", "--party", "999", "--file", str(text_pdf))

    assert result.exit_code == 1
    assert result.stderr == "Error: party 999 not found\n"
    assert not files_dir.exists()


def test_add_rejects_missing_path(run, party, tmp_path: Path, files_dir: Path) -> None:
    result = run("source", "add", "--party", "1", "--file", str(tmp_path / "nope.pdf"))

    assert result.exit_code == 2
    assert "does not exist" in result.stderr
    assert not files_dir.exists()


def test_add_rejects_too_large_file(
    run, party, text_pdf: Path, files_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ideology_app.source_documents.MAX_UPLOAD_BYTES", 10)

    result = run("source", "add", "--party", "1", "--file", str(text_pdf))

    assert result.exit_code == 1
    assert "too large" in result.stderr
    assert not files_dir.exists()


def test_duplicate_upload(run, party, text_pdf: Path, files_dir: Path) -> None:
    assert run("source", "add", "--party", "1", "--file", str(text_pdf)).exit_code == 0
    digest = hashlib.sha256(text_pdf.read_bytes()).hexdigest()

    again = run("source", "add", "--party", "1", "--file", str(text_pdf))
    other_party = run("source", "add", "--party", "2", "--file", str(text_pdf))

    assert again.exit_code == 1
    assert again.stderr == (
        f"Error: party 1 already has a source document with content hash {digest}\n"
    )
    assert len(_list_rows(run, "1")) == 2
    assert other_party.exit_code == 0, other_party.output
    assert other_party.output == "Created source document 2: parsed (2 pages)\n"
    assert [p.name for p in files_dir.iterdir()] == [f"{digest}.pdf"]


def test_list_and_text(run, party, text_pdf: Path, blank: Path) -> None:
    run("source", "add", "--party", "1", "--file", str(text_pdf))
    run("source", "add", "--party", "1", "--file", str(blank))
    text_hash = hashlib.sha256(text_pdf.read_bytes()).hexdigest()
    blank_hash = hashlib.sha256(blank.read_bytes()).hexdigest()

    assert _list_rows(run) == [
        HEADER,
        ["1", "upload", "parsed", "2", text_hash, "manifesto.pdf", "", ""],
        ["2", "upload", "failed", "2", blank_hash, "scan.pdf", "", NO_TEXT_LAYER],
    ]

    full = run("source", "text", "--document", "1")
    assert full.exit_code == 0, full.output
    assert full.output == (
        "--- page 1 ---\n"
        "Programa electoral\nSubir el salario mínimo.\n"
        "--- page 2 ---\n"
        "Página dos: educación.\n"
    )

    page_two = run("source", "text", "--document", "1", "--page", "2")
    assert page_two.exit_code == 0
    assert page_two.output == "--- page 2 ---\nPágina dos: educación.\n"


def test_list_empty_party_prints_header_only(run, party) -> None:
    assert _list_rows(run, "2") == [
        HEADER
    ]


@pytest.mark.parametrize(
    "args, message",
    [
        (("source", "text", "--document", "99"), "Error: source document 99 not found\n"),
        (
            ("source", "text", "--document", "1", "--page", "3"),
            "Error: page 3 of source document 1 not found\n",
        ),
        (("source", "list", "--party", "999"), "Error: party 999 not found\n"),
    ],
    ids=["unknown-document", "unknown-page", "unknown-party"],
)
def test_not_found(run, party, text_pdf: Path, args: tuple[str, ...], message: str) -> None:
    run("source", "add", "--party", "1", "--file", str(text_pdf))

    result = run(*args)

    assert result.exit_code == 1
    assert result.stderr == message


@pytest.mark.parametrize(
    "revision",
    [None, "0001", "0002", "0003", "0004"],
    ids=["not-migrated", "at-0001", "at-0002", "at-0003", "at-0004"],
)
@pytest.mark.parametrize(
    "args",
    [
        ("source", "add", "--party", "1", "--file", "PDF"),
        ("source", "list", "--party", "1"),
        ("source", "text", "--document", "1"),
    ],
    ids=["add", "list", "text"],
)
def test_requires_current_schema(
    db_url: str, files_dir: Path, text_pdf: Path, revision: str | None, args: tuple[str, ...]
) -> None:
    if revision:
        run_migrations(db_url, revision)
    argv = [str(text_pdf) if a == "PDF" else a for a in args]

    result = CliRunner().invoke(main, ["--database-url", db_url, *argv])

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not files_dir.exists()

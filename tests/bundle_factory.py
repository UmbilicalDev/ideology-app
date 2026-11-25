"""Build Source Text Bundles in ``tmp_path`` for tests (never under ``data/``)."""

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ideology_app.source_bundle import serialise_source_text

SLUG = "es-general-2023-07-23"
EXTRACTOR = "pypdf 0.0-test"


@dataclass
class PartySpec:
    short_name: str
    name: str
    file: str
    pages: Sequence[str]
    source_url: str | None = None
    pdf_sha256: str = field(default="")
    # ``(manifest path, bytes)``, e.g. ``("logos/pp.svg", logo_factory.svg())``.
    logo: tuple[str, bytes] | None = None

    def content(self) -> bytes:
        pdf = self.pdf_sha256 or hashlib.sha256(self.file.encode()).hexdigest()
        return serialise_source_text(
            party=self.short_name,
            source_url=self.source_url,
            pdf_sha256=pdf,
            extractor=EXTRACTOR,
            pages=self.pages,
        )


PP = PartySpec(
    "PP",
    "Partido Popular",
    "pp.md",
    ["Propuestas sobre vivienda y alquiler.", "", "Propuestas sobre sanidad pública.\n"],
    source_url="https://example.org/pp.pdf",
)
PSOE = PartySpec(
    "PSOE",
    "Partido Socialista Obrero Español",
    "psoe.md",
    ["Medidas fiscales y de empleo.", "Medidas sobre educación y universidades."],
)


def manifest_text(
    parties: Sequence[PartySpec],
    *,
    country: str = "ES",
    type: str = "general",
    date: dt.date = dt.date(2023, 7, 23),
    name: str = "Elecciones generales 2023",
) -> str:
    lines = [
        "format = 1",
        "",
        "[election]",
        f"country = {json.dumps(country)}",
        f"type = {json.dumps(type)}",
        f"date = {date.isoformat()}",
        f"name = {json.dumps(name, ensure_ascii=False)}",
    ]
    for party in parties:
        lines += [
            "",
            "[[parties]]",
            f"short_name = {json.dumps(party.short_name, ensure_ascii=False)}",
            f"name = {json.dumps(party.name, ensure_ascii=False)}",
            f"file = {json.dumps(party.file)}",
        ]
        if party.logo is not None:
            lines.append(f"logo = {json.dumps(party.logo[0])}")
    return "\n".join(lines) + "\n"


def write_bundle(
    root: Path,
    parties: Sequence[PartySpec] = (PP, PSOE),
    *,
    slug: str = SLUG,
    manifest: str | None = None,
) -> Path:
    """Write ``root/slug/`` with ``election.toml`` and one file per Party; return the dir."""
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "election.toml").write_text(
        manifest if manifest is not None else manifest_text(parties), encoding="utf-8"
    )
    for party in parties:
        (directory / party.file).write_bytes(party.content())
        if party.logo is not None:
            logo_path = directory / party.logo[0]
            logo_path.parent.mkdir(parents=True, exist_ok=True)
            logo_path.write_bytes(party.logo[1])
    return directory


# --- Manifest format 2 (constituencies-and-candidatures) --------------------------

BOE_SOURCE = "BOE núm. 150, de 24 de junio de 2023: candidaturas proclamadas"
BOE_URL = "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2023-0000"


@dataclass
class CandidatureSpec:
    """A format-2 ``[[parties]]`` entry: ``constituencies`` is ``"all"`` or INE codes."""

    short_name: str
    name: str
    constituencies: Sequence[str] | str
    logo: tuple[str, bytes] | None = None


@dataclass
class DocumentSpec:
    """A format-2 ``[[documents]]`` entry and its Source Text (front-matter ``party``)."""

    file: str
    party: str
    pages: Sequence[str]
    parties: Sequence[str]
    constituencies: Sequence[str] | str | None = None
    source_url: str | None = None
    joint_for: Sequence[str] | None = None

    def content(self) -> bytes:
        return serialise_source_text(
            party=self.party,
            source_url=self.source_url,
            pdf_sha256=hashlib.sha256(self.file.encode()).hexdigest(),
            extractor=EXTRACTOR,
            pages=self.pages,
        )


V2_PP = CandidatureSpec("PP", "Partido Popular", "all")
V2_PSC = CandidatureSpec(
    "PSC", "Partit dels Socialistes de Catalunya", ["43", "08", "17", "25"]
)
V2_PSOE = CandidatureSpec(
    "PSOE",
    "Partido Socialista Obrero Español",
    [code for code in (f"{n:02d}" for n in range(1, 53)) if code not in ("08", "17", "25", "43")],
)
V2_UPN = CandidatureSpec("UPN-PP", "Unión del Pueblo Navarro", ["31"])
V2_SMALL = CandidatureSpec("PACMA", "Partido Animalista", ["28"])
DOC_PP = DocumentSpec("pp.md", "PP", PP.pages, ["PP", "UPN-PP"], source_url=PP.source_url)
DOC_UPN = DocumentSpec("upn.md", "UPN-PP", ["Navarra primero."], ["UPN-PP"])
DOC_PSOE = DocumentSpec("psoe.md", "PSOE", PSOE.pages, ["PSOE", "PSC"])
DOC_PSC = DocumentSpec("psc.md", "PSC", ["Programa del PSC."], ["PSC"], ["08"])
V2_PARTIES = (V2_PP, V2_PSOE, V2_PSC, V2_UPN, V2_SMALL)
V2_DOCUMENTS = (DOC_PP, DOC_UPN, DOC_PSOE, DOC_PSC)


def _toml_codes(value: Sequence[str] | str) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    return "[" + ", ".join(json.dumps(code) for code in value) + "]"


def manifest_v2_text(
    parties: Sequence[CandidatureSpec] = V2_PARTIES,
    documents: Sequence[DocumentSpec] = V2_DOCUMENTS,
    *,
    source: str | None = BOE_SOURCE,
    url: str | None = BOE_URL,
    date: dt.date = dt.date(2023, 7, 23),
    name: str = "Elecciones generales 2023",
) -> str:
    lines = [
        "format = 2",
        "",
        "[election]",
        'country = "ES"',
        'type = "general"',
        f"date = {date.isoformat()}",
        f"name = {json.dumps(name, ensure_ascii=False)}",
        "",
        "[candidatures]",
    ]
    if source is not None:
        lines.append(f"source = {json.dumps(source, ensure_ascii=False)}")
    if url is not None:
        lines.append(f"url = {json.dumps(url)}")
    for party in parties:
        lines += [
            "",
            "[[parties]]",
            f"short_name = {json.dumps(party.short_name, ensure_ascii=False)}",
            f"name = {json.dumps(party.name, ensure_ascii=False)}",
            f"constituencies = {_toml_codes(party.constituencies)}",
        ]
        if party.logo is not None:
            lines.append(f"logo = {json.dumps(party.logo[0])}")
    for document in documents:
        lines += [
            "",
            "[[documents]]",
            f"file = {json.dumps(document.file)}",
            "parties = [" + ", ".join(json.dumps(p, ensure_ascii=False) for p in document.parties)
            + "]",
        ]
        if document.constituencies is not None:
            lines.append(f"constituencies = {_toml_codes(document.constituencies)}")
        if document.joint_for is not None:
            lines.append(
                "joint_for = ["
                + ", ".join(json.dumps(p, ensure_ascii=False) for p in document.joint_for)
                + "]"
            )
    return "\n".join(lines) + "\n"


def write_bundle_v2(
    root: Path,
    parties: Sequence[CandidatureSpec] = V2_PARTIES,
    documents: Sequence[DocumentSpec] = V2_DOCUMENTS,
    *,
    slug: str = SLUG,
    manifest: str | None = None,
) -> Path:
    """Write a format-2 bundle ``root/slug/``; return the dir. Existing files are overwritten."""
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "election.toml").write_text(
        manifest if manifest is not None else manifest_v2_text(parties, documents),
        encoding="utf-8",
    )
    for document in documents:
        (directory / document.file).write_bytes(document.content())
    for party in parties:
        if party.logo is not None:
            logo_path = directory / party.logo[0]
            logo_path.parent.mkdir(parents=True, exist_ok=True)
            logo_path.write_bytes(party.logo[1])
    return directory

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

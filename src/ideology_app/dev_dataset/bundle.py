"""Render the dev dataset's format-2 Source Text Bundle into a directory (dev-dataset, D1).

``render(root)`` writes ``root/<slug>/``: ``election.toml``, one canonical
Source Text file per document (``source_bundle.serialise_source_text``),
``logos/*.svg`` and ``statement-rewordings.toml``. The ledger is not written
here: the seed creates it through ``ingestion_ledger``. Every byte depends
only on ``content``.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from ideology_app.dev_dataset import content, logos
from ideology_app.pipeline.v2.rewording import REWORDINGS_NAME
from ideology_app.source_bundle import MANIFEST_NAME, serialise_source_text


def _quoted(values: Sequence[str]) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


def manifest_text() -> str:
    lines = [
        "format = 2",
        "",
        "[election]",
        f"country = {json.dumps(content.COUNTRY)}",
        f"type = {json.dumps(content.ELECTION_TYPE)}",
        f"date = {content.ELECTION_DATE.isoformat()}",
        f"name = {json.dumps(content.ELECTION_NAME, ensure_ascii=False)}",
        "",
        "[candidatures]",
        f"source = {json.dumps(content.CANDIDATURES_SOURCE, ensure_ascii=False)}",
    ]
    for party in content.PARTIES:
        codes = (
            json.dumps(party.constituencies)
            if isinstance(party.constituencies, str)
            else _quoted(party.constituencies)
        )
        lines += [
            "",
            "[[parties]]",
            f"short_name = {json.dumps(party.short_name)}",
            f"name = {json.dumps(party.name, ensure_ascii=False)}",
            f"constituencies = {codes}",
        ]
        if party.logo_file is not None:
            lines.append(f"logo = {json.dumps(party.logo_file)}")
    for document in content.DOCUMENTS:
        lines += [
            "",
            "[[documents]]",
            f"file = {json.dumps(document.file)}",
            f"parties = {_quoted(document.parties)}",
        ]
        if document.joint_for:
            lines.append(f"joint_for = {_quoted(document.joint_for)}")
    return "\n".join(lines) + "\n"


def source_text(document: content.DevDocument) -> bytes:
    return serialise_source_text(
        party=document.party,
        source_url=document.source_url,
        pdf_sha256=hashlib.sha256(f"dev-dataset/{document.file}".encode()).hexdigest(),
        extractor=content.EXTRACTOR,
        pages=document.page_texts(),
    )


def rewordings_text() -> str:
    statement = content.STATEMENTS_BY_KEY[content.REWORDING.statement]
    return (
        "format = 1\n\n[[rewordings]]\n"
        f"ai_text = {json.dumps(statement.text, ensure_ascii=False)}\n"
        f"text = {json.dumps(content.REWORDING.text, ensure_ascii=False)}\n"
        f"reason = {json.dumps(content.REWORDING.reason, ensure_ascii=False)}\n"
    )


def render(root: Path) -> Path:
    """Write the bundle into ``root/<slug>/`` (which must not exist) and return it."""
    directory = Path(root) / content.SLUG
    directory.mkdir(parents=True)
    (directory / MANIFEST_NAME).write_bytes(manifest_text().encode("utf-8"))
    for document in content.DOCUMENTS:
        (directory / document.file).write_bytes(source_text(document))
    (directory / "logos").mkdir()
    for party in content.PARTIES:
        if party.logo_file is not None:
            (directory / party.logo_file).write_bytes(logos.svg(party))
    (directory / REWORDINGS_NAME).write_bytes(rewordings_text().encode("utf-8"))
    return directory


__all__ = ["manifest_text", "render", "rewordings_text", "source_text"]

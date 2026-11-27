"""``ideology ingestion next``: the first pending step of a v2 Election (ingestion-guide).

``derive(directory, url)`` looks at the Source Text Bundle, its Ingestion
Ledger and the database, and returns the first step of ``STEPS`` whose
condition holds (``docs/specs/ingestion-guide.md``, Technical Approach): what
is missing, in which file and format, the command to run next, whether that
command spends LLM calls (and how many) and what it writes.

Strictly read-only:

- the bundle is read with ``source_bundle.read_bundle`` and the raw
  ``election.toml`` bytes; nothing under the directory is written;
- the ledger is read only through ``ingestion_ledger`` (``read_ledger``,
  ``reconcile``, ``render_ledger``, ``party_states``, the derived
  ``Ledger.documents`` / ``conflicts`` and ``phase4_blockers``);
- a SQLite database is opened only with ``shared_db.read_only_url``
  (``mode=ro``) after checking that the file exists, so a missing file is
  never created; any other URL goes through a Session that is rolled back;
- no LLM provider is built: the provider and model come from
  ``config.llm_settings()`` (or the pinned ones of an extraction or run), and
  planned calls are counted with the pure planners (chunks, conflict
  requests, ``plan_calls``).

Bundle and ledger steps (phases 1-2) come before any database step, so
phases 1-2 work without a database (G11). Pure apart from those reads; no
click, no clock.
"""

import os
import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic.migration import MigrationContext
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ideology_app import config
from ideology_app import ingestion_ledger as ledgers
from ideology_app import shared_db
from ideology_app.bundle_import import check_against_bundle, find_election
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.db import head_revision, make_engine
from ideology_app.elections import ElectionsError, list_elections
from ideology_app.models import (
    ModelGeneration,
    PipelineRun,
    PipelineRunStatus,
    ProposalExtractionStatus,
)
from ideology_app.pipeline.runs import find_unfinished_run
from ideology_app.pipeline.v2.gate import Phase4Error, Phase4Input, load_phase4
from ideology_app.pipeline.v2.rewording import (
    REWORDINGS_NAME,
    STATUS_APPLIED,
    STATUS_REJECTED,
    RewordingFile,
    RewordingFileError,
    read_rewordings,
    rewording_summary,
)
from ideology_app.pipeline.v2.run import MAX_V2_CALLS_PER_RUN, plan_calls
from ideology_app.pipeline.v2.stored import constituency_summary
from ideology_app.proposals import store as proposal_store
from ideology_app.proposals.conflict_prompts import ConflictProposal, conflict_requests
from ideology_app.source_bundle import MANIFEST_NAME, Bundle, read_bundle
from ideology_app.validation.evidence_quotes import normalize_for_match

STEPS: tuple[str, ...] = (
    # Phase 1: candidatures per Constituency (bundle only).
    "create-bundle-directory",
    "write-manifest",
    "fill-manifest-placeholders",
    "fix-manifest",
    "convert-to-format-2",
    "declare-candidatures",
    # Phase 2: provide and review manifestos (bundle and ledger only).
    "provide-manifestos",
    "repair-ledger",
    "update-ledger",
    "review-manifestos",
    # Phase 3: database, import, Proposals and conflicts.
    "create-database",
    "upgrade-database",
    "import-bundle",
    "extract-proposals",
    "fix-proposal-counts",
    "check-conflicts",
    "decide-conflicts",
    # Phase 4: Statements (the v2 Pipeline Run), then rewording.
    "phase4-blocked",
    "resume-run",
    "generate-statements",
    "read-failed-run",
    "reword-statements",
    "done",
)

PHASES = {1: "candidatures", 2: "manifestos", 3: "proposals", 4: "statements"}
TEMPLATE = "docs/templates/election-format-2.toml"
GUIDE = "docs/ingestion-guide.md"
COSTS = f"{GUIDE}, section Costes"
PLACEHOLDER = "<<"
MAX_LINES = 20

_SLUG_RE = re.compile(r"^[a-z]{2}-[a-z]+-[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_FILE_SAFE_RE = re.compile(r"[^a-z0-9._-]+")

# What a step's command writes (the "Shared database:" line).
_NOTHING = "nothing"
_FILES = "files"
_LEDGER = "ledger"
_DATABASE = "database"

_FORMAT_PARTIES = (
    '[[parties]]: short_name = "SIGLAS", name = "full ballot name", '
    'constituencies = "all" or a list of INE codes such as ["08", "28"] '
    '(strings; see "ideology constituency list")'
)
_FORMAT_CANDIDATURES = (
    '[candidatures]: source = "the BOE proclamation of candidatures" '
    '(optional url = "https://www.boe.es/...")'
)
_FORMAT_DOCUMENTS = (
    '[[documents]]: file = "siglas.md", parties = ["SIGLAS", ...]; optional '
    'constituencies = ["08"] (the scope) and joint_for = ["SIGLAS"] (a coalition\'s '
    "joint manifesto); added in phase 2, after ideology source extract"
)


class NextError(ElectionsError):
    """``next`` cannot derive a step (an unreadable database); the CLI exits 1."""


@dataclass(frozen=True)
class NextStep:
    """The first pending step. Every field is printed by ``ideology ingestion next``.

    ``missing``: one line per missing item; ``format`` / ``command``: one line
    each; ``llm``: ``no`` or the spend; ``shared``: what the command writes on
    the database in use; ``notes``: warnings (one active run at a time) and,
    for ``done``, the published summary.
    """

    phase: int
    code: str
    missing: tuple[str, ...]
    file: str
    format: tuple[str, ...]
    command: tuple[str, ...]
    llm: str
    shared: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Context:
    directory: Path
    shown: str  # DIR as given, shell-quoted
    raw: str  # DIR as given
    url: str
    shared: bool

    def path(self, name: str) -> str:
        """``DIR/name`` as given, shell-quoted."""
        return shlex.quote(os.path.join(self.raw, name))


def _capped(lines: Iterable[str], limit: int = MAX_LINES) -> tuple[str, ...]:
    items = list(lines)
    if len(items) <= limit:
        return tuple(items)
    return (*items[:limit], f"(+{len(items) - limit} more)")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _constituencies(count: int) -> str:
    return f"{count} Constituency" if count == 1 else f"{count} Constituencies"


def _impact(ctx: _Context, writes: str) -> str:
    """The ``Shared database:`` value: whether the URL is shared and what the command writes."""
    if ctx.shared:
        if writes == _DATABASE:
            return (
                "yes; this command writes data/ideology.db. First confirm: git status --short "
                "is clean and you pulled; nobody else is generating (one active run at a time, "
                "any Election); no ideology process or server has the file open. Then pass "
                "--yes to proposals extract or pipeline run-v2 (data import and db upgrade "
                "take no --yes), and run ideology db check after"
            )
        if writes == _LEDGER:
            return "yes; this command does not write the database (it writes the ledger)"
        return "yes; this command does not write the database"
    if writes == _DATABASE:
        return "no; this command writes the database on the Database: line"
    if writes == _LEDGER:
        return "no; this command writes the ledger, not the database"
    return "no; this command does not write the database"


def _spend(calls: int, *, provider: str | None = None, model: str | None = None,
           pinned: str | None = None, bound: bool = False,
           planned_text: str | None = None) -> str:
    """The ``LLM:`` value of an LLM step. Never builds a provider."""
    planned = planned_text or f"{'at most ' if bound else ''}{calls}"
    if provider is None or model is None:
        try:
            settings = config.llm_settings()
        except config.ConfigError as exc:
            return f"not configured: {exc}; planned calls {planned}; cost: {COSTS}"
        provider, model = settings.provider, settings.model
        who = f"provider {provider}, model {model} (LLM_PROVIDER / LLM_MODEL)"
    else:
        who = f"provider {provider}, model {model}" + (f" ({pinned})" if pinned else "")
    return f"yes; {who}; planned calls {planned}; cost: {COSTS}"


def _step(
    ctx: _Context,
    phase: int,
    code: str,
    *,
    missing: Sequence[str] = (),
    file: str = "-",
    format: Sequence[str] = (),
    command: Sequence[str] = (),
    llm: str = "no",
    writes: str = _NOTHING,
    notes: Sequence[str] = (),
) -> NextStep:
    assert code in STEPS, code
    return NextStep(
        phase, code, tuple(missing), file, tuple(format), tuple(command), llm,
        _impact(ctx, writes), tuple(notes),
    )


# --- Phase 1: the bundle directory and election.toml ------------------------------------


def _slug_note(ctx: _Context) -> list[str]:
    name = ctx.directory.name
    if _SLUG_RE.match(name):
        return []
    return [
        f"the directory name {name!r} is not <country>-<type>-<date> "
        "(e.g. es-general-2030-06-02); read_bundle requires it to equal the [election] values"
    ]


def _phase1(ctx: _Context) -> NextStep | Bundle:
    directory = ctx.directory
    manifest = directory / MANIFEST_NAME
    if not directory.is_dir():
        missing = (
            [f"{ctx.raw} exists but is not a directory"]
            if directory.exists() or directory.is_symlink()
            else [f"bundle directory {ctx.raw}"]
        )
        return _step(
            ctx, 1, "create-bundle-directory",
            missing=missing,
            file=ctx.raw,
            format=(
                "a directory named <country>-<type>-<date>, lower case with an ISO date, "
                "e.g. es-general-2030-06-02, under data/elections/ (shared) or a scratch "
                "directory",
            ),
            command=(f"mkdir -p {ctx.shown} && cp {TEMPLATE} {ctx.path(MANIFEST_NAME)}",),
            writes=_FILES,
            notes=_slug_note(ctx),
        )
    if not manifest.is_file():
        return _step(
            ctx, 1, "write-manifest",
            missing=[f"{ctx.raw}/{MANIFEST_NAME}"],
            file=f"{ctx.raw}/{MANIFEST_NAME}",
            format=(f"manifest format 2: copy the template {TEMPLATE}",),
            command=(f"cp {TEMPLATE} {ctx.path(MANIFEST_NAME)}",),
            writes=_FILES,
            notes=_slug_note(ctx),
        )
    text = manifest.read_bytes().decode("utf-8", errors="replace")
    placeholders = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.split("\n"), start=1)
        if PLACEHOLDER in line
    ]
    if placeholders:
        return _step(
            ctx, 1, "fill-manifest-placeholders",
            missing=placeholders,
            file=f"{ctx.raw}/{MANIFEST_NAME}",
            format=(
                'replace each <<...>> placeholder with a quoted value ("PP"), a TOML date '
                "(2030-06-02, unquoted) or a list of quoted INE codes",
                '[election]: country = "ES", type = "general", date = YYYY-MM-DD, '
                'name = "Elecciones generales YYYY"',
                _FORMAT_CANDIDATURES,
                _FORMAT_PARTIES,
                _FORMAT_DOCUMENTS,
            ),
            command=(
                f"edit {ctx.path(MANIFEST_NAME)} with values from the Operator only",
                "ideology constituency list",
            ),
            writes=_FILES,
        )
    try:
        bundle = read_bundle(directory)
    except ElectionsError as exc:
        return _step(
            ctx, 1, "fix-manifest",
            missing=[str(exc)],
            file=f"{ctx.raw}/{MANIFEST_NAME}",
            format=(
                f"manifest format 2 as in {TEMPLATE}; every top-level .md must be listed in "
                "[[documents]] and every listed file must exist; no PDF in the directory",
                _FORMAT_DOCUMENTS,
                "a .md Source Text file is never edited: rewrite it with "
                "ideology source extract ... --force",
            ),
            command=(
                f"edit {ctx.path(MANIFEST_NAME)} (never a .md: rewrite it with ideology source "
                f"extract ... --force), then ideology ingestion next {ctx.shown}",
            ),
            writes=_FILES,
        )
    if bundle.format != 2:
        return _step(
            ctx, 1, "convert-to-format-2",
            missing=[f"{MANIFEST_NAME} is format 1 (one file per Party, no candidatures)"],
            file=f"{ctx.raw}/{MANIFEST_NAME}",
            format=(
                f"v2 needs manifest format 2 ({TEMPLATE}); see {GUIDE}, phase 1",
                _FORMAT_CANDIDATURES,
                _FORMAT_PARTIES,
                _FORMAT_DOCUMENTS,
            ),
            command=(f"convert {ctx.path(MANIFEST_NAME)} by hand, keeping each .md file's bytes",),
            writes=_FILES,
        )
    covered = {code for party in bundle.parties for code in party.constituencies or ()}
    uncovered = [f"{code} {name}" for code, name in CONSTITUENCIES if code not in covered]
    if uncovered:
        return _step(
            ctx, 1, "declare-candidatures",
            missing=uncovered,
            file=f"{ctx.raw}/{MANIFEST_NAME} ([[parties]] constituencies)",
            format=(
                _FORMAT_PARTIES,
                "source: the BOE proclamation of candidatures ([candidatures] source); every "
                "Constituency needs at least one candidature",
            ),
            command=("ideology constituency list",),
            writes=_FILES,
        )
    return bundle


# --- Phase 2: manifestos, the ledger and the reviews ----------------------------------------


def _file_name(short_name: str) -> str:
    name = _FILE_SAFE_RE.sub("-", short_name.lower()).strip("-._") or "party"
    return f"{name}.md"


def _phase2(ctx: _Context, bundle: Bundle) -> NextStep | ledgers.Ledger:
    try:
        stored = ledgers.read_ledger(bundle.path)
    except ledgers.LedgerError as exc:
        # The ledger is needed to know the no_manifesto decisions, so an invalid
        # file is reported before provide-manifestos.
        return _step(
            ctx, 2, "repair-ledger",
            missing=[str(exc)],
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME}",
            format=(
                "the ledger is written only by ideology ingestion / conflicts / proposals commands; never "
                "edit it by hand",
                "after a git merge conflict: take one side of the file, then rerun the "
                "commands of the other side",
            ),
            command=(
                f"git checkout --ours {ctx.path(ledgers.LEDGER_NAME)} (or --theirs; the "
                "Operator runs git)",
                f"ideology ingestion update {ctx.shown}",
            ),
            writes=_LEDGER,
        )
    derived, lines = ledgers.reconcile(bundle, stored)
    listing = {
        party.short_name: [d.file for d in bundle.documents if party.short_name in d.parties]
        for party in bundle.parties
    }
    states = {party.short_name: party for party in ledgers.party_states(bundle, stored)}
    without = [
        party
        for party in bundle.parties
        if not listing[party.short_name]
        and states[party.short_name].phase is not ledgers.Phase.EXCLUDED
    ]
    if without:
        first = without[0].short_name
        out = ctx.path(_file_name(first))
        return _step(
            ctx, 2, "provide-manifestos",
            missing=[
                f"{party.short_name} ({party.name}): no [[documents]] entry and no "
                f"no-manifesto decision; runs in {_constituencies(len(party.constituencies or ()))}"
                for party in without
            ],
            file=f"{ctx.raw}/<file>.md and {ctx.raw}/{MANIFEST_NAME} ([[documents]])",
            format=(
                "the Party's official manifesto PDF, kept outside data/ (never commit a PDF), "
                "and its public URL (Evidence links to it)",
                _FORMAT_DOCUMENTS,
                "or, when the Party has no manifesto, the Operator's no-manifesto decision "
                "with a one-line note",
            ),
            command=(
                f"ideology source extract PDF --party {first} --out {out} --url URL",
                f"then add a [[documents]] entry for {_file_name(first)} to "
                f"{ctx.path(MANIFEST_NAME)}",
                f"or: ideology ingestion no-manifesto {ctx.shown} {first} --note NOTE",
                "repeat for each Party listed",
            ),
            writes=_FILES,
        )
    if stored is None or ledgers.render_ledger(derived) != ledgers.render_ledger(stored):
        missing = ["no ingestion ledger yet"] if stored is None else ["the ledger is out of date"]
        missing.extend(lines)
        return _step(
            ctx, 2, "update-ledger",
            missing=_capped(missing),
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME}",
            format=(
                "written only by the command; N (--min-proposals, the fewest validated "
                f"Proposals a Party needs) is the Operator's decision, {ledgers.DEFAULT_MIN_PROPOSALS} "
                "when the ledger is created",
            ),
            command=(f"ideology ingestion update {ctx.shown}",),
            writes=_LEDGER,
        )
    unreviewed = [entry for entry in stored.documents if entry.review is None]
    if unreviewed:
        first = unreviewed[0].file
        missing = []
        for entry in unreviewed:
            pages = ledgers.listed_document(bundle, entry.file).text.pages
            empty = sum(1 for page in pages if not page.strip())
            characters = sum(len(page) for page in pages)
            missing.append(
                f"{entry.file} (parties {', '.join(entry.parties)}): {len(pages)} pages, "
                f"{empty} without text, {characters} characters"
            )
        return _step(
            ctx, 2, "review-manifestos",
            missing=missing,
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME} (review of each file)",
            format=(
                "one decision per file, for every Party listing it: --keep, or --discard "
                "no-text-layer | not-a-manifesto | incomplete, with an optional one-line --note; "
                "the Operator decides after reading the file",
            ),
            command=(
                f"ideology ingestion review {ctx.shown} {first}",
                f"ideology ingestion review {ctx.shown} {first} --keep",
                f"ideology ingestion review {ctx.shown} {first} --discard REASON --note NOTE",
            ),
            writes=_LEDGER,
        )
    return stored


# --- Phase 3: the database -------------------------------------------------------------------


def _database_step(ctx: _Context) -> NextStep | Engine:
    """The Engine to read (``mode=ro`` for SQLite), or the create-database step."""
    path = shared_db.sqlite_path(ctx.url)
    if path is None:
        return make_engine(ctx.url)
    if path.is_file():
        return make_engine(shared_db.read_only_url(path))
    if ctx.shared:
        return _step(
            ctx, 3, "create-database",
            missing=[
                f"no database at {config.SHARED_DATABASE_PATH}; the shared file is committed: "
                "restore it from git instead of building it"
            ],
            file=str(config.SHARED_DATABASE_PATH),
            format=("the committed shared database (DATABASE_URL=sqlite:///data/ideology.db)",),
            command=("git pull, or git checkout -- data/ideology.db (the Operator runs git)",),
        )
    return _step(
        ctx, 3, "create-database",
        missing=[f"no database at {path}"],
        file=str(path),
        format=(
            "DATABASE_URL: a scratch SQLite file (sqlite:///<path>) or the shared "
            "sqlite:///data/ideology.db",
        ),
        command=("ideology db upgrade",),
        writes=_DATABASE,
    )


def _revision_step(ctx: _Context, engine: Engine) -> NextStep | None:
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    head = head_revision()
    if current is None:
        return _step(
            ctx, 3, "create-database",
            missing=["the database is not initialised (no migration applied)"],
            file=str(shared_db.sqlite_path(ctx.url) or "-"),
            format=("the schema is created by the migrations",),
            command=("ideology db upgrade",),
            writes=_DATABASE,
        )
    if current != head:
        notes = []
        if ctx.shared:
            notes.append(
                "on the shared database a migration is applied and committed by the PR that "
                "adds it (CONSTRAINTS, Shared Database): pull first"
            )
        return _step(
            ctx, 3, "upgrade-database",
            missing=[f"the schema is at migration {current}, the code's head is {head}"],
            file=str(shared_db.sqlite_path(ctx.url) or "-"),
            format=("the schema is upgraded by the migrations; never downgrade the shared file",),
            command=("ideology db upgrade",),
            writes=_DATABASE,
            notes=notes,
        )
    return None


def _activity_notes(session: Session, election_id: int | None) -> list[str]:
    """One active run at a time: other Elections' unfinished runs and in-progress extractions."""
    notes: list[str] = []
    for election in list_elections(session):
        if election.id == election_id:
            continue
        unfinished = find_unfinished_run(session, election.id)
        if unfinished is not None:
            notes.append(
                f"election {election.id} has an unfinished run {unfinished.run_id} "
                f"({unfinished.status.value}, {unfinished.recorded_calls} recorded calls); "
                "one active run at a time: do not generate while it may be running"
            )
    for extraction in proposal_store.unfinished_extractions(session):
        notes.append(
            f"proposal extraction {extraction.content_hash[:12]}: in_progress, "
            f"{extraction.chunks_done}/{extraction.chunk_count} chunks; one active run at a "
            "time: do not start another while it may be running"
        )
    return notes


def _conflict_calls(
    session: Session, ledger: ledgers.Ledger, entries: Sequence[ledgers.ConflictEntry]
) -> dict[tuple[str, str, str], int | None]:
    """Planned calls per unchecked overlap, as ``conflicts detect`` would make them.

    0 when another overlap with the same content-hash pair is checked (or will
    be checked first in this invocation); ``None`` when a side's Proposals are
    not complete yet.
    """
    checked = {entry.content_hashes for entry in ledger.conflicts if entry.check is not None}
    planned: dict[tuple[str, str, str], int | None] = {}
    for entry in entries:
        if entry.content_hashes in checked:
            planned[entry.key] = 0
            continue
        sides: list[list[ConflictProposal]] = []
        for file, content_hash in zip(entry.files, entry.content_hashes, strict=True):
            count = ledger.document(file).proposals
            proposals = proposal_store.load_proposals(session, content_hash)
            if count is None or len(proposals) != count:
                break
            sides.append(
                [ConflictProposal(p.ordinal, p.text, tuple(p.categories)) for p in proposals]
            )
        if len(sides) != 2:
            planned[entry.key] = None
            continue
        planned[entry.key] = len(conflict_requests(sides[0], sides[1]))
        checked.add(entry.content_hashes)
    return planned


def _phase3(
    ctx: _Context, session: Session, bundle: Bundle, ledger: ledgers.Ledger, notes: list[str]
) -> NextStep | None:
    problems = check_against_bundle(session, bundle)
    if problems:
        return _step(
            ctx, 3, "import-bundle",
            missing=_capped(problems),
            file=f"{ctx.raw} (election.toml and every listed .md)",
            format=("imports the Election, Parties, candidatures and documents; idempotent",),
            command=(f"ideology data import {ctx.shown}", f"ideology data check {ctx.shown}"),
            writes=_DATABASE,
            notes=notes,
        )
    rows = proposal_store.status_rows(session, bundle, ledger)
    pending = [row for row in rows if row.state != ProposalExtractionStatus.COMPLETE.value]
    if pending:
        calls = sum(max(row.chunk_count - row.chunks_done, 0) for row in pending)
        pins = []
        for row in pending:
            extraction = proposal_store.get_extraction(session, row.content_hash)
            if extraction is not None and extraction.status is ProposalExtractionStatus.IN_PROGRESS:
                pins.append((row.file, extraction.llm_provider, extraction.llm_model))
        pinned = {(provider, model) for _, provider, model in pins}
        if len(pinned) == 1:
            provider, model = next(iter(pinned))
            llm = _spend(
                calls, provider=provider, model=model,
                pinned="pinned by the in-progress extraction; set LLM_PROVIDER / LLM_MODEL to match",
            )
        else:
            llm = _spend(calls)
        step_notes = [
            f"{file} is in progress with provider {provider}, model {model}"
            for file, provider, model in pins
        ] if len(pinned) > 1 else []
        return _step(
            ctx, 3, "extract-proposals",
            missing=[
                f"{row.file}: {row.state}, {row.chunks_done}/{row.chunk_count} chunks "
                f"({max(row.chunk_count - row.chunks_done, 0)} calls)"
                for row in pending
            ],
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME} (Proposal counts) and the database",
            format=("no input: the kept documents are read from the bundle",),
            command=(f"ideology proposals extract {ctx.shown} --max-calls {max(calls, 1)}",),
            llm=llm,
            writes=_DATABASE,
            notes=[
                *step_notes,
                "a big extraction takes hours on claude_code: run it in sittings with "
                "--max-calls K; each call is recorded, so the next invocation continues",
                *notes,
            ],
        )
    counts = proposal_store.ledger_count_problems(session, bundle, ledger)
    counts.extend(
        f"document {row.file}: complete extraction, count not yet recorded in the ledger"
        for row in rows
        if row.ledger is None
    )
    if counts:
        return _step(
            ctx, 3, "fix-proposal-counts",
            missing=_capped(counts),
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME} (Proposal counts)",
            format=("written only by the command from the stored complete extractions",),
            command=(f"ideology proposals extract {ctx.shown}",),
            llm="no (0 calls: complete extractions are reused and their counts recorded)",
            writes=_DATABASE,
            notes=notes,
        )
    excluded = {p.short_name for p in ledger.parties if p.phase is ledgers.Phase.EXCLUDED}
    active = [entry for entry in ledger.conflicts if entry.party not in excluded]
    unchecked = [e for e in active if e.status is ledgers.ConflictStatus.UNCHECKED]
    if unchecked:
        planned = _conflict_calls(session, ledger, unchecked)
        calls = sum(value or 0 for value in planned.values())
        missing = []
        for entry in unchecked:
            value = planned[entry.key]
            calls_label = "Proposals not complete" if value is None else f"{value} calls"
            missing.append(
                f"{ledgers.conflict_label(entry)} ({ledgers.codes_label(entry.constituencies)}): "
                f"not checked ({calls_label})"
            )
        return _step(
            ctx, 3, "check-conflicts",
            missing=missing,
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME} (conflicts)",
            format=(f"{len(unchecked)} overlaps; no input: the Proposals are read from the database",),
            command=(f"ideology conflicts detect {ctx.shown} --max-calls {max(calls, 1)}",),
            llm=_spend(calls),
            writes=_LEDGER,
            notes=notes,
        )
    undecided = [e for e in active if e.status is ledgers.ConflictStatus.PENDING]
    if undecided:
        first = undecided[0]
        return _step(
            ctx, 3, "decide-conflicts",
            missing=[
                f"{ledgers.conflict_label(entry)} ({ledgers.codes_label(entry.constituencies)}): "
                f"{len(entry.contradictions)} contradictions"
                for entry in undecided
            ],
            file=f"{ctx.raw}/{ledgers.LEDGER_NAME} (conflict decisions)",
            format=(
                "the Operator chooses which document prevails and writes a one-line reason "
                "after reading conflicts show",
            ),
            command=(
                f"ideology conflicts show {ctx.shown} {first.party} {first.files[0]} "
                f"{first.files[1]}",
                f"ideology conflicts decide {ctx.shown} {first.party} --prevails FILE "
                "--over FILE --reason REASON",
            ),
            writes=_LEDGER,
            notes=notes,
        )
    return None


# --- Phase 4: the v2 run and rewording ------------------------------------------------------


def _fake_note(run: PipelineRun) -> list[str]:
    """The scripted dev-dataset run (``fake``) cannot be resumed or replayed from the CLI."""
    if run.llm_provider != "fake":
        return []
    return [
        f"run {run.id} used provider fake (scripted, e.g. the dev dataset): a replay from the "
        "CLI has no answers for new calls and fails; reseed the dev dataset instead"
    ]


def _rewording_file(ctx: _Context) -> RewordingFile | None | NextStep:
    try:
        return read_rewordings(ctx.directory)
    except RewordingFileError as exc:
        return _step(
            ctx, 4, "reword-statements",
            missing=[str(exc)],
            file=f"{ctx.raw}/{REWORDINGS_NAME}",
            format=_REWORDING_FORMAT,
            command=(f"fix {ctx.path(REWORDINGS_NAME)}, then ideology ingestion next {ctx.shown}",),
            writes=_FILES,
        )


_REWORDING_FORMAT = (
    f"{REWORDINGS_NAME}: format = 1, then one [[rewordings]] per Statement with "
    'ai_text = "the exact AI text, copied from ideology pipeline statements", '
    'text = "the new wording (the Operator\'s)", reason = "why the AI text confuses '
    '(the Operator\'s)"',
    "Context Notes are not rewordable; each entry is checked for equivalence by the LLM in "
    "the next run",
)


def _phase4(
    ctx: _Context, session: Session, bundle: Bundle, ledger: ledgers.Ledger, notes: list[str]
) -> NextStep:
    blockers = ledgers.phase4_blockers(bundle, ledger)
    phase4: Phase4Input | None = None
    if not blockers:
        try:
            phase4 = load_phase4(session, ctx.directory)
        except Phase4Error as exc:
            blockers = list(exc.blockers) or [str(exc)]
    if blockers or phase4 is None:
        return _step(
            ctx, 4, "phase4-blocked",
            missing=_capped(blockers),
            file=ctx.raw,
            format=("each line names the command that unblocks it",),
            command=(f"ideology ingestion gate {ctx.shown}", f"ideology ingestion status {ctx.shown}"),
            notes=notes,
        )
    rewordings = _rewording_file(ctx)
    if isinstance(rewordings, NextStep):
        return rewordings
    entries = 0 if rewordings is None else len(rewordings.entries)
    runs = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.election_id == phase4.election_id,
            PipelineRun.model_generation == ModelGeneration.V2,
        )
        .order_by(PipelineRun.id.desc())
    ).all()
    unfinished = find_unfinished_run(
        session, phase4.election_id, generation=ModelGeneration.V2
    )
    if unfinished is not None:
        run = session.get(PipelineRun, unfinished.run_id)
        assert run is not None
        missing = [
            f"run {run.id}: {run.status.value}, {unfinished.recorded_calls} recorded calls, "
            "no Dataset Version"
        ]
        if run.failure_reason:
            missing.append(f"failure: {_one_line(run.failure_reason)}")
        run_notes = []
        if run.status is PipelineRunStatus.RUNNING:
            run_notes.append(
                f"run {run.id} is running: it may be active on another machine (or was "
                "killed); resume only when no ideology process is running it"
            )
        remaining = max(plan_calls(phase4, entries) - unfinished.recorded_calls, 0)
        return _step(
            ctx, 4, "resume-run",
            missing=missing,
            file="the database (Pipeline Run)",
            format=(f"the resumed run must use run {run.id}'s provider and model",),
            command=(
                f"LLM_PROVIDER={run.llm_provider} LLM_MODEL={shlex.quote(run.llm_model)} "
                f"ideology pipeline run-v2 {ctx.shown} --resume-from {run.id}",
            ),
            llm=_spend(
                remaining, provider=run.llm_provider, model=run.llm_model,
                pinned=f"run {run.id}'s", bound=True,
            ),
            writes=_DATABASE,
            notes=[*run_notes, *_fake_note(run), *notes],
        )
    finished = [run for run in runs if run.dataset_version is not None]
    if not finished:
        planned = plan_calls(phase4, entries)
        proposals = sum(len(party.proposals) for party in phase4.parties)
        run_notes = [
            f"{len(phase4.parties)} Parties with {proposals} counted Proposals, "
            f"{len(phase4.excluded)} Excluded"
        ]
        if planned > MAX_V2_CALLS_PER_RUN:
            run_notes.append(
                f"{planned} planned calls exceed the limit of {MAX_V2_CALLS_PER_RUN}: the run "
                "would fail before any call"
            )
        run_notes.append(
            "a full run takes 3-5 hours on claude_code: the Operator runs it in their own "
            f"terminal, e.g. caffeinate -is ideology pipeline run-v2 {ctx.shown} 2>&1 | tee "
            f"$HOME/ideology-logs/{bundle.slug}-run-v2.log"
        )
        if entries:
            run_notes.append(f"{REWORDINGS_NAME} has {entries} entries; each is checked in the run")
        return _step(
            ctx, 4, "generate-statements",
            missing=[f"no v2 Pipeline Run with a Dataset Version for {bundle.slug}"],
            file="the database (Pipeline Run, Dataset Version)",
            format=("no input: phase 4 reads the counted Proposals; the minimums come from "
                    "VALIDATION_V2_MIN_STATEMENTS / VALIDATION_V2_MIN_PARTY_SIDES",),
            command=(f"ideology pipeline run-v2 {ctx.shown}",),
            llm=_spend(planned, bound=True),
            writes=_DATABASE,
            notes=[*run_notes, *notes],
        )
    latest = finished[0]
    if latest.status is PipelineRunStatus.FAILED:
        return _step(
            ctx, 4, "read-failed-run",
            missing=[
                f"run {latest.id} failed Validation: "
                f"{_one_line(latest.failure_reason or 'no reason recorded')}"
            ],
            file="the database (Pipeline Run report)",
            format=("read the failed checks; then fix the cause and start a new run",),
            command=(
                f"ideology pipeline checks --run {latest.id}",
                f"ideology pipeline report --run {latest.id}",
                f"then: ideology pipeline run-v2 {ctx.shown} --reuse-from {latest.id} "
                "(identical calls reused)",
            ),
            notes=notes,
        )
    selection = latest.statement_selection or {}
    recorded = (selection.get("rewordings") or {}).get("sha256")
    current = None if rewordings is None else rewordings.sha256
    if recorded != current:
        if recorded is None:
            what = f"{REWORDINGS_NAME} was added after run {latest.id}"
        elif current is None:
            what = f"{REWORDINGS_NAME} was removed after run {latest.id}"
        else:
            what = f"{REWORDINGS_NAME} changed after run {latest.id}"
        checked = {
            (normalize_for_match(str(entry.get("ai_text", ""))), entry.get("text"))
            for entry in (selection.get("rewordings") or {}).get("entries", [])
            if entry.get("status") in (STATUS_APPLIED, STATUS_REJECTED)
        }
        new_checks = 0 if rewordings is None else sum(
            1
            for entry in rewordings.entries
            if (normalize_for_match(entry.ai_text), entry.text) not in checked
        )
        return _step(
            ctx, 4, "reword-statements",
            missing=[f"{what} ({entries} entries)"],
            file=f"{ctx.raw}/{REWORDINGS_NAME}",
            format=_REWORDING_FORMAT,
            command=(
                f"LLM_PROVIDER={latest.llm_provider} LLM_MODEL={shlex.quote(latest.llm_model)} "
                f"ideology pipeline run-v2 {ctx.shown} --reuse-from {latest.id}",
            ),
            llm=_spend(
                new_checks, provider=latest.llm_provider, model=latest.llm_model,
                pinned=f"run {latest.id}'s; drafts, positions and the equivalence checks "
                "already recorded for the same wording are reused",
                planned_text=(
                    f"{new_checks} (one per new or changed entry) if nothing in phases 1-3 "
                    f"changed since run {latest.id}; up to {plan_calls(phase4, entries)} "
                    "otherwise"
                ),
            ),
            writes=_DATABASE,
            notes=[
                f"the low figure holds only if nothing in phases 1-3 changed since run "
                f"{latest.id} (not detected, G10); otherwise this replay is a full run",
                *_fake_note(latest),
                *notes,
            ],
        )
    version = latest.dataset_version
    assert version is not None
    summary = constituency_summary(session, version.id)
    done_notes = [
        f"Dataset Version {version.id} ({version.status.value}), run {latest.id}",
        f"Constituencies: {summary or 'not recorded'}",
        f"Rewordings: {rewording_summary(selection) or 'none'}",
    ]
    for entry in (selection.get("rewordings") or {}).get("entries", []):
        if entry.get("status") != "applied":
            done_notes.append(
                f"rewording {entry.get('status')}: {_one_line(str(entry.get('ai_text', '')))}"
            )
    done_notes.append(
        "a change in phases 1-3 after this run is not detected: after one, run "
        f"ideology pipeline run-v2 {ctx.shown} again"
    )
    return _step(
        ctx, 4, "done",
        file=f"{ctx.raw}/{REWORDINGS_NAME} (only to reword a confusing Statement)",
        format=_REWORDING_FORMAT,
        command=(
            f"ideology pipeline report --run {latest.id}",
            f"ideology pipeline statements --run {latest.id}",
            "ideology db check",
        ),
        notes=[*done_notes, *notes],
    )


# --- Entry point --------------------------------------------------------------------------


def derive(directory: Path, url: str, *, shown: str | None = None) -> NextStep:
    """The first pending step of the bundle in ``directory`` against the database ``url``.

    ``shown`` is DIR as the Operator typed it (default ``str(directory)``);
    commands use it shell-quoted. Read-only (module docstring). Raises
    ``NextError`` only when the database cannot be read.
    """
    raw = str(directory) if shown is None else shown
    ctx = _Context(Path(directory), shlex.quote(raw), raw, url, shared_db.is_shared(url))
    bundle = _phase1(ctx)
    if isinstance(bundle, NextStep):
        return bundle
    ledger = _phase2(ctx, bundle)
    if isinstance(ledger, NextStep):
        return ledger
    engine = _database_step(ctx)
    if isinstance(engine, NextStep):
        return engine
    try:
        step = _revision_step(ctx, engine)
        if step is not None:
            return step
        session = Session(engine)
        try:
            election = find_election(session, bundle)
            notes = _activity_notes(session, None if election is None else election.id)
            step = _phase3(ctx, session, bundle, ledger, notes)
            if step is not None:
                return step
            return _phase4(ctx, session, bundle, ledger, notes)
        finally:
            session.rollback()
            session.close()
    except SQLAlchemyError as exc:
        raise NextError(f"cannot read the database: {exc}") from exc
    finally:
        engine.dispose()


__all__ = ["PHASES", "STEPS", "NextError", "NextStep", "derive"]

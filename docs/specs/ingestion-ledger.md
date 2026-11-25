# Feature Implementation Spec: Ingestion Ledger (per-Party ingestion state and phase-2 manifesto review)

## Source Feature

- `id`: ingestion-ledger
- `area`: data
- `depends_on`: constituencies-and-candidatures (accepted)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest for ledger transitions, review discard with reason, the phase-4 gate refusing with a pending Party and passing when every Party is Extracted or Excluded; `CI=true ./init.sh` passes)
- Branch: `feature/ingestion-ledger`, stacked on `feature/constituencies-and-candidatures` (PR #125), which is stacked on `feature/topic-catalog` (PR #124). The PR goes into `v2`, never `main`.
- Owns the Open entry in `docs/risks-and-open-questions.md` "Constituency redesign": partly discarded Parties, and what the Ledger records for a discarded document. Default L4 below, for team review.

## Goal

Each format-2 Election gets a committed Ingestion Ledger file next to its bundle. Per Party it records the phase reached (candidature declared → manifesto reviewed → Proposals extracted) or Excluded with a reason (no manifesto, discarded at review, too few Proposals). It also records the Operator's phase-2 review of each manifesto (kept, or discarded with a reason). `ideology ingestion` commands write it and report what is pending. A gate function refuses phase 4 until every Party is Extracted or Excluded and no Conflict is pending. Phase 3 (`proposal-extraction`, not built yet) records its results through a defined interface, tested here with a stub. No AI, no database, no UI.

## Non-Goals

- Proposal extraction, the Proposal table, or any LLM call (`proposal-extraction`). Only the interface it will call.
- Conflict records and decisions (`proposal-conflicts`). This feature only leaves an empty `conflicts` slot and the gate hook.
- The phase-4 run and wiring the gate into it (`statements-from-proposals`). Copying Excluded Parties into a Dataset Version (`constituency-selection-validation`).
- Any change to `pipeline/`, `validation/`, `api/`, `apps/web/`, `packages/`, the legacy `pipeline run` / `run-queued`, live triggers, migrations or `data/ideology.db`.
- Creating a ledger for the committed bundles. Both are format 1 and get no ledger.
- The guided procedure (`ingestion-guide`).

## Job Story

When I am ingesting an Election over several sessions, possibly on several machines,
I want one committed file that says, per Party, which phase it has reached or why it is Excluded, and which manifestos I kept or discarded,
so I can resume where I left off, and phase 4 cannot start on an incomplete Election.

## Users And Permissions

- Operator: runs `ideology ingestion status|update|review|no-manifesto|gate`. Never edits the ledger file by hand.
- `proposal-extraction` code: calls `record_extraction` only.
- Voter: nothing visible.

## Decisions (L4 is a default for team review; the others are design choices, justified)

**L1. File and format.** `data/elections/<slug>/ingestion-ledger.json`, beside `election.toml`. `read_bundle` ignores it, because it rejects only unlisted top-level `.md` files, PDFs and undeclared `logos/` files. JSON rather than TOML: the standard library can read and write it, while TOML would need a new dependency (`tomli-w`) or a hand-written writer. Nobody edits the file, so TOML's hand-editing comfort does not matter. Output is canonical: `json.dumps(obj, ensure_ascii=False, indent=2) + "\n"`, UTF-8, keys in the order shown below, Parties and documents in manifest order. The reader refuses any file that does not re-serialise to the same bytes (`not in canonical form (written by "ideology ingestion" commands, never edited)`), the same rule as Source Text files. Writes are atomic: a temp file `.ingestion-ledger-*.tmp` in the same directory, then `os.replace`.

**L2. File only, no database.** The ledger depends only on the bundle (Party short names, document files and their `content_hash`), never on database ids. Any checkout derives the same state, and the commands need no database. That avoids the committed-DB rules (one active writer, `db check` before commit) and the copies of `data/ideology.db` held on other machines. A database copy would need a migration, a sync rule and a second source of truth. Proposals themselves will live in the database (`proposal-extraction`). The ledger holds only per-document counts.

**L3. Facts are stored; phases are derived and stored as a checked summary.** Facts are what commands record:
- `min_proposals`;
- per document: the review (with the `content_hash` it applies to) and the validated Proposal count;
- per Party: a `no_manifesto` exclusion.

Every command rebuilds the derived fields from the facts and the bundle: each Party's `phase`, `reason` and `proposals`, and each document's `parties`. While rebuilding it drops stale facts and prints one change line for each fact it drops:
- a review or count whose `content_hash` is not the file's current one;
- entries for Parties or files no longer in the manifest;
- a `no_manifesto` exclusion on a Party that now has documents.

The ledger is **up to date** when its bytes equal what `ingestion update` would write. A missing ledger means no decision has been made yet. A missing ledger is not a check problem, but the gate is blocked because every Party is still pending.

**L4. Partial discard (default for team review).** Review is per document. A Party is Excluded `discarded_at_review` only when it lists at least one document and **every** one of them is discarded. A Party that has at least one kept document goes on to phase 3 with its kept documents only. The N threshold sums only those. For a discarded document, the ledger records the file, its `content_hash`, the Parties it applies to, `decision = discarded`, the reason, and an optional note. It never records a Proposal count for it. Why: Excluding a Party because one of several manifestos is unusable would drop a Party that still has a valid national or regional manifesto. The summed-N rule already covers a Party left with too little content.

**L5. A review belongs to a file and its bytes.** A document shared by several Parties (D1) is reviewed once, and the decision applies to every Party that lists it. A changed file (new `content_hash`) voids its review and its count, so the Party goes back to `candidature_declared`. Proposal counts follow the same rule (a shared document is extracted once per `content_hash`, the earlier handoff).

**L6. No manifesto is an explicit Operator decision.** A Party with no `[[documents]]` is pending, not Excluded, because the manifesto may simply not have been provided yet. `ingestion no-manifesto` records the exclusion. It is refused while the Party lists a document, and it is cleared automatically (with a printed line) once a document is listed. `--undo` removes it.

**L7. N lives in the ledger.** `min_proposals` is a ledger field. It is 30 (`DEFAULT_MIN_PROPOSALS`) when the ledger is created, and only `ingestion update --min-proposals N` (1..1000) changes it. It is not an environment variable: an env value could differ between machines, and then `data check` would derive different exclusions from the same committed file. A Party is `proposals_extracted` when every kept document has a count for its current hash and the sum is ≥ N. It is Excluded `too_few_proposals` when the sum is < N. While any kept document is still uncounted, the Party stays `manifesto_reviewed`.

**L8. Checks.** For a format-2 bundle, `data check` and `db check` report as `Error:` lines (exit 1) an invalid ledger, or one that is not up to date (`ingestion ledger is out of date: <first change line> (+k more); run "ideology ingestion update <dir>"`). Pending Parties are not a problem. Format-1 bundles never have their ledger read. The success lines are unchanged.

**L9. Live mode and the legacy pipeline are not affected.** The ingestion commands never queue or run a Pipeline Run and never touch the database. The legacy `pipeline run`, `run-queued`, live triggers and the format-2 `data import` trigger stay as they are. The handoff to `statements-from-proposals` (gate the v2 run, including runs queued in live mode, and keep the legacy run off Elections with candidatures) is recorded in the risks doc.

## File Shape (ledger format 1)

```json
{
  "format": 1,
  "election": "es-general-2026-11-29",
  "min_proposals": 30,
  "parties": [
    {"short_name": "PP", "phase": "proposals_extracted", "reason": null, "note": null, "proposals": 412},
    {"short_name": "XYZ", "phase": "excluded", "reason": "no_manifesto", "note": "Sin programa publicado a 26/11", "proposals": null}
  ],
  "documents": [
    {"file": "pp.md", "content_hash": "<64 hex>", "parties": ["PP", "UPN-PP"],
     "review": {"decision": "kept", "reason": null, "note": null}, "proposals": 412}
  ],
  "conflicts": []
}
```

Values: `phase` ∈ `candidature_declared`, `manifesto_reviewed`, `proposals_extracted`, `excluded`. `reason` ∈ `no_manifesto`, `discarded_at_review`, `too_few_proposals`, and is non-null exactly when the phase is `excluded`. `note` is used only with `no_manifesto`. A Party's `proposals` is the sum once every kept document is counted, else null. `review` is null (not reviewed) or `{decision: kept|discarded, reason: null | no_text_layer | not_a_manifesto | incomplete (required when discarded), note}`. A document's `proposals` is null unless `review.decision` is `kept`. A note is null or 1..500 characters, trimmed, single line, with no control characters. `conflicts` must be `[]`, because `proposal-conflicts` defines its entries and bumps `format`. Every listed Party has an entry, and so does every `[[documents]]` file. Structural errors raise `LedgerError` with the message `<path>: <json path>: <problem>` (for example `…/ingestion-ledger.json: parties[1].phase: unknown phase 'done'`). The checks cover unknown or missing keys, `bool` passed as `int`, bad enums, duplicate short names or files, a bad hash, `election` ≠ bundle slug, non-empty `conflicts`, a file over 5 MiB, and non-canonical bytes.

## Module `ideology_app.ingestion_ledger`

The module uses no database, clock or LLM. It imports `source_bundle` and `elections` (errors only). Every mutating function first rebuilds from the bundle (L3) and returns `(new Ledger, change lines)`. Pure functions take a `Bundle`; the `*_in_dir` wrappers read the bundle, read the ledger, apply, and write.

- `LEDGER_NAME`, `LEDGER_FORMAT = 1`, `DEFAULT_MIN_PROPOSALS = 30`. StrEnums `Phase`, `ExclusionReason`, `DiscardReason`, `ReviewDecision`. Frozen dataclasses `Review`, `DocumentEntry`, `PartyEntry`, `Ledger`.
- `LedgerError(InvalidInputError)`. `Phase4Blocked(ElectionsError)` with `.blockers: tuple[str, ...]`.
- `read_ledger(bundle_dir) -> Ledger | None`, `render_ledger(ledger) -> bytes`, `write_ledger(bundle_dir, ledger)`.
- `reconcile(bundle, ledger | None, *, min_proposals=None)`. It creates the ledger when it is None, and raises `LedgerError` for a format-1 bundle (`the Ingestion Ledger needs a format-2 election.toml`).
- `review_document(bundle, ledger, file, *, decision, reason=None, note=None)`. It refuses an unlisted file and a discard without a reason. Re-reviewing overwrites the decision and prints `was …`. Discarding clears the document's count.
- `set_no_manifesto(bundle, ledger, short_name, *, note=None, undo=False)`.
- **Phase-3 interface:** `record_extraction(bundle, ledger, file, *, content_hash, validated_proposals)` and `record_extraction_in_dir(bundle_dir, file, *, content_hash, validated_proposals) -> tuple[PartyEntry, ...]` (the affected Parties after the change). `proposal-extraction` calls it once per document `content_hash` when that document's extraction is complete. The threshold and the Party's Extracted or Excluded state follow from L7, so extraction never sets a phase itself. It refuses an unlisted file, a hash that is not the bundle's current one (`stale`), a document not reviewed `kept`, and a count that is not an int ≥ 0 or is a bool. Recording again overwrites the count.
- `party_states(bundle, ledger | None) -> tuple[PartyEntry, ...]` (derived; also the read path for `ingestion-guide` and `constituency-selection-validation`).
- `ledger_problems(bundle) -> list[str]` (L8; empty when there is no file).
- `pending_conflicts(ledger) -> tuple[str, ...]` (always `()` in ledger format 1; `proposal-conflicts` fills it).
- `phase4_blockers(bundle, ledger | None) -> list[str]` covers these cases:
  - an invalid ledger, or one that is not up to date;
  - each Party that is not `proposals_extracted` or `excluded`, as `party S: <phase> (next: <step>)`;
  - each pending conflict.

  `require_phase4_ready(bundle_dir) -> Ledger` raises `Phase4Blocked`.

Next-step texts: `list a manifesto in [[documents]] or record "ingestion no-manifesto"`, `review a.md, b.md`, `extract Proposals from a.md`.

## CLI (`ideology ingestion`, no database needed; `BundleError` / `LedgerError` become `ClickException`)

- `status DIRECTORY`: read-only, exit 0 unless the bundle or ledger is invalid. Prints `Ingestion ledger <slug> (N = 30)`. If there is no file it adds `Warning: no ingestion ledger yet; "ideology ingestion update" creates it`. If the file is out of date it adds `Warning: ledger is out of date; run "ideology ingestion update <dir>"` and shows the derived state. Then one `short_name<TAB>phase<TAB>detail` line per Party. Detail is one of:
  - `next: …`;
  - `412 proposals`;
  - `no_manifesto: <note>`;
  - `discarded_at_review (a.md: no_text_layer)`;
  - `too_few_proposals (12 < 30)`.

  Then `Parties: P; extracted E, excluded X, pending phase 2: A, pending phase 3: B`, `Conflicts pending: 0` and `Phase 4: ready` or `Phase 4: blocked`.
- `update DIRECTORY [--min-proposals N]`: creates or rebuilds the file and prints the change lines, or `Ledger unchanged`. The change lines are `Created ingestion ledger <path> (N = 30)`, `Party S: added`, `Party S: removed (not in election.toml)`, `Document f: review cleared (content changed)`, `Document f: proposals cleared (content changed)`, `Document f: removed (not in election.toml)`, `Party S: no_manifesto cleared (documents listed: f)`, `N: 30 -> 25` and `Party S: <old> -> <new>`. It then prints the status block.
- `review DIRECTORY FILE [--keep | --discard {no-text-layer,not-a-manifesto,incomplete}] [--note TEXT]`: with no decision it is read-only and prints `Document f (parties A, B): P pages, K without text, C characters` and `Review: not reviewed|kept|discarded (<reason>)`. With a decision it writes, then prints the change lines and one phase line per affected Party.
- `no-manifesto DIRECTORY SHORT_NAME [--note TEXT] [--undo]`: writes, then prints the change lines.
- `gate DIRECTORY`: read-only. It prints `Phase 4: ready (E extracted, X excluded)` and exits 0. When blocked it prints one `Error: <blocker>` line per blocker, then `Phase 4: blocked (k blockers)`, and exits 1.
- `data check` and `db check` (format 2 only) add `ledger_problems`. `db check` prefixes them with `election <id> (<slug>): `.

## Acceptance Scenarios

1. **Create.** Given a format-2 bundle with Parties `A` (`a.md`), `B` (shares `a.md`, D1, plus `b.md`), `C` (no document) and no ledger, when `ingestion update` runs, then the file is created with N = 30 and every Party `candidature_declared`. `status` lists the next steps, and `gate` exits 1 naming A, B and C.
2. **Review keep, shared document.** When `a.md` is kept, A becomes `manifesto_reviewed`. B stays `candidature_declared` (next: review b.md) until `b.md` is reviewed.
3. **Discard.** When `b.md` is discarded `incomplete`, B is `manifesto_reviewed` (L4, partial). When `a.md` is then discarded `not-a-manifesto`, A and B are both `excluded`, `discarded_at_review`. `--discard` without a reason and an unlisted file are refused, and the file stays unchanged.
4. **No manifesto.** `no-manifesto … C --note …` makes C `excluded`, `no_manifesto`. The same command for A is refused. Listing `c.md` for C in the manifest and running `update` clears it (printed) and C is pending again. `--undo` also clears it.
5. **Extraction stub.** A stub that does what `proposal-extraction` will do calls `record_extraction_in_dir` once per kept document. A with 20 and B with 20 + 15 summed: A becomes `excluded`, `too_few_proposals` (20 < 30) and B becomes `proposals_extracted` (35). `update --min-proposals 20` makes A `proposals_extracted`. A stale hash, an unreviewed or discarded document, and a negative or bool count are refused.
6. **Changed content.** When `a.md`'s bytes change, `update` prints `review cleared` and `proposals cleared`, and A goes back to `candidature_declared`. Before the update, `data check` reports the ledger as out of date (exit 1) and `gate` is blocked.
7. **Gate.** With every Party `proposals_extracted` or `excluded`, `require_phase4_ready` returns and `gate` exits 0. With one Party pending it raises `Phase4Blocked` naming that Party. A ledger that is missing or out of date blocks. `pending_conflicts` is wired into the blockers (a monkeypatched non-empty result blocks).
8. **Read validation.** A hand-edited file (re-indented, unknown key, bad enum, `excluded` without a reason, wrong `election`, non-empty `conflicts`) gives `LedgerError` with its JSON path in `status`, `gate`, `data check` and `db check`, and the write commands refuse to overwrite it.
9. **Legacy untouched.** The `ingestion` commands refuse a format-1 bundle. `data check` and `db check` output for both committed bundles is unchanged, even with a stray `ingestion-ledger.json` in a copy of a format-1 bundle. Running `review`/`update` with `GENERATION_MODE=live` queues no run, and the database is unchanged (row counts equal).

## Repository Research

### Files Inspected

- `src/ideology_app/source_bundle.py`: `Bundle.format`, `documents`, `BundleDocument`, `SourceText.content_hash`/`pages`, `read_bundle` (other files ignored), `BundleError`.
- `src/ideology_app/bundle_import.py`: `_check_v2`, `candidatures_by_party`, `document_scopes`, module docstring seams.
- `src/ideology_app/cli.py`: `main` (the engine is created lazily, and `constituency list` runs without a DB), `requires_db`, `data import` and `data check`, `db check` → `_bundle_and_run_checks`, `_write_atomically`, `pipeline run` / `run-queued`.
- `src/ideology_app/pipeline/triggers.py` (the live trigger, unchanged), `config.py` (no new setting), `elections.py` (errors).
- `tests/bundle_factory.py` (`manifest_v2_text`, `write_bundle_v2`, `DocumentSpec`), `tests/test_cli_data.py`.
- `CONTEXT.md`, `docs/domain-model.md` (phases, gate), `docs/risks-and-open-questions.md` "Constituency redesign", `docs/specs/constituencies-and-candidatures.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md`, `docs/technical-discovery.md`, `feature_list.json` (this feature and its dependents).

### Existing Patterns To Follow

- A canonical file format that the reader enforces (Source Text `NOT_CANONICAL`), atomic writes in the bundle directory with a dot-prefixed temp file, `<file>: <where>: <problem>` errors, and check functions that return problem strings which the CLI prints as `Error:` lines.
- `data import` and `data check` take the bundle directory as an argument, and `db check` finds bundles with `bundle_slug`.

## Expected File Changes

- `src/ideology_app/ingestion_ledger.py`: create.
- `src/ideology_app/cli.py`: modify (the `ingestion` group, plus ledger problems in `data check` and `_bundle_and_run_checks`).
- `tests/test_ingestion_ledger.py` (pure: transitions, L3–L7, read validation, canonical form, gate, extraction stub): create. `tests/test_cli_ingestion.py` (exact output, exit codes, scenario 9 live/DB unchanged): create. `tests/test_cli_data.py` (data check and db check, format-2 ledger problems, format-1 unchanged): modify. `tests/bundle_factory.py`: helper only if needed.
- Docs as below. No migration, and no change to `data/` or `pipeline/`.

## Visual Design Impact

- UI involved: no. This is a CLI and file feature, so no browser check is needed (AGENTS.md exemption).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add the module, its place (pure, after `source_bundle`), the file location and the `ingestion` CLI group.
- `CONSTRAINTS.md`: update with a new section, "Ingestion Ledger":
  - the file is written only by `ingestion_ledger` functions and `ideology ingestion` commands, never by hand or by AI;
  - phases are derived, never set directly;
  - v2 Parties are Excluded only for the three ledger reasons;
  - later features read it only through `party_states` / `require_phase4_ready`, and Dataset Versions copy the Excluded Parties (they never read the ledger live).

  Also add one sentence to the coverage rule (line 82): it applies to the legacy pipeline, and v2 exclusion happens only in the ledger.
- `docs/technical-discovery.md`: add an "Ingestion Ledger" bullet under Data and Storage (location, JSON shape, the phase-2 runbook `status` → `review` → `update` → `data check` → commit, L1–L8, and a git merge conflict on the file: take one side, then rerun the commands).
- `CONTEXT.md` (Ingestion Ledger, Excluded Party) and `docs/domain-model.md` (Ingestion phases: the values written): replace "values belong to `ingestion-ledger`" with the phase and reason names and the L4 rule.
- `docs/risks-and-open-questions.md`:
  - Move the partial-discard entry to Settled-by-default and add "Open, for team review (`ingestion-ledger` defaults): L4, L6, L7 (N in the ledger)".
  - Drop `ingestion-ledger` from the CONSTRAINTS handoff.
  - Add these handoffs:
    - `proposal-extraction`: extract only `kept` documents read from the ledger; check that the DB row's `content_hash` equals the ledger's; call `record_extraction_in_dir` once per hash.
    - `proposal-conflicts`: the `conflicts` slot, the `pending_conflicts` hook and a ledger format bump.
    - `statements-from-proposals`: call `require_phase4_ready` before queuing or executing a v2 run, live mode included.
    - `constituency-selection-validation`: copy the Excluded Parties and their reasons from `party_states` into the Dataset Version.
    - `ingestion-guide`: `status` is its read path.
- `README.md`: update. Add one Spanish bullet next to the format-2 candidatures bullet (about line 277), covering the `ideology ingestion` commands, the file location and a pointer to `docs/technical-discovery.md`.
- `AGENTS.md`, `DESIGN.md`: not needed (no workflow or UI change).

## Implementation Plan

1. Dataclasses, enums, render and read with full structural validation, plus their tests.
2. `reconcile` (derivation and stale-fact dropping), then `review_document`, `set_no_manifesto`, `record_extraction`, the gate functions and `ledger_problems`, with pure tests for scenarios 1–8.
3. The CLI `ingestion` group, and the additions to `data check` and `db check`. CLI tests, including scenario 9.
4. Docs, `feature_list.json`, `PROGRESS.md`, then `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `ingestion_ledger.py` types, `render_ledger`, `read_ledger` (each refusal in "File Shape" has a test).
- [ ] `reconcile` with the change lines, and idempotence (a second `update` gives `Ledger unchanged` and the same bytes).
- [ ] Review, no-manifesto and extraction transitions, the L4 partial discard, the L5 shared document, the L7 threshold and an N change.
- [ ] `phase4_blockers`, `require_phase4_ready`, the `pending_conflicts` hook, and an extraction-stub test that uses only the public interface.
- [ ] CLI commands with exact-output tests. `data check` / `db check` ledger problems. Format-1 output unchanged.
- [ ] Docs and risks entries. Evidence in `feature_list.json` and `PROGRESS.md`.

## Verification Plan

- `.venv/bin/python -m pytest tests/test_ingestion_ledger.py tests/test_cli_ingestion.py tests/test_cli_data.py tests/test_bundle_import.py tests/test_source_bundle.py tests/test_committed_database.py`
- Format 1 unchanged: `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology data check data/elections/es-general-2023-07-23` (and `…2026-11-29`) still print the same lines. `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` still prints `Safe to commit: yes`. `ideology ingestion status data/elections/es-general-2026-11-29` refuses (format 1).
- Manual run on a scratch format-2 bundle written with `tests/bundle_factory.write_bundle_v2` outside the repo: `update`, `review`, `no-manifesto`, `status`, `gate` (exit 1, then 0 after stub extraction from a Python one-liner), and a hand edit, which is refused.
- `git diff --stat` shows no change under `src/ideology_app/pipeline/`, `validation/`, `api/`, `migrations/`, `apps/`, `packages/` or `data/`.
- `CI=true ./init.sh` passes. No E2E or browser check: no API or UI change.

## Evidence To Capture

- Test counts, the format-1 `data check` / `db check` output, the scratch-bundle command transcript (summarised), the `git diff --stat` scope, and the `CI=true ./init.sh` result. Record them in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist

- [ ] The ledger depends only on the bundle (no DB ids). Its bytes are canonical, and a second `update` is a no-op.
- [ ] L4: a partly discarded Party goes on to phase 3, and only an all-discarded one is Excluded. A discarded document records its file, hash, Parties, reason and note, with no count.
- [ ] A changed file voids its review and count. A shared document is reviewed once for every Party that lists it.
- [ ] The gate blocks on a pending Party, on a missing or out-of-date ledger, and on the conflict hook, and passes when every Party is Extracted or Excluded.
- [ ] The extraction interface is tested through a stub only. No LLM, no database writes, no runs queued (live mode included).
- [ ] Format-1 bundles, the legacy pipeline and the committed DB are untouched. Docs, CONSTRAINTS and the risks entries are updated, and L4/L6/L7 are recorded for team review.

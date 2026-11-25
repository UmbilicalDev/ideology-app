# Feature Implementation Spec: Conflicts between manifestos of one Party

## Source Feature

- `id`: proposal-conflicts
- `area`: pipeline
- `depends_on`: proposal-extraction (PR #127, not merged into `v2` at planning time)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest with the fake provider: joint-manifesto precedence, a flagged conflict blocks phase 4 until decided, the decision and reason are recorded and applied; `CI=true ./init.sh` passes)
- Branch: `feature/proposal-conflicts`, stacked on `feature/proposal-extraction` (#127) → #126 → #125 → #124. The PR goes into `v2`, never `main`.
- Owns these entries in `docs/risks-and-open-questions.md` "Constituency redesign": the `joint manifesto` marker handoff (from `constituencies-and-candidatures`) and the `conflicts` slot / `pending_conflicts` handoff (from `ingestion-ledger`). It changes the `statements-from-proposals` handoff on how Proposals are read.

## Goal

Two kept Source Documents of the same Party whose scopes intersect form an **overlap**. Overlaps are derived deterministically into the Ingestion Ledger. `ideology conflicts detect DIR` asks the configured LLM, one shared category at a time, which Proposals of one document contradict Proposals of the other. It records the result in the ledger. If there are contradictions, the overlap is a **Conflict**. When exactly one of the two documents is marked as the Party's joint manifesto, that document prevails automatically. Otherwise the Operator records which document prevails and why, with `ideology conflicts decide`. Phase 4 then reads each Party's Proposals through one helper, `counted_proposals`. The helper sets aside the losing document's contradicting Proposals in the overlap Constituencies. Proposals are never edited or deleted. The phase-4 gate stays closed while any overlap of a non-Excluded Party is unchecked or undecided.

## Non-Goals

- A real detection run or any real LLM spend (`e2e-2026-constituencies`). Tests use only `FakeProvider`.
- Statement generation, v2 Evidence, the v2 run and calling the gate from it (`statements-from-proposals`). This feature only provides `counted_proposals` and fills `pending_conflicts`.
- Contradictions inside one document, or between different Parties.
- Converting the committed 2026 bundle to format 2 or marking its joint manifestos (`e2e-2026-constituencies`).
- Re-checking a pair after a prompt bump (C7). An undo command for decisions (C11). Any change to `pipeline/`, `validation/`, `api/`, `apps/web/` or `packages/`. No migration and no DB writes. No UI, so no browser check.

## Job Story

When a Party has a national and a regional manifesto that both apply in some Constituencies,
I want the system to tell me only where they really contradict, resolve the coalition's joint manifesto by itself, and record my decision for the rest,
so phase 4 positions the Party from a consistent set of Proposals without anyone editing them.

## Users And Permissions

- Operator: runs `ideology conflicts detect|list|show|decide`. `detect` and `show` read the database but never write it, so the shared-DB confirmation is not needed. `decide` and `list` need no database.
- `statements-from-proposals`: calls `require_phase4_ready`, then `proposals.conflicts.counted_proposals` for each Party.
- `ingestion-guide`: reads `pending_conflicts` and runs the `conflicts` commands.
- Voter: nothing visible.

## Decisions (C1–C11 are defaults for team review; the rest are design choices)

Defaults for team review, in short:
- C1: detect with an LLM per shared category, not by flagging every overlap.
- C2: a decision sets aside only the losing document's contradicting Proposals, per Party and overlap Constituency.
- C3: the marker is `joint_for`. Exactly one joint file in a pair wins automatically; both or neither goes to the Operator.
- C4: joint pairs are checked too.
- C5: a content change clears the check and the decision; a scope change keeps both.
- C6: no migration. Checks are recorded in the ledger, and resume is per overlap.
- C7: a prompt bump does not re-check.
- C8: an identical hash pair is reused across Parties.
- C9: unchecked overlaps block phase 4, except those of Excluded Parties.
- C10: at most 40k characters per request, 40 contradictions per call and 300-character explanations.
- C11: re-deciding overwrites, with no undo command.

**Overlap (deterministic, pure, in `ingestion_ledger`).** For each manifest Party, take its `[[documents]]` whose ledger review is `kept`. Every unordered pair whose `source_bundle.document_scope(bundle, doc, party)` sets intersect is one overlap entry. The entry has the Party, both files sorted by name (stable when `[[documents]]` is reordered), their current `content_hash`es and the sorted intersecting Constituencies. The ledger is DB-free, so it uses the bundle rule `document_scope`. The DB scope rows come from the same D1 rule, and `data check` already enforces that they are equal. The phase-4 helper uses the DB seam `bundle_import.document_scopes`.

**Joint-manifesto marker (C3).** Add an optional `joint_for = ["UPN-PP"]` key on `[[documents]]`. It names the listed Parties for which this file is the coalition's own joint manifesto. Validation in `source_bundle._read_documents`, with manifest line numbers: a non-empty list of strings, each one in that document's `parties`, no duplicates. Add `joint_for` to `_MANIFEST_DOCUMENT_OPTIONAL_KEYS`. Add `BundleDocument.joint_for: tuple[str, ...] = ()`. There is no format bump (an optional key, as the handoff says) and no DB column: only the ledger derivation reads it. In an overlap of Party P, the entry's `joint` is the file when exactly one of the two lists P in `joint_for`. Otherwise `joint` is null: both joint or neither means the Operator decides. A shared national file such as `pp.md`, listed for `PP` and `UPN-PP`, is not joint for either.

**Detection (C1, C4, C10).** An LLM comparison, not "flag every overlap". The user wants the Operator bothered only when needed, and the cost is small (see Cost Estimate). A flag-every-overlap rule also gives no Proposal to set aside, so a decision would have to drop the whole losing document. Joint pairs are checked as well, because the check says which Proposals the joint manifesto overrides. Requests are built per topic-catalog category in catalog order. A Proposal goes in the bucket of each of its categories. A bucket is compared only when both sides are non-empty. If side A plus side B is over `CONFLICT_REQUEST_MAX_CHARS = 40_000` characters of Proposal text, each side is sliced, in ordinal order, into slices of at most 20,000 characters, and every A-slice × B-slice pair becomes one request. A single Proposal over the limit is a slice alone. The outputs are merged in this order: deduplicate by `(ordinal_a, ordinal_b)`, keep the first category and its explanation, and sort by `(a, b)`. If either document has 0 Proposals, the check is recorded with 0 calls and no contradictions.

**Prompt (`proposals/conflict_prompts.py`, task `proposal_conflict_check`, version `v1`).** It is its own frozen prompt and does not touch `proposals/prompts.py` or `pipeline.prompts`. A pinned fingerprint test, `tests/test_conflict_prompts.py`, covers the system text, the template and the schema JSON. Spanish system text: "two lists of Proposals by the same political force on one topic, from documents A and B". It reports only pairs where both cannot be held at once: opposite measures, or incompatible figures or deadlines. It does not report extra detail, a topic only one side covers, complementary measures, or a regional addition. The answer is an empty list when there are none. The prompt shows only the category name and the numbered texts (`A1`..`An`, `B1`..`Bm`), with no Party names, file names or pages. The schema is built by the cached `conflict_list_schema(len_a, len_b)`: `contradictions` has at most 40 items, each with `a` (int, 1..len_a), `b` (int, 1..len_b) and `explanation` (Spanish, 1..300 characters, single line). A validator rejects anything `ingestion_ledger.note_problem` would reject, which raises an output error. `max_tokens = 4096`.

**Ledger entries (ledger format 2).** `LEDGER_FORMAT = 2`. A format-1 file is still read, but only with `conflicts: []`. `reconcile` rewrites it as format 2 with the line `Ledger: format 1 -> 2`, so until `ingestion update` runs the file is "out of date". No ledger file is committed today. `conflicts` holds one object per overlap, ordered by manifest Party and then by sorted file pair, with keys in this order:

```json
{"party": "UPN-PP", "files": ["pp.md", "upn.md"], "content_hashes": ["<64 hex>", "<64 hex>"],
 "constituencies": ["31"], "joint": "upn.md",
 "check": {"provider": "anthropic", "model": "…", "prompt_version": "v1", "calls": 14},
 "contradictions": [{"proposals": [40, 7], "category": "economy", "explanation": "…"}],
 "status": "joint_manifesto", "prevails": "upn.md", "reason": null}
```

`proposals` holds the 1-based Proposal ordinals in `files[0]` and `files[1]`. Ordinals are stable because extraction is per content hash and is never redone (P4). The **facts** are `check` + `contradictions` (written only by `record_conflict_check`) and the Operator decision `prevails` + `reason` (written only by `decide_conflict`). Everything else is **derived**: `status` is `unchecked` (no check), `no_contradiction`, `joint_manifesto` (with `prevails = joint` and `reason` null), `decided` or `pending`. The reader enforces exact keys, files in `documents` and in the Party's list, `party` in `parties`, unique `(party, files)`, categories from `topic_catalog.TOPIC_CATALOG`, ordinals from 1 up to that document's ledger `proposals`, explanations and reasons under the `note_problem` rules (a reason is required for `decided`), status consistency, and canonical bytes as today.

**Staleness (C5).** `reconcile` keeps a check or decision fact only while an overlap with the same Party and files exists and both `content_hashes` are equal. Otherwise it drops the fact and prints a line such as `Conflict UPN-PP pp.md + upn.md: check cleared (content changed)`, `… decision cleared (content changed)` or `… removed (no longer an overlap)`. A change of `constituencies` keeps the facts and prints `… constituencies 31 -> 31, 20`. When `joint` becomes set, a stored decision is dropped with `… decision cleared (joint manifesto upn.md prevails)`. A status change prints `Conflict … : unchecked -> pending`. Discarding a document removes its overlaps.

**Recording without a migration (C6, C8).** Detection writes only the ledger, never the DB. The ledger records the full parsed result of every call, merged, together with the provider, model, prompt version and call count. A check whose content-hash pair (in the same order) is already recorded for another entry is copied with 0 calls. The cost of this choice: an interrupted overlap loses the calls it made, because the ledger is written after each overlap and not after each call. With about 20–30 calls per overlap, that is acceptable and avoids a migration and binary DB merges. The DB-free ledger stays the single place for every conflict fact. Tokens are printed, not stored.

**Gate (C9).** `pending_conflicts(ledger)` returns one line for each entry with status `unchecked` or `pending` whose Party is not `excluded`. For example: `UPN-PP: pp.md + upn.md (31): not checked; run "ideology conflicts detect DIR"` or `PSC: psc.md + psoe.md (08, 17, 25, 43): 3 contradictions; run "ideology conflicts decide DIR PSC --prevails FILE --over FILE --reason TEXT"`. `phase4_blockers` calls it on the derived ledger. `ingestion status` keeps its `Conflicts pending: N` line.

**Applied by phase 4 (`proposals/conflicts.py`).** Two functions:
- `set_aside(ledger, short_name) -> dict[tuple[str, int], frozenset[str]]` (pure). It maps `(content_hash, ordinal)` to the Constituencies where that Proposal is set aside for the Party: the losing file's ordinals of every `joint_manifesto` or `decided` entry, over that entry's `constituencies`.
- `counted_proposals(session, bundle, ledger, short_name) -> list[CountedProposal]`. `CountedProposal(proposal, file, content_hash, source_document_id, constituencies)`. For the Party's kept documents in `[[documents]]` order, it takes `load_proposals(content_hash)` in ordinal order and the current Source Document row `(party_id, content_hash)`. Its `constituencies` are the row's `document_scopes` minus `set_aside`, and items with an empty set are left out. It raises `ConflictError` when the Party has pending conflicts or a ledger count differs from the stored Proposals.

**Granularity (C2).** A decision sets aside only the losing document's *contradicting* Proposals, only for that Party and only in the overlap Constituencies. Every other Proposal of both documents still counts. Re-deciding overwrites the decision (C11).

**Effect on checks.** `data check` / `db check` get nothing new beyond `ledger_problems`. That already reports an invalid or out-of-date ledger, which now includes conflict entries and ordinals over the ledger count. Together with P8 (ledger count = stored rows), every recorded ordinal exists. A format-1 bundle is unchanged: its ledger is never read and `joint_for` does not exist in format 1.

## Cost Estimate (2026, for `e2e-2026-constituencies`)

These are assumptions, because no real extraction has run. National manifestos yield about 100–170k characters of Proposal text and regional ones about 50–100k (40–60 % of the text, see the `proposal-extraction` estimate). Multi-category membership adds about 1.3×. That gives about 200–300k characters per overlap, or 20–30 calls of up to 40k characters, ≈ 90–135k input tokens with the system text. Plan ≈ 200k with the 1.5× measured on `claude_code`. Output is at most about 1k tokens per call, usually far less, so ≈ 5–15k per overlap. 2026 is expected to have **4–8 overlap entries** (for example PSC, UPN-PP and the Sumar regional coalitions), and fewer distinct hash pairs. Total: **≈ 80–240 calls, 0.5–1.6M input tokens and 0.05–0.12M output tokens**. That is roughly **$2–7** on `anthropic` at the Sonnet list price of $3 / $15 per M tokens (check before use), or **1–3 h** of sequential calls on `claude_code`, spread over sittings with `--max-calls` (default 300). This is well under extraction's $8–12. Each overlap with no contradiction saves the Operator a decision.

## Acceptance Scenarios

1. **Overlap derivation.** Party P lists `a.md` (all) and `b.md` (["28"]), both kept. After `ingestion update` there is one `unchecked` entry with constituencies `["28"]`. A pair with disjoint scopes, a discarded document and a single-document Party give no entry.
2. **Gate.** An `unchecked` entry and then a `pending` entry each make `ingestion gate` exit 1 with the conflict line. `require_phase4_ready` raises `Phase4Blocked`. An entry of a Party `excluded (too_few_proposals)` does not block.
3. **Detect, no contradiction.** A fake answering `[]` gives the status `no_contradiction` and records the call count. The gate opens (when everything else is ready).
4. **Detect, flagged.** A fake returns one contradiction in `housing`, in a bucket requested twice (two categories). The ledger holds it once. The prompts contain no Party or file name. The status is `pending`.
5. **Joint precedence.** `b.md` has `joint_for = ["P"]`. Detection flags a contradiction, and the status becomes `joint_manifesto` with `prevails = b.md` and no Operator step. `decide` on it is refused. With both files joint, the status is `pending`.
6. **Decide and apply.** `conflicts decide DIR P --prevails a.md --over b.md --reason "…"` records `decided` and the reason, and the gate opens. `counted_proposals(P)` leaves out b.md's contradicting Proposal in `28` only. All other Proposals of both files are present with their scopes. `load_proposals` output and the Proposal rows are unchanged.
7. **Refusals.** These are refused, with the ledger byte-identical: `decide` on an unchecked or no-contradiction entry, an unknown Party or pair, `--prevails`/`--over` not the entry's two files, a missing or multi-line reason, an out-of-date ledger, a format-1 bundle. `detect` before both extractions are complete reports `Error:` and skips the entry (exit 1).
8. **Staleness.** Changing `b.md`'s bytes, then import and `ingestion update`, clears the check and decision with the stated lines, and the entry is `unchecked` again. Changing only its constituencies keeps both.
9. **Reuse and budget.** A rerun makes 0 calls. The same hash pair for a second Party is copied with 0 calls. With `--max-calls` lower than an entry's requests, detect stops before that entry, prints the stop line and exits 0. A fake raising `LLMError` mid-entry exits 1 and leaves that entry unchecked.
10. **Ledger format.** A format-1 ledger is read, and `ingestion update` rewrites it to format 2. The reader rejects a hand-edited entry: a wrong status, an ordinal above the count, an unknown category, or a non-canonical file.
11. **Manifest.** `joint_for` naming a Party not in the document's `parties`, an empty list, a duplicate or a non-list is refused with a line number. A format-2 bundle without `joint_for` reads as before.
12. **Checks.** `data check` on a format-2 bundle whose ledger is out of date because of a conflict change reports it (exit 1). Format-1 `data check` / `db check` output is unchanged.

## Repository Research

Files inspected: `AGENTS.md`, `CONTEXT.md` (Source Document, Ingestion Ledger, Proposal), `docs/domain-model.md` (Conflict lifecycle, phase-4 gate), `docs/risks-and-open-questions.md` (Constituency redesign), `CONSTRAINTS.md` and `ARCHITECTURE.md` (Ingestion Ledger rules), `feature_list.json`, `docs/specs/proposal-extraction.md`, `src/ideology_app/ingestion_ledger.py` (whole), `source_bundle.py` (`BundleDocument`, `document_scope`, `_read_documents`), `bundle_import.py` (`candidatures_by_party`, `document_scopes`, `find_election`), `proposals/store.py`, `proposals/prompts.py`, `proposals/extraction.py` (ordinals 1..n), `models.py` (Proposal tables), `llm/base.py`, `llm/fake.py`, `pipeline/checkpoint.py` (`request_hash`), `cli.py` (`data check`, `ingestion`, `proposals` groups), `tests/bundle_factory.py` (`DocumentSpec`), `tests/proposal_fixtures.py`, `tests/test_ingestion_ledger.py` (format-1 cases), `tests/test_cli_ingestion.py`, and `data/elections/` (no committed ledger; the 2026 bundle is still format 1).

Patterns to follow: facts versus derived state with `_Facts` / `_derive` / `_reconcile` / `_apply` / `*_in_dir`, change lines, canonical render, cached bounded schemas (`_subclass`), pinned prompt fingerprints, `cli._provider()` as the test seam, `FakeProvider` tasks, and `read_phase3` for an up-to-date ledger.

Gaps: no conflict entries or `joint_for`, `pending_conflicts` always returns `()`, and there is no Party-level Proposal read path.

## Expected File Changes

- `src/ideology_app/source_bundle.py`: `joint_for` key, validation and `BundleDocument.joint_for`.
- `src/ideology_app/ingestion_ledger.py`: `LEDGER_FORMAT = 2` with format-1 read and upgrade; `ConflictEntry`, `ConflictCheck`, `Contradiction` and `ConflictStatus`; parse/render; overlap derivation and staleness in `_reconcile`/`_derive`; `record_conflict_check[_in_dir]`, `decide_conflict[_in_dir]`; a real `pending_conflicts`; `phase4_blockers` on the derived ledger; `__all__`.
- `src/ideology_app/proposals/conflict_prompts.py` (create): the prompt, `conflict_list_schema`, `conflict_requests(...)`.
- `src/ideology_app/proposals/conflicts.py` (create): pure bucketing and slicing, merge, `set_aside`; DB side `detect(...)` (reads only), `counted_proposals`, `CountedProposal`, `ConflictError`, `show_rows`.
- `src/ideology_app/cli.py`: the `conflicts` group (`detect`, `list`, `show`, `decide`).
- Tests: `tests/test_conflict_prompts.py`, `tests/test_conflict_ledger.py`, `tests/test_proposal_conflicts.py` and `tests/test_cli_conflicts.py` (create). Update `test_ingestion_ledger.py` (format 2), `test_source_bundle.py` (`joint_for`), `test_cli_ingestion.py` / `test_cli_data.py` where outputs change, and `tests/bundle_factory.py` (`DocumentSpec.joint_for`).

## Visual Design Impact

UI involved: no. No browser check (CLI and data only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update with the conflict entries in `ingestion_ledger`, the `proposals.conflicts` / `conflict_prompts` modules and their dependency direction (ledger stays DB-free; `conflicts` → `store`, `bundle_import`, `ingestion_ledger`, `llm.base`), and the CLI group.
- `CONSTRAINTS.md`: update.
  - The ledger writers now include `record_conflict_check` / `decide_conflict`. LLM output enters the ledger only as a check recorded by `conflicts detect`.
  - Conflict status is derived, never set.
  - A `proposal_conflict_check` prompt or schema change bumps its version and fingerprint. No Party or file names appear in it.
  - `proposals.conflicts` may read `Ledger.conflicts`/`documents` through `read_phase3`.
  - Phase 4 MUST read a Party's Proposals only through `counted_proposals`.
- `CONTEXT.md` / `docs/domain-model.md`: `joint_for`. The Conflict lifecycle becomes overlap unchecked → no contradiction | flagged → joint_manifesto | decided. Only the contradicting Proposals are set aside, per Party and Constituency.
- `docs/technical-discovery.md`: add a "Proposal conflicts" section with detection, the ledger entry, the cost estimate and C1–C11.
- `docs/risks-and-open-questions.md`:
  - Settle the two `proposal-conflicts` handoffs.
  - Rewrite the `statements-from-proposals` Proposal-read handoff to use `counted_proposals`.
  - Add "Open, for team review (`proposal-conflicts` defaults)" with C1–C11.
  - Add Open (`e2e-2026-constituencies`): mark `joint_for` in the format-2 2026 bundle, and record real calls, cost and the false-positive rate. If the false-positive rate is high, a prompt v2 is a follow-up.
- `AGENTS.md`: not needed.

## Implementation Plan

1. `joint_for` in `source_bundle` and the bundle factory, with tests.
2. The ledger: format 2, entries, derivation, staleness, record/decide, `pending_conflicts`, with pure tests.
3. The prompt module and its fingerprint test.
4. `proposals/conflicts.py`: requests, merge, `detect`, `set_aside`, `counted_proposals`, with FakeProvider tests.
5. The CLI group and output, with CLI tests.
6. Docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks

- [ ] `joint_for` parse and validation, plus `DocumentSpec.joint_for` (scenario 11).
- [ ] Format-1 read and upgrade line; entry dataclasses, reader rules and canonical render (scenario 10).
- [ ] Overlap derivation, `joint`, derived status, and staleness lines (scenarios 1, 5, 8).
- [ ] `record_conflict_check` (validates hashes, ordinals and categories), `decide_conflict` (refusals), `*_in_dir` (scenario 7).
- [ ] `pending_conflicts` and `phase4_blockers` on derived (scenario 2).
- [ ] Prompt, `conflict_list_schema` with the single-line validator, fingerprint, and a no-names test.
- [ ] Buckets, 40k slicing, merge and dedupe; `detect` with reuse, budget, `LLMError` and a ledger write per entry (scenarios 3, 4, 9).
- [ ] `set_aside` and `counted_proposals` (scenario 6).
- [ ] CLI `detect` (lines below), `list` (tab-separated: party, `fileA + fileB`, codes, status, contradictions, prevails, reason; then `Conflicts: N; pending P`), `show` (each contradiction: `#k [category] explanation`, then `A <file> p.<page> #<ordinal>: <text>` and the same for B, then the decision), `decide` (change lines + row).
- [ ] `detect` output lines: `Conflict P a.md + b.md (28): <n> contradictions; pending Operator decision` (or `; joint manifesto b.md prevails`, `no contradiction`, `reused check (Party Q)`, `skipped (Party P excluded)`), `Error: … extract Proposals from b.md first`, `Stopped before …; run again or raise --max-calls`, `Calls: N new; input_tokens …, output_tokens …`, `Conflicts pending: N`.
- [ ] Docs and evidence.

## Verification Plan

- `.venv/bin/python -m pytest tests/test_conflict_prompts.py tests/test_conflict_ledger.py tests/test_proposal_conflicts.py tests/test_cli_conflicts.py tests/test_ingestion_ledger.py tests/test_source_bundle.py tests/test_cli_ingestion.py tests/test_cli_data.py tests/test_cli_proposals.py`: scenarios 1–12, all with `FakeProvider` (the autouse LLM guards stay on).
- Unchanged: `tests/test_pipeline_*.py`, `tests/test_validation_*.py`, the `proposal_extraction` fingerprint, `PROMPT_VERSIONS` and the migration head. `data/ideology.db` is byte-identical (`git diff --stat data/ideology.db` is empty).
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology data check data/elections/es-general-2026-11-29` (and 2023) prints the same lines as before.
- `CI=true ./init.sh` passes. `init.sh` is unchanged.

## Evidence To Capture

In `feature_list.json` and `PROGRESS.md`: the pytest counts, the `init.sh` result, the unchanged DB and migration head, the unchanged format-1 `data check` output, and that no real LLM call was made.

## Validator Checklist

- [ ] Only `FakeProvider` in tests. No real detection ran, and there is no DB change or migration.
- [ ] Scenarios 1–12 pass. Reuse and budget make exactly the stated number of calls.
- [ ] The ledger is written only through `ingestion_ledger` functions. Status is derived, and stale facts are cleared on content change.
- [ ] Joint precedence needs no Operator step. Other contradictions block phase 4 until decided with a reason.
- [ ] `counted_proposals` sets aside only the losing contradicting Proposals, per Party and overlap Constituency. Proposals are untouched.
- [ ] Format-1 bundles and legacy behavior are unchanged. The prompt has no Party or file names.
- [ ] The docs and risk entries listed above are updated, with C1–C11 recorded for team review.

## Implementation Notes (2026-11-25, implementer)

- Scenario 8: a content change of a document also clears its phase-2 review (`ingestion-ledger` L5), so `ingestion update` prints `check cleared (content changed)`, `decision cleared (content changed)` and then `removed (no longer an overlap)`; the entry is `unchecked` again once the new bytes are reviewed `kept` (`Conflict P a.md + b.md (28): added (unchecked)`). Recorded as an accepted Low in `docs/risks-and-open-questions.md`.
- Extra change lines, so every ledger change has one: `Conflict P a.md + b.md (28): added (<status>)`, `… joint manifesto none -> b.md`, and `… checked (n contradictions, k calls)` from `record_conflict_check`.
- `detect` also prints `… already checked; <outcome>` for an overlap it skips because it is checked, and `reused check (Party Q); <outcome>` for a copied one.
- `conflicts show DIR PARTY FILE FILE` takes the two files in either order. `list` prints `-` for an empty `prevails` / `reason` and the codes comma-separated.
- `record_conflict_check_in_dir` and `decide_conflict_in_dir` refuse a missing or out-of-date ledger (byte-identical file). `record_conflict_check` refuses a different check over an existing one (`already checked`); recording the same check again changes nothing.
- `pending_conflicts(ledger, bundle_dir="DIR")`: the optional directory replaces `DIR` in the command hint; `phase4_blockers` passes the bundle path.


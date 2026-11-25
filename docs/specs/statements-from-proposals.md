# Feature Implementation Spec: Statements and Proposal-backed Party Positions (ingestion phase 4, slice 1)

## Source Feature

- `id`: statements-from-proposals
- `area`: pipeline
- `depends_on`: proposal-conflicts (PR #128, not merged into `v2` at planning time)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest with the fake provider: Statements link to source Proposals, every sided Position's Evidence is a Proposal of that Party, against-positions need a backing Proposal, no stance when there is none, Validation checks 1, 2 and 7 still apply; `CI=true ./init.sh` passes)
- Branch: `feature/statements-from-proposals`, stacked on `feature/proposal-conflicts` (#128) → #127 → #126 → #125 → #124. The PR goes into `v2`, never `main`.
- **Split.** This spec is slice 1 of 2. Slice 2 is the new feature `v2-run-inspection` (see "Follow-up Slice"). `constituency-selection-validation` depends only on this slice.
- Owns these "Constituency redesign" entries in `docs/risks-and-open-questions.md`: grouping and pool size; whether v2 keeps Anchors; the `require_phase4_ready` / `ledger_count_problems` gate (live mode included); reading Proposals only through `counted_proposals`; the legacy `pipeline run` on Elections with candidatures; the `CONSTRAINTS.md` rules for the Agenda, Anchors, `StatementDraft` / `_COMMON_RULES` and the finding rules. Each is settled below or handed off by name.

## Goal

`ideology pipeline run-v2 data/elections/<slug>` runs phase 4 of a format-2 Election. It refuses to start unless the gate passes: every Party is Extracted or Excluded, no conflict is pending, the ledger is up to date and its counts match the database. It then reads each non-Excluded Party's Proposals only through `counted_proposals`. It groups similar Proposals and writes one neutral, single-proposition Statement per group, with a Context Note and a topic-catalog category, recording the group as the Statement's source Proposals. It then positions every non-Excluded Party on every Statement (−2..+2 or `no stance`). Each sided Position has Evidence made of one or more of that Party's own Proposals. The run writes a `candidate` Dataset Version marked `v2`: the whole filtered Statement Pool with its Positions. Validation runs checks 1, 2 (on Proposal Evidence) and 7. A passing v2 run is **not published** in this slice. `constituency-selection-validation` adds the per-Constituency validity, order and availability, and then turns publishing on. Every LLM call is recorded, so a run can be resumed, and a replay with `--reuse-from` makes 0 calls.

## Non-Goals

- Per-Constituency validity, priority order, offered lengths, availability, copying candidatures or Excluded Parties into the Dataset Version, checks 3–6 for v2, and publishing v2 versions (`constituency-selection-validation`).
- Rendering v2 sources and Evidence in `pipeline report|statements|positions` beyond a minimal summary (`v2-run-inspection`). Statement Rewording (`statement-rewording`). Any API, web or `packages/` change (`public-dataset-api-v2`). No UI, so no browser check.
- A real LLM run or converting the committed 2026 bundle (`e2e-2026-constituencies`). Tests use only `FakeProvider`.
- Changing legacy prompts, Agenda, selection v3 or legacy checks. Format-1 runs must behave byte for byte as before.
- Automatic queuing of v2 runs in `live` mode (S11).

## Job Story

When every Party of a format-2 Election is Extracted or Excluded and the conflicts are settled,
I want one command to turn the counted Proposals into neutral Statements and Proposal-backed Party Positions,
so the next feature can choose each Constituency's Questionnaire from an auditable pool, without anyone editing AI output.

## Users And Permissions

- Operator: runs `ideology pipeline run-v2 DIR [--resume-from R | --reuse-from R] [--fresh] [--yes]`. The shared-database confirmation and the unfinished-run guard work as for `pipeline run`.
- `constituency-selection-validation`: consumes the in-memory `V2Pool` before the Dataset Version is written (see "Handoff").
- Voter: nothing visible. A v2 `candidate` is never served by the API.

## Decisions (S1–S12 are defaults for team review)

**S1 Grouping: deterministic buckets, LLM groups.** Each counted Proposal (distinct by Proposal id, over all non-Excluded Parties) goes into the bucket of its **main** category (`categories[0]`). Inside a bucket, Proposals are sorted by `(tags casefolded in order, or ("￿",) when there are none; content_hash; ordinal)`, so similar Proposals sit next to each other. The order is stable across machines because it does not use database ids. Tags-only grouping is rejected: P6 tags are free text (`alquiler` vs `precio del alquiler`), so exact matching would split groups. A separate clustering call is rejected as well: it would double the generation calls and still need a writing step. One `statement_drafts` call per bucket slice does both jobs. The model groups Proposals on the same issue (same category and tags, different wording, either direction), writes one Statement per group, and cites the group's Proposal numbers in `sources`. Those cited Proposals are the Statement's recorded source Proposals. A Proposal may go unused, for example a detail measure.

**S2 Slices and carry-forward.** A bucket is cut, in sorted order, into slices of at most `DRAFT_SLICE_MAX_CHARS = 40_000` characters of Proposal text. A single Proposal over the limit is a slice by itself. The calls for one category are sequential. Each call also lists the Statements already drafted for that category (`S1..Sm`, text only). It returns new Statements (at most `DRAFTS_MAX_NEW = 25`), plus `additions`: extra source numbers for an existing `Sk`. This avoids near-duplicates across slices without a merge call. Replays stay exact because each request depends only on recorded outputs. The prompt asks for about `clamp(ceil(len(slice) / 12), 3, 25)` new Statements. Categories run in catalog order. The pool order is category order, then call order, then draft order. That order is `Statement.position`.

**S3 Pool size and filter.** There is no hard bound. The target is 200 or more, about 1 Statement per 12 Proposals, so 225–335 for 2,700–4,000 Proposals. Reasoning: a Constituency typically has 6–9 included Parties, and if roughly 40–50 % of pool Statements separate them, 200 or more gives 80 or more valid Statements per Constituency, well above 50. Ceuta and Melilla, with about 4 Parties, still get an estimated 50–70. Below 200 the CLI prints a warning; the run does not fail. Before positioning, a deterministic pool filter removes Statements whose Context Note fails `check_context_note` (`context_invalid`) and exact duplicates (`check_statement_uniqueness`; the first copy stays). Both use the run's `ValidationSettings`. So checks 1 and 7 pass by construction, and positioning is not paid for Statements that would be dropped. This filter is not Statement Selection. It is party-blind and recorded in the report.

**S4 Positions per Party × category.** For each non-Excluded Party (in Party id order) and each category with pool Statements (in catalog order), one `proposal_positions` call is made when the Party has counted Proposals that carry that category among their 1–3 categories. The call lists the category's Statements (`[k] text`) and those Proposals (`P1..Pm`, text only, in `counted_proposals` order). The output gives, per Statement it addresses, a `value` from −2 to 2 and `evidence`: 1 to 5 Proposal numbers. A Statement left out, a category with no Proposals of the Party (no call is made), or a Party with no Proposals at all means `no stance`. Because `evidence` needs at least 1 entry, every Position, including any against-position, has a backing Proposal. If a Party's Proposals in one category exceed `POSITION_SLICE_MAX_CHARS = 60_000`, they are sliced and each slice gets a call. When a Statement is positioned in several slices: if all slices give the same side (in favour, against or 0), the first slice's value is kept and the Evidence is the union in slice order; if the sides differ, the Party gets `no stance` and the report records a `slice_disagreement`.

**S5 One Position per Party, with per-Constituency Evidence.** A Party Position stays `(Dataset Version, Statement, Party)`. Each Evidence Proposal stores the Constituencies where it counts for that Party, taken from `CountedProposal.constituencies` and frozen in the Dataset Version. Handoff rule for `constituency-selection-validation`: a Position applies in Constituency c only when one of its Evidence Proposals counts in c; otherwise it is read as `no stance` there. A Party whose counted Proposals differ between its Constituencies (a regional annex, or a partly overlapping conflict) is listed in the report under `partial_scope_parties`.

**S6 Evidence storage (migration `0018`).** A new table, `party_position_proposals`, holds `(id, party_position_id → party_positions ON DELETE CASCADE, rank ≥ 1, proposal_id → proposals (no cascade), source_document_id → source_documents ON DELETE CASCADE, constituencies JSON)`, with unique `(party_position_id, rank)` and `(party_position_id, proposal_id)`. Rank follows citation order. Rank 1 is also **mirrored** into the existing columns: `evidence_source_document_id`, `evidence_quote` = the Proposal text exactly as stored, `evidence_page` = the Proposal page, and `evidence_url` = the row's `source_url`. So the `evidence_matches_value` CHECK stays as it is, with no table recreate. `party_positions` had no referencing table before. Legacy quote Evidence (Dataset Versions 1–5) is untouched and still readable. `evidence_quotes` (check 2) and the v1 API code paths work on v2 rows unchanged. A second new table, `statement_proposals`, holds `(id, statement_id → statements ON DELETE CASCADE, rank ≥ 1, proposal_id → proposals)`, with unique `(statement_id, rank)` and `(statement_id, proposal_id)`. The category is stored in the existing `statements.topic`, since the catalog keys equal the legacy topic keys.

**S7 v2 marker.** A `model_generation` column is added to both `pipeline_runs` and `dataset_versions`. It is a non-native Enum `model_generation` (`legacy`, `v2`), NOT NULL, `server_default 'legacy'`, added with `batch_alter_table(..., recreate='never')`. Existing rows read as `legacy`. The run's value is set at queue time. `_finish_v2` copies it into the Dataset Version at insert, and it is never updated. This slice decides the marker because it writes the first v2 rows, which are immutable. `constituency-selection-validation` builds on it. The `CONTEXT.md` / `docs/domain-model.md` sentence "decided by `constituency-selection-validation`" is updated. The implementer confirms that SQLite emits exactly one CHECK per new column and that `alembic check` reports no drift. If the inline CHECK is not emitted, use a named `sa.CheckConstraint` on a `String(10)`, and record the deviation.

**S8 No Anchors in v2.** v2 runs record `anchor_dataset_version_id = NULL` and never call `_resolve_anchors`. Reasons: 2026 is re-ingested from scratch, legacy Statements have no source Proposals, old Share Links open the outdated-version notice anyway, and an Anchor would be prompt input without provenance. The Anchor rules in `CONSTRAINTS.md` become legacy-only.

**S9 Not published yet.** `validate_run` picks the checks by `model_generation`. `PUBLISH_ON_PASS = {legacy: True, v2: False}` in `pipeline/publishing.py` is the one switch, and `constituency-selection-validation` sets v2 to True. A passed v2 run is `passed`, its version stays `candidate`, and the CLI prints `Not published: v2 dataset versions are published from constituency-selection-validation on`.

**S10 CLI and legacy guard.** A new `ideology pipeline run-v2 DIR` command. Legacy `queue_run` refuses an Election that has candidatures (`bundle_import.candidatures_by_party` is not empty) with `election N has candidatures (format 2); run "ideology pipeline run-v2 DIR"`. Legacy `_start` marks an already-queued legacy run of such an Election `failed`, with the reason `legacy run refused: election has candidatures`. `--resume-from` / `--reuse-from` (`_check_resumable`) and `find_unfinished_run` also require the same `model_generation`.

**S11 Live mode.** `queue_run_for_source_change` returns "nothing queued" for an Election with candidatures. This depends on the kind of Election, not on the mode, so `QUEUE_ON_SOURCE_CHANGE` stays the only place a mode gets behaviour. Reason: in v2, a content change voids the document's review (L5), so phase 4 cannot run until phases 2–3 and the conflicts are redone by the Operator. The ingestion commands have no database and cannot queue. v2 phase 4 is started by the Operator in both modes. `live` keeps queuing for format-1 Elections. The import must flush candidatures before the trigger reads them.

**S12 Sources versus Positions.** Source Proposals may go in either direction. A Party that owns a source Proposal can still end up with `no stance` on that Statement. The report counts such cases (`source_party_no_stance`); they are not an error.

## Prompts (`src/ideology_app/pipeline/v2/prompts.py`, own frozen `V2Prompt`s)

Neither prompt is added to legacy `PROMPTS` / `PROMPT_VERSIONS`. A v2 run records `V2_PROMPT_VERSIONS = {"statement_drafts": "v1", "proposal_positions": "v1"}`. Fingerprints of system + template + `max_tokens` + schema JSON at fixed bounds are pinned in `tests/test_v2_prompts.py`. No Party name, short name, file name or page reaches either prompt.
- **`statement_drafts` v1** (`max_tokens` 16384). The Spanish system text keeps the legacy Statement rules: Spanish of Spain; one proposition; neutral; affirmative by content (no "derogar" unless that is the whole content); no double negatives; plain and self-contained; a clear direction; no figures unless they are the core; no Party or politician names. It also keeps the legacy Context Note rules. On top of these, it adds: group similar Proposals on the same issue in either direction, cite every Proposal of a group, do not repeat a listed Statement (add its numbers to `additions` instead), and prefer issues that several Proposals address. The template gives the category's Spanish name; the previous Statements (`S1. text`, or `(ninguna)`); the Proposals as `P1. [tag, tag] text` on one line each (`conflict_prompts.one_line`); the target and maximum count; the note length range; and the evaluative words from `ValidationSettings`. The schema comes from cached `draft_set_schema(n_proposals, n_previous)`: `statements` holds 0..25 items of `{text: 1..300, \S; context_note: 1..500, \S; sources: list[int 1..n], 1..40}`, and `additions` holds at most `n_previous` items of `{statement: 1..n_previous; sources: list[int 1..n], 1..40}` (with `n_previous` = 0, `additions` must be empty). Duplicate numbers inside `sources` are removed in code, keeping the first. The text is never touched.
- **`proposal_positions` v1** (`max_tokens` 4096). The system text gives the legacy 5-point scale and the rules: report only Statements that a Proposal addresses explicitly; a Proposal in the opposite direction means disagreement, cited; never infer from general ideology or from silence; cite 1–5 Proposals that back the value; leave a Statement out for no stance. The schema comes from cached `position_set_schema(n_statements, n_proposals)`: `positions` has at most `n_statements` items of `{statement: 1..n_statements; value: −2..2; evidence: list[int 1..n_proposals], 1..5}`. A repeated Statement raises `GenerationError` (as in legacy).

## Technical Approach

New package `src/ideology_app/pipeline/v2/` (it depends on `llm.base` only, never a concrete provider):
- `gate.py`: `load_phase4(session, bundle_dir) -> Phase4Input`. Steps: `ingestion_ledger.require_phase4_ready(bundle_dir)`, then `bundle_import.find_election` (an Election that is not imported is an error), then `proposals.store.ledger_count_problems` (refuse if any), then, for each Party of `party_states` with phase `proposals_extracted`, matched by short name to its Party row with candidatures, `proposals.conflicts.counted_proposals`. It returns the Election id, the slug, the Parties `(party_id, short_name, tuple[CountedProposal])` and the sorted distinct source document ids. Every refusal raises `Phase4Error(InvalidInputError)`, with `Phase4Blocked` lines kept.
- `pool.py` (pure apart from the provider): `draft_buckets`, `draft_slices`, `build_pool(provider, counted, usage, settings) -> DraftPool`, `filter_pool(pool, settings)`.
- `positions.py`: `plan_position_calls` (upper bound: Parties × 18 categories × slices) and `assign_positions(provider, statements, parties, usage) -> dict[party_id, list[V2Position]]`, where a `V2Position` holds its `value` and its Evidence refs `(proposal_id, source_document_id, constituencies)`.
- `run.py`: `queue_v2_run`, `execute_v2_run(engine, run_id, provider, bundle_dir, settings)`, `_start_v2`, `_finish_v2`. `_start_v2` checks that the run is queued, `v2`, with the same provider and model. It reloads `load_phase4`; if that refuses, the run is marked `failed` with `phase 4 blocked: …` and the method returns. It records `pipeline_run_source_documents` (role `main` for a Party's first kept document in `[[documents]]` order, `additional` otherwise) and sets the run `running`. A planned-call check against `MAX_V2_CALLS_PER_RUN = 800` runs before any call. The run uses the existing `CheckpointProvider`, `Usage` and `RunOutcome`, and handles `LLMError` / `GenerationError` / Ctrl-C exactly as `execute_run` does. `_finish_v2` writes, in one commit: the Dataset Version (`model_generation = v2`, `questionnaire_lengths` NULL), Statements in pool order, `statement_proposals`, one Position per Party × Statement with mirrored rank-1 columns, `party_position_proposals`, and `statement_selection` (the v2 report: `{"version": "v2-pool-1", "bundle", "parties": [{party_id, proposals, partial_scope}], "categories": [{category, proposals, calls, drafted, additions}], "filtered": [{pool, status, text}], "pool_size", "positions": {calls, sided, no_stance, slice_disagreements: [...], source_party_no_stance}}`).
- **Handoff to `constituency-selection-validation`:** `execute_v2_run` runs `build_pool` → `filter_pool` → `assign_positions` → `V2Pool(statements, positions, report)` → `_finish_v2(engine, run_id, usage, pool)` → `validate_run`. The next feature inserts its selection between `V2Pool` and `_finish_v2`, extends `_finish_v2` with its per-Constituency rows in the same commit, and flips `PUBLISH_ON_PASS[v2]`.

Validation (`validation/`, still pure):
- `ValidationInput` gains optional fields, which stay empty for legacy: `generation`, `statement_sources: Mapping[statement_id, tuple[int, ...]]`, `evidence: Mapping[(statement_id, party_id), tuple[EvidenceRow, ...]]` (`proposal_id`, `source_document_id`, `constituencies`), `proposals: Mapping[int, ProposalRow]` (`content_hash`, `page`, `text`). `RunDocument` gains `content_hash`. `load_input` fills them for v2 runs. For v2, `party_ids` are the distinct Party ids of the Positions.
- New check `evidence_proposals` (check 2 on Proposal Evidence). Every sided Position has 1 or more Evidence rows, and a `no stance` Position has none. Each Evidence row's document is a run document of that Party, the Proposal's `content_hash` equals that document's, `find_quote_miss(proposal.text, pages, proposal.page)` is `None`, `constituencies` is non-empty, and rank 1 equals the mirrored columns.
- New check `statement_sources`: every Statement has 1 or more sources, each one a Proposal whose `content_hash` is one of a run document's.
- `V2_CHECKS = (EVIDENCE_QUOTES, EVIDENCE_PROPOSALS, STATEMENT_SOURCES, STATEMENT_UNIQUENESS, CONTEXT_NOTE)` and `checks_for(generation)`. Legacy `CHECKS` and its order are unchanged.

CLI (`cli.py`): `pipeline run-v2 DIR`. Order: config and settings; `load_phase4` in a read session (`Phase4Blocked` prints one `Error: <blocker>` line each and exits 1, like `ingestion gate`; other refusals print `Error: …` and exit 1, and nothing is written); `_provider()`; the unfinished-run guard (same generation); `_confirm_shared`; queue; resume/reuse lines as in `pipeline run`; execute. Output: `_echo_passed`, then the S9 line, then `Warning: pool of N statements is below the 200 target` when it applies. `pipeline report` on a v2 run prints the generic run fields plus one `statement_selection` line, `v2 pool N statements from M proposals (K filtered), P position calls`, instead of the legacy selection lines. That is the minimal guard; the full view is in slice 2. `RunReport` gains `model_generation`.

## Expected File Changes

- `src/ideology_app/pipeline/v2/{__init__,gate,prompts,pool,positions,run}.py` — create.
- `src/ideology_app/models.py` — modify: `ModelGeneration`, `model_generation` on `PipelineRun` and `DatasetVersion`, `StatementProposal`, `PartyPositionProposal`.
- `src/ideology_app/migrations/versions/0018_v2_statements_evidence.py` — create, by hand, with downgrade.
- `src/ideology_app/pipeline/runs.py` (`queue_run` guard, `_start` refusal, `_check_resumable` and `find_unfinished_run` by generation, `validate_run` checks and publish switch), `pipeline/publishing.py` (`PUBLISH_ON_PASS`), `pipeline/triggers.py` (S11), `pipeline/reports.py` (`model_generation`), `pipeline/__init__.py` (exports) — modify.
- `src/ideology_app/validation/{base,__init__}.py`, `validation/evidence_proposals.py`, `validation/statement_sources.py` — modify and create.
- `src/ideology_app/cli.py` — modify: `pipeline run-v2`, the v2 report line.
- `data/ideology.db` — upgrade to `0018`, `db check`, commit (shared-DB rule).
- Tests: `tests/test_v2_prompts.py`, `test_v2_pool.py`, `test_v2_positions.py`, `test_v2_runs.py`, `test_validation_v2.py`, `test_cli_pipeline_v2.py`, plus a `tests/v2_fixtures.py` built on `proposal_fixtures` and `conflict_fixtures` — create. `tests/test_migrations.py`, `test_pipeline_runs.py`, `test_pipeline_triggers.py`, `test_cli_live_mode.py` — extend.

## Visual Design Impact

- UI involved: no. No browser check: CLI, data and pipeline only. A v2 candidate is never served.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. New "Phase 4 (v2 pipeline)" section: the modules, the data flow, the `V2Pool` seam, the `model_generation` marker and the two new tables.
- `CONSTRAINTS.md`: update.
  - Mark the Agenda, Anchors, `StatementDraft` / `_COMMON_RULES`, `position_findings` / `party_positions` and selection v3 rules as **legacy pipeline only**.
  - Add the v2 rules: the v2 prompts' bump-and-fingerprint rule and no Party names in them; Evidence Proposals and Statement sources written only by `_finish_v2`, insert-only; rank 1 always mirrored; Statement sources and Evidence only through `counted_proposals` (rule already there); `model_generation` written once at insert; legacy runs refused on Elections with candidatures; v2 not published while `PUBLISH_ON_PASS[v2]` is False; a migration MUST NOT recreate `party_positions` now that it is referenced with CASCADE.
  - Extend "Dataset Version written in one transaction" to `_finish_v2`.
- `AGENTS.md`: not needed. The invariants are unchanged.
- `CONTEXT.md`, `docs/domain-model.md`: update. Statement Pool (v2: the filtered pool, no bound, target ≥ 200), Anchor (v2: none), the marker sentence, Evidence (rank, mirror, Constituencies), the Party Position applicability rule (S5), "passed v2 stays candidate until `constituency-selection-validation`", and the v2 checks list (`evidence_proposals`, `statement_sources`).
- `docs/technical-discovery.md`: update. A "Phase 4 (v2 run)" section: the command, the gate, S1–S12, the prompts, the cost estimate and the runbook.
- `docs/risks-and-open-questions.md`: update.
  - Mark Settled: grouping and pool size (S1–S3), Anchors (S8), the gate and `counted_proposals` handoffs, the legacy run handoff (S10), the live trigger handoff (S11), and the `CONSTRAINTS.md` handoff for the Agenda, Anchors, `StatementDraft` and finding rules.
  - Add Open, for team review: S1–S12, with **S5 and S6 called out**.
  - Add handoffs to `constituency-selection-validation`: the applicability rule, `PUBLISH_ON_PASS`, the `V2Pool` seam and `partial_scope_parties`.
  - Add a handoff to `methodology-v2`: describe the v2 checks.
  - Add for `e2e-2026-constituencies`: measure the real pool size, separation rate, calls, cost, `slice_disagreements` and the share of `no stance` caused by the same-category limit (S4).
- `apps/web/src/features/methodology/MethodologyPage.tsx`: not needed. No legacy check, setting or prompt changes. The v2 checks are not public until `methodology-v2`, which gets the handoff above.

## Cost Estimate (2026, assumptions; no real run here)

Inputs: 2,700–4,000 Proposals (`proposal-extraction` estimate), about 350 characters each, so 0.93–1.39M characters (regional manifestos add 20–40 %). Allow 15–25 included Parties.
- `statement_drafts`: about 32–45 calls (main-category text / 40k characters, plus per-category rounding; up to about 57 with the regional manifestos). Input ≈ 0.35–0.6M tokens, output ≈ 0.1M.
- `proposal_positions`: about 210–350 calls (Parties × about 14 categories each). About 5k input tokens per call, so ≈ 1.0–1.75M input and ≈ 0.13–0.2M output.
- Total: ≈ 245–410 calls, ≈ 1.4–2.4M input tokens (plan ≈ 2.1–3.6M with the 1.5× measured on `claude_code`) and ≈ 0.23–0.3M output. That is about **$8–12 on `anthropic`** at the Sonnet list price ($3 / $15 per M; check before use), up to about $15 with the 1.5× factor, or **3–5 h** of sequential calls on `claude_code` (about 45 s per call). Legacy run 5 used 353 calls and 9.75M input tokens. A `--reuse-from` replay of an identical run makes 0 calls.

## Acceptance Scenarios

1. **Gate.** Given a format-2 test bundle where one Party is pending, or a conflict is `unchecked` or `pending`, or the ledger is out of date, or a ledger count differs from the database, or the Election is not imported, when `pipeline run-v2 DIR` runs, it exits 1 with the blocker lines, and no run, call or row is written.
2. **Happy path.** Given 3 Parties (one Excluded), 2 categories, and fake responses, when the run executes, then: the run is `passed` with `model_generation = v2`; the Dataset Version is `v2` and `candidate` (not published); each Statement has `topic` = its bucket's category, a Context Note and ≥ 1 `statement_proposals` row in citation order; the Excluded Party has no Positions; the other two have exactly one Position per Statement; and all five v2 checks pass.
3. **Evidence belongs to the Party.** Every sided Position's `party_position_proposals` rows reference Proposals counted for that Party, with its own source row, and rank 1 equals the mirrored columns. A fake answer cannot cite another Party's Proposal, because the numbers are bounded to that Party's list.
4. **Against and no stance.** A Proposal in the opposite direction gives −1/−2 with that Proposal as Evidence. A Party with no Proposal in a category gets no call and `no stance` on its Statements, and so does a Statement the answer leaves out. A fake answer with `evidence: []` fails its call (`LLMOutputError`) and the run is `failed`.
5. **Conflict and scope.** With a `decided` conflict (C2), the losing Proposals set aside in all of the Party's overlap Constituencies are not in that Party's prompt. A Proposal counting in only some Constituencies has those codes in its Evidence `constituencies`, and the Party is listed under `partial_scope_parties`.
6. **Slices.** A bucket over 40k characters makes ordered calls, where the second lists `S1..Sm` and its `additions` extend the sources. A Party × category over 60k characters follows the S4 merge rule, including a `slice_disagreement` → `no stance`.
7. **Filter.** A draft with a note containing an evaluative word, and an exact duplicate, are left out before positioning, recorded in `filtered`, and get no position calls.
8. **Resume and replay.** An `LLMError` in the middle of positioning gives a `failed` run with its calls recorded. `--resume-from` reuses them, and `FakeProvider.calls` holds only the rest. `--reuse-from` a passed v2 run makes 0 provider calls and writes Statements, sources, Positions and Evidence equal to the source run's (ids aside). Resuming a legacy run as v2, or a v2 run as legacy, is refused.
9. **Party neutrality.** No prompt contains a Party name, short name, file name or page marker. Permuting Party ids or manifest order gives each Party the same Positions.
10. **Legacy guards.** `pipeline run --election N` on an Election with candidatures exits 1 with the S10 message. A legacy run already queued there is marked `failed` by `run-queued`. In `live`, a format-2 `data import` with a changed document queues nothing, while a format-1 import still queues. Every existing pipeline, validation and CLI test passes unchanged, and the legacy prompt fingerprints are unchanged.
11. **Validation pure cases.** `evidence_proposals` fails each of: a sided Position without Evidence, a `no stance` Position with Evidence, Evidence from another Party's document, a content-hash mismatch, a Proposal not on its page, empty `constituencies`, and rank 1 differing from the mirror. `statement_sources` fails a Statement without sources or with a foreign Proposal.
12. **Migration.** `0018` upgrades a database holding legacy runs, versions and Positions: they read `legacy`, the partial unique index is still in `sqlite_master`, and the downgrade keeps the child rows. `data/ideology.db` is at head and `db check` prints `Safe to commit: yes`.

## Implementation Plan And Tasks

- [ ] Write the migration `0018` and the models, with tests for upgrade, downgrade and drift. Upgrade `data/ideology.db` and run `db check`.
- [ ] Write `v2/prompts.py` and pin the fingerprints and schema bounds.
- [ ] Write `v2/gate.py` with every refusal path.
- [ ] Write `v2/pool.py` (buckets, slices, carry-forward, filter).
- [ ] Write `v2/positions.py` (calls, merge rule, symmetry).
- [ ] Write the validation inputs and the two checks, plus `V2_CHECKS` and `checks_for`.
- [ ] Write `v2/run.py`, plus the `runs.py` and `publishing.py` changes (generation-aware resume, checks and publish switch).
- [ ] Add the legacy guards and the S11 trigger skip.
- [ ] Add the CLI command `pipeline run-v2` and the minimal v2 `pipeline report` line.
- [ ] Update the docs (see the impact list) and the risks entries.
- [ ] Run `CI=true ./init.sh`. Record the evidence in `feature_list.json` and `PROGRESS.md`.

## Verification Plan

- `.venv/bin/pytest tests/test_v2_prompts.py tests/test_v2_pool.py tests/test_v2_positions.py tests/test_v2_runs.py tests/test_validation_v2.py tests/test_cli_pipeline_v2.py tests/test_migrations.py tests/test_pipeline_runs.py tests/test_pipeline_triggers.py tests/test_cli_live_mode.py tests/test_pipeline_prompts.py` — all pass, with `FakeProvider` only and the offline guard in every new module.
- Legacy unchanged: on scratch copies of `data/ideology.db`, the output of `pipeline report --run 5`, `pipeline statements` / `positions` for Dataset Version 5, `data check` for both committed bundles and `db check` is byte-identical to before (git archive of the base commit, as `proposal-conflicts` did).
- Manual CLI walk on a scratch format-2 bundle and scratch database (`LLM_PROVIDER=fake`, as `proposal-conflicts` did): run the gate refusal, a passing run (with fake responses it may be `failed` by design; record what it printed), `--reuse-from` with 0 calls, and the legacy refusal.
- `CI=true ./init.sh` exits 0. There is no E2E or browser step, since nothing is user-visible.

## Evidence To Capture

The test counts before and after; the pinned fingerprints; the byte-identical legacy outputs; the head and `db check` result of `data/ideology.db`; the scenario-to-test mapping; and any deviation from S1–S12, recorded in an "Implementation Notes" section of this spec.

## Validator Checklist

- [ ] Scope: no API, web, per-Constituency or publish-on change. No real LLM call.
- [ ] Scenarios 1–12 pass. The gate refuses with nothing written.
- [ ] Every sided v2 Position has ≥ 1 Evidence Proposal of its own Party, and rank 1 equals the mirror.
- [ ] Legacy outputs and prompt fingerprints are unchanged. The migration's downgrade keeps the child rows. `data/ideology.db` is at head and safe to commit.
- [ ] Docs and the risks entries are updated as listed. `feature_list.json` and `PROGRESS.md` hold the evidence.

## Follow-up Slice (new feature entry, for `feature_list.json`)

- `id`: `v2-run-inspection`. `area`: pipeline. `depends_on`: [`statements-from-proposals`].
- `title`: Inspect a v2 Pipeline Run: pool report, Statement sources and Proposal Evidence.
- `user_visible_behavior`: For a v2 run, `ideology pipeline report --run R` shows the pool report: Parties with their counted Proposals and partial scope; per category the Proposals, calls, drafted Statements and additions; the filtered Statements with their reason; position calls, sided and `no stance` counts per Party; slice disagreements; and source Parties with no stance. `ideology pipeline statements --run R --sources` lists each Statement's source Proposals (file, page, an excerpt of the text). `ideology pipeline positions --run R --evidence` lists each Position's Evidence Proposals with their Constituencies. Read-only. Legacy output is byte-identical.
- `verification`: pytest with exact CLI output for v2 runs and byte-identical legacy output for runs 1–5 on a scratch copy; `CI=true ./init.sh` passes.
- Suggested: add it to `depends_on` of `ingestion-guide` (the guide shows the Operator the pool) or of `e2e-2026-constituencies`. `constituency-selection-validation` does not need it.

## Implementation Notes (2026-11-25, implementer)

Deviations and additions, none changing S1–S12:

- **S7 CHECK (anticipated fallback).** On SQLite, Alembic skips an `sa.Enum`'s implicit CHECK on `ADD COLUMN` (it warns "Skipping unsupported ALTER for creation of implicit constraint", which the `-W error` gate turns into a failure). Migration `0018` therefore adds `model_generation VARCHAR(10) DEFAULT 'legacy' NOT NULL` with one named column-level `CHECK (model_generation IN ('legacy', 'v2'))` (`ck_pipeline_runs_model_generation`, `ck_dataset_versions_model_generation`). The model keeps a non-native `sa.Enum(ModelGeneration, length=10, create_constraint=True)` that names the same CHECK. Verified: exactly one CHECK per new column in `sqlite_master` and in the offline PostgreSQL render, and `compare_metadata` reports no drift.
- **`Phase4Input` is plain data.** `load_phase4` returns `Phase4Party(party_id, short_name, proposals: tuple[PhaseProposal, ...])` instead of `tuple[CountedProposal]`: a `CountedProposal` holds an ORM `Proposal`, whose attributes expire when `_start_v2`'s session commits. `PhaseProposal` copies the Proposal fields, the Source Document row id and URL and the Constituencies from `counted_proposals`, in the same order.
- **Run documents.** `pipeline_run_source_documents` records each Party's documents that have counted Proposals, `main` for the first in `[[documents]]` order. It differs from "first kept document" only when every Proposal of that document is set aside (accepted Low in the risks doc).
- **Report keys.** The v2 `statement_selection` also holds `partial_scope_parties` (the S5 list) and `proposals` (distinct counted Proposals, used by the `pipeline report` line).
- **`proposal_positions` template** starts with `Tema: <category name>` (no Party information).
- **`find_unfinished_run`** gains an optional `generation` filter; `None` (used by `db check`) keeps the old "any run" behaviour. The legacy CLI guard passes `legacy`, `run-v2` passes `v2`.
- **Legacy `_start`** also refuses a queued v2 run (`InvalidInputError`, nothing changes), so `run-queued` never executes a v2 run as legacy.
- **Empty input.** No counted Proposal at all, or an empty pool after the filter, fails the run (`GenerationError`) instead of writing an empty Dataset Version.
- **Warning stream.** `Warning: pool of N statements is below the 200 target` goes to stderr, like the other CLI warnings.
- **Existing tests changed by design:** `test_bundle_import.py::test_live_mode_queues_only_for_documents` (S11: a format-2 live import now queues nothing), the shared-head pins in `test_feedback_migrations.py` / `test_feedback_store.py` (0018), and head-schema assertions in `test_migrations.py` (CHECK count 16 → 20, the new CHECK names, `model_generation` dropped by downgrades through 0018).

Scenario → tests:

1. Gate: `test_v2_runs.py::test_gate_refuses_*` (pending Party, unchecked conflict, pending decision, out-of-date ledger, count mismatch, not imported), `test_start_marks_the_run_failed_when_the_gate_closes`; `test_cli_pipeline_v2.py::test_gate_refusal_writes_nothing`, `test_not_imported_is_one_error_line`.
2. Happy path: `test_v2_runs.py::test_happy_path_writes_a_candidate_v2_version`, `test_report_records_the_pool_and_partial_scope`; `test_cli_pipeline_v2.py::test_run_passes_stays_candidate_and_replays_with_zero_calls`.
3. Evidence belongs to the Party: `test_happy_path_*` (Evidence rows, mirror), `test_v2_positions.py::test_empty_evidence_fails_the_call_and_a_repeat_is_a_generation_error` (out-of-range number).
4. Against and no stance: `test_v2_positions.py::test_against_no_stance_and_no_call_without_proposals`; `test_v2_runs.py::test_omitted_statement_is_no_stance_and_counted_as_source_party`, `test_empty_evidence_fails_the_run`.
5. Conflict and scope: `test_v2_runs.py::test_set_aside_proposals_are_not_in_the_party_prompt`, `test_happy_path_*` (Constituencies), `test_report_records_the_pool_and_partial_scope`.
6. Slices: `test_v2_pool.py::test_carry_forward_lists_earlier_statements_and_additions_extend_sources`, `test_slices_cut_at_the_limit_and_keep_a_long_proposal_alone`; `test_v2_positions.py::test_slices_merge_same_side_and_disagreement_is_no_stance`; budget: `test_v2_runs.py::test_budget_refuses_before_any_call`.
7. Filter: `test_v2_pool.py::test_filter_drops_invalid_notes_then_exact_duplicates`; `test_v2_runs.py::test_filtered_statements_get_no_position_calls`.
8. Resume and replay: `test_v2_runs.py::test_resume_reuses_recorded_calls_and_reuse_replays_with_zero_calls`, `test_resume_across_generations_is_refused`; `test_cli_pipeline_v2.py::test_resume_after_a_failure`.
9. Party neutrality: `test_happy_path_*` (no name in any prompt), `test_v2_positions.py::test_positions_do_not_depend_on_party_ids_or_order`, `test_v2_prompts.py::test_no_party_or_file_names_in_the_prompts`.
10. Legacy guards: `test_v2_runs.py::test_legacy_run_is_refused_on_an_election_with_candidatures`, `test_legacy_executor_refuses_a_queued_v2_run`; `test_cli_pipeline_v2.py::test_legacy_commands_refuse_an_election_with_candidatures`; `test_pipeline_triggers.py::test_live_format_2_import_queues_nothing`; `test_cli_live_mode.py::test_live_format_2_import_queues_nothing_and_format_1_still_queues`; `test_v2_prompts.py::test_versions_and_limits` (legacy `PROMPT_VERSIONS`); `test_pipeline_prompts.py` unchanged.
11. Validation pure cases: `test_validation_v2.py`.
12. Migration: `test_migrations.py::test_upgrade_0018_*`, `test_0018_constraints_and_cascades`, `test_downgrade_to_0017_*`, `test_offline_postgresql_render_of_0018`, `test_migrations_match_models`; `test_committed_database.py`.

# Feature Implementation Spec: Proposal extraction (ingestion phase 3)

## Source Feature

- `id`: proposal-extraction
- `area`: pipeline
- `depends_on`: ingestion-ledger (accepted), topic-catalog (accepted)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest with the fake provider: verbatim/page check drops a misquoted Proposal, resume after interruption makes no repeated calls, reuse for an unchanged document, threshold exclusion recorded in the ledger; `CI=true ./init.sh` passes)
- Branch: `feature/proposal-extraction`, stacked on `feature/ingestion-ledger` (PR #126) → #125 → #124. The PR goes into `v2`, never `main`.
- Owns these entries in `docs/risks-and-open-questions.md` "Constituency redesign": the Open extraction cost and chunking entry; the D1 handoff (extract once per `content_hash`); the `ingestion-ledger` phase-3 handoff; the hand-edit handoff (ledger count = validated Proposal rows), shared with `statements-from-proposals`.

## Goal

`ideology proposals extract DIRECTORY` runs phase 3 for a format-2 Election. For each document the Ingestion Ledger records as `kept`, it asks the configured LLM for every concrete measure or commitment, chunk by chunk. A Proposal is stored only when its verbatim text starts on its cited page. When a document is complete, the validated count is written to the ledger through `record_extraction_in_dir`, and the ledger derives Extracted or `too_few_proposals` from the summed N. Extraction runs over several invocations and records every call as it returns. A resumed extraction makes no repeated call. A document whose content hash already has a complete extraction (same file shared by several Parties, an unchanged file, the same bytes in another Election) costs zero calls. Proposals belong to document content, not to a Dataset Version, and are never updated or deleted.

## Non-Goals

- A real extraction of the 2026 manifestos, or spending any real LLM budget (`e2e-2026-constituencies`). Tests use only `FakeProvider`.
- Conflicts between documents (`proposal-conflicts`); grouping Proposals into Statements, v2 Evidence, the v2 run and wiring the phase-4 gate (`statements-from-proposals`).
- Re-extracting a document that already has a complete extraction (for example after a prompt bump). That needs a later feature (P4).
- Quote repair for Proposals (P1). Any change to `pipeline/` (legacy prompts, `PROMPT_VERSIONS`, runs, checkpoint, triggers), `validation/`, `api/`, `apps/web/`, `packages/`.
- Converting the committed 2026 bundle to format 2. No UI, so no browser check.

## Job Story

When I have reviewed an Election's manifestos,
I want every kept manifesto turned into verbatim, page-cited, categorised Proposals, over as many sittings as my LLM budget allows,
so I can reach phase 4 knowing each Party's Proposal count, without paying twice for any chunk or shared file.

## Users And Permissions

- Operator: runs `ideology proposals extract|status|list`, on the shared DB with the usual one-active-writer rule and confirmation.
- `statements-from-proposals`: reads Proposals (`proposals.store.load_proposals`) and calls `ledger_count_problems` before a v2 run.
- Voter: nothing visible.

## Decisions (P1–P10 are defaults for team review; the rest are design choices)

**Storage (migration `0017_proposals`, head `0016` → `0017`).** Three new tables, no change to existing ones:
- `proposal_extractions`: `id`; `content_hash` String(64), **unique**; `status` non-native enum `proposal_extraction_status` (`in_progress`, `complete`); `llm_provider`, `llm_model`, `prompt_version` (pinned at creation); `chunk_max_chars`, `chunk_count`; `check_version` (`v1`); `validated_count` int null; `report` JSON null (counts per drop reason, plus the dropped items `{chunk, page, reason, found_on, text}`); `created_at`, `completed_at`.
- `proposal_extraction_calls`: `id`; `extraction_id` FK; `chunk_index` (0-based); `first_page`, `last_page`; `request_hash` String(64); `output` JSON (exactly as validated); `input_tokens`, `output_tokens`; `created_at`. Unique `(extraction_id, chunk_index)`.
- `proposals`: `id`; `extraction_id` FK; `content_hash` String(64), indexed (denormalised for lookup); `ordinal` (1-based, unique per extraction); `chunk_index`; `page` (≥ 1, CHECK); `text` Text; `categories` JSON (1..3 catalog keys, main first); `tags` JSON (0..5 strings).

Categories and tags are JSON lists, not join tables. `statements-from-proposals` loads every Proposal of an Election in Python (a few thousand rows), and JSON is portable to PostgreSQL. FKs use no `ON DELETE CASCADE`, because nothing is ever deleted. The single exception is `--restart` on an `in_progress` extraction (below). Follow `CONSTRAINTS.md`: hand-reviewed revision, one CHECK per enum, upgrade/downgrade/offline-PG tests. **`data/ideology.db` is upgraded to `0017` and committed** (empty tables, no extraction), as `test_committed_database.py::test_is_at_migration_head` and the Shared Database rule require.

**Identity = content hash, not Dataset Version and not document row.** A Source Document row keeps the same `content_hash` for life. Shared rows (D1) and identical bytes in another Election have equal hashes. So one extraction per hash serves every row, and the per-Party unique `(party_id, content_hash)` constraint lets later code map a Proposal to the positioned Party's Source Document row. A changed file has a new hash, so it gets a new extraction and new Proposals. The old extraction and its Proposals stay for older Evidence. Dataset Versions will reference Proposal ids (`statements-from-proposals`); a Proposal row is never updated or deleted.

**Inputs and checks before any call (`extract`).** The command reads the bundle with `read_bundle`; a format-1 bundle is refused with `the Ingestion Ledger needs a format-2 election.toml`. Then `ledger = read_ledger(dir)`, and `reconcile` must reproduce it byte for byte. If it does not, the command refuses with `out_of_date_problem`. A missing ledger is refused with `no ingestion ledger yet; run "ideology ingestion update DIR"`. Documents are taken from `ledger.documents` in manifest order, those with `review.decision == kept` only (`--file F` narrows to one; a non-kept `--file` is refused). For each document the command finds the Election with a new public `bundle_import.find_election(session, bundle)` (a wrapper of `_find_election`). It then needs a current parsed Source Document row of that Election with `bundle_file == file` and `content_hash ==` the ledger document's hash. If no such row exists, the document fails with `document F: content_hash <12>… is not imported; run "ideology data import DIR"`, and other documents continue. Page text comes from the lowest-id such row. The command reads neither candidatures nor scopes. `CONSTRAINTS.md` gains: phase 3 may read `Ledger.documents` through `read_ledger` + `reconcile`.

**Chunking (P2).** `proposals.extraction.build_chunks(pages)` is pure:
- Whole consecutive non-blank pages up to `PROPOSAL_CHUNK_MAX_CHARS = 12_000`, counting the markers. A page is never sliced, because slicing breaks the page citation. A single page over the limit is a chunk alone.
- Each chunk except the last also gets the next non-blank page as trailing context, marked `[página N — solo contexto]`. The real pages are marked `[página N]`, the existing format.
- A Proposal cites the page it **starts** on, and its text may run onto the next page. That is the matcher's rule, `find_quote_miss`. The context page lets a Proposal that starts on a chunk's last page be copied whole.
- A Proposal that starts on the context page is dropped as `context_page`, because the next chunk extracts it.
- Text running over more than two pages fails the check (rare, reported).

Why 12,000 and not the legacy 40,000: output is verbatim copy, so a call's output grows with its input. At 12,000 the worst case (a chunk that is all bullet points) stays near 5k output tokens, well under `max_tokens`. A truncated or schema-failing call is expensive: `claude_code` retries it up to 5 times, re-sending the whole chunk. Smaller chunks also make the "extract everything" instruction more reliable.

**Prompt and output (`proposals/prompts.py`, task `proposal_extraction`, version `v1`, `max_tokens = 16384`).** The module defines its own frozen `ProposalPrompt(task, version, system, template, max_tokens)` and does not import `pipeline.prompts`. That keeps legacy `PROMPTS` / `PROMPT_VERSIONS` and their fingerprints unchanged. A pinned fingerprint test, `tests/test_proposal_prompts.py`, covers the system text, template and schema JSON. Any change bumps the version (a new `CONSTRAINTS.md` rule). Schema, built per request by the cached `proposal_list_schema(first_page, last_page)` (both ints ≥ 1, first ≤ last; `last_page` is the context page when there is one):
```python
Category = Literal[<the 18 TOPIC_CATALOG keys, catalog display order>]
class ProposalItem(BaseModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=1500, pattern=r"\S")]
    page: int = Field(ge=first_page, le=last_page)
    categories: list[Category] = Field(min_length=1, max_length=3)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"\S")]] = Field(max_length=5)
class ProposalList(BaseModel):
    proposals: list[ProposalItem] = Field(max_length=120)
```
System text (Spanish, exactly this content; wording may be polished before the fingerprint is pinned):
> Eres un analista político que prepara la base de un cuestionario de orientación de voto para unas elecciones generales en España. Lees un fragmento de un programa electoral y extraes todas sus propuestas: cada medida concreta o compromiso que el programa dice que hará, apoyará o rechazará.
> Reglas:
> - Una propuesta es un punto de una lista o un párrafo con una medida o un compromiso. Cada punto de una lista es una propuesta distinta.
> - Extrae todas las propuestas, también las de detalle y las que solo aparecen una vez, sin elegir, resumir ni unir.
> - Incluye texto de diagnóstico o de contexto solo cuando está en el mismo párrafo que la medida o la medida no se entiende sin él; nunca extraigas un diagnóstico solo.
> - `text` se copia literalmente del fragmento: sin parafrasear, sin puntos suspensivos, sin añadir ni quitar palabras y sin el marcador [página N]. Como máximo unos 1.000 caracteres: si el párrafo es más largo, copia el tramo continuo que contiene la medida.
> - `page` es el número del marcador de la página donde empieza el texto; el texto puede seguir en la página siguiente.
> - La página marcada «solo contexto» sirve solo para completar una propuesta que empieza antes; no extraigas propuestas que empiecen en ella.
> - `categories`: de una a tres claves de esta lista, la principal primero; normalmente una: `housing` (Vivienda), … (all 18 as `key (Nombre)`, catalog order).
> - `tags`: de cero a cinco etiquetas libres en español, en minúsculas, de una a cuatro palabras, que nombran el asunto concreto (por ejemplo «alquiler», «salario mínimo», «energía nuclear»).
> - Si el fragmento no contiene propuestas (portada, índice, presentación), devuelve una lista vacía.

Template: `Fragmento de programa electoral (cada página va precedida de su marcador):\n\n{chunk}\n\nExtrae todas las propuestas de este fragmento.` Only page text reaches the prompt: no Party names, no file names.

**Recording and resume.** The checkpoint mechanism is reused through its pure `pipeline.checkpoint.request_hash` (provider, model, task, system, prompt, schema, max_tokens). `CheckpointProvider` itself is not reused, because it is keyed by Pipeline Run and progress here is per document. For chunk *i* of an extraction:
- If a call row exists with an equal `request_hash`, its output is re-validated against the request schema and used, with zero calls.
- If no row exists, the provider is called. The row is inserted in its own commit as soon as the call returns.
- If a row exists with a different hash (the config or the code changed mid-document), the command refuses. The message names the pinned provider/model/prompt version and says `set LLM_PROVIDER/LLM_MODEL to match, or pass --restart F`.

`--restart F` deletes the calls and the row of an `in_progress` extraction only, and refuses a complete one. When every chunk has a call, **finalize** runs. It is deterministic, has no LLM, and is a single transaction: it inserts the Proposal rows, sets `validated_count`, `report`, `status = complete` and `completed_at`. A crash between the last call and finalize is therefore repaired by the next invocation with zero calls. That is the "replay": rerunning on a DB that holds the recorded calls never calls the LLM. Call rows are insert-only, like `pipeline_run_calls`.

**Check and dedupe in finalize (P1, P5; `CHECK_VERSION = "v1"`).** Recorded outputs are processed in chunk order, then item order:
1. Drop `context_page`: `page` is the chunk's context page.
2. Drop on `find_quote_miss(text, normalize_pages(all pages), page)`, reasons `no_letters` / `other_page` (with `found_on`) / `not_found`. Text and page are never changed (no `quote_repair`).
3. Drop `duplicate`: the `normalize_for_match(text)` equals the text of an earlier kept Proposal of the same document.

The kept items get ordinals 1..n. Text, page, categories and tags are stored exactly as returned.

**Ledger handoff.** After finalize commits, for every complete extraction of a kept document whose ledger count differs from `validated_count`, or is missing, the command calls `ingestion_ledger.record_extraction_in_dir(bundle_dir, file, content_hash=…, validated_proposals=validated_count)` and prints the affected Parties' `state_label`s. It never sets a phase. If the ledger write fails after the DB commit, the next run re-records it. A shared file (D1) is recorded once, and the ledger applies the count to every Party listing it.

**Phase-4 count check.** `proposals.store.ledger_count_problems(session, bundle, ledger) -> list[str]` returns, for each document whose review is kept and whose `proposals` is not null, one of:
- `document F: ledger records N validated proposals but there is no complete extraction for <hash12>…`;
- `document F: ledger records N validated proposals, the database has M for <hash12>…`.

Callers:
- (a) `db check` and `data check` add it to the format-2 problems next to `ledger_problems`, when a ledger exists (P8);
- (b) `proposals status` prints it;
- (c) handoff: `statements-from-proposals` calls it right after `require_phase4_ready` before queuing or executing a v2 run (live mode included) and refuses on any problem.

**CLI (`ideology proposals`, `@requires_db`).**
- `extract DIRECTORY [--file F] [--max-calls K] [--restart F] [--yes]`. Before any write, `config.llm_settings()` and the provider are resolved through `cli._provider()`, so the provider and model come only from configuration. On the shared DB it calls `_confirm_shared`. Documents are processed in order, one finished before the next. Each document prints one of:
  - `Document F (<hash12>): reused complete extraction (N proposals)`;
  - `… chunk i/n` progress;
  - `… complete: N proposals (dropped: not_found a, other_page b, context_page c, duplicate d, no_letters e)`.

  The run stops cleanly once `K` new calls have been made (default `300`, P9; prints `Stopped after K calls; run again to continue`). On `LLMError` it stops, prints `Error:`, exits 1, and keeps the progress. It ends with `Calls: C new, R reused; input_tokens I, output_tokens O`.
- `status DIRECTORY` (read-only): one `file<TAB>hash12<TAB>state<TAB>chunks done/total<TAB>validated<TAB>ledger` line per kept document, then the `ledger_count_problems` lines (exit 1 if any).
- `list DIRECTORY --file F [--dropped]`: tab-separated `ordinal page categories tags text` (text on one line), or the dropped items.
- `db check` also prints the info line `proposal extraction <hash12>: in_progress, i/n chunks` for unfinished extractions.

**Legacy path.** Format-1 bundles are refused by `proposals` and have no ledger. Nothing in `pipeline/`, the legacy run, live triggers, `PROMPT_VERSIONS` or the Dataset Version code changes. Existing tests pass unchanged.

**P-defaults for team review:**
- P1: strict check, no repair.
- P2: 12,000 chars plus one context page.
- P3: reuse is global by content hash, across Elections too.
- P4: a complete extraction is never redone; a prompt bump does not re-extract.
- P5: exact normalised dedupe only, so near-duplicates and a bullet that repeats its paragraph are both kept.
- P6: 1–3 categories, 0–5 tags of at most 40 characters.
- P7: text 1..1500 characters, a contiguous verbatim excerpt.
- P8: a count mismatch is a `db check` / `data check` error.
- P9: `--max-calls` defaults to 300 per invocation.
- P10: a resume is pinned to the provider, model and prompt version; `--restart` is explicit.

## Cost Estimate (settles the Open cost entry with a number)

Measured on the committed 2026 bundle: 12 files, 1,044 PDF pages, 1,033 non-blank, 2.32M characters. With P2 that is **225 calls** (PP 15, PSOE 24, VOX 5, Podemos 33, Frente Amplio 33, Junts 33, ERC 19, Adelante Andalucía 21, BNG 16, Compromís 12, EH Bildu 9, SALF 5) and 2.98M input characters including context pages.

- Input tokens: about 3.5 characters per token, so ≈ 0.85M, plus about 1.2k system tokens × 225 ≈ 0.27M, for ≈ 1.1M. The 2023 runs measured 1.5× their estimate on `claude_code`, so plan for **≈ 1.7M**.
- Output tokens: if 40–60 % of the text is Proposals, that is 0.27–0.40M tokens of copy. Add about 2,700–4,000 Proposals × ~35 tokens of JSON, for **≈ 0.36–0.54M**.
- Per call: at most about 5k output tokens.
- Totals: on `claude_code` (Sonnet) about **2.5–3.5 h** of sequential calls, which `--max-calls` spreads over several sittings. On `anthropic` at the Sonnet list price of $3 / $15 per M tokens (check before use), roughly **$8–12**.
- Regional manifestos added in `e2e-2026-constituencies` scale this linearly by their pages (estimate +20–40 %).

Real-LLM yield (drop rate, Proposals per page) is unknown until `e2e-2026-constituencies`. That feature records it.

## Acceptance Scenarios

1. **Happy path and ledger.** Given a format-2 bundle with one kept document, a ledger at N = 3 and a fake provider returning 4 valid items per chunk, when `extract` runs, then every chunk is called once, the Proposals are stored with their pages, categories and tags as returned, the ledger records the count, and the Party is `proposals_extracted`.
2. **Misquote dropped.** Given a fake item whose text is not on any page, one that starts on another page, one on the context page and one duplicate, then none is stored, the report counts each reason, and the validated count excludes them.
3. **Straddling page kept.** An item whose text starts at the end of page p and continues on p+1 (the context page) is kept with page p.
4. **Resume.** Given a fake that raises `LLMError` on chunk 3 of 5, the first run exits 1 with 2 call rows. The second run calls the provider exactly for chunks 3–5 (`fake.calls`), and the final Proposals equal those of an uninterrupted run.
5. **Finalize-only replay.** Given every call recorded but status `in_progress`, `extract` makes 0 calls and completes.
6. **Reuse.** A rerun after completion makes 0 calls. A file shared by two Parties (D1) is extracted once, and the ledger applies the count to both. The same bytes in another Election reuse the extraction with 0 calls.
7. **Changed document.** After a file change, import and `ingestion update`/`review`, a new extraction is created for the new hash, and the old extraction and Proposals are byte-for-byte unchanged.
8. **Summed N.** A Party with two kept documents of 2 and 2 Proposals at N = 3 is `proposals_extracted` (4). At N = 5 it is `excluded (too_few_proposals, 4 < 5)`.
9. **Refusals.** These are refused with nothing called or written: a format-1 bundle, a missing or out-of-date ledger, a non-imported document, a provider/model mismatch on resume, `--restart` on a complete extraction, and the shared DB without `--yes` on a non-interactive stdin. A discarded document is never extracted.
10. **Count check.** A ledger count changed through the ledger API to differ from the DB makes `ledger_count_problems`, `proposals status`, `data check` and `db check` report it (exit 1).
11. **Budget.** With `--max-calls 2` on a 5-chunk document, exactly 2 calls are made, the run prints the stop line and exits 0, and the next run continues at chunk 3.
12. **Migration and DB.** `0017` upgrades, downgrades and renders offline for PostgreSQL. The committed DB is at `0017`, `db check` says `Safe to commit: yes`, and the existing tables' content hashes are unchanged.

## Repository Research

Files inspected:
- `CONTEXT.md`, `docs/domain-model.md` (Proposal, phases, Excluded Party).
- `docs/risks-and-open-questions.md` (Constituency redesign).
- `CONSTRAINTS.md`, `ARCHITECTURE.md`.
- `docs/specs/ingestion-ledger.md`, `docs/specs/constituencies-and-candidatures.md`.
- `src/ideology_app/ingestion_ledger.py` (`record_extraction[_in_dir]`, `reconcile`, `Ledger.documents`, `state_label`, `out_of_date_problem`).
- `bundle_import.py` (`_find_election`, `candidatures_by_party`, `document_scopes`).
- `models.py` (`SourceDocument` unique `(party_id, content_hash)`, `bundle_file`, `_enum`).
- `migrations/versions/0016_*`.
- `topic_catalog.py` (`TOPIC_CATALOG`, 18 keys).
- `pipeline/checkpoint.py`, `generation.py` (`build_document_chunks`, page markers), `positions.py`, `prompts.py`, `quote_repair.py`.
- `validation/evidence_quotes.py` (`find_quote_miss`, `normalize_pages`, `normalize_for_match`).
- `llm/base.py`, `fake.py`, `__init__.py`, `claude_code_provider.py` (`max_tokens` → `CLAUDE_CODE_MAX_OUTPUT_TOKENS`).
- `cli.py` (`requires_db`, `_provider`, `_confirm_shared`, `db check`, `_bundle_and_run_checks`, `ingestion` group).
- `config.py` (`LLMSettings`, `DEFAULT_MODELS`), `tests/test_committed_database.py`, `init.sh`.
- `data/elections/es-general-2026-11-29/*.md` (page counts above).

Patterns to follow:
- Bounded cached schema builders (`_subclass`/`create_model`).
- Pinned prompt fingerprints.
- Per-call commits.
- `session_scope`.
- Non-native enums.
- `cli._provider()` as the test seam.
- `tests/bundle_factory.py` (`manifest_v2_text`, `DocumentSpec`) for format-2 bundles.
- `migrated_engine` / `--database-url` fixtures.

Gaps: no Proposal tables, no public way to find a bundle's Election, no phase-3 command.

## Expected File Changes

- `src/ideology_app/proposals/__init__.py`, `prompts.py` (spec, `Category`, `proposal_list_schema`, `proposal_request(chunk)`), `extraction.py` (pure: `Chunk`, `build_chunks`, `check_items`/dedupe, `CHECK_VERSION`, drop reasons), `store.py` (DB: get/create extraction, `extract_document(engine, provider, …)`, finalize, `load_proposals`, `ledger_count_problems`, status rows): create. Depends on `llm.base`, `topic_catalog`, `validation.evidence_quotes`, `pipeline.checkpoint.request_hash`, `models`, `db`, `ingestion_ledger`, `source_bundle`, `bundle_import`; never on a concrete provider.
- `src/ideology_app/models.py`: `ProposalExtraction`, `ProposalExtractionCall`, `Proposal`, `ProposalExtractionStatus`.
- `src/ideology_app/migrations/versions/0017_proposals.py`: create.
- `src/ideology_app/bundle_import.py`: public `find_election`.
- `src/ideology_app/cli.py`: `proposals` group; count check and info line in `db check` / `data check`.
- Tests: `tests/test_proposal_prompts.py`, `test_proposal_extraction.py` (pure), `test_proposal_store.py`, `test_cli_proposals.py`; `test_migrations.py` (0017), `test_committed_database.py` (Proposal tables empty), `test_cli_data.py` (count check).
- `data/ideology.db`: upgraded to `0017`, no rows added.

## Visual Design Impact

UI involved: no. No browser check (CLI and data only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add the `proposals` package, its dependency direction, the tables and the CLI commands.
- `CONSTRAINTS.md`: update with these rules:
  - Proposals and extraction calls are insert-only, except `--restart` on an `in_progress` extraction.
  - Proposals are written only by finalize, exactly as returned, with the strict check (P1).
  - A `proposal_extraction` prompt or schema change bumps its version and fingerprint.
  - No Party names in the prompt.
  - Phase 3 may read `Ledger.documents` through `read_ledger` + `reconcile`.
  - Extraction state is per content hash.
  - Exclusion side of the coverage handoff: exclusion goes only through the ledger counts.
- `AGENTS.md`: not needed.
- `CONTEXT.md` / `docs/domain-model.md`: one line each. Proposals are identified by the document content hash and reused across rows and Elections, and dropped reasons are recorded.
- `docs/technical-discovery.md`: add a "Proposal extraction" section (chunking, prompt, cost, P-defaults).
- `docs/risks-and-open-questions.md`:
  - Settle the cost/chunking entry with the estimate.
  - Settle the D1 and ledger-interface handoffs.
  - Change the hand-edit handoff: the helper exists and `db check` calls it; `statements-from-proposals` still calls it before a v2 run.
  - Add "Open, for team review (`proposal-extraction` defaults)" with P1–P10.
  - Add Open (`e2e-2026-constituencies`): measure the real drop rate and yield. If `not_found` drops are high, a repair check version is a follow-up.

## Implementation Plan

1. Models plus migration `0017`, with its tests. Upgrade a copy of the committed DB, then the real one.
2. `proposals/prompts.py` and the pinned fingerprint test.
3. `proposals/extraction.py` (chunking, check, dedupe) with pure tests.
4. `proposals/store.py` (resume, finalize, reuse, ledger handoff, count check) with FakeProvider tests.
5. CLI `proposals` group, plus the `db check` / `data check` additions, with CLI tests.
6. Docs, `feature_list.json`, `PROGRESS.md`.

## Implementation Tasks

- [ ] ORM models and `0017` (one CHECK per enum, page ≥ 1 CHECK, unique constraints); upgrade/downgrade/PG tests.
- [ ] `ProposalPrompt`, `Category` from `TOPIC_CATALOG`, cached `proposal_list_schema`, `proposal_request`; fingerprint pinned; test that no Party name or file name reaches the prompt.
- [ ] `build_chunks` (limit, context page, blank pages, oversized page) and `check_items` (five drop reasons, ordinals).
- [ ] `extract_document`: per-chunk hash reuse, per-call commit, mismatch refusal, `--restart`, `max_calls`, finalize transaction.
- [ ] Ledger handoff via `record_extraction_in_dir`, and `ledger_count_problems`.
- [ ] CLI `extract|status|list`, `_confirm_shared`, output lines; `db check` / `data check` problems and the info line.
- [ ] `bundle_import.find_election`.
- [ ] Upgrade `data/ideology.db` (with `db check` before and after, and existing-table hashes equal); update docs and evidence.

## Verification Plan

- `.venv/bin/python -m pytest tests/test_proposal_prompts.py tests/test_proposal_extraction.py tests/test_proposal_store.py tests/test_cli_proposals.py tests/test_migrations.py tests/test_committed_database.py tests/test_cli_data.py`: scenarios 1–12, all with `FakeProvider` (the autouse LLM guards stay on).
- Legacy unchanged: `tests/test_pipeline_*.py` and `tests/test_validation_*.py` pass untouched, and `PROMPT_VERSIONS` is unchanged.
- Committed DB: `cp data/ideology.db $TMP/c.db; DATABASE_URL=sqlite:///$TMP/c.db .venv/bin/ideology db upgrade && … db check` gives `Safe to commit: yes`. Then do the same on `data/ideology.db`. The SHA-256 of `sqlite3 -readonly` dumps of the pre-existing tables is equal before and after.
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology data check data/elections/es-general-2026-11-29` (and 2023) prints the same lines as before.
- `CI=true ./init.sh` passes. `init.sh` itself is unchanged (it runs pytest, starts no server).
- No E2E/browser: no user-visible or API change.

## Evidence To Capture

In `feature_list.json` and `PROGRESS.md`: the pytest counts, the `init.sh` result, the committed DB revision and the `db check` line, the equal pre/post table hashes, and the fact that no real LLM call was made.

## Validator Checklist

- [ ] Only `FakeProvider` in tests. No real extraction ran, and no Proposal rows are in `data/ideology.db`.
- [ ] Scenarios 1–12 pass. Resume and replay make exactly the stated number of provider calls.
- [ ] Proposals are stored exactly as returned. A misquote, an other-page item, a context-page item and a duplicate are dropped and reported.
- [ ] The ledger is written only via `record_extraction_in_dir`, and summed-N exclusion follows from it.
- [ ] `ledger_count_problems` is wired into `db check` / `data check`, and the handoff is recorded for `statements-from-proposals`.
- [ ] Legacy pipeline, prompts, `PROMPT_VERSIONS` and format-1 behaviour are unchanged.
- [ ] `0017` is applied to the committed DB, with `Safe to commit: yes`.
- [ ] The docs listed above are updated, the risks entries are settled or opened, and `feature_list.json` / `PROGRESS.md` hold the evidence.

# Feature Implementation Spec: Fictional dev dataset to run and test the app without real ingestion

## Source Feature

- `id`: dev-dataset
- `area`: data
- `depends_on`: public-dataset-api-v2 (accepted), statement-rewording (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json`
- Branch: `feature/dev-dataset`, cut from `feature/v2-run-inspection` (base `17baae1`, PR #134). Merged into `v2` by PR, after #129–#134.

## Goal

`ideology dev seed` builds a SQLite database holding one fictional format-2 Election, with no PDFs and no real LLM. The database is published and served by the public API. Every later web feature (`constituency-picker`, `questionnaire-length-and-context`, `share-link-v3`, `results-by-constituency`, `comparator-page`, `results-party-agreements`, `methodology-v2`) builds and browser-checks against it. The seed drives the **real** phases (import, Ingestion Ledger review, Proposal extraction, conflict detection and decision, `run-v2` with rewording, Validation, publishing) through a scripted fake provider, so it also exercises the whole v2 pipeline end to end. The same command gives the same database content every time.

## Non-Goals

- Any change to the pipeline, prompts, Validation, API, web client or `packages/`. If the seed exposes a pipeline bug, stop and report it. Do not work around it in the seed.
- Committing a dev database or the generated bundle. Touching `data/ideology.db` or `data/elections/`.
- Adding the scripted provider to `llm.PROVIDERS`. `LLM_PROVIDER` can never select it.
- A browser walk. There is no UI change. The current client cannot open a v2 version (see Visual Design Impact).
- `ingestion-guide` work (it may later reuse the generated bundle) and a PostgreSQL dev database.

## Job Story

When I build or check a web feature,
I want one command that gives me realistic, clearly fictional v2 data covering every Constituency case,
so I can work in the browser without real manifestos, LLM costs, or any risk to the shared database.

## Users And Permissions

- Developer / agent (local CLI): runs the seed against a dev file only. Voters never see this data in production.

## Decisions (defaults for team review)

- **D1 Where the content lives.** All dataset content lives in a committed Python package, `src/ideology_app/dev_dataset/`: Parties, documents (pages of prose with verbatim measures), Statements, stances, conflicts, the rewording and the Operator decisions. The seed **renders** the format-2 bundle from it at seed time: `election.toml`, canonical `.md` through `source_bundle.serialise_source_text`, `logos/*.svg` and `statement-rewordings.toml`. Rejected alternative: a committed bundle under `data/dev/` plus a separate answer script. Canonical `.md` files cannot be hand-edited (they carry `text_sha256`), and the measure texts would live in two files that can drift. Rejected alternative: direct inserts like `tests/api_v2_fixtures.py`. They are faster, but they skip the pipeline, so the data could hold states the real phases never produce, and they would duplicate every invariant. The rendered bundle stays on disk next to the database for inspection (`ideology data check`, `ingestion status`, `conflicts list`, `pipeline report`).
- **D2 Scripted provider.** `dev_dataset/provider.py` builds a `FakeProvider` (name `fake`, model `dev-dataset-1`) with one responder per task. The responders match the texts in the prompt (after `one_line`) against the content and never use prompt order or Party identity:
  - `proposal_extraction`: every content measure whose text is on a real `[página N]` section of the chunk, with that page, its categories and tags. Context pages are ignored.
  - `proposal_conflict_check`: the scripted contradiction pairs whose texts are in lists A and B, in either order.
  - `statement_drafts`: the category's scripted Statements not yet listed as `S<k>`, each citing the listed Proposals that hold a stance on it. No additions. One slice per category.
  - `proposal_positions`: for each listed Statement, the listed Proposals with a stance on it. Value = their common value, Evidence = the first 5. No stance when there is none. Values of mixed sign raise `LLMOutputError` (a content bug).
  - `statement_rewording_check`: the scripted verdict for the new text.
- **D3 Determinism.** The seed:
  - starts from an empty file;
  - reads no environment configuration other than the database target. It uses `ValidationSettings()`, `ConstituencySettings()`, `GenerationMode.PRECOMPUTED` and its own provider;
  - processes everything in content order;
  - as its last write, sets every `DateTime` column of the main schema to the fixed instant `SEED_INSTANT = 2031-05-01T10:00:00Z`. These are wall-clock audit fields, not AI output. Nothing orders by them.
  
  "Same content" means the same SHA-256 of the logical dump (`sqlite3` `iterdump`, joined with `\n`) and the same bytes for every rendered bundle file, including `ingestion-ledger.json`. The command prints the hash. No golden hash is committed: it would break on every unrelated prompt bump. The tests compare two seeds instead.
- **D4 Target and guard.** The target is the global `--database-url` / `DATABASE_URL` when either is given, else `sqlite:///data/dev/dev.db`, relative to the current directory. `.gitignore` gains `data/dev/`. The seed refuses, with exit 1 and before any write (no file, directory or temp created), when:
  - (a) the URL is not a SQLite file URL (server backend, in-memory, unparsable): "the dev dataset is built only in a SQLite file";
  - (b) it resolves to `config.SHARED_DATABASE_PATH`, or is the same file through a symlink or hard link (as `feedback.store.check_separate`);
  - (c) its file name is `ideology.db`. This covers the shared file, the CLI default, and the production container's `DATABASE_URL=sqlite:////app/data/ideology.db`. "Production configuration" in this feature means exactly (a) and (c);
  - (d) the file exists and is not a dev-seed database. A dev-seed database has exactly one Election, with the dev country, type, date and name, read through `shared_db.read_only_url`;
  - (e) the bundle directory exists and holds anything other than the dev slug's bundle.
  
  A developer with `DATABASE_URL=sqlite:///data/ideology.db` exported is therefore refused. The message says to unset it or point it at the dev file.
- **D5 Build and swap.** The seed builds into a temporary sibling directory, `.<stem>-seed-tmp/`, holding the database and the bundle. It then runs a self-check: run `passed`, version published, `check_against_bundle` and `ledger_problems` empty, every scenario-1 invariant. Only after the self-check passes does it `os.replace` both into place: `<dir>/<stem>.db` and `<dir>/<stem>-bundle/<slug>/`. On any failure the old database and bundle stay untouched and the temporary directory is removed. A server that is already running keeps the old file open until it restarts.
- **D6 init.sh does not run the seed.** pytest already covers it. `init.sh` only prints two hint lines after `All checks passed.`. The seed runs in a few seconds, so agents run it before each browser check.
- **D7 Running the app.** The new `.claude/launch.json` entry `web-dev-db` runs uvicorn on port 8002 with `DATABASE_URL=sqlite:///data/dev/dev.db`. The README documents the command (`DATABASE_URL=sqlite:///data/dev/dev.db .venv/bin/uvicorn ideology_app.main:app --port 8002`). `AGENTS.md` (Browser Validation) names the dev dataset as the default data for browser checks of v2 features.
- **D8 Names.** Every Party is named after a mineral, with invented names and acronyms. The Election is "Elecciones generales ficticias (datos de desarrollo)" on 2031-05-18, a Sunday. Each manifesto's first page opens with "Programa electoral ficticio de <name>, creado para el conjunto de datos de desarrollo de IdeologiApp. No corresponde a ningún partido real." A test denylist (Scenario 6) rejects real Spanish party names and acronyms in every rendered text. Statements are plausible, neutral policy propositions in Spanish.
- **D9 Coverage beyond the brief.** Two additions:
  - A third Excluded reason, `discarded_at_review` (`PIZARRA`), so `results-by-constituency` can show all three reason codes.
  - One Party without a logo (`ZAFIRO`), so the logo fallback is exercised.
  
  `min_proposals` stays at the default 30.

## Dataset Content

Election `ES` / `general` / 2031-05-18. `[candidatures] source = "Candidaturas ficticias del conjunto de datos de desarrollo"`, no `url`.

| Party (short / name) | Runs in | Documents (`[[documents]]` order) | Outcome |
|---|---|---|---|
| `CUARZO` Partido Cuarzo | all 52 | `cuarzo.md` (`source_url` `https://example.org/ideologiapp-dev/cuarzo.pdf`) | Extracted |
| `JADE` Movimiento Jade | all except 15, 27, 32, 36, 51, 52 | `jade.md` (listed for `JADE`, `TURQUESA`; URL) | Extracted |
| `ONIX` Unión Ónix | all except 08, 17, 25, 43, 52 | `onix.md` (listed for `ONIX`, `ONIX-CAT`; URL) | Extracted |
| `ONIX-CAT` Ònix Catalunya | 08, 17, 25, 43 | `onix.md` + `onix-cat.md` | Extracted; overlap **decided**: `onix-cat.md` prevails over `onix.md` (one contradiction, reason recorded) |
| `ZAFIRO` Confederación Zafiro (no logo) | all except 51, 52 | `zafiro.md` (no `source_url`) | Extracted |
| `TURQUESA` Coalición Turquesa | 15, 27, 32, 36 | `turquesa.md` (`joint_for = ["TURQUESA"]`) + `jade.md` | Extracted; overlap **joint_manifesto** (one contradiction, joint wins) |
| `BASALTO` Bloque Basalto | 08 | `basalto.md` | Extracted |
| `MICA` Partido Mica | 28 | `mica.md` (about 6 measures) | Excluded `too_few_proposals` |
| `GRAFITO` Agrupación Grafito | 51, 52 | none; `ingestion no-manifesto` with a note | Excluded `no_manifesto` |
| `PIZARRA` Candidatura Pizarra | 52 | `pizarra.md` (an index page only) reviewed `discarded` / `incomplete` | Excluded `discarded_at_review` |

Every Extracted Party has at least 30 counted Proposals. Each measure has one main category and stances only on Statements of that category. Each document fits one extraction chunk (≤ 12,000 characters).

Targets. The realised numbers are pinned in the tests and listed in the README:

- **Pool**: ≥ 55 Statements over ≥ 10 categories. Each has a Context Note (30–300 characters, no evaluative word).
- **Typical Constituencies** (e.g. 28, 01; CUARZO, JADE, ONIX, ZAFIRO): n between 41 and 49, not a multiple of 5.
- **Galicia** (15/27/32/36): n differs from the typical value. **08 Barcelona** (adds BASALTO): n between 50 and 59, not a multiple of 5. **51 Ceuta** (CUARZO vs ONIX): n between 10 and 19, so it offers `[n]` (`Todas`).
- **52 Melilla**: unavailable, `fewer_than_two_parties`. All other 51 Constituencies are available.

Authoring guide:

- About 14 Statements split CUARZO and ONIX. They are valid wherever both run.
- About 29 more are split only by JADE or ZAFIRO.
- About 10 have the four national Parties on one side and BASALTO on the other.
- About 3 depend on `turquesa.md`.
- The decided contradiction must change ONIX-CAT's value on one Statement compared with ONIX.

**Rewording**: `statement-rewordings.toml` has one entry for a Statement that is valid in 28 and 08. The verdict is `equivalent: true`, so the entry is `applied`.

**Logos**: generated, passive SVG, 64×64 viewBox. Each is a muted rounded square with a white geometric crystal mark, unique per Party. They contain no `<text>` and no real-party symbol or colour scheme, and each is ≤ 1 KB.

## Acceptance Scenarios

Tests use a session-scoped seed into `tmp_path_factory` (absolute paths; `conftest` chdirs per test), with the socket guard of `tests/test_llm.py`.

### S1: every case is present
Given a fresh seed
When the database is read
Then:
- the Election, Parties and candidatures match the table;
- `dataset_version_candidatures` carries the three Excluded reasons;
- the ledger shows TURQUESA `joint_manifesto` and ONIX-CAT `decided`, with `prevails = onix-cat.md`, the reason, and ≥ 1 contradiction each;
- the set-aside Proposal is absent from ONIX-CAT's `dataset_version_proposals`, but ONIX keeps it;
- one `statement_rewordings` row is `applied`;
- the per-Constituency n, availability and reasons meet the targets;
- the run is `passed`, `llm_provider = fake`, the version is published and the Election is `active`;
- every Party except ZAFIRO has an SVG logo.

### S2: the API serves it
Given the seeded database
When `TestClient(main.app)` runs with `DATABASE_URL` on it
Then:
- `/api/v1/elections` lists one Election, `published_dataset_version_generation = "v2"`;
- `…/constituencies` has 52 rows (52 unavailable with its reason, 51 with `offered_lengths == [n]`, 08 includes 50);
- `…/constituencies/28` serves n Statements with Context Notes, including the reworded text, and lists MICA under `excluded_parties`;
- `…/constituencies/52` answers 200 with empty Statements;
- `…/constituencies/08/proposals/<category>` lists Parties with Proposals;
- `/api/v1/parties/{id}/logo` answers `image/svg+xml`.

### S3: deterministic
Given two seeds into two different directories, the second one with `LLM_PROVIDER=anthropic`, `GENERATION_MODE=live`, `VALIDATION_V2_MIN_STATEMENTS=99` and `VALIDATION_MIN_STATEMENTS=1` set
When their dump hashes and bundle files are compared
Then they are identical.
And re-seeding over an existing dev database gives the same hash.

### S4: refuses the shared database and production configuration
Given each of the following targets:
- `sqlite:///data/ideology.db` (in a tmp cwd holding `data/ideology.db`);
- a symlink and a hard link to it;
- `sqlite:////somewhere/ideology.db`;
- `postgresql://u@h/db`;
- `sqlite://`;
- an existing non-dev SQLite file;
- a bundle directory with a foreign entry.
When `ideology dev seed` runs
Then it exits 1 with an `Error:` line naming the rule.
And no file or directory is created or modified (hashes and listings before and after).
And the repository's real `data/ideology.db` SHA-256 is unchanged after a refusal aimed at its absolute path.

### S5: failure leaves the previous data
Given a seeded dev database
When a reseed fails mid-way (the test monkeypatches the provider to raise)
Then it exits 1, the old database and bundle are byte-identical, and no temporary directory remains.

### S6: fictional only
Given every rendered text (manifesto pages, names, Statements, notes, rewording, conflict explanations and reason, ledger note)
When it is checked against the denylist of real party names and acronyms (whole word; acronyms case-sensitive)
Then nothing matches: PP, PSOE, PSC, Vox, Sumar, Podemos, ERC, Esquerra, Junts, PNV, EAJ, Bildu, BNG, Coalición Canaria, CC, UPN, PACMA, Ciudadanos, Cs, IU, Izquierda Unida, Más País, Más Madrid, Compromís, CUP, Teruel Existe, Nueva Canarias, PRC, Foro, Geroa Bai, SALF, Se Acabó La Fiesta, Partido Popular, Partido Socialista, Partido Animalista.

### S7: content self-consistency
`dev_dataset.content.check()` returns no problems. It checks that:
- measure texts are unique and each is verbatim on its page;
- every stance targets a Statement of the measure's category, and every Statement has ≥ 1 stance;
- Statement texts are unique under `normalize_for_match`, and notes are valid;
- the 52 codes are covered.

### S8: CLI output
`ideology dev seed` prints the target, the bundle directory, `Election 1`, the run and dataset version ids, the pool size, `Constituencies: 51 available, 1 unavailable`, the realised n for 08, 28, 15 and 51, `Dump SHA-256: <hex>`, and the start command. It exits 0.

## Repository Research

### Files Inspected

- `src/ideology_app/source_bundle.py`: format 2, `joint_for`, slug `es-general-<date>` checked against the directory name, logo rules, `serialise_source_text`.
- `src/ideology_app/bundle_import.py`: the `import_bundle` service. D4 coverage problems: every code needs a candidature.
- `src/ideology_app/ingestion_ledger.py`: `update_in_dir`, `review_in_dir`, `no_manifesto_in_dir`, `decide_conflict_in_dir`, `ledger_problems`. The ledger lives beside `election.toml`, has no clock, and its bytes are canonical.
- `proposals/store.py`: `prepare_extraction` and `execute_plan`. `proposals/conflicts.py`: `detect`, and `counted_proposals`, which omits a Proposal left with no Constituency. `proposals/prompts.py` and `proposals/extraction.py`: the `[página N]` markers, the context page, 12,000-character chunks. `proposals/conflict_prompts.py`: lists A and B.
- `pipeline/v2/` (`run.py`, `gate.py`, `pool.py`, `positions.py`, `prompts.py`, `rewording.py`, `selection.py`), `constituency_rules.py` (K1–K10, `OFFERED_LENGTHS`), `validation/__init__.py` (`V2_CHECKS`), `statement_uniqueness.py`, `context_note.py`.
- `pipeline/publishing.py`: publishing sets the Election `active`. `models.py`: the `_utcnow` defaults and the `DateTime` columns.
- `api/routes.py`, `api/queries_v2.py`: the v2 routes.
- `config.py`: `SHARED_DATABASE_PATH` and the env readers. `shared_db.py`: `is_shared`, `sqlite_path`, `read_only_url`. `feedback/store.py`: the same-file check. `cli.py`: the `main` group, `requires_db`, `run-v2`. `Dockerfile`: the production `DATABASE_URL`.
- `llm/__init__.py`, `llm/fake.py`. `tests/v2_fixtures.py`, `proposal_fixtures.py`, `conflict_fixtures.py`, `bundle_factory.py`, `logo_factory.py`, `api_v2_fixtures.py`, `test_llm.py` (socket guard).
- `.claude/launch.json`, `.gitignore`, `init.sh`, `README.md`.
- `apps/web/src/features/landing/LandingPage.tsx`, `questionnaire/useQuestionnaireData.ts`.
- `docs/risks-and-open-questions.md`: the "Constituency redesign" section.

### Existing Patterns To Follow

- The seed orchestration mirrors `tests/v2_fixtures.setup` (write → `import_bundle` → `update_in_dir` → reviews → extract → `no_manifesto_in_dir` → `conflicts.detect` → `decide_conflict_in_dir`). It then runs `load_phase4` → `queue_v2_run` → `execute_v2_run`, the same as `cli.pipeline_run_v2`, but with explicit default settings.
- Prompt-parsing responders follow `tests/v2_fixtures.py` (`_PROPOSAL_RE`, `_STATEMENT_RE`, `_PREVIOUS_RE`, `Nueva redacción:`). Move or share parsing only inside `dev_dataset`; tests keep their own.
- CLI errors go through `click.ClickException` (`Error: …`, exit 1). Path refusals follow `feedback.store.check_separate`.

### Current Gaps

- No `dev` command group, no dev database path, no fixed clock. Timestamps come from `models._utcnow` defaults; D3 resolves this.
- `import_bundle` does not queue live runs (only `cli.data_import` does), so the seed must call the service.

## Technical Approach

`dev_dataset/` package:

- `__init__.py`: `seed(url: str) -> SeedReport`, `SeedError`.
- `content.py`: frozen dataclasses (`DevParty`, `DevDocument`, `DevPage`, `DevMeasure`, `DevStatement`, `DevConflict`, `DevDecision`) plus `check()`. It may be split per Party under `content/`.
- `bundle.py`: renders the bundle into a directory.
- `logos.py`: deterministic SVG strings.
- `provider.py`: D2.
- `guard.py`: D4. Pure apart from `stat`/`samefile` and a read-only open.
- `dump.py`: timestamp normalisation and `dump_sha256(path)`.

Seed steps:

1. Run the guard.
2. Create the temporary directory and render the bundle.
3. `run_migrations(url_of_tmp_db)`.
4. `import_bundle` in one `session_scope`.
5. `update_in_dir` and the reviews in content order (all `kept` except `pizarra.md`).
6. Extract with the provider.
7. `no_manifesto_in_dir("GRAFITO", note=…)`.
8. `conflicts.detect`, then `decide_conflict_in_dir("ONIX-CAT", prevails="onix-cat.md", over="onix.md", reason=…)`.
9. `load_phase4`, `read_rewordings`, `queue_v2_run(generation_mode=PRECOMPUTED, llm_provider="fake", llm_model="dev-dataset-1")`, `execute_v2_run(..., ValidationSettings(), ConstituencySettings())`.
10. Self-check.
11. Normalise timestamps.
12. Dispose the engine, then swap into place.

Any service exception becomes `SeedError` with the step name. CLI: `@main.group() dev` + `dev seed`, no `requires_db`. It reads the root context's raw `database_url` param to apply the D4 default.

Speed budget: about 8 extraction, ≤ 40 conflict, ≤ 20 draft, ≤ 120 position and 1 rewording call. Target < 10 s per seed on a laptop, and < 30 s added to pytest (one session seed plus one for S3 and one for S5).

## Expected File Changes

- `src/ideology_app/dev_dataset/{__init__,content,bundle,logos,provider,guard,dump}.py`: create.
- `src/ideology_app/cli.py`: modify. Add the `dev` group and `dev seed`.
- `tests/test_dev_dataset.py` (S1, S3, S5–S8), `tests/test_dev_dataset_guard.py` (S4), `tests/test_dev_dataset_api.py` (S2): create.
- `.gitignore` (`data/dev/`), `.claude/launch.json` (`web-dev-db`), `init.sh` (2 hint lines): modify.
- `README.md` ("Datos de desarrollo": the command, the start command, the table of realised n, and what the Landing shows until `constituency-picker`): modify. Also modify `docs/technical-discovery.md` (Testing and Verification), `ARCHITECTURE.md`, `CONSTRAINTS.md` and `AGENTS.md`.
- `docs/risks-and-open-questions.md`, `feature_list.json`, `PROGRESS.md`: modify.

## Visual Design Impact

- UI involved: no. Design source: not applicable. No new design artifact.
- What the current client shows on the dev database: the Landing lists the fictional Election with "Realizar cuestionario". Opening it gives the questionnaire's generic error, because `useQuestionnaireData` gets `404 dataset_version_is_v2` (handoff recorded for `constituency-picker`). This is expected. Record it in the README and do not fix it here.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. New "Dev Dataset" section: the package, its dependency direction (it uses services, nothing imports it except `cli`), and that the scripted provider is not in `PROVIDERS`.
- `CONSTRAINTS.md`: update. New "Dev Dataset" rules:
  - the seed never targets the shared database or an `ideology.db` / non-SQLite URL;
  - it reads no env config but the target;
  - content is fictional and passes the denylist;
  - the dev provider is never registered;
  - dev data is never imported into the shared database or production.
- `AGENTS.md`: update (Browser Validation). The dev dataset (`ideology dev seed`, launch `web-dev-db`) is the default data for v2 browser checks unless a spec says otherwise.
- `README.md`, `docs/technical-discovery.md`: update as listed above.
- `docs/risks-and-open-questions.md`:
  - turn the "Decided: a fictional dev dataset…" bullet into Settled (`dev-dataset`), clarifying that the version is published only inside the dev database;
  - add "Open, for team review (`dev-dataset` defaults)" with D1–D9.

## Implementation Plan

1. Write the guard and the CLI skeleton, with the S4 tests, before any write path exists.
2. Write the content model, `check()`, logos and bundle rendering. Test that the rendered bundle passes `read_bundle` and that `check()` passes.
3. Write the scripted provider, with unit tests per responder on hand-built requests from the real request builders.
4. Write the seed orchestration, self-check, normalisation and swap.
5. Author the content to the targets. Iterate with `ideology --database-url sqlite:///data/dev/dev.db pipeline report --run 1` (the 52-row table).
6. Write S1–S3, S5–S8 and pin the realised numbers.
7. Update the docs, launch entry, `.gitignore` and `init.sh` hints. Run the API smoke and the full gate.

## Implementation Tasks

- [ ] `guard.py` with refusals a–e. CLI `dev seed`. S4 tests.
- [ ] `content.py` (+ `check()`), `logos.py`, `bundle.py`. S7, plus a `read_bundle` test.
- [ ] `provider.py` responders and their unit tests.
- [ ] `seed()` steps 1–12, `SeedError`, the build-and-swap. S5.
- [ ] Author ~10 manifestos, ≥ 55 Statements with notes, stances, 2 contradictions, the decision and the rewording. Meet the targets.
- [ ] `dump.py`. S3, with a different cwd and env per seed.
- [ ] S1, S2, S6, S8.
- [ ] `.gitignore`, `launch.json`, `init.sh` hints, README, ARCHITECTURE, CONSTRAINTS, AGENTS, technical-discovery, risks.

## Verification Plan

- `.venv/bin/python -m pytest tests/test_dev_dataset*.py -q`, then `CI=true ./init.sh` (expect `All checks passed.`; `init.sh` still starts no server and does not seed).
- Run twice from the repo root: `.venv/bin/ideology dev seed`. Expect exit 0 and the same `Dump SHA-256`. `git status` shows no change under `data/`. `shasum -a 256 data/ideology.db` is unchanged.
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology dev seed` exits 1 with nothing written.
- API smoke: start `DATABASE_URL=sqlite:///data/dev/dev.db .venv/bin/uvicorn ideology_app.main:app --port 8002` (or launch `web-dev-db`) and `curl`:
  - `/health` gives 200;
  - `/api/v1/elections` gives one v2 Election;
  - `/api/v1/dataset-versions/{id}/constituencies` gives 52 rows;
  - `…/constituencies/08`, `/28`, `/51` and `/52` give the pinned counts;
  - `…/constituencies/28/proposals/housing` gives 200;
  - `/api/v1/parties/{id}/logo` gives `image/svg+xml`.
- Optionally, open `/` in a browser to confirm the Landing card and the expected generic error. This is not a validation requirement: there is no UI change.
- No persistent E2E harness for the API exists beyond pytest. The S2 `TestClient` test covers the API flow.

## Evidence To Capture

- Test counts, `init.sh` result, the two equal dump hashes, the realised n table, the refusal output for the shared URL, the unchanged `data/ideology.db` hash, and the curl results. Record them in `feature_list.json` `evidence` and `PROGRESS.md`.

## Validator Checklist

- [ ] Only `dev_dataset/`, `cli.py` (dev group), tests, docs, `.gitignore`, `launch.json` and `init.sh` hints changed. No pipeline, API, web or `packages/` change.
- [ ] The seed runs the real phases (no direct inserts of Proposals, Statements, Positions or Dataset Versions). No real LLM or socket. The provider is not in `PROVIDERS`.
- [ ] S1–S8 pass. The re-seed hash is stable. Refusals write nothing. `data/ideology.db` and `data/elections/` are untouched.
- [ ] No real party name appears anywhere (S6), and logos are passive SVG.
- [ ] The app starts on the dev database and the API smoke matches the pinned numbers.
- [ ] Docs and the risks entry are updated. `feature_list.json` and `PROGRESS.md` hold the evidence.

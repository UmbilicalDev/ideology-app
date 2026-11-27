# Feature Implementation Spec: Guided ingestion procedure for Operators (phases 1-4)

## Source Feature

- `id`: ingestion-guide
- `area`: ops
- `depends_on`: statement-rewording (accepted), v2-run-inspection (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json`
- Branch: `feature/ingestion-guide`, cut from `feature/dev-dataset` (base `43ad557`, PR #135). Merged into `v2` by PR, after #129–#135.

## Goal

An Operator can take an Election from nothing to a published v2 Dataset Version, and fix confusing Statements later, by following one procedure. At every point the procedure says what data is missing, in which file, in which format, and the exact command to run next. It resumes where the last session stopped, because it derives the position from the committed files and the database, not from memory.

There are three parts, all derived from one source of truth:

1. **`ideology ingestion next DIR`**: a new read-only command. It looks at the bundle, the Ingestion Ledger and the database, and prints the first pending step: phase, step code, what is missing, file, format, command, LLM spend and shared-database impact.
2. **`docs/ingestion-guide.md`**: the Operator runbook in Spanish, plus the template `docs/templates/election-format-2.toml`.
3. **`.agents/skills/ingestion-guide/SKILL.md`**: a project skill. The agent loops on `ingestion next`, asks the Operator for exactly the data listed and runs only allowed commands. It never invents data, never edits AI output, and gets explicit approval before any LLM spend.

## Non-Goals

- Converting the committed 2026 bundle to format 2, entering real BOE candidatures, or any real extraction or run (`e2e-2026-constituencies`).
- New write commands, such as an `ingestion init` that writes the template. Changes to ledger, extraction, conflict, run-v2 or rewording behaviour, prompts, migrations, API or UI.
- Detecting that a published v2 version is older than later changes in phases 1–3 while the gate is open (G10). Only a rewording file change is detected.
- A subagent wrapper (G3), a `--json` output (G9), and automatic git actions.
- Changes to `data/ideology.db`, `data/elections/`, `data/dev/` or `init.sh`.

## Job Story

When I ingest a new Election, or come back to one after days,
I want to be told the next step, the data it needs, where it goes and in what format,
so I can finish phases 1–4 without rereading every runbook and without spending LLM money by accident.

## Users And Permissions

- Operator: runs `ingestion next` and every command, decides every review, conflict, exclusion and rewording, and approves every LLM spend and shared-database write.
- Agent following the skill: reads and suggests. It runs non-LLM commands after telling the Operator. It runs LLM commands only after explicit approval in the conversation (G6). It never commits.

## Decisions (defaults for team review)

- **G1 Language.** The guide is in Spanish, like README's Operator sections ("Ejecutar el pipeline a mano"), because its readers are the Operators. CLI terms and domain terms stay in English, as in README. The skill is in English, like every other `.agents/skills/*`, because it instructs an agent; it talks to the Operator in the Operator's language. `ingestion next` output is in English, like every CLI line. The technical detail stays in `docs/technical-discovery.md`; the guide links to it instead of copying it.
- **G2 A command, not skill reasoning.** `ingestion status` cannot do the job alone:
  - it fails on a missing directory, a missing manifest or an invalid manifest (the empty-Election case);
  - it never reads the database (import state, extraction progress, runs, rewordings);
  - its `next:` text is per Party, not per step.
  
  If the skill combined five commands' output by itself, the result would be untestable and agent-dependent. `ingestion next` is deterministic and pytest-covered. Humans can use it without an agent, and the skill and the guide share its step codes.
- **G3 Skill only, no `.claude/agents/ingestion-guide.md`.** The guide is a conversation: it asks for data and approvals. A subagent cannot talk to the Operator, and its report is never consent. The skill runs in the Operator's main session. It is invoked as in the rest of the repo: "Use $ingestion-guide on data/elections/<slug>", which reads `.agents/skills/ingestion-guide/SKILL.md`. It also gets `agents/openai.yaml` like its siblings.
- **G4 Who writes `election.toml` and `statement-rewordings.toml`.** The agent may write entries only from values the Operator gave in the conversation, or from a file the Operator named (e.g. a CSV they made from the BOE). It shows the diff, and the Operator confirms it against the source. It never fills candidatures, Constituencies, names or manifesto URLs from its own knowledge or a web search. Rejected alternative: the Operator always edits by hand. That is safer but slow for 52 Constituencies; the team may still choose it.
- **G5 Operator-only content.** The agent never proposes or chooses any of these:
  - a review decision or discard reason;
  - a `no-manifesto` note;
  - a conflict winner or reason;
  - N (`--min-proposals`);
  - `--fresh` or `--restart`;
  - a rewording's `text` or `reason`.
  
  It may show objective facts: page and character counts, `conflicts show`, `pipeline statements` output. It passes the Operator's words to the command verbatim. The rewording `ai_text` is copied exactly from `pipeline statements` output.
- **G6 LLM spend.** Before each LLM invocation (`proposals extract`, `conflicts detect`, `pipeline run-v2` including a rewording replay), the agent states the provider and model, the planned calls from `ingestion next`, and the guide's cost band. It asks "¿Apruebo el gasto?" and waits for an explicit yes in that turn. Approval covers one invocation. Bounded invocations may run in the agent session after approval: `proposals extract --max-calls K`, `conflicts detect --max-calls K`, and a `run-v2 --reuse-from R` replay whose planned new calls are only rewording checks. A full `run-v2` takes 3–5 hours on `claude_code`, so the agent prints its exact command for the Operator to run in their own terminal (`caffeinate -is …`, tee to `$HOME/ideology-logs/`).
- **G7 Shared database.** Before any write to `data/ideology.db` (`db upgrade`, `data import`, `proposals extract`, `run-v2`), the agent asks the Operator to confirm three things:
  - `git status --short` is clean and they pulled;
  - nobody else is generating (one active run at a time, any Election);
  - no `ideology` process or server has the file open.
  
  Only then does it pass `--yes` where the command needs it: a non-interactive shell refuses without it, and the confirmation it replaces was just given. After writing, it runs `db check` and tells the Operator what to commit (bundle files, ledger, `data/ideology.db`) and when. It never runs `git pull`, `commit` or `push`.
- **G8 Template.** `docs/templates/election-format-2.toml` uses **unquoted** placeholders (`short_name = <<SIGLAS>>`). An unfilled template is invalid TOML, so `data import` and every reader refuse it. `next` lists every placeholder line before parsing. The template comment says each value is written quoted (`"PP"`).
- **G9 `next` output.** Fixed `Key: value` lines, exit 0 for every derived step including `done`. `ingestion gate` stays the gate. No `--json`.
- **G10 Not detected.** When the gate is open and a v2 version exists, `next` cannot tell whether inputs changed after that run (e.g. a re-decided conflict). It says `done`. The guide says: after any change in phases 1–3, run `run-v2 DIR` again.
- **G11 Order.** Bundle and ledger steps (phases 1–2) come before any database step, so phases 1–2 work without a database. The import is the first step of phase 3 (the phase-3 runbook already puts `data import` there).

## Acceptance Scenarios

### Scenario 1: empty Election

Given `DIR` does not exist
When the Operator runs `ideology ingestion next DIR`
Then it prints step `create-bundle-directory`, the expected directory name pattern (`<country>-<type>-<date>`, e.g. `es-general-2030-06-02`) and the command `mkdir -p DIR && cp docs/templates/election-format-2.toml DIR/election.toml`
And it creates no file, no directory and no database file.

### Scenario 2: unfilled template

Given `DIR/election.toml` is the copied template
When `next` runs
Then step `fill-manifest-placeholders` lists every `line N: <<…>>` of the template, and the format line explains `[candidatures]`, `[[parties]]` (`"all"` or INE codes; see `ideology constituency list`) and `[[documents]]`.

### Scenario 3: candidatures incomplete

Given a valid format-2 manifest with no candidature in 51 and 52
When `next` runs
Then step `declare-candidatures` lists `51 Ceuta` and `52 Melilla`, the file `election.toml` (`[[parties]] constituencies`) and the source (the BOE proclamation).

### Scenario 4: phases 2 and 3 in order

Given candidatures are complete
When the Operator follows `next` repeatedly
Then the steps come in this order, each with the file and the command:
- `provide-manifestos` (per Party: `source extract PDF --party SHORT --out DIR/<file>.md --url URL` plus a `[[documents]]` entry, or `ingestion no-manifesto DIR SHORT --note …`)
- `update-ledger`
- `review-manifestos` (per file: parties, pages, pages without text, characters; `ingestion review DIR FILE --keep|--discard …`)
- `create-database` or `upgrade-database` when needed
- `import-bundle`
- `extract-proposals`
- `check-conflicts`
- `decide-conflicts`
- `generate-statements`

And no step is skipped while its condition holds.

### Scenario 5: LLM steps show the spend

Given kept documents not yet extracted
When `next` runs
Then step `extract-proposals` prints `LLM: yes`, the provider and model (from the environment, or the pinned ones of an in-progress extraction), the exact number of remaining chunk calls, and a pointer to the guide's cost table
And it builds no provider and makes no call.
The same applies to `check-conflicts` (overlap count) and `generate-statements` (`plan_calls`).

### Scenario 6: resume an unfinished run

Given the Election's latest v2 run with recorded calls is `failed` or `running` with no Dataset Version
Then step `resume-run` prints `pipeline run-v2 DIR --resume-from R` with that run's provider and model, plus the `running` warning (it may be active on another machine).

### Scenario 7: validation failed

Given the latest finished v2 run failed with a Dataset Version
Then step `read-failed-run` prints the failure reason and `pipeline checks --run R` / `pipeline report --run R`.

### Scenario 8: done, and rewording

Given a published v2 version whose run recorded the current `statement-rewordings.toml` SHA-256 (or both have none)
Then step `done` prints the Dataset Version, run, Constituency summary and rewording summary, lists every non-applied rewording, and gives `pipeline report --run R`, `db check` and the rewording file format
When the file is added, edited or removed
Then step `reword-statements` prints `pipeline run-v2 DIR --reuse-from R` and the planned new calls (one per entry).

### Scenario 9: read-only, no LLM

Given any state, including the shared database
When `next` runs
Then:
- the bundle, the ledger and the database bytes are unchanged;
- a SQLite database is opened only with `mode=ro`;
- a missing SQLite file is not created;
- `cli._provider` is never called.

### Scenario 10: skill dry runs

The skill dry runs follow the scripts in the Verification Plan. In each, the agent asks only for the listed data, writes only the listed files, and stops at the first approval when the Operator says no.

## Repository Research

### Files Inspected

- `src/ideology_app/cli.py`:
  - commands: `ingestion status|update|review|no-manifesto|gate` (no database), `data import|check`, `proposals extract|status|list`, `conflicts detect|list|show|decide`, `pipeline run-v2|report|statements|positions`, `db check`, `dev seed`, `source extract`;
  - helpers: `_confirm_shared`, `SHARED_PROMPT`, `_guard_unfinished`, `requires_db`, `_provider`;
  - `conflicts detect` has no `--yes` or confirmation: it writes only the ledger and reads the database.
- `src/ideology_app/ingestion_ledger.py`: `read_ledger`, `reconcile`, `render_ledger`, `party_states`, `next_step`, `pending_conflicts`, `phase4_blockers`, `ConflictStatus`.
- `src/ideology_app/source_bundle.py`: `read_bundle` errors. A format-2 bundle needs `[candidatures]` and at least one party.
- `src/ideology_app/bundle_import.py`: `check_against_bundle`, `_coverage_problems` (bundle-only D4).
- `src/ideology_app/proposals/store.py`: `status_rows` (chunks per kept document, even `not_started`), `ledger_count_problems`, `read_phase3`.
- `src/ideology_app/pipeline/v2/gate.py` (`load_phase4`), `run.py` (`plan_calls`, `MAX_V2_CALLS_PER_RUN`), `rewording.py` (`read_rewordings`; the run records `statement_selection["rewordings"]["sha256"]`).
- `src/ideology_app/pipeline/runs.py`: `find_unfinished_run(session, election_id, generation=V2)`.
- `src/ideology_app/shared_db.py` (`sqlite_path`, `is_shared`, `read_only_url`, `MISSING_SHARED`) and `db.py` (`head_revision`).
- `tests/conftest.py` (`dev_seed` session fixture: "copy it first"), `tests/bundle_factory.py` (`write_bundle_v2`), `tests/dev_dataset_fixtures.py` (`snapshot`), `tests/test_cli_proposals.py`, `test_cli_conflicts.py`, `test_cli_pipeline_v2.py` (fake-provider fixtures), `tests/pdf_factory.py`.
- `data/dev/dev-bundle/es-general-2031-05-18/`: `ingestion status` gives 7 extracted and 3 excluded (one per reason), 2 conflicts (decided and joint), and Phase 4 ready. `data/dev/dev.db` has run 1 passed, Dataset Version 1 published, and 1 rewording applied.
- `.agents/skills/*/SKILL.md` + `agents/openai.yaml` and `.claude/agents/*.md` (thin wrappers that point at a skill).
- Docs: `docs/technical-discovery.md` (runbooks and cost estimates per phase), `README.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `CONTEXT.md`.

### Existing Patterns To Follow

- Read-only database access as in `db check`: `make_engine(shared_db.read_only_url(path))`, `MigrationContext` for the revision, `Session` + `rollback`, `engine.dispose()` in `finally` (CONSTRAINTS: dispose every Engine).
- `ingestion status` detects a missing or out-of-date ledger with `reconcile` + `render_ledger` comparison.
- CLI tests use `CliRunner` with `--database-url` on tmp SQLite files, plus `offline_guard`.

### Risks-doc entries addressed

- "Open (handoff, `ingestion-guide` …)": `ideology ingestion status` and `party_states` / `next_step` are the read path. Settled: `ingestion next` reads the ledger only through `ingestion_ledger` functions, and the skill writes only through `ingestion`, `conflicts`, `proposals`, `data` and `pipeline` commands. Replace the entry with a Settled line.
- Accepted Low "hand edit of the Ingestion Ledger … revisit with `ingestion-guide`": revisited, no change. The skill never edits the ledger, and the guide tells reviewers to read ledger diffs in PRs. Append that note.
- The `proposal-conflicts` spec handoff (the guide runs the `conflicts` commands) and the `statement-rewording` handoff (the guide documents the file) are covered by the steps above.
- Cost estimates (phase 3 225 calls, conflicts 80–240, run-v2 245–410) are copied into the guide's cost table with their "check before use" caveat.

## Technical Approach

New module `src/ideology_app/ingestion_next.py` (pure derivation, no click). It exports:
- `STEPS`, the ordered tuple of step codes;
- `@dataclass NextStep(phase, code, missing: tuple[str, ...], file, format, command, llm, shared, notes)`;
- `derive(directory: Path, url: str) -> NextStep`.

`cli.py` adds `@ingestion.command("next")`. It prints `Bundle:`, `Database:` (safe URL; `shared, read-only` when `is_shared`), `Phase:`, `Step:`, `Missing (k):` followed by indented lines, `File:`, `Format:`, `Command:`, `LLM:`, `Shared database:` and `Then: ideology ingestion next DIR`. `Note:` lines warn about any unfinished or running run of another Election and any `in_progress` extraction (the one-active-run rule).

`derive` returns the first step whose condition holds:

| Phase | Code | Condition | File / format |
|---|---|---|---|
| 1 | `create-bundle-directory` | DIR missing | DIR named `<country>-<type>-<date>` |
| 1 | `write-manifest` | no `election.toml` | copy the template |
| 1 | `fill-manifest-placeholders` | raw text contains `<<` | each line listed |
| 1 | `fix-manifest` | `read_bundle` raises | the BundleError text (file:line) |
| 1 | `convert-to-format-2` | format 1 | v2 needs format 2; see guide |
| 1 | `declare-candidatures` | `_coverage_problems` non-empty | codes + INE names |
| 2 | `provide-manifestos` | a Party lists no document and is not `no_manifesto` | `[[documents]]` / `source extract` / `no-manifesto` |
| 2 | `repair-ledger` | `read_ledger` raises | take one side of a merge, rerun commands |
| 2 | `update-ledger` | ledger missing or out of date | `ingestion update DIR` |
| 2 | `review-manifestos` | a listed document has no review | `ingestion review DIR FILE --keep / --discard …` |
| 3 | `create-database` | SQLite file missing (shared: `MISSING_SHARED`-style "restore from git"), or not initialised | `DATABASE_URL`, `db upgrade` |
| 3 | `upgrade-database` | revision ≠ head | `db upgrade` (shared: migration PR rule) |
| 3 | `import-bundle` | `check_against_bundle` non-empty | `data import DIR`, then `data check DIR` |
| 3 | `extract-proposals` | a `status_rows` row is not `complete` | remaining chunks = calls |
| 3 | `fix-proposal-counts` | `ledger_count_problems` | `proposals extract DIR` (0 calls; records counts) |
| 3 | `check-conflicts` | a non-Excluded Party's overlap is `unchecked` | `conflicts detect DIR --max-calls K` |
| 3 | `decide-conflicts` | a non-Excluded Party's overlap is `pending` | `conflicts show …`, then `conflicts decide …` |
| 4 | `phase4-blocked` | `phase4_blockers` or `load_phase4` still refuses (fallback) | the blocker lines |
| 4 | `resume-run` | `find_unfinished_run(..., generation=V2)` | `run-v2 DIR --resume-from R` |
| 4 | `generate-statements` | no finished v2 run with a Dataset Version | `run-v2 DIR`; `plan_calls(phase4, entries)`, limit 800 |
| 4 | `read-failed-run` | latest finished v2 run `failed` | `pipeline checks/report --run R` |
| 4 | `reword-statements` | rewording file SHA (or absence) ≠ the latest run's recorded one | `run-v2 DIR --reuse-from R` |
| 4 | `done` | otherwise | version, summaries, rewording format |

Rules:
- Ledger reads go only through `read_ledger`, `reconcile`, `render_ledger`, `party_states`, the derived `Ledger.documents` / `conflicts` (read-only, as `ingestion status` and `conflicts list` do) and `phase4_blockers`.
- Database steps open SQLite through `read_only_url` after checking that the file exists; any other URL goes through a Session that is rolled back.
- The provider and model come from `config.llm_settings()`. A `ConfigError` is printed as `LLM: not configured: …`, not raised.
- Never import or call `cli._provider` / `build_provider`.
- In the `Command:` lines, `DIR` is the path as given.

## Expected File Changes

- `src/ideology_app/ingestion_next.py`: create. The derivation above.
- `src/ideology_app/cli.py`: modify. Add `ingestion next` and its printer. Nothing else changes.
- `tests/test_ingestion_next.py`: create. See the Verification Plan.
- `docs/templates/election-format-2.toml`: create. The commented template with unquoted `<<…>>` placeholders: `[election]`, `[candidatures]`, two `[[parties]]` (one `"all"`, one list), two `[[documents]]` (one shared, one with `constituencies` and `joint_for` commented out).
- `docs/ingestion-guide.md`: create, in Spanish (about 200–300 lines). It contains:
  - 0 before you start: choose the database (shared or scratch), the shared-database cycle, provider and model (`LLM_MODEL=claude-sonnet-5-5`), and the cost table per phase with the `claude_code` hours;
  - phases 1–4, then rewording, each listing what you need, where to get it (BOE proclamation, the party's official manifesto PDF kept outside `data/`), file, format, commands and checks;
  - resuming with `ingestion next`;
  - the step table (every code in `STEPS`);
  - "never do": edit a `.md`, the ledger or the DB by hand; commit a PDF; lower thresholds for a run; import dev data.
- `.agents/skills/ingestion-guide/SKILL.md`: create, in English. It contains:
  - hard rules G4–G7;
  - the session start: ask for DIR, the database (scratch or shared) and the `DATABASE_URL`;
  - the loop: run `next`, explain the step in the Operator's language, ask for exactly the listed data, run, rerun `next`;
  - a per-step playbook: what to ask, what the agent may run, what needs approval or the shared-database confirmation;
  - the session end: `db check`, the files to commit, `ingestion status`.
- `.agents/skills/ingestion-guide/agents/openai.yaml`: create, like its siblings.
- Docs updates are listed below.

## Visual Design Impact

- UI involved: no. There is no browser check (`AGENTS.md` exempts CLI and data features).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add one line on `ingestion_next` as a read-only CLI derivation over the bundle, ledger and database (SQLite `mode=ro`, no provider).
- `CONSTRAINTS.md`: update.
  - Ingestion Ledger rule: add `ingestion_next` to the read exceptions (derived `documents` / `conflicts`, read-only).
  - New section "Guided Ingestion":
    - `ingestion next` MUST NOT write any file or database, MUST open SQLite only with `mode=ro` after checking the file exists, and MUST NOT build an LLM provider;
    - an agent assisting ingestion MUST NOT write candidatures, Constituencies or manifesto URLs it did not get from the Operator, MUST get explicit Operator approval before each LLM-spending command, and MUST NOT run git writes.
- `AGENTS.md`: update. Under the optional docs, add `docs/ingestion-guide.md` and `$ingestion-guide` for ingesting an Election.
- `README.md`: update. Add a short Spanish section "Ingesta guiada (v2)" under "Programas y elecciones": `ingestion next`, a link to the guide and how to invoke the skill. (`v2-domain-docs` handed README to this feature.)
- `docs/technical-discovery.md`: update. Add one bullet "Guided ingestion" pointing to the guide and listing `STEPS`.
- `docs/risks-and-open-questions.md`: update.
  - Settle the handoff entry.
  - Annotate the hand-edit Low.
  - Add "Open, for team review (`ingestion-guide` defaults, <date>): G1–G11".
  - Add an Open entry for G10 (stale published version not detected; revisit with `e2e-2026-constituencies`).
- `CONTEXT.md`, `docs/domain-model.md`: not needed. Their wording ("the guided procedure that reads it is `ingestion-guide`") stays true.

## Implementation Plan

1. Write `ingestion_next.py` with `STEPS`, `NextStep` and `derive`, bundle steps first, then the database ones. Add the CLI printer.
2. Write `tests/test_ingestion_next.py`, one test per step, plus the walk and read-only tests.
3. Write the template and the test that it is refused while unfilled and accepted when filled.
4. Write the guide, then the skill and `openai.yaml`, then the docs test that ties `STEPS` to both.
5. Update the durable docs. Run the two skill dry runs and record the evidence.

## Implementation Tasks

- [ ] `ingestion_next.derive` and `STEPS`, as in the table, with the read-only database helper.
- [ ] `ingestion next` CLI output, exactly the keys listed.
- [ ] Tests T1–T8 (below).
- [ ] `docs/templates/election-format-2.toml`.
- [ ] `docs/ingestion-guide.md`.
- [ ] `.agents/skills/ingestion-guide/SKILL.md` and `agents/openai.yaml`.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `AGENTS.md`, `README.md`, `docs/technical-discovery.md` and risks doc updates.
- [ ] Dry runs B1 and B2. Evidence goes in `feature_list.json` and `PROGRESS.md`.

## Verification Plan

Automated (`.venv/bin/pytest tests/test_ingestion_next.py` and `CI=true ./init.sh`):

- **T1, one state per step:** each code in `STEPS` is reached by at least one fixture state and asserted on `Step:`, `File:`, `Command:` and the `Missing` items. States are built with:
  - `write_bundle_v2`, the real `ingestion` commands and tmp SQLite;
  - the fake-provider fixtures of `test_cli_proposals.py`, `test_cli_conflicts.py` and `test_cli_pipeline_v2.py` for the phase-3/4 states;
  - a copy of `dev_seed` for `done`, `reword-statements` (file edited, and file removed) and `read-failed-run`, if a fixture can produce a failed v2 run with a Dataset Version; otherwise use the `test_cli_pipeline_v2.py` failure fixture.
- **T2, walk:** from a missing DIR through phase 3 with CLI commands and the fake provider, collect the `Step:` codes. The sequence must equal `create-bundle-directory, write-manifest, fill-manifest-placeholders, declare-candidatures, provide-manifestos, update-ledger, review-manifestos, create-database, import-bundle, extract-proposals, check-conflicts, decide-conflicts, generate-statements` (conflict steps need an overlap in the fixture bundle).
- **T3, planned calls:** `extract-proposals` equals the sum of the remaining `status_rows` chunks; `generate-statements` equals `plan_calls`; an in-progress extraction shows its pinned provider and model.
- **T4, read-only:** for every T1 state, `snapshot` of the bundle directory and the database file are unchanged; a missing SQLite file is not created (also with the default URL in a tmp cwd); `cli._provider` and `build_provider` are patched to fail.
- **T5:** `Note:` lines report another Election's unfinished run and an `in_progress` extraction.
- **T6, template:** the copied template gives `fill-manifest-placeholders` with exactly as many lines as it has `<<`, and `read_bundle` refuses it. With every placeholder replaced by fixed test values (and one source text file from `serialise_source_text`), `read_bundle` accepts it.
- **T7, docs:** every code in `STEPS` appears in `docs/ingestion-guide.md` and in `.agents/skills/ingestion-guide/SKILL.md`. The skill contains the approval, shared-database and "never invent" rules (assert key phrases).
- **T8, format 1:** the committed 2023 bundle gives `convert-to-format-2` and its bytes are unchanged.

Manual skill dry runs. Run in an agent session that follows `$ingestion-guide`, with the implementer or validator acting as Operator from these scripts. Always work in the session scratch directory, never on `data/ideology.db`, with no real LLM:

- **B1, dev dataset:** `ideology dev seed --database-url sqlite:///$S/dev/dev.db` (the guard allows a `dev.db` outside the repo; else copy `data/dev/`).
  1. With `DIR=$S/dev/dev-bundle/es-general-2031-05-18`, expect `done` (version 1, run 1, 1 rewording applied).
  2. When asked "¿Reformular alguna afirmación?", answer yes and pick one statement from `pipeline statements --run 1`. Supply a new text and reason.
  3. Expect the agent to copy `ai_text` exactly, write the entry and show the diff.
  4. `next` gives `reword-statements` with 1 planned call. The agent states provider, model and cost and asks for approval. Answer no: it stops and prints the resume command.
- **B2, empty Election:** `DIR=$S/elections/es-general-2030-06-02` (absent), `DATABASE_URL=sqlite:///$S/dry.db`. Supply fictional data only (mineral names from the dev dataset):
  1. date and type;
  2. the BOE source "BOE ficticio";
  3. CUARZO with codes `01`..`50` and BASALTO `["08"]`, so 51 and 52 are missing; after `declare-candidatures`, add PIZARRA `["51","52"]`;
  4. for CUARZO a PDF made with `tests/pdf_factory.py` and a URL `https://example.org/cuarzo.pdf`; for BASALTO a copy of the dev `basalto.md`; PIZARRA no manifesto with a note;
  5. keep both reviews;
  6. confirm the scratch database.
  
  The run must reach `extract-proposals`; answer no at the approval prompt.
- Record each step's code, what the agent asked, which file it wrote or asked for, and what format it stated, as a table in `PROGRESS.md`. Fail the dry run if the agent:
  - asks for data not listed by `next`;
  - invents a value;
  - runs an LLM command without a yes;
  - writes outside `$S`;
  - runs git.

## Evidence To Capture

- pytest counts for `tests/test_ingestion_next.py` and the full `CI=true ./init.sh` result.
- The B1 and B2 tables (step, question, file, format, outcome) in `PROGRESS.md`, and a summary in `feature_list.json` evidence.
- `git status` shows no change under `data/` (`data/ideology.db` and `data/elections/` untouched).

## Validator Checklist

- [ ] `ingestion next` matches the step table and output keys. It is read-only: T4, plus a manual run on `data/ideology.db` that leaves `git status` clean.
- [ ] The guide is in Spanish, covers phases 1–4, rewording, resume, the costs table and every step code. The skill is in English and enforces G4–G7.
- [ ] The template is refused unfilled and accepted filled (T6).
- [ ] Dry runs B1 and B2 were rerun independently, with the same steps and no rule broken.
- [ ] CONSTRAINTS, ARCHITECTURE, AGENTS, README, technical-discovery and risks updates are present. The handoff entry is settled and G1–G11 are recorded for team review.
- [ ] No real LLM call, no change to `data/ideology.db`, no UI change, and `feature_list.json` / `PROGRESS.md` are updated.

## Implementation Notes (Session 137)

- `STEPS` has the 23 codes of the step table (6 + 4 + 7 + 6).
- The template's two `[[documents]]` examples are commented out, without `<<` (an active entry in phase 1 would name a file that only `source extract` creates in phase 2, so every filled template would stop at `fix-manifest`). T6 fills the 12 placeholders (accepted with no document), then uncomments the first example with one `serialise_source_text` file (accepted).
- An unreadable ledger gives `repair-ledger` before `provide-manifestos`, because the `no_manifesto` decisions live in it.
- `reword-statements` plans one call per new or changed entry: an entry whose normalised AI text and wording equal an `applied` / `rejected` entry of the run is reused by `--reuse-from` (verified by a replay test). The bound is printed as "at most".
- `check-conflicts` prints the exact `conflict_requests` count per overlap (0 when the hash pair is already checked), besides the overlap count.
- `phase4-blocked` cannot be reached once the earlier steps pass; its test forces both sources (`phase4_blockers`, `load_phase4`).
- B1: the seed command is `ideology --database-url sqlite:///$S/dev/dev.db dev seed` (`--database-url` is the global option). B2: `ingestion no-manifesto` creates the ledger already up to date (N = 30), so `update-ledger` does not appear; the skill tells the Operator N on the first ledger write.

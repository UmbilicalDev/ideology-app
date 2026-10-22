# Feature Implementation Spec: End-to-end run on the real 2023 general election

## Source Feature

- `id`: e2e-real-2023-election
- `area`: validation
- `depends_on`: share-link-open, methodology-page, pipeline-run-report, llm-provider-claude-code, pipeline-run-checkpoint, source-text-bundle, shared-database, pipeline-output-bounds (all `accepted`)
- `status`: accepted 2026-10-22 by the independent validator (re-planned 2026-10-22 onto the shared database; run 3 passed and published, see "Run History (as executed)")
- Later dependencies (added while the feature was blocked): pipeline-coverage-selection, pipeline-balanced-statements, pipeline-verified-findings (all `accepted`)
- `source`: `feature_list.json` (verification: "A recorded Pipeline Run report with status passed"; "A manual walkthrough on mobile and desktop, recorded in PROGRESS.md"; "A sample of 10 positions read against their Evidence (an observation, not editing)")

## Goal

The MVP success criterion, run once for real. The 2023 manifestos of the seat-winning tickets (minus CCa and UPN, user decisions) are committed as the Source Text Bundle `data/elections/es-general-2023-07-23/` and imported into the shared database `data/ideology.db` (Election 1, 9 Parties, no runs). The user runs one fresh real-provider Pipeline Run on that database in their own terminal (`claude_code` / `claude-sonnet-5-5`, `precomputed`), resuming it if it stops, and a second fresh run only if the first fails Validation. A passing run publishes on its own. The DB is committed after the run (or each stop). Then a Voter completes Landing → Questionnaire → results → Share Link → identical result in a real browser. This is an operational run, not a code feature: the output is the committed DB, recorded evidence and settled (or explicitly deferred) risk entries.

## Fixed User Decisions (not open to the implementer)

- Provider `claude_code` (the user's local Claude Code CLI with their Claude subscription: no API key, no API spend), `LLM_MODEL=claude-sonnet-5-5` (not the provider's `claude-sonnet-4-6` default), `GENERATION_MODE=precomputed`, default Validation thresholds (coverage 70, Statements 25–35, topic share 30). As run: the coverage default was later lowered by user decision, in code and for every run, to 60 (`pipeline-balanced-statements`, used by run 2) and 50 (`pipeline-verified-findings`, used by run 3); the runs never set a threshold themselves.
- **Run 1 on the old local e2e DB is discarded** (user decision 2026-10-22). It ran outside the repo, stopped after generating 38 Statements, before `pipeline-output-bounds` existed. It is history only, not an attempt and not resumable (its calls are not in the shared DB). The next real run is a **fresh run on `data/ideology.db`**, following the "Shared database" runbook in `docs/technical-discovery.md`.
- **At most 2 fresh attempts that fail Validation.** Only a fresh run (no `--resume-from`) whose result ends in failed Validation counts, or another non-resumable failure the user decides to restart from scratch. **Resuming with `--resume-from R` is not a new attempt**: a run that stops halfway (usage limit beyond `LLM_CLAUDE_CODE_MAX_WAIT_HOURS`, crash, Ctrl-C, a killed process, a provider or output error) is resumed, not restarted. `--fresh` (which overrides the unfinished-run guard) is used only if the user decides so. If both attempts fail Validation, stop and report. There is no third attempt. As run (user decisions 2026-10-22): runs 1 and 2 used both attempts (run 2 was `--reuse-from 1` after `pipeline-balanced-statements`); run 3 is a zero-call replay of run 2 (`--reuse-from 2`, 168/168 calls reused) authorized by the user after the `pipeline-verified-findings` code fix, not a new LLM attempt.
- **Coalición Canaria (CCa, 1 seat) is excluded** (user decision 2026-10-21, Phase A): its only 2023 general-election document is a joint manifesto of about 11 Canarian forces ("Un objetivo común, la defensa de Canarias"), not a CC programme.
- **Unión del Pueblo Navarro (UPN, 1 seat) is excluded** (user decision 2026-10-21, after the smoke run): its 6-page programme alone took positions on 11 of 30 Statements (36%, minimum 70%), so it would very likely fail `party_coverage` and the whole multi-hour run. A decision about the Party set, not a threshold change. The Election has 9 Parties (348 of 350 seats); "one Party per seat-winning ticket" reads "every seat-winning ticket except CCa and UPN".
- Documents (Phase A, user-confirmed): the full programmes for PP and BNG (not their summaries), EH Bildu's 16-page "Compromiso de Euskal Herria Bildu". One document per Party, the ticket-wide 23J manifesto.
- **Agents never have, look for, print or handle credentials** (Claude login tokens, any API key). No `env`/`printenv`/`set`, no reading shell rc files, `.env`, keychains or shell history. Agents make no real `claude`/LLM call (not even the ping). Only the user runs `pipeline run`, in their own terminal. Agents never run `pipeline run`, `run-queued`, `data import`, `db upgrade` or any other write command on `data/ideology.db`, with any provider (a `fake` run would publish fake data).
- AI output is never edited by hand: no DB rows, stored quotes, Statements or bundle `.md` files touched. Thresholds, call caps (`MAX_LLM_CALLS_PER_RUN=200`, `MAX_POSITION_CALLS_PER_RUN=300`), `CHUNK_MAX_CHARS` and prompts are never changed. Any such change is a user decision: **stop and ask**.
- Never commit a PDF, a secret, a log or another `.db`. Never touch the main checkout (`/Users/kike/PycharmProjects/ideology-app`), other worktrees, the old local data folder, or port 8000 (the user's own server).
- Code changes happen only if a real bug blocks the run. The implementer reports it first (symptom, evidence, proposed narrow fix) and the user decides.

## Non-Goals

- Prompt tuning, new Validation checks (e.g. compound propositions), threshold or cap changes, a price table, OCR, per-Election thresholds.
- PostgreSQL, deployment, scheduling `run-queued`, `live` mode, `source refetch`.
- Changing the bundle (other documents, regional sub-programmes, CCa/UPN back in), migrating the old local DB.
- Any UI, API or copy change. Methodology copy stays as is because no threshold changes.

## Job Story

When the whole pipeline has only ever run on `FakeProvider` (plus a one-Party smoke run),
I want to run it once on the real 2023 manifestos with a real model, without editing anything,
so I can see whether a fully AI-generated, evidence-backed Questionnaire passes Validation and works for a Voter end to end.

## Users And Permissions

- **User (human):** owns the Claude subscription login, runs the ping and every `pipeline run` command, decides on a second attempt, `--fresh` and every STOP question.
- **Orchestrating session (agent):** after each `db check` that prints `Safe to commit: yes`, commits ONLY `data/ideology.db` on `feature/e2e-real-2023-election` and pushes.
- **Implementer (agent):** preparation checks and Phase B/C evidence with read-only commands. Stops at every STOP.
- **Validator (agent):** read-only commands (`db check`, `data check`, `pipeline report|checks|statements|positions|list`, `source list|text`, `party list`) and its own browser walk. Never runs a pipeline.

## Source Provenance (history; the bundle is the current source)

- Official result: BOE-A-2023-18907 (JEC resolution of 30 Aug 2023; correction BOE-A-2023-19537 changes one Senate vote figure only): 11 seat-winning tickets, 350 seats. Mapping: PSOE 121 = PSOE 102 + PSC-PSOE 19; Sumar 31 as one candidatura (incl. lists with partner names such as En Comú Podem, Compromís).
- Phase A (Session 054) registered the manifestos in a local DB from official URLs, with PSOE (psoe.es, Incapsula) and VOX (voxespana.es, Cloudflare 403) from the user's browser downloads. The table of URLs, user files, SHA-256, page counts and title checks is in `PROGRESS.md` Session 054. Pages: PP 112, PSOE 272, VOX 178, SUMAR 182, ERC 132, JUNTS 151, EH Bildu 16, EAJ-PNV 52, BNG 68.
- `source-text-bundle` extracted the same PDFs into `data/elections/es-general-2023-07-23/` (page text identical to the Phase A DB); `shared-database` built `data/ideology.db` from it. Today 7 documents carry a `source_url` (Evidence links `url#page=N`); PSOE and VOX have none (Evidence shows quote and page, no link).
- Smoke run (history, scratch DB, UPN alone, `claude_code`/`claude-sonnet-5-5`): smoke 1 failed before any call with an expired OAuth token although `claude auth status` showed `loggedIn`; after `claude auth login`, smoke 2 made 4 calls (42,007 in / 9,103 out tokens, 90.1 s, 30 Statements) and failed only on the expected `party_coverage`/`statement_separation`. It proved the provider/model end to end. No further smoke run is planned.

## Run-Size Estimate

Re-measured read-only on `data/ideology.db` (2026-10-22, same as Phase A for 9 Parties): 2,844,891 characters, 79 chunks, Statement calls 80 (cap 200) + position calls 88 (cap 300) = **168 LLM calls**, about **2.0M input tokens** (output about 0.23M typical, 0.74M upper bound). Several usage-limit windows likely; calls run one after another (hours). `pipeline-output-bounds` changes only the request schemas, not the planned calls; the actual count can differ slightly only if a call breaks a bound (the CLI retries it internally, spending usage; if it still fails the run stops and the resume re-sends that call).

## Phases And Stop Points

Read-only prefix `P` (agents and the user), from the worktree root `/Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election`:

```
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology
```

### Phase A: Preparation check (implementer)

1. `pwd`; `CI=true ./init.sh` passes (it also builds `apps/web/dist`). `git status` clean.
2. `P db check` prints `Safe to commit: yes` and no unfinished run. `P data check data/elections/es-general-2023-07-23` prints `Database matches bundle es-general-2023-07-23: 9 documents`.
3. `P election list`: one Election (1, ES, general, 2023-07-23). `P party list --election 1`: PP, PSOE, VOX, SUMAR, ERC, JUNTS, EH Bildu, EAJ-PNV, BNG. `P source list --party N` (N = 1..9): exactly one current `parsed` document with a `bundle_file`.
4. `P pipeline list --election 1` shows no runs. Record `shasum data/ideology.db`.
5. **STOP** if any of these fails (do not repair the DB yourself).

### HUMAN STOP 1: hand back the commands (implementer ends its turn)

The user runs everything below in their own terminal, from the worktree root. Tell them: one active run on the shared DB (tell the team), AC power and lid open, usage-limit waits are printed and handled in-process, to stop press Ctrl-C **once** and wait for the exit (`failed: interrupted`), then reply "done" or "stopped".

Preflight:

```
cd /Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election
git status --short   # must be empty; then git pull with no ideology process or server open on the DB
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check   # Safe to commit: yes
claude -p "responde solo: ok"   # must answer ok; on a 401 run `claude auth login`, then ping again
mkdir -p "$HOME/ideology-e2e-2023-logs"
```

Fresh real run (attempt `N` = 1, or 2 only after attempt 1 failed Validation):

```
caffeinate -is env -u VALIDATION_MIN_PARTY_COVERAGE_PERCENT -u VALIDATION_MIN_STATEMENTS -u VALIDATION_MAX_STATEMENTS -u VALIDATION_MAX_TOPIC_SHARE_PERCENT -u LLM_PROVIDER -u LLM_MODEL -u LLM_CLAUDE_CODE_BIN -u LLM_CLAUDE_CODE_TIMEOUT_SECONDS -u LLM_CLAUDE_CODE_MAX_WAIT_HOURS DATABASE_URL=sqlite:///data/ideology.db LLM_PROVIDER=claude_code LLM_MODEL=claude-sonnet-5-5 GENERATION_MODE=precomputed .venv/bin/ideology pipeline run --election 1 --yes 2>&1 | tee -ai "$HOME/ideology-e2e-2023-logs/attempt-N.log"
```

Resume of an unfinished run `R` (not an attempt; same command plus `--resume-from R`, same log; same code revision, provider and model):

```
caffeinate -is env -u VALIDATION_MIN_PARTY_COVERAGE_PERCENT -u VALIDATION_MIN_STATEMENTS -u VALIDATION_MAX_STATEMENTS -u VALIDATION_MAX_TOPIC_SHARE_PERCENT -u LLM_PROVIDER -u LLM_MODEL -u LLM_CLAUDE_CODE_BIN -u LLM_CLAUDE_CODE_TIMEOUT_SECONDS -u LLM_CLAUDE_CODE_MAX_WAIT_HOURS DATABASE_URL=sqlite:///data/ideology.db LLM_PROVIDER=claude_code LLM_MODEL=claude-sonnet-5-5 GENERATION_MODE=precomputed .venv/bin/ideology pipeline run --election 1 --resume-from R --yes 2>&1 | tee -ai "$HOME/ideology-e2e-2023-logs/attempt-N.log"
```

The unfinished-run guard: on the shared DB a fresh `pipeline run` is refused while Election 1 has an unfinished run (`running`, or `failed` without a Dataset Version) and names `--resume-from R`. That message means "resume", never "add `--fresh`". `--fresh` only on an explicit user decision (and the user decides whether the abandoned run counts as an attempt). A run that failed Validation has a Dataset Version, so attempt 2 needs no `--fresh`. Logs stay outside the repo and are never committed.

After the run ends or stops (every time):

1. The user (or the implementer, read-only) runs `P db check`; it must print `Safe to commit: yes` (it lists an unfinished run as info; with `running`, first make sure no `ideology` process is still running it). If it prints `Safe to commit: no`, **STOP and ask**: do not commit, do not repair.
2. The orchestrating session commits ONLY the DB and pushes: `git add data/ideology.db`, `git commit -m "data(e2e-real-2023-election): run R <passed|failed: reason|stopped>; resume with --resume-from R"` (omit the resume part for a finished run), `git push`. `git status` must show nothing else staged.

### Phase B: Read the result (implementer, after the user says the run ended)

1. `P pipeline list --election 1` to find the run, then `P pipeline report --run R` and `P pipeline checks --run R`. Confirm `provider: claude_code`, `model: claude-sonnet-5-5`, `generation_mode: precomputed`, `prompt_versions: generate_statements=v2, party_positions=v2, position_findings=v2, statement_candidates=v1` and `validation_settings: max_statements=35, max_topic_share_percent=30, min_party_coverage_percent=70, min_statements=25`. Record them, plus `resumed_from`/`reused_calls` for resumed runs. (As run: these are run 1's values except `generate_statements=v3`; runs 2 and 3 show `generate_statements=v4, position_findings=v3` and `min_party_coverage_percent` 60 and 50, the code defaults of their revisions.)
2. **Passed** (`status: passed`, `publication: published: live for election 1`): go to Phase C.
3. **Stopped halfway** (`failed: interrupted`, a provider or `LLMOutputError` failure, a usage-limit wait beyond the maximum, or stuck `running` after a kill): not judged. Hand back the resume command with that R. A run that failed before any LLM call (preflight: CLI missing or not logged in, a cap) is reported; whether it counts is the user's call.
4. **Failed Validation**: summarise the failure reason and every failed check entry, grouped by check, with counts:
   - quotes not found / page slips, and their causes when visible (`P source text`);
   - coverage per Party;
   - non-separating Statements;
   - count / duplicates / topic share.

   Inspect the candidate Dataset Version with `P pipeline statements` / `positions` (read-only). **HUMAN STOP 2:** hand back the summary plus the fresh command for attempt 2. Attempt 2 uses identical inputs and settings; any change in between is a user decision.
5. **Both attempts failed Validation:** no third run, no browser walk. Record both summaries in `feature_list.json` evidence and `PROGRESS.md`, set the feature to `blocked` with the reasons, do Phase C step 4 with the observations available, and hand back.

### Phase C: Evidence, sample, browser walk, risks (passed run only)

1. Evidence: the `pipeline report` summary (run id, status, provider/model, mode, prompt_versions, llm_calls, reused_calls, input/output tokens, duration, validation_settings, dataset_version, statements, publication), the passed-check list, the estimate vs the actuals (calls, tokens, duration) and the commit hash of the committed DB go into `feature_list.json` `evidence` and `PROGRESS.md`.
2. Sample of 10 Party Positions, an observation only:
   - across at least 8 Parties and 10 Statements, with at least 1 `no stance` if any exist and a mix of signs;
   - for each: Statement position + short text, Party, value, document/page, a quote excerpt (≤ 120 chars), and a verdict (`supports` / `weak/partial` / `does not support` / `quote about another Statement`), read against `P source text --document D --page P`;
   - for a `no stance`, a short keyword search of that Party's text;
   - the table goes in `PROGRESS.md`. No edits, re-runs or defect reports.
3. Browser walk (UI evidence rule in `AGENTS.md`):
   - Add a **temporary** entry `tmp-e2e-real-2023-election` to this worktree's `.claude/launch.json` (practical-notes pattern): `/usr/bin/env` with `WEB_DIST_DIR=/Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election/apps/web/dist`, `DATABASE_URL=sqlite:////Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election/data/ideology.db` (the absolute form of `sqlite:///data/ideology.db`, because launch commands run from the main checkout) and `/Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election/.venv/bin/uvicorn ideology_app.main:app --port 8051`, `"port": 8051`. If the browser tool only reads the main checkout's `launch.json`, **STOP and ask**.
   - At 375px and at desktop width:
     - Landing lists "Elecciones generales 2023";
     - the Questionnaire shows every Statement; answer with a mix including `skip` and ≥ 1 Important;
     - results rank all 9 Parties (CCa and UPN excluded by user decision) with the breakdown and Evidence;
     - open one Evidence link of a Party with a `source_url` (new tab, `url#page=N`); a PSOE or VOX row shows page only, no link;
     - `Comparte tu resultado`: copy the link (clipboard, or the fallback field);
     - open it in a new tab: `/resultados` shows the same order, percentages and `Baja cobertura` badges (compare 3 breakdown rows too).
   - Console has no errors. Every request is a `GET` to `/api/v1/…` or a static asset, with no query string, body or answer data. Record browser, widths and results.
   - Stop the server, remove the entry. `shasum data/ideology.db` is unchanged by the walk and `git status` is clean apart from the intended doc edits.
   - As run (implementer, 2026-10-22): the worktree is `…/e2e-real-2023-election-main`, port 8091, and the server read a scratch copy of `data/ideology.db` outside the repo (orchestrator instruction), so no server ever opened the committed file. The validator may use 8051 or another free port, with the same scratch-copy pattern.
4. Risks doc (`docs/risks-and-open-questions.md`): settle or explicitly defer every entry naming this feature, with run ids and counts:
   - **Real-LLM behaviour unverified**: model id; structured output (any `LLMOutputError`, how often bounds were broken); wording neutrality; topic list; chunking and caps (actual calls vs caps).
   - **Usage limits and multi-hour runs**: number of stops/resumes, waits observed, total wall time.
   - **Quote matching**: quote failures / page slips / elisions per run; whether the cited-page rule held.
   - **Coverage threshold**, **Separation**, **Questionnaire shape**: observed per-Party coverage minimum (EH Bildu, 16 pages, is the one to watch), non-separating Statements, count and topic shares. Keep each open (one run is not proof) with the numbers.
   - **Compound-proposition** (Implementation-Time Questions): count Statements that read as compound vs legitimate "y". Keep deferred, or open it for a named future feature.
   - **Low: `party_positions` newline/`»`**: count stored Evidence quotes containing `\n`, `«` or `»`. With 0, note "not observed in run R" and keep it Low.
   - **PostgreSQL publish lock**: defer explicitly to the first deployment feature (SQLite only here).
   - **Subscription terms** open question: leave to the user (no agent judgement).
   - **Perceived bias**: add the reading observation. Mark the Research Task "Collect the 2023 manifestos…" and the "text-based manifesto" Assumption settled with the Phase A/bundle results.

## Run History (as executed)

All on `data/ideology.db`, Election 1, `claude_code` / `claude-sonnet-5-5` / `precomputed`, default thresholds of the code revision. Details and the Phase C evidence are in `PROGRESS.md` Session 059–060 and `feature_list.json`.

- **Run 1** (fresh, attempt 1, main `4a280d5`, commit `455abde`): 168 calls, 901.9 s; failed Validation: `party_coverage` (only ERC ≥ 70%) and one quote slip (VOX).
- **User decision**: feature blocked; follow-up feature `pipeline-balanced-statements` (balanced agenda, prompt v4/v3, default coverage 60).
- **Run 2** (attempt 2, `--reuse-from 1`, commit `e73c2de`): 89 calls made, 79 reused, 9,390 s with one in-process usage-limit wait; failed Validation: `party_coverage` (6 Parties at 50–58%) and two quote slips (EAJ-PNV, BNG).
- **User decision**: follow-up feature `pipeline-verified-findings` (unverifiable findings never become Positions, default coverage 50, no prompt change).
- **Run 3** (user-authorized replay, `--reuse-from 2`, commit `9c13392`): 0 calls (168/168 reused), 1.6 s; findings checked 312, discarded 3, cleared 2; pool 55 → 26, `coverage_met`; every check passed; Dataset Version 3 published, Election 1 active. PP, EH Bildu and EAJ-PNV exactly at 50%.

## Acceptance Scenarios

### Scenario 1: The shared database holds the 2023 data

Given `data/ideology.db` at the branch HEAD
When the validator runs `P db check`, `P data check data/elections/es-general-2023-07-23`, `P election list`, `P party list --election 1` and `P source list --party N`
Then `Safe to commit: yes`; the DB matches the bundle (9 documents); one Election (ES, general, 2023-07-23); the 9 Parties of the recorded official result except CCa and UPN; exactly one current `parsed` bundle document per Party. `git ls-files` lists no PDF and no `.db` other than `data/ideology.db`.

### Scenario 2: The real run passed, published and was committed

Given the run id recorded in evidence
When the validator runs `P pipeline report --run R` on the committed DB
Then it shows `status: passed`, `provider: claude_code`, `model: claude-sonnet-5-5`, `generation_mode: precomputed`, the `prompt_versions` of its code revision (run 3: `generate_statements=v4, party_positions=v2, position_findings=v3, statement_candidates=v1`), the default `validation_settings` of that revision (run 3: coverage 50, Statements 25–35, topic share 30), `publication: published: live for election 1`, and every check `passed`. Across the runs in `P pipeline list --election 1`, at most 2 are fresh attempts (`pipeline report` shows `resumed_from: none`) that reached Validation; resumed runs (`resumed_from: R`) continue an attempt. (As run: run 1 `resumed_from: none`; run 2 `resumed_from: 1` with `--reuse-from`, counted by the user as attempt 2; run 3 `resumed_from: 2`, `reused_calls: 168`, 0 tokens, the user-authorized replay.) `git log -- data/ideology.db` shows the DB commits named in evidence, and the pushed HEAD's DB passes `db check`.

### Scenario 3: No hand editing and no threshold change

Given the diff of the branch against `main`
When the validator inspects it
Then only docs (`docs/specs/…`, `docs/risks-and-open-questions.md`, `docs/technical-discovery.md`, `PROGRESS.md`, `feature_list.json`) and `data/ideology.db` changed: no change to `src/`, `apps/`, `packages/`, tests, prompts, caps, `ValidationSettings` defaults or the bundle, and no leftover `.claude/launch.json` entry. The DB changed only through the runs: `data check` still matches, the Parties are the same 9, every run in `pipeline list` is `claude_code`/`claude-sonnet-5-5`, and `validation_settings` equals the defaults of the run's code revision (coverage 70 / 60 / 50 for runs 1 / 2 / 3).

### Scenario 4: Evidence sample is recorded and checkable

Given the 10-position table in `PROGRESS.md`
When the validator re-reads at least 3 entries with `P pipeline positions --dataset-version V --party N` and `P source text --document D --page P`
Then the value, page and quote match the stored data. The table covers ≥ 8 Parties and 10 Statements, with ≥ 1 `no stance` if any exist.

### Scenario 5: Voter flow and Share Link in a real browser

Given the passed Dataset Version served from `data/ideology.db` on port 8051 with this worktree's build
When the validator walks Landing → Questionnaire → results → copy Share Link → open it, at 375px and desktop
Then the shared page shows the same ranking, percentages and badges, the console is clean, no request carries answers, and the DB's `shasum` is unchanged.

### Scenario 6: Both attempts fail (alternative outcome)

Given two fresh attempts that failed Validation
When the implementer stops
Then the feature is `blocked` (not `passing`), both failure summaries are in `feature_list.json` and `PROGRESS.md`, the DB with both runs is committed, the risk entries carry the observations, and there is no third run, no threshold change and no edit.

### Scenario 7: Risks doc is current

Given `docs/risks-and-open-questions.md`
When the validator searches for `e2e-real-2023-election`
Then every remaining mention is either settled with run-specific numbers or explicitly deferred to a named feature (or to the user, for the subscription-terms question), including the PostgreSQL lock, the newline/`»` Low finding and the compound-proposition note.

## Repository Research

- Inspected (2026-10-22 re-plan): `AGENTS.md`, `PROGRESS.md` (Sessions 048–054), `feature_list.json`, `docs/specs/source-text-bundle.md`, `shared-database.md`, `pipeline-output-bounds.md`, `docs/technical-discovery.md` (Data and Storage, Local Claude Code CLI, Shared database), `docs/risks-and-open-questions.md`, `data/elections/es-general-2023-07-23/election.toml`, `src/ideology_app/pipeline/runs.py` (`find_unfinished_run`: unfinished = latest run with recorded calls, no Dataset Version, `running`/`failed`), `prompts.py` (versions), `cli.py` (`pipeline run --resume-from|--fresh|--yes`, report `_sorted_pairs`), `tests/test_committed_database.py` (no assertion on runs, so a committed run keeps `init.sh` green), `.claude/launch.json` (one `api` entry on 8000), practical-notes (launch commands run from the main checkout).
- Read-only commands run on `data/ideology.db` (shasum `7fff3800…` unchanged): `db check` → `Safe to commit: yes`; `data check` → 9 documents; 9 Parties; `pipeline list --election 1` empty; the estimate script used `shared_db.read_only_url`.

## Technical Approach

No code. The existing Operator CLI with env-var configuration, the user's terminal for the run, the runbook's `db check` → commit → push cycle for the DB, and read-only CLI commands for analysis.

## Expected File Changes

- `data/ideology.db`: modified only by the user's runs; committed by the orchestrating session.
- `PROGRESS.md`, `feature_list.json`, `docs/risks-and-open-questions.md`: evidence, state, risk entries.
- `.claude/launch.json`: temporary only, reverted before finishing.
- Nothing else. Run logs live in `$HOME/ideology-e2e-2023-logs/`, outside the repo.

## Visual Design Impact

- UI involved: checked only, not changed. `DESIGN.md` widths 375px and desktop. No new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `AGENTS.md`: not needed (no boundary, rule or workflow change).
- `docs/risks-and-open-questions.md`: update (Phase C step 4).
- `PROGRESS.md` "Current Verified State": the published run id and Dataset Version of 2023 in `data/ideology.db`.

## Verification Plan

- `CI=true ./init.sh` passes at the start and at the end (including `tests/test_committed_database.py` on the committed DB).
- The read-only commands of Scenarios 1–4; the browser walk of Scenario 5 (implementer, then validator independently on port 8051, entry removed afterwards).
- No persistent E2E test: the run depends on a real provider, which tests must not use (`CONSTRAINTS.md`).

## Evidence To Capture

- The `pipeline report` summary of each run (fresh and resumed) and the failed-check summary of a failed attempt; the DB commit hashes.
- Estimate vs actuals (calls, tokens, duration, stops). The 10-position sample table. The browser walk: browser, widths, flow steps, console and network findings. The risk entries changed, by name.

## Validator Checklist

- [ ] Scenarios 1–5 pass (or Scenario 6 applies, and the feature is `blocked`, not `passing`).
- [ ] At most 2 fresh attempts (resumes excluded); the discarded local run 1 is not counted. Default thresholds recorded. No code, prompt, cap, threshold or bundle change. No PDF, log or secret in git.
- [ ] Nobody but the user ran `claude` or `pipeline run`; no agent output contains or references a credential's value.
- [ ] Every DB commit passed `db check` first and contains only `data/ideology.db`.
- [ ] Sample table re-checked (≥ 3 entries). Browser walk re-done at 375px and desktop on port 8051. Temporary launch entry removed.
- [ ] Risks doc entries naming this feature are settled with numbers or deferred to a named feature.
- [ ] `feature_list.json` and `PROGRESS.md` updated. `git status` is clean apart from the intended docs.

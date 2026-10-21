# Feature Implementation Spec: End-to-end run on the real 2023 general election

## Source Feature

- `id`: e2e-real-2023-election
- `area`: validation
- `depends_on`: share-link-open, methodology-page, pipeline-run-report (all `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "A recorded Pipeline Run report with status passed"; "A manual walkthrough on mobile and desktop, recorded in PROGRESS.md"; "A sample of 10 positions read against their Evidence (an observation, not editing)")

## Goal

The MVP success criterion, run once for real. The 2023 Congress tickets that won seats and their 2023 general-election manifestos are registered in a database outside the repo. The user runs one real-provider Pipeline Run (`claude_code` / `claude-sonnet-5-5`, `precomputed`) in their own terminal, and a second fresh run only if the first fails Validation. A run that passes Validation publishes on its own. Then a Voter completes Landing → Questionnaire → results → Share Link → identical result in a real browser. This is an operational run, not a code feature. Its output is recorded evidence plus settled (or explicitly deferred) risk entries.

## Fixed User Decisions (not open to the implementer)

- Provider `claude_code` (`llm-provider-claude-code`: the user's local Claude Code CLI with their Claude subscription, no API spend), `LLM_MODEL=claude-sonnet-5-5` (not the provider's `claude-sonnet-4-6` default), `GENERATION_MODE=precomputed`, default Validation thresholds (coverage 70, Statements 25–35, topic share 30). User decision 2026-10-21, replacing the original `anthropic` API choice because the user does not want to pay for API usage.
- **At most 2 fresh real attempts.** Only a fresh run (no `--resume-from`) that ends with failed Validation counts, or another non-resumable failure the user decides to restart from scratch. **Resuming a stopped run with `--resume-from R` (`pipeline-run-checkpoint`) is not a new attempt** (user decision 2026-10-21): if a run stops halfway (usage limit beyond `LLM_CLAUDE_CODE_MAX_WAIT_HOURS`, crash, Ctrl-C, killed process), the next command is a resume of that run, not a fresh one. If both attempts fail Validation, stop and report. There is no third attempt.
- Before the real run, the user runs one small smoke run on a scratch DB (`/Users/kike/PycharmProjects/ideology-app-data/e2e-2023/smoke/`, one Party, UPN's 6-page programme), never on the e2e DB. Before starting the real run the user checks the login with `claude -p "responde solo: ok"` (re-login with `claude auth login` on a 401), because `claude auth status` does not prove the token is fresh. It proves the provider/model work end to end; its Validation result is irrelevant (one Party cannot separate Statements), and it is not an attempt.
- **Agents never have, look for, print or handle credentials** (`ANTHROPIC_API_KEY`, Claude login tokens). No `env`/`printenv`/`set`, no reading shell rc files, `.env`, keychains or the user's history. Agents make no real `claude`/LLM call. Only the user runs a real-provider `pipeline run`, in their own terminal. Agents never run `pipeline run` or `run-queued` against the e2e database with any provider, including `fake`, because a fake run could publish fake data.
- AI output is never edited by hand. Nobody touches DB rows, stored quotes, Statements or files. Validation thresholds, call caps (`MAX_LLM_CALLS_PER_RUN=200`, `MAX_POSITION_CALLS_PER_RUN=300`), `CHUNK_MAX_CHARS` and prompts are never changed. Any such change is a user decision: **stop and ask**.
- Data lives outside the repo:
  - `DATABASE_URL=sqlite:////Users/kike/PycharmProjects/ideology-app-data/e2e-2023/ideology.db`
  - `SOURCE_FILES_DIR=/Users/kike/PycharmProjects/ideology-app-data/e2e-2023/source_files`

  Never commit a DB, PDF or secret. Never touch the main checkout (`/Users/kike/PycharmProjects/ideology-app`), its `ideology.db`, or port 8000 (the user's own server).
- **Coalición Canaria (CCa, 1 seat) is excluded from the whole analysis** (user decision, 2026-10-21, taken in Phase A). Its only 2023 general-election document is a joint manifesto of about 11 Canarian forces ("Un objetivo común, la defensa de Canarias"), not a CC programme. The Election has 10 Parties; Scenario 1's "one Party per seat-winning ticket" reads "every seat-winning ticket except CCa". The e2e DB was rebuilt with the CLI to drop it (the earlier DB is kept as `ideology.db.pre-cca-removal` in the data folder).
- **Unión del Pueblo Navarro (UPN, 1 seat) is also excluded from the whole analysis** (user decision, 2026-10-21, after the smoke run): in the `claude_code` smoke run UPN's 6-page programme alone took positions on only 11 of 30 Statements (36%, minimum 70%), so it would very likely fail `party_coverage` and with it the whole multi-hour run. This is a user decision about the Party set, not a threshold change: Validation thresholds stay at their defaults. The Election has 9 Parties (348 of 350 seats); Scenario 1 reads "every seat-winning ticket except CCa and UPN". The e2e DB was rebuilt with the CLI again (the 10-Party DB is kept as `ideology.db.pre-upn-removal`). EH Bildu's 16-page document stays.
- Document choices confirmed by the user in Phase A: the full programmes for PP and BNG (not their summaries), and EH Bildu's 16-page "Compromiso de Euskal Herria Bildu".
- Code changes happen only if a real bug blocks the run. The implementer reports it first (symptom, evidence, proposed narrow fix) and the user decides.

## Non-Goals

- Prompt tuning, new Validation checks (e.g. a compound-proposition check), threshold or cap changes, a price table, OCR, per-Election thresholds.
- PostgreSQL, deployment, scheduling `run-queued`, `live` mode, `source refetch`.
- Regional sub-programmes (e.g. the PSC or Compromís programmes) as additional Source Documents. Exactly one document per Party, the ticket-wide 2023 manifesto.
- Any UI, API or copy change. Methodology copy stays as is because no threshold changes.

## Job Story

When the whole pipeline has only ever run on `FakeProvider`,
I want to run it once on the real 2023 manifestos with a real model, without editing anything,
so I can see whether a fully AI-generated, evidence-backed Questionnaire passes Validation and works for a Voter end to end.

## Users And Permissions

- **User (human):** owns the Claude subscription login and runs the real-provider command. Decides whether a second run happens and every stop-point question.
- **Implementer (agent):** does the Phase A preparation and the Phase C evidence work through the documented CLI only. Stops at every STOP below.
- **Validator (agent):** checks everything with read-only commands (`pipeline report|checks|statements|positions|list`, `source list|text`, `party list`) and its own browser walk. It never runs a pipeline.

## Phases And Stop Points

Every CLI command below runs from this worktree with the prefix `P`:

```
DATABASE_URL=sqlite:////Users/kike/PycharmProjects/ideology-app-data/e2e-2023/ideology.db SOURCE_FILES_DIR=/Users/kike/PycharmProjects/ideology-app-data/e2e-2023/source_files GENERATION_MODE=precomputed .venv/bin/ideology
```

### Phase A: Preparation (implementer)

1. `pwd`, then `CI=true ./init.sh` must pass (baseline gate, and it builds `apps/web/dist`). `mkdir -p` the two data directories, then `P db upgrade`.
2. `P election create --country ES --type general --date 2023-07-23 --name "Elecciones generales 2023"`. Exactly one Election.
3. Parties: one per 2023 Congress ballot ticket that won seats, taken from the official result (BOE proclamation by the Junta Electoral Central, or the Ministerio del Interior results). Record the source used. Planner's expectation, to be confirmed:
   - PP 137, PSOE 121, VOX 33, SUMAR 31, ERC 7, JUNTS 7, EH Bildu 6, EAJ-PNV 5, BNG 1, CCa 1, UPN 1 = 11 Parties, 350 seats.
   - Confirmed by BOE-A-2023-18907 (Phase A). **User decision (2026-10-21): CCa is excluded**, so the Election had 10 Parties (349 seats); **user decision (2026-10-21, after the smoke run): UPN is excluded too**, so it has 9 Parties (348 seats). See Fixed User Decisions.

   Use `P party add --election E --name "<official ticket name>" --short-name <short>`. Mapping rule: a nationwide party's regional lists count as that Party (PSC-PSOE in Catalonia under PSOE). Sumar is one Party, including lists carrying partner names (e.g. En Comú Podem in Catalonia, Compromís in the Valencian Community). Record every such mapping. If the official result disagrees with the expectation, follow the official result and note the difference. **STOP** only if a ticket's identity is unclear (e.g. a coalition that could be one or two Parties).
4. Source Documents: for each Party, find its 2023 general-election (23J) manifesto on an official source (the party's or coalition's own domain). It must not be a 2019 or 28M-2023 regional/municipal programme: check the title page with `P source text --document D --page 1`. Register it with `P source add --party N --url <url>`.
   - If the fetch is blocked (HTTP 403, a JavaScript page, a non-PDF answer), download the same official URL into a new empty directory outside the repo (e.g. `/Users/kike/PycharmProjects/ideology-app-data/e2e-2023/downloads/<short>/`), then `P source add --party N --file <pdf>`. Record the origin URL anyway. Evidence from uploaded documents shows no link (risks doc, deferred entry).
   - **STOP and ask (batched into one question)** if:
     - a manifesto is no longer on any official domain (an archive.org copy is a user decision);
     - several candidate documents exist (e.g. a full vs a summary programme);
     - a document ends `failed`;
     - a document parses with almost no text (scanned PDF: OCR is out of scope).
5. `P source list --party N` for every Party. Every registered document must be `parsed` (a `failed` row cannot be deleted, so avoid stray attempts; record any that happen). Exactly one current `parsed` document per Party.
6. Run-size estimate. Write a throwaway read-only script in the scratchpad (never in the repo). It loads each Party's current parsed document from the e2e DB, builds `pipeline.generation.DocumentPages` (as `runs._start` does), and calls `build_document_chunks` and `plan_position_calls`. Record:
   - per Party: pages, characters (sum of stored page text), chunks;
   - totals: chunks, Statement calls = chunks + 1 (cap 200), position calls = chunks + Parties with chunks (cap 300), total calls ≈ 2 × chunks + Parties + 1.

   **STOP and ask** if either cap would be exceeded (the run would fail before any LLM call). Never change a cap or the chunk size.
7. Cost and time estimate:
   - Input tokens ≈ (2 × total chunk characters + chunks × Statement-list characters (~35 lines) + the reduce inputs) / an explicit chars-per-token assumption (~3.5 for Spanish).
   - Output tokens: the upper bound is `max_tokens` per call (4096 per map call, 8192 per reduce), plus a typical guess.
   - Money: none with `claude_code` (subscription; usage-limit bound). For reference, Phase A estimated the API equivalent at Anthropic's published `claude-sonnet-5-5` price ($2 / $10 per MTok input/output).
   - Wall time: calls run one after another; give a range.
8. `P pipeline list --election E` shows no runs. `git status` is clean.

### HUMAN STOP 1: hand back (implementer ends its turn)

The hand-back message has three parts.

(a) The table of Parties, URLs, origin (`url`/`upload`), document ids, pages, characters and chunks, plus the mapping notes.

(b) The estimate from steps 6–7.

(c) The exact commands (all run by the user in their own terminal, after `claude auth status` shows `authMethod` `claude.ai`). `G` below is the guard prefix that clears overrides left in the shell:

```
env -u VALIDATION_MIN_PARTY_COVERAGE_PERCENT -u VALIDATION_MIN_STATEMENTS -u VALIDATION_MAX_STATEMENTS -u VALIDATION_MAX_TOPIC_SHARE_PERCENT -u LLM_PROVIDER -u LLM_MODEL -u LLM_CLAUDE_CODE_BIN -u LLM_CLAUDE_CODE_TIMEOUT_SECONDS -u LLM_CLAUDE_CODE_MAX_WAIT_HOURS GENERATION_MODE=precomputed LLM_PROVIDER=claude_code LLM_MODEL=claude-sonnet-5-5
```

1. Smoke run on the scratch DB (`DATABASE_URL=sqlite:////Users/kike/PycharmProjects/ideology-app-data/e2e-2023/smoke/ideology.db`, `SOURCE_FILES_DIR=…/smoke/source_files`), `pipeline run --election 1`, log to `smoke/smoke.log`. It worked when `pipeline report` shows `provider: claude_code`, `model: claude-sonnet-5-5`, `llm_calls` 4, non-zero tokens, and the run either passed or failed only on Validation checks (not a `claude_code:`/provider/output error).
2. Real run 1 on the e2e DB inside `caffeinate -is`, `pipeline run --election 1`, log appended to `run-1.log` (`tee -ai`, so Ctrl-C does not kill the log).
3. Resume template if run R stops halfway: the same command plus `--resume-from R`, same log.

Also tell the user: keep the machine awake (AC power, lid open); usage-limit waits are printed and handled in-process; after it ends they reply "done".

### Phase B: Read the result (implementer, after the user says the run ended)

1. Use `P pipeline list --election E` to find the run, then `P pipeline report --run R` and `P pipeline checks --run R`. Confirm `provider: claude_code`, `model: claude-sonnet-5-5`, `generation_mode: precomputed` and `validation_settings: max_statements=35, max_topic_share_percent=30, min_party_coverage_percent=70, min_statements=25`. Record them.
2. **Passed** (`status: passed`, `publication: published: live for election E`): go to Phase C.
3. **Failed** (Validation or generation): summarise the failure reason and every failed check entry, grouped by check, with counts:
   - quotes not found / page slips, and their causes when visible (`P source text`);
   - coverage per Party;
   - non-separating Statements;
   - count / duplicates / topic share.

   Inspect the candidate Dataset Version with `P pipeline statements` / `positions` (read-only). **HUMAN STOP 2:** hand back the summary plus the same fresh command with `run-2.log`. Run 2 uses identical inputs and settings. Any change in between (another document, a threshold, a prompt) is a user decision. A run that **stopped halfway** (`failed: interrupted`, a provider error, a usage-limit wait beyond the maximum, or stuck `running` after a kill) is not judged: hand back the resume command (`--resume-from R`), which does not count as an attempt. A run that failed before any LLM call (preflight: CLI missing or not logged in, a cap) is reported; whether it counts is the user's call.
4. **Both runs failed:** no third run and no browser walk. Record both reports' summaries in `feature_list.json` evidence and `PROGRESS.md`, set the feature to `blocked` with the reasons, and do Phase C step 4 (risk entries) with the observations available. Then hand back.

### Phase C: Evidence, sample, browser walk, risks (passed run only)

1. Evidence: the `pipeline report` summary lines (run id, status, provider/model, mode, prompt_versions, llm_calls, input/output tokens, duration, validation_settings, dataset_version, statements, publication) and the passed-check list go into `feature_list.json` `evidence` and `PROGRESS.md`. Add the Phase A table (Parties, URLs, pages, characters, chunks) to `PROGRESS.md`.
2. Sample of 10 Party Positions, an observation only.
   - Choose them across at least 8 different Parties and 10 different Statements, with at least 1 `no stance` if any exist and a mix of signs.
   - For each, record: Statement position + short text, Party short name, value, document/page, a short quote excerpt (≤ 120 chars), and a verdict:
     - `supports`;
     - `weak/partial`;
     - `does not support`;
     - `quote about another Statement` (the risk in `Quote verified but stance misread`).
   - Read each against `P source text --document D --page P`.
   - For a `no stance`, a short keyword search of that Party's text, noting whether the manifesto seems to address it.
   - Record the table in `PROGRESS.md`. No edits, re-runs or reporting as defects.
3. Browser walk (UI evidence rule in `AGENTS.md`):
   - Add a **temporary** entry `tmp-e2e-real-2023-election` to this worktree's `.claude/launch.json` (practical-notes pattern). It runs `/usr/bin/env` with `WEB_DIST_DIR=/Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election/apps/web/dist`, the e2e `DATABASE_URL` and `/Users/kike/PycharmProjects/ideology-app-worktrees/e2e-real-2023-election/.venv/bin/uvicorn ideology_app.main:app --port 8051`, with `"port": 8051`. If the browser tool only reads the main checkout's `launch.json`, **STOP and ask**: do not edit the main checkout.
   - At 375px and at desktop width:
     - Landing lists "Elecciones generales 2023";
     - the Questionnaire shows every Statement; answer them with a mix including `skip` and ≥1 Important;
     - results show the ranking of all 9 Parties (CCa and UPN excluded by user decision) and the breakdown with Evidence;
     - open one Evidence link (new tab, `url#page=N`);
     - `Comparte tu resultado`: copy the link (clipboard, or the fallback field if the clipboard is unavailable);
     - open it in a new tab; `/resultados` shows the same order, the same percentages and the same `Baja cobertura` badges as the end screen (compare 3 breakdown rows too).
   - Console has no errors. Every request is a `GET` to `/api/v1/…` or a static asset, with no query string, body or answer data. Record browser, widths and results.
   - Stop the server and remove the entry. `git status` must be clean (apart from the intended doc edits).
4. Risks doc (`docs/risks-and-open-questions.md`): settle or explicitly defer every entry naming this feature, each with real observations (run ids, counts):
   - **Real-LLM behaviour unverified**: whether the model id worked; whether structured output held (any `LLMOutputError`); wording neutrality from reading the Statements; topic list; whether chunking and caps fitted (actual calls vs caps).
   - **Quote matching**: quote failures / page slips / elisions per run, and whether the cited-page rule held. Keep the entry only for what is still open.
   - **Coverage threshold**, **Separation**, **Questionnaire shape**: the observed per-Party coverage minimum, non-separating Statements and count/topic shares. Keep each risk open (one run is not proof) but record the numbers.
   - **Compound-proposition** (Implementation-Time Questions): count the Statements that read as compound ("X y Y" joining two policies) vs legitimate "y". Keep the check deferred, or open it for a named future feature, with that number.
   - **Low: `party_positions` newline/`»`**: candidate quotes are not stored, but a stored Evidence quote is the cited candidate's quote verbatim. Count stored quotes containing `\n`, `«` or `»` (read-only script or `positions` output). With 0, note "not observed in run R" and keep it Low. Otherwise describe it.
   - **PostgreSQL publish lock**: defer explicitly to the first deployment feature, because this run used SQLite only.
   - **Perceived bias** entry: add the reading observation. Mark the Research Task "Collect the 2023 manifestos…" and the "text-based manifesto" Assumption as settled with the Phase A results.

## Acceptance Scenarios

### Scenario 1: Preparation is complete and outside the repo

Given the e2e DB path
When the validator runs `P election list`, `P party list --election E` and `P source list --party N` for each Party
Then there is one Election (ES, general, 2023-07-23), one Party per seat-winning 2023 ticket matching the recorded official result, and exactly one current `parsed` document per Party, with the URL (or upload plus origin URL) recorded in `PROGRESS.md`. `git ls-files` contains no `.db` or `.pdf`, and nothing exists under the worktree's `source_files/`.

### Scenario 2: The real run passed and published

Given the run id recorded in evidence
When the validator runs `P pipeline report --run R`
Then it shows `status: passed`, `provider: claude_code`, `model: claude-sonnet-5-5`, `generation_mode: precomputed`, the default `validation_settings`, `publication: published: live for election E`, and every check `passed`. `P pipeline list --election E` shows at most 2 fresh attempts (runs with `resumed_from: none` that ended in Validation); resumed runs (`resumed_from: R`) continue an attempt.

### Scenario 3: No hand editing and no threshold change

Given the diff of the branch against `main`
When the validator inspects it
Then only docs changed (`docs/specs/…`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`): no change to `src/`, `apps/`, `packages/`, tests, prompts, caps or `ValidationSettings` defaults, and no leftover `.claude/launch.json` entry. The recorded `validation_settings` equals the defaults.

### Scenario 4: Evidence sample is recorded and checkable

Given the 10-position table in `PROGRESS.md`
When the validator re-reads at least 3 entries with `P pipeline positions --dataset-version V --party N` and `P source text --document D --page P`
Then the value, page and quote match the stored data. The table covers ≥ 8 Parties and 10 Statements, with ≥ 1 `no stance` if any exist.

### Scenario 5: Voter flow and Share Link in a real browser

Given the passed Dataset Version served on port 8051 from this worktree's build
When the validator walks Landing → Questionnaire → results → copy Share Link → open it, at 375px and desktop
Then the shared page shows the same ranking, percentages and badges, the console is clean, and no request carries answers.

### Scenario 6: Both runs fail (alternative outcome)

Given two failed real runs
When the implementer stops
Then the feature is `blocked` (not `passing`), both reports' failure summaries are in `feature_list.json` and `PROGRESS.md`, the risk entries carry the observations, and there is no third run, no threshold change and no edit.

### Scenario 7: Risks doc is current

Given `docs/risks-and-open-questions.md`
When the validator searches for `e2e-real-2023-election`
Then every remaining mention is either settled with run-specific numbers or explicitly deferred to a named feature, including the PostgreSQL lock, the newline/`»` Low finding and the compound-proposition note.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md` (partly), `CONTEXT.md`, `docs/build-brief.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md` (head), `feature_list.json`, `.agents/skills/github-flow/references/practical-notes.md`, `.claude/launch.json` (tracked, one `api` entry on 8000), `.gitignore` (`*.db`, `source_files/` ignored).
- `src/ideology_app/config.py`: `DEFAULT_MODELS["anthropic"] = "claude-sonnet-5-5"`, `GENERATION_MODE`, `VALIDATION_*` env names and defaults.
- `src/ideology_app/llm/anthropic_provider.py`: the key is read lazily from `ANTHROPIC_API_KEY` on the first call, `max_retries=2`, `timeout=120`.
- `src/ideology_app/pipeline/generation.py` (`CHUNK_MAX_CHARS`, `MAX_LLM_CALLS_PER_RUN`, `build_document_chunks`, `DocumentPages`), `positions.py` (`plan_position_calls`, `check_position_budget`, `_candidate_line` with `«quote»`, `_reduce` storing the cited candidate's quote verbatim), `prompts.py` (four `v1` prompts, `max_tokens` 4096/8192), `runs.py` (`execute_run`: both caps are checked before any LLM call; `_start` loads current parsed docs).
- `src/ideology_app/cli.py` (`pipeline run|report|checks|positions|statements|list`, `source add|list|text`) and `--help` of each.
- Specs for this repo's pipeline, validation, publishing, report and share-link features were consulted through the risks doc and ARCHITECTURE summaries, not read line by line.
- Not inspected: the actual manifesto URLs or their sizes (Phase A measures them). `/Users/kike/PycharmProjects/ideology-app-data` does not exist yet.

### Existing Patterns To Follow

- Worktree browser check via a temporary `launch.json` entry (practical-notes).
- Evidence only in `feature_list.json` / `PROGRESS.md`, never `docs/validations/`.

## Technical Approach

No code. Use the existing Operator CLI with env-var configuration, a throwaway scratchpad script for the size estimate, the user's terminal for the real run, and read-only CLI commands for analysis.

## Expected File Changes

- `PROGRESS.md`, `feature_list.json`: modify (evidence, state).
- `docs/risks-and-open-questions.md`: modify (settle or defer entries).
- `.claude/launch.json`: temporary only, reverted before finishing.
- Nothing else. Outside the repo: `/Users/kike/PycharmProjects/ideology-app-data/e2e-2023/` (DB, PDFs, run logs).

## Visual Design Impact

- UI involved: checked only, not changed. `DESIGN.md` widths 375px and desktop. No new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `AGENTS.md`: not needed, because no boundary, rule or workflow changes.
- `docs/risks-and-open-questions.md`: update (Phase C step 4).
- `PROGRESS.md` "Current Verified State": add where the real 2023 dataset lives and the published run id.

## Verification Plan

- `CI=true ./init.sh` passes at the start and at the end.
- The read-only CLI commands in Scenarios 1, 2 and 4 against the e2e DB.
- The browser walk in Scenario 5 (implementer, then validator independently on port 8051, entry removed afterwards).
- No persistent E2E test is added: the run depends on a real provider and on data outside the repo, which tests must not use (`CONSTRAINTS.md`).

## Evidence To Capture

- Official-result source, the Party/URL/pages/characters/chunks table, and the estimate vs the actuals (calls, tokens, duration).
- The `pipeline report` summary of each real run (1 or 2) and the failed-check summary of a failed run.
- The 10-position sample table. The browser walk: browser, widths, flow steps, console and network findings.
- The risk entries changed, by name.

## Validator Checklist

- [ ] Scenarios 1–5 pass (or Scenario 6 applies, and the feature is `blocked`, not `passing`).
- [ ] At most 2 fresh attempts (resumes excluded). Default thresholds recorded. No code, prompt, cap or threshold change. No DB/PDF/secret in git.
- [ ] Nobody but the user ran the real-provider command, and no agent output contains or references a credential's value.
- [ ] Sample table re-checked (≥ 3 entries). Browser walk re-done at 375px and desktop on port 8051. Temporary launch entry removed.
- [ ] Risks doc entries naming this feature are settled with numbers or deferred to a named feature.
- [ ] `feature_list.json` and `PROGRESS.md` updated. `git status` is clean apart from the intended docs.

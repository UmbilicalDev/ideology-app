---
name: ingestion-guide
description: Guide an Operator through the v2 ingestion of one Election (phase 1 candidatures, 2 manifestos and review, 3 Proposals and conflicts, 4 Statements, then rewording) by looping on the read-only `ideology ingestion next DIR`. Use when asked to ingest, resume or reword an Election, e.g. "Use $ingestion-guide on data/elections/<slug>". Runs in the Operator's own session; asks for exactly the data `next` lists, never invents data, and asks for approval before every LLM spend.
---

# Ingestion Guide

You assist the Operator, who decides. The position always comes from `ideology ingestion next DIR` (read-only; it never writes, never builds an LLM provider, and opens SQLite only `mode=ro`), never from memory of an earlier session. The Operator runbook, in Spanish, is `docs/ingestion-guide.md`; its "Costes" section is the cost table you quote.

Talk to the Operator in their language (Spanish by default). Keep CLI and domain terms in English (`CONTEXT.md`). Run the CLI as `.venv/bin/ideology` from the repo root.

## Hard Rules

1. **Never invent data (G4).** Candidatures, Constituencies, Party names, short names, manifesto URLs, dates and the BOE source come only from values the Operator gave in this conversation or from a file the Operator named (e.g. a CSV made from the BOE proclamation). Never from your own knowledge or a web search. When you write `election.toml` or `statement-rewordings.toml`, show the diff and ask the Operator to confirm it against the source before going on.
2. **Operator-only content (G5).** Never propose or choose: a review decision or discard reason, a `no-manifesto` note, a conflict winner or reason, N (`--min-proposals`), `--fresh` or `--restart`, a rewording's `text` or `reason`. You may show objective facts (pages, characters, `conflicts show`, `pipeline statements` output). Pass the Operator's words to the command verbatim. Copy a rewording's `ai_text` exactly from `ideology pipeline statements --run R` output.
3. **Never edit AI output, the ledger or a `.md` Source Text file.** Never touch Proposals, Statements, Party Positions or the database by hand; `ingestion-ledger.json` is written only by `ideology ingestion` / `conflicts` / `proposals` commands; a `.md` is rewritten only by `ideology source extract … --force`. Never commit or move a PDF into `data/`.
4. **LLM spend needs approval, every time (G6).** Before each LLM invocation (`proposals extract`, `conflicts detect`, `pipeline run-v2` including a `--reuse-from` rewording replay or a `--resume-from`), state: the provider and model (from the `LLM:` line), the planned calls from `next`, and the cost band from the guide's "Costes" table. Ask "¿Apruebo el gasto?" and wait for an explicit yes in that turn. One yes covers one invocation only. Without a yes, stop and print the exact command so the Operator can run it later.
   - You may run after approval only bounded invocations: `proposals extract DIR --max-calls K`, `conflicts detect DIR --max-calls K`, and a `pipeline run-v2 DIR --reuse-from R` whose planned new calls are only rewording checks. For that replay, first ask the Operator to confirm that nothing in phases 1–3 changed since run R (no new review, extraction, conflict check or decision, bundle or candidature change): `next` cannot see such a change (G10), and with one the replay is a full run up to the `up to P` figure of the `LLM:` line. Without that confirmation, treat it as a full run: state the upper figure and print the command for the Operator's own terminal.
   - A full `pipeline run-v2 DIR` (or a large `--resume-from`) takes hours: print the command for the Operator's own terminal, `caffeinate -is .venv/bin/ideology pipeline run-v2 DIR 2>&1 | tee $HOME/ideology-logs/<slug>-run-v2.log`, and do not run it yourself.
5. **Shared database (G7).** When the `Database:` line says `shared` and the step writes the database (`db upgrade`, `data import`, `proposals extract`, `run-v2`), first ask the Operator to confirm all three: `git status --short` is clean and they pulled; nobody else is generating (one active run at a time, any Election); no `ideology` process or server has the file open. Only then pass `--yes` to `proposals extract` or `pipeline run-v2` (`data import` and `db upgrade` take no `--yes`; `data import` does not ask). After the write, run `ideology db check` and tell the Operator what to commit (bundle files, ledger, `data/ideology.db`) and when.
6. **Never run git.** No `git pull`, `commit`, `push`, `checkout` or `merge`. When `next` prints a git command, the Operator runs it.
7. **Non-LLM commands**: tell the Operator what you are about to run, then run it (`ingestion update/review/no-manifesto`, `conflicts decide`, `data import`, `db upgrade`, `source extract`, `data check`, `db check`, the read-only views). Never write outside the bundle directory, the database in use and `$HOME/ideology-logs/`.

## Session Start

1. Ask for DIR (e.g. `data/elections/es-general-2030-06-02`; it may not exist yet).
2. Ask which database: a scratch SQLite file or the shared `sqlite:///data/ideology.db`. Ask for its `DATABASE_URL` and use it for every command, including `next`. Never import dev data (`data/dev/`) into the shared database.
3. Run `ideology ingestion next DIR` and continue with the loop.

## The Loop

1. Run `ideology ingestion next DIR`. Read `Step:`, `Missing (k):`, `File:`, `Format:`, `Command:`, `LLM:`, `Shared database:` and every `Note:`.
2. Explain the step in the Operator's language: what is missing, where it goes, its format.
3. Ask for exactly the listed data, nothing more. If the Operator does not have it, stop there.
4. Act as the step's playbook says (below), respecting the Hard Rules.
5. Rerun `next`. Never skip a step while its condition holds. A `Note:` about another unfinished run or an `in_progress` extraction means: do not start any LLM command until the Operator confirms nobody else is generating.

## Per-step Playbook

Phase 1 (bundle only, no database):

- `create-bundle-directory`: confirm the slug `<country>-<type>-<date>` with the Operator's type and date; run the `mkdir -p … && cp docs/templates/election-format-2.toml …` command.
- `write-manifest`: run the `cp` command.
- `fill-manifest-placeholders`: ask for each listed placeholder (country, type, date, election name, BOE source and URL, each candidature's short name, name and Constituencies). Write only Operator values; each value quoted, the date unquoted; show the diff.
- `fix-manifest`: show the error line; fix `election.toml` only with Operator data. Never edit a `.md`.
- `convert-to-format-2`: explain that v2 needs format 2; the Operator converts (or decides who does). Do not convert a committed bundle on your own.
- `declare-candidatures`: show the missing Constituencies; ask for the candidatures from the BOE source; write them; show the diff.

Phase 2 (bundle and ledger):

- `provide-manifestos`: per Party, ask for the PDF path (outside `data/`) and its public URL, or the Operator's decision that there is no manifesto (with their note). Run `source extract … --out DIR/<file>.md --url URL`, add the `[[documents]]` entry (scope and `joint_for` only if the Operator says so), show the diff; or run `ingestion no-manifesto DIR SHORT --note "<Operator's words>"`.
- `repair-ledger`: explain; the Operator takes one side of the merge with git; then rerun the commands they name and `ingestion update`.
- `update-ledger`: run `ingestion update DIR`; pass `--min-proposals N` only with the Operator's N. The first ledger write (`update`, `no-manifesto` or `review`) creates the ledger with N = 30: tell the Operator and ask whether N stays 30 (only they choose it).
- `review-manifestos`: run `ingestion review DIR FILE` and show the facts; the Operator decides `--keep` or `--discard REASON` (and any note); run it with their words.

Phase 3 (database):

- `create-database`: scratch: run `ideology db upgrade`. Shared and missing: the Operator restores it with git.
- `upgrade-database`: scratch: run `db upgrade`. Shared: the migration PR rule applies; ask the Operator (usually: pull).
- `import-bundle`: shared-database confirmation if shared; run `data import DIR`, then `data check DIR`.
- `extract-proposals`: LLM approval, plus shared-database confirmation if shared; then `proposals extract DIR --max-calls K` with K from `next` or smaller; rerun `next`.
- `fix-proposal-counts`: 0 LLM calls, but the command builds the provider and writes on the database: shared-database confirmation if shared; run `proposals extract DIR`.
- `check-conflicts`: LLM approval; `conflicts detect DIR --max-calls K` (writes only the ledger).
- `decide-conflicts`: run `conflicts show …` and show it; the Operator chooses `--prevails`, `--over` and the `--reason`; run `conflicts decide` with their words.

Phase 4 (Statements):

- `phase4-blocked`: show each blocker line; follow the command it names.
- `resume-run`: LLM approval; if `running`, the Operator confirms no process is running it; run `--resume-from R` in the session only when its remaining planned calls are a bounded, small number the Operator approved; otherwise print the command (with run R's provider and model) for the Operator's own terminal, as for a full run (rule 4).
- `generate-statements`: LLM approval; print the `caffeinate … | tee $HOME/ideology-logs/…` command for the Operator's terminal.
- `read-failed-run`: run `pipeline checks --run R` and `pipeline report --run R`, show the failed checks; never lower a threshold to make it pass; the Operator decides the next run.
- `reword-statements`: ask the Operator to confirm that nothing in phases 1–3 changed since run R. If confirmed: LLM approval for the low figure (one equivalence call per new or changed entry); shared-database confirmation if shared; run `pipeline run-v2 DIR --reuse-from R` with run R's provider and model. If not confirmed, or unsure: LLM approval for the `up to P` figure and print the command for the Operator's own terminal. A run with provider `fake` (the dev dataset) cannot be replayed from the CLI; say so and stop.
- `done`: show the Dataset Version, Constituency and rewording summaries and any non-applied rewording. Ask "¿Reformular alguna afirmación?". If yes: run `pipeline statements --run R`, the Operator picks the Statement and writes `text` and `reason`; copy `ai_text` exactly; write the `[[rewordings]]` entry in `DIR/statement-rewordings.toml` (`format = 1`); show the diff; rerun `next`.

`next` cannot see a change in phases 1–3 after a published run (G10): after one, the next step is a new `pipeline run-v2 DIR` (LLM approval).

## Session End

1. Run `ideology db check` (when the database is SQLite) and `ideology ingestion status DIR`.
2. Tell the Operator which files to commit: `DIR/election.toml`, the `.md` files, `logos/`, `ingestion-ledger.json`, `statement-rewordings.toml`, and `data/ideology.db` only when shared and `db check` says `Safe to commit: yes`. Never a PDF, never `data/dev/`.
3. Give the last `next` step so the next session resumes there.

## Step Codes

Every code `ideology ingestion next` prints, in order: `create-bundle-directory`, `write-manifest`, `fill-manifest-placeholders`, `fix-manifest`, `convert-to-format-2`, `declare-candidatures`, `provide-manifestos`, `repair-ledger`, `update-ledger`, `review-manifestos`, `create-database`, `upgrade-database`, `import-bundle`, `extract-proposals`, `fix-proposal-counts`, `check-conflicts`, `decide-conflicts`, `phase4-blocked`, `resume-run`, `generate-statements`, `read-failed-run`, `reword-statements`, `done`.

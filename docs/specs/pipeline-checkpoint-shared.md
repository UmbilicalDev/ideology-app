# Feature Implementation Spec: Shared Pipeline Run checkpoint (JSONL in the repository, resume on another machine)

## Source Feature

- `id`: pipeline-checkpoint-shared
- `area`: pipeline
- `depends_on`: pipeline-run-checkpoint (`accepted`), source-text-bundle (`not_started` at planning time; specified in parallel)
- `source`: `feature_list.json`

## Goal

`pipeline-run-checkpoint` records every LLM call in `pipeline_run_calls`, inside the gitignored local SQLite DB, and `--resume-from R` takes a DB-local run id. When the developer running a real run stops (session out of tokens, laptop closed), nobody else can continue it. This feature makes the checkpoint travel through git. Every call is also appended to a JSONL file under the Election's bundle directory. A run on another machine resumes from that file. The developer commits and pushes the file by hand when a run stops.

User decisions (2026-10-21), binding: JSONL file per run, flushed per call; `--resume-from-file` with exactly the `--resume-from` semantics; FakeProvider-only tests. Checkpoint files are committed by hand and merged into `main` with the PR of the feature or run that produced them, as the record of how published data was made. Auto-commit was dropped: hooks are never bypassed, and commit + push is manual.

**Relies on `source-text-bundle`:** (a) the Election ↔ **bundle slug** mapping it defines (this spec calls it `bundle_slug(election)`; an Election may have none); (b) its data root (`data/elections/` by default; if that feature adds no setting, this one adds `ELECTIONS_DATA_DIR`, default `data/elections`, relative to the cwd, read by `config.elections_data_dir()`); (c) its import keeps the page text byte-identical and creates each Party's Source Documents in manifest order. Prompts contain no DB ids (checked: `generation.py`, `positions.py`, `prompts.py`). The `generate_statements` reduce sorts its candidates, and a Party's documents are ordered by id only *within* the Party (main first). So `request_hash` is equal on every machine that imported the same bundle. Scenario 3 tests this with different id offsets.

## Behaviour

1. **Checkpoint file.** When the run's Election has a bundle slug, `execute_run` writes `<data root>/<slug>/checkpoints/<UTC yyyymmddThhmmssZ>-<6 lowercase hex from secrets>.jsonl`, opened with mode `x` (exclusive create: if the name exists, draw a new suffix). The name is collision-free across machines and sorts by start time. The DB run id is never used: it is local to one DB. Line 1 is the header: `{"type":"header","format":1,"election":<slug>,"provider","model","prompt_versions","created_at":<UTC ISO seconds>,"resumed_from_file":<name>|null}`. Each successful call, right after its `pipeline_run_calls` commit, appends `{"type":"call","sequence","task","request_hash","output","input_tokens","output_tokens","reused"}`, with the same values as the DB row. A line is canonical JSON (`sort_keys`, `ensure_ascii=False`, compact) plus `\n`, written with one `write`, then `flush()` and `os.fsync()`. **Reused calls are written too**, so the newest file of a chain is enough to resume after several stops. A failed call writes nothing. An `OSError` on the file fails the run like any unexpected error (`unexpected error: OSError`); the DB rows remain. With no bundle slug there is no file and the CLI prints `Pipeline run N: no checkpoint file (election E has no source-text bundle)`; everything else is unchanged. `pipeline run` and `pipeline run-queued` both write files, because both go through `execute_run`. The run stores the file name in the new column `pipeline_runs.checkpoint_file`, and the CLI prints `Pipeline run N: checkpoint file <relative path>` before the first call.
2. **Resume from a file.** `ideology pipeline run --election N --resume-from-file <path>` reads and checks the file *before* `queue_run`. It refuses with exit 1 and no run row when:
   - the file is missing or unreadable;
   - line 1 is not a `format: 1` header;
   - any line other than the last is not valid JSON, has an unknown `type` or wrong field types, or sequences do not strictly increase (git conflict markers land here);
   - the Election has no bundle slug, or the header `election` is a different slug;
   - the header `provider`/`model` differ from the configured provider's `name`/`model`.

   A last line without `\n` or not parseable (crash mid-write) is ignored with the notice `checkpoint file <name>: ignoring an incomplete last line`. Reuse is exactly that of `--resume-from` (`CheckpointProvider` takes a preloaded list of `(request_hash, output)` in sequence order instead of a run id): it uses the first unused record with the same hash, each record once, re-validates against the request schema (a record that no longer validates is a miss), returns it with zero tokens without calling the provider, and records it `reused = true` in the DB and the new file.

   Differences from `--resume-from`: a different `prompt_versions` is not refused, because changed prompts change the hash and simply miss. A file whose run already produced a Dataset Version is **not** refused: on another machine, replaying it rebuilds the same Dataset Version at zero tokens, which is useful. `--resume-from` and `--resume-from-file` are mutually exclusive (`click.UsageError`, exit 2). The run stores `pipeline_runs.resumed_from_file` (the name) and prints `Pipeline run N: resuming from file <name> (K recorded calls)`. `pipeline report` adds `resumed_from_file` (name or `none`) and `checkpoint_file` (name or `none`) after `resumed_from`.
3. **Manual commit and convention (runbook).**
   - **Commit by hand.** When a run stops (it failed, was interrupted, or the session ran out of tokens), or at any time during a run, the developer runs `git add data/elections/<slug>/checkpoints/<file> && git commit && git push` on their feature branch. The file is already fsynced, so committing it mid-run is safe: the next line is appended after it. The other machine runs `git pull`, imports the bundle, then resumes with `--resume-from-file` from the **newest** file in `checkpoints/` (names sort by start time).
   - **One active run per Election.** Announce the run in the feature's issue. Every run writes its own file, so two machines never edit the same file and `git pull --rebase` never conflicts on checkpoints. If two machines run at once, they pay twice. The second to push is rejected as non-fast-forward and has to run `git pull --rebase && git push`.
   - **Merged into `main`.** Checkpoint files reach `main` through the PR of the feature or run that produced them.
   - **Never edited.** Files are append-only and never edited by hand (AI output is never edited); a file that was edited only produces misses or a refusal.

## Data

Migration `0012` (after `source-text-bundle`'s `0011`): nullable `String(64)` columns `pipeline_runs.checkpoint_file` and `pipeline_runs.resumed_from_file`, `recreate='never'`, with a downgrade. A 2023 run of about 176 calls produces a file of roughly 1–2 MB (record the real size in evidence).

## Acceptance Scenarios

1. A FakeProvider run on an Election with a bundle slug writes the header plus one line per call, equal to the `pipeline_run_calls` rows. The test patches `os.fsync` and counts one fsync per line. A provider that fails on call k leaves k−1 call lines.
2. An Election without a bundle slug: no file, the notice is printed, and the existing `test_pipeline_checkpoint.py` tests still pass unchanged.
3. Cross-machine: run on DB A (from the bundle) stops at call k (k ∈ {2, 5, last}). DB B is fresh, built from the same bundle *after another Election*, so its ids differ. `--resume-from-file` on B calls the provider only for calls k.. and reuses 1..k−1 (`reused`, zero tokens). B ends with the same Statements and Party Positions as an uninterrupted run, its file holds all lines, and `resumed_from_file` is recorded.
4. A chain of two stops resumes from the newest file only. A completed run's file replays with zero provider calls and yields the same Dataset Version content.
5. A record whose output no longer validates is a miss. Identical hashes are each used once, in sequence order.
6. Refusals (exit 1, zero new run rows, exact messages): missing file, bad header, corrupted middle line (conflict markers), another slug, Election without slug, another provider/model. Both resume options together exit 2. An incomplete last line is ignored with the notice.
7. `pipeline report` prints `resumed_from_file` and `checkpoint_file`.

## Expected File Changes

- `src/ideology_app/pipeline/checkpoint_file.py` — create: `CheckpointHeader`, `RecordedCall`, `new_checkpoint_path`, `CheckpointFileWriter`, `read_checkpoint_file` → `CheckpointFileError`, `check_resumable_file`.
- `src/ideology_app/pipeline/checkpoint.py` — `CheckpointProvider(..., *, resume_records=None, on_record=None)` (it is an error to pass both `resumed_from_run_id` and `resume_records`).
- `src/ideology_app/pipeline/runs.py` — `queue_run(..., resumed_from_file=None)`; `execute_run(..., *, checkpoint_path=None, resume_records=None, on_record=None)` writes the header after `_start` and stores `checkpoint_file`; a helper `checkpoint_path_for(session, election_id, now)` returns `None` without a slug.
- `src/ideology_app/pipeline/reports.py`, `cli.py` (`--resume-from-file`, prints), the new migration, `models.py`. `config.elections_data_dir()` comes from `source-text-bundle`. No change to `llm/`.
- Tests: `tests/test_pipeline_checkpoint_file.py`, `tests/test_migrations.py` (new head), `tests/test_cli_pipeline_report.py`.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add the Pipeline module `checkpoint_file.py`, the new CLI option and lines, and the report lines.
- `CONSTRAINTS.md`: update.
  - Checkpoint files are append-only and never edited.
  - Amend the recorded-calls rule: reuse also via an explicit `resumed_from_file`.
- `docs/technical-discovery.md`: update the `claude_code` runbook. Step 4 adds `--resume-from-file` and the manual commit, push and resume convention of Behaviour 3.
- `docs/domain-model.md` (Pipeline Run): checkpoint file and resumed-from file.
- `CONTEXT.md`: not needed (no new domain term; "checkpoint file" is operational).
- `docs/risks-and-open-questions.md`: update "Usage limits and multi-hour runs" (shared resume through committed checkpoint files). The merge-policy question was settled at planning time.
- `AGENTS.md`: not needed.

## Implementation Tasks

- [ ] Migration, model columns, `test_migrations.py` head.
- [ ] `checkpoint_file.py` writer/reader plus unit tests (format, fsync, incomplete last line, refusals).
- [ ] `CheckpointProvider` `resume_records` / `on_record`; `execute_run` / `queue_run` wiring; scenarios 1–7.
- [ ] Docs listed above; `feature_list.json` and `PROGRESS.md` evidence.

## Non-Goals

Auto-commit or auto-push of checkpoint files (manual commit + push is the documented flow; hooks are never bypassed); SIGTERM/SIGHUP handling; a usage-limit hook in `ClaudeCodeProvider`; any git invocation from the app; resuming `run-queued` from a file; a `checkpoints` list command; pruning old files; encrypting or signing files; recovering SIGKILLed runs; changing `request_hash`; exporting old DB runs to JSONL.

## Verification

`CI=true ./init.sh`; the new tests above; `alembic upgrade head`, `check` (clean), downgrade and re-upgrade on a scratch DB. Greps: no `subprocess` or `git` invocation in `pipeline/`; `pipeline/` still imports no concrete provider; `llm/` unchanged. Tests never call a real LLM. Record in evidence the checkpoint file size of a FakeProvider run on the 2023 bundle. No browser-visible change (AGENTS.md exemption).

## Validator Checklist

- [ ] Scenarios 1–7 pass. No auto-commit and no git invocation exist in the app.
- [ ] The runbook documents the manual commit, push and resume flow.
- [ ] Scope stays within Non-Goals. Docs, `feature_list.json` and `PROGRESS.md` are updated.

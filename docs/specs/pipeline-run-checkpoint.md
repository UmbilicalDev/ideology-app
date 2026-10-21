# Feature Implementation Spec: Pipeline Run checkpoint

## Source Feature

- `id`: pipeline-run-checkpoint
- `area`: pipeline
- `depends_on`: pipeline-run-report, llm-provider-claude-code (both `accepted`)
- `source`: `feature_list.json`

## Goal

A real Pipeline Run on the 2023 manifestos makes about 170 sequential LLM calls (about 2M input tokens). With `LLM_PROVIDER=claude_code` it runs under subscription usage limits and can take hours. Today a run that stops halfway (a weekly limit beyond the maximum wait, a crash, a killed process, a closed laptop) loses every call it made: usage is only stored at the end, and a new run starts from zero. This feature makes every successful call durable and lets the Operator resume.

User decisions (2026-10-21): the manifestos are always read in full (no sampling or budget per Party); Sonnet is used for generation; other token-reduction ideas are out of scope.

## Behaviour

1. Every successful LLM call of a run is inserted into a new table `pipeline_run_calls` in its own commit, right after the provider returns: run id, sequence number (1-based, call order), task, `request_hash`, the validated output (`model_dump(mode="json")`), input/output tokens, and `reused` (true when the output came from an earlier run). A call that fails stores nothing.
2. `request_hash` is the SHA-256 of canonical JSON (sorted keys) of: provider name, model, task, system text, prompt, the output schema's JSON schema and `max_tokens`. Identical inputs give the same hash; any prompt, chunk, model or schema change gives another.
3. `ideology pipeline run --election N --resume-from R` queues a new run with `resumed_from_run_id = R` and executes it. Before every LLM call the run looks for an unused recorded call of run R with the same hash (in sequence order, each recorded call used at most once). On a hit it re-validates the stored output against the request schema and returns it with zero tokens, without calling the provider, and records it in the new run with `reused = true`. A stored output that no longer validates is a miss (the provider is called). Without `--resume-from` nothing is reused, so a deliberate re-run still regenerates.
4. Because the new run records reused calls too, resuming from the latest run is enough after several stops.
5. Resume is refused (exit 1, no run created) when R is unknown, belongs to another Election, was queued for another provider/model, or already has a Dataset Version (generation finished; resuming would only reproduce it).
6. Run totals: `llm_calls` counts every call the run used (reused ones included), while `input_tokens` / `output_tokens` count only provider calls made by this run (reused calls carry zero tokens). `pipeline report` adds `resumed_from` (run id or `none`) and `reused_calls` (count of `reused` rows).
7. The checkpoint is a provider wrapper (`pipeline/checkpoint.py`, `CheckpointProvider`) used by `execute_run` for every run; `generation.py` / `positions.py` are unchanged. Party names still never enter a prompt; outputs are stored exactly as validated (no editing).

## Data

- Migration `0010`: table `pipeline_run_calls` (FK `pipeline_run_id` → `pipeline_runs.id` `ON DELETE CASCADE`, unique `(pipeline_run_id, sequence)`, index on `request_hash`), and `pipeline_runs.resumed_from_run_id` (nullable INTEGER, no FK: adding an FK column on SQLite needs a table recreate, see `CONSTRAINTS.md`), added with `recreate='never'`.

## Acceptance Scenarios

1. A FakeProvider run records one row per call, in order, with tokens; totals unchanged.
2. A run whose provider fails on call k keeps rows 1..k-1 committed and ends `failed`.
3. Resuming that run calls the provider only for calls k.., reuses 1..k-1 (`reused = true`, zero tokens), and ends with the same Statements as an uninterrupted run with the same fake responses.
4. A stored output that fails schema validation is not reused.
5. Resume refused for another Election, another provider/model, a run with a Dataset Version, an unknown run.
6. A run killed while `running` (rows committed, no `_finish`) can be resumed.
7. `pipeline report` prints `resumed_from` and `reused_calls`.

## Non-Goals

Automatic reuse across runs, caching across Elections, sampling input, per-task models, prompt caching, Batch API, recovering `running` runs.

## Verification

`CI=true ./init.sh`; new `tests/test_pipeline_checkpoint.py`; `tests/test_migrations.py` head `0010`; `alembic check` clean. No browser-visible change.

# Feature Implementation Spec: Passing runs auto-publish; failing runs keep the previous version

## Source Feature

- `id`: auto-publish-dataset-version (GitHub issue #23)
- `area`: pipeline
- `depends_on`: validation-evidence-quotes, validation-party-coverage, validation-statement-separation, validation-questionnaire-shape (all `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "pass → published with exactly one Published version per Election; fail → previous version unchanged"; notes: "Superseded versions stay readable for old Share Links.")

## Goal

When `validate_run` ends a run `passed`, the same commit publishes the run's Dataset Version. Its status goes `candidate` → `published`, and the Election's previous Published version goes `published` → `superseded`. When a check fails, nothing about publication changes: the previous Published version stays live and the failed run's version stays `candidate`. An Election has at most one Published version at any time (zero before its first passing run). The application enforces this, and a new partial unique index in migration `0007` backs it up. Superseded versions stay fully readable. Apart from this one status transition, Dataset Versions stay immutable.

## Decisions

- **Atomicity: one transaction, inside `validate_run`.** The publish step runs in the `validate_run` session, after the Validation results and the `passed` status are flushed and before the commit. The commit then holds all of it: the results, `passed`, the supersede, the publish and the Election status change. If anything raises, all of it rolls back, and the existing error path marks the run `failed` (`unexpected error: <ClassName>`) in a new session and re-raises. The previous Published version is untouched in that case. Do not add a second commit.
- **Concurrency: three layers.**
  1. *Election row lock.* The publish step first runs `select(Election).where(Election.id == run.election_id).with_for_update()`. On PostgreSQL this serialises publishers of the same Election until commit. Under READ COMMITTED, the second publisher's later reads see the first publisher's commit.
  2. *SQLite write lock.* SQLAlchemy drops `FOR UPDATE` on SQLite. There, the publish step runs after the session's first write (the flush of the results), and that write takes the database write lock. A second `validate_run` blocks at its own first write until the first one commits (pysqlite's default 5 s busy timeout), and only then reads the current Published version. This was checked in a throwaway environment with SQLAlchemy 2.1 and SQLite 3.53: the second writer waited and then saw the first writer's published row.
  3. *DB backstop.* Migration `0007` adds the partial unique index `uq_dataset_versions_published_election_id` on `dataset_versions (election_id) WHERE status = 'published'`, for both SQLite and PostgreSQL. A race that gets past layers 1 and 2 fails with `IntegrityError` and rolls back as described above. It never yields two Published versions.
- **What tests can prove.** CI uses SQLite only (there is no PostgreSQL). Tests prove:
  - the logic, sequentially;
  - SQLite serialisation, with a threaded test;
  - the partial index rejects a second published row;
  - the lock statement compiles to `... FOR UPDATE` on the PostgreSQL dialect;
  - the offline PostgreSQL migration renders `CREATE UNIQUE INDEX ... WHERE status = 'published'`.

  Real PostgreSQL row-lock behaviour is **not** proven. This is recorded as a risk.
- **Election status: `draft` → `active` on its first publish.** This follows the Election lifecycle in the domain model ("active = has a Published Dataset Version"), and it happens in the same transaction. An `active` Election stays `active`. An `archived` Election keeps `archived`, and its version is still published. Nothing archives Elections yet, and a later feature may refuse to publish into an archived Election. A failing run never changes the Election status.
- **Publish order = Pipeline Run id (queue order).** A passing run publishes unless the Election's current Published version belongs to a run with a **higher** id. So:
  - When an older run passes after a newer run's version is already Published, the older run ends `passed`, its Dataset Version stays `candidate` (never published), and the newer version stays live.
  - An older run that passes while the newer run failed, or has not finished, publishes normally. If the newer run passes later, it supersedes the older one.

  Reason: a later-queued run read the same or newer Source Documents, so publishing an older run must never roll Voters back to staler data. In `live` mode runs can overlap. Run ids are unique and monotonic. Dataset Version ids follow finish order, not queue order, so they must not be used.
- **No backfill.** Runs that passed before this feature keep `candidate` versions. The migration publishes nothing, so the Operator re-runs.
- **Code location.** A new module `ideology_app/pipeline/publishing.py` holds the transition (pure session logic, no commit). `validate_run` calls it on its `passed` path. The pipeline/validation flow and the `CHECKS` registry are not redesigned. Checks stay unaware of publishing.

## Non-Goals

- No `pipeline-run-report` (no new report command, no version-status column in `pipeline list`), no live-mode triggers, no public API or HTTP endpoint, no UI.
- No manual publish, unpublish, rollback or re-publish of a superseded version. Statuses only go `candidate → published → superseded`.
- No change to checks, `ValidationInput`, `ValidationSettings`, prompts, generation or `init.sh`. No new dependency.
- No archiving of Elections and no recovery of runs stuck in `running`.

## Job Story

When a Pipeline Run passes every Validation check,
I want its Dataset Version to replace the live one automatically, in one step,
so that Voters always see exactly one validated Questionnaire, and old Share Links keep resolving.

## Users And Permissions

- Operator: CLI only. Triggers runs (`pipeline run`) or finishes `validating` ones (`pipeline validate`). Cannot publish, unpublish or edit by hand.
- Voter: not affected yet (no public API). Later features read the Published version and old superseded ones.

## Acceptance Scenarios

All tests use temporary SQLite databases with `FakeProvider` (`tests/pipeline_fixtures.py`) and the autouse env/socket guard. They need no API key and no network. Election 1 is seeded `draft`.

### Scenario 1: First passing run publishes

Given Election 1 with no Published version
When a run passes (through `execute_run`, and separately through `validate_run` on a run left `validating`)
Then its version is `published`, `get_published_dataset_version(session, 1)` returns it, Election 1 is `active`, `RunOutcome.publish == PublishOutcome(election_id=1, published=True, superseded_dataset_version_id=None, published_dataset_version_id=<own id>, published_run_id=<own run id>)`, and the run's six Validation results are stored.

### Scenario 2: Next passing run supersedes

Given run 1 published version V1
When run 2 passes with V2
Then:
- V2 is `published` and V1 is `superseded`, and `outcome.publish.superseded_dataset_version_id == V1`;
- `count(status='published' AND election_id=1) == 1`;
- the Election stays `active`;
- V1 is still readable: `get_dataset_version`, its Statements and `list_positions(V1)` return the same rows as before, and `pipeline statements` / `pipeline positions` for V1 work.

### Scenario 3: Failing run changes nothing

Given V1 published
When run 2 fails Validation (for example the 20-Statement payload)
Then:
- V1 is still `published` and V2 is `candidate`;
- the Election status is unchanged;
- `outcome.publish is None`;
- the run is `failed` with the usual `validation failed: ...`.

Given there is no Published version and the Election is `draft`, when the first run fails, then nothing is published and the Election stays `draft`.

### Scenario 4: Out-of-order runs

Given runs A (id 1) and B (id 2) both queued
- When B passes, and then A passes, then:
  - B's version is `published`;
  - A is `passed`, and A's version is `candidate`;
  - `outcome.publish == PublishOutcome(election_id=1, published=False, superseded_dataset_version_id=None, published_dataset_version_id=<B's version>, published_run_id=2)`.
- When A passes and then B passes, B supersedes A.
- When B fails and then A passes, A publishes.

### Scenario 5: Atomic rollback

Given V1 published
When the publish step raises after superseding V1 (a test wrapper around `publishing.publish_dataset_version` calls the real function, then raises `RuntimeError`)
Then:
- V1 is still `published` and the new version is `candidate`;
- the Election status is unchanged;
- the run has no `validation_results` rows;
- the run is `failed` with `unexpected error: RuntimeError`;
- the exception is re-raised.

### Scenario 6: Concurrent finishers (SQLite, threaded)

Given two runs left `validating` for Election 1
When thread X runs `validate_run`, and its publish step is held (a wrapper waits on a `threading.Event` after the real call, before the commit), and thread Y starts `validate_run` for the other run, and X is released about 0.3 s later
Then:
- both runs end `passed`;
- exactly one version is `published`, and it belongs to the higher run id;
- the other version is `superseded` if it was published first, otherwise `candidate`.

Parametrise on which run X is. Use `join(timeout=10)`, and assert that neither thread raised.

### Scenario 7: Database backstop and lock statement

- After `upgrade head`, raw SQL that sets a second `published` row in Election 1 raises `IntegrityError`.
- These are accepted: `published` rows in two different Elections, and any number of `superseded` or `candidate` rows.
- `sqlite_master.sql` for the index contains `WHERE status = 'published'`.
- `str(publishing.election_lock_statement(1).compile(dialect=postgresql.dialect()))` ends with `FOR UPDATE`.

### Scenario 8: CLI

- `pipeline run` on a passing first run prints the existing line plus `Published dataset version 1 for election 1`.
- A second passing run prints `Published dataset version 2 for election 1 (superseded dataset version 1)`.
- An older run that passes after a newer one prints `Not published: dataset version V of newer pipeline run R is published for election E`.
- `pipeline validate` prints the same second line.
- All of these exit 0.
- Failing runs keep their current output and exit 1.
- `election list` shows `active` after the first publish.

## Repository Research

### Files Inspected

- `AGENTS.md`, `ARCHITECTURE.md` (Pipeline, Validation: "`auto-publish-dataset-version` hooks into `validate_run`'s `passed` path"), `CONSTRAINTS.md` (Pipeline immutability; Validation: "Only `auto-publish-dataset-version` MAY change a Dataset Version's status"), `CONTEXT.md` (Published: "Exactly one per Election at a time"), `docs/domain-model.md` (Election and Dataset Version lifecycles), `docs/build-brief.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.
- `src/ideology_app/pipeline/runs.py` (`validate_run`, `RunOutcome`, `_mark_failed`, `get_dataset_version`, `list_positions`), `models.py` (`Election.status` default `draft`, `ElectionStatus`, `DatasetVersion` with `status` default `candidate`, `pipeline_run_id` unique, election index; `NAMING_CONVENTION`), `db.py` (`session_scope`, `make_engine`), `cli.py` (`pipeline run` / `validate` output), `migrations/env.py`, `migrations/versions/0006_validation_results.py`.
- `tests/conftest.py`, `tests/test_migrations.py` (head `0006` asserts, `is_initialised` ladder, offline PostgreSQL render with `CHECK` count 14, drift), `tests/test_validation_runs.py` (`validating_run`, `queue`, `read_run`; line 157 asserts `CANDIDATE` on a passed run), `tests/test_pipeline_runs.py:163` (same), `tests/test_cli_pipeline.py:98,601` (exact passed output).

### Current Gaps

- Nothing ever changes `DatasetVersion.status` or `Election.status`. There is no "current Published version" query and no index guarding it.

## Technical Approach

**Model and migration.**
- Add to `DatasetVersion.__table_args__`: `sa.Index("uq_dataset_versions_published_election_id", "election_id", unique=True, sqlite_where=sa.text("status = 'published'"), postgresql_where=sa.text("status = 'published'"))`. The name is explicit, because the `ix_` convention does not apply to it.
- Generate `0007_published_dataset_version_index.py` per `ARCHITECTURE.md` (`--rev-id 0007`, `down_revision = '0006'`).
- Review it by hand: there should be one `create_index` with both `*_where` kwargs inside `batch_alter_table`, and a `drop_index` on downgrade. There is no data migration.
- `alembic check` and `compare_metadata` report no drift. They do not compare the WHERE clause, which is why Scenario 7 checks `sqlite_master`.

**`pipeline/publishing.py`** (imports `sqlalchemy` and `models` only, never commits):
- `@dataclass(frozen=True) PublishOutcome(election_id: int, published: bool, published_dataset_version_id: int, published_run_id: int, superseded_dataset_version_id: int | None = None)`. After the call, `published_*` always names the version that is live.
- `election_lock_statement(election_id)` returns `select(Election).where(Election.id == election_id).with_for_update()`.
- `get_published_dataset_version(session, election_id) -> DatasetVersion | None`.
- `publish_dataset_version(session, version) -> PublishOutcome`:
  1. Assert `version.status is CANDIDATE`.
  2. Run the lock statement (the Election must exist).
  3. `current = get_published_dataset_version(...)`.
  4. If `current` is not None and `current.pipeline_run_id > version.pipeline_run_id`, return `published=False` with `current`'s ids.
  5. Otherwise, if `current` exists, set it `SUPERSEDED` and `session.flush()`. **The flush must come before step 6**, so the index never sees two published rows: the unit of work orders UPDATEs by primary key, not by intent.
  6. Set `version.status = PUBLISHED`.
  7. If the Election is `DRAFT`, set it `ACTIVE`.
  8. `flush()`, then return.

**`pipeline/runs.py`:**
- `RunOutcome` gets `publish: PublishOutcome | None = None`.
- In `validate_run`, after the existing `session.flush()`, when there are no failed checks: `publish = publish_dataset_version(session, version)`. It goes inside the same `with session_scope` and `try`, so errors follow the existing rollback, `_mark_failed` and re-raise path. Put `publish` into the outcome.
- Update the module and `validate_run` docstrings (they currently say the version "stays `candidate` either way").
- Re-export `PublishOutcome`, `publish_dataset_version` and `get_published_dataset_version` from `pipeline/__init__.py`.

**`cli.py`:** a helper `_echo_publish(outcome)` used by `pipeline run` and `pipeline validate` after the existing line. It prints the Scenario 8 messages.

**Existing tests:** update without weakening intent.
- Passed-run version assertions (`test_validation_runs.py:157`, `test_pipeline_runs.py:163`) become `PUBLISHED`.
- The CLI expected outputs gain the second line.
- `test_migrations.py`: head is `0007`, add the `0006` step to `is_initialised`, the offline render contains the partial index (`CHECK` count still 14), downgrade to `0006` drops only that index.
- Failed-run tests that assert `CANDIDATE` stay as they are.

## Expected File Changes

- `src/ideology_app/models.py`: modify (index).
- `src/ideology_app/migrations/versions/0007_published_dataset_version_index.py`: create.
- `src/ideology_app/pipeline/publishing.py`: create.
- `src/ideology_app/pipeline/runs.py`, `src/ideology_app/pipeline/__init__.py`, `src/ideology_app/cli.py`: modify.
- `tests/test_publishing.py`: create (Scenarios 1–7).
- `tests/test_migrations.py`, `tests/test_validation_runs.py`, `tests/test_pipeline_runs.py`, `tests/test_cli_pipeline.py`: modify (Scenario 8 and the updated expectations).
- No change to `validation/`, `config.py`, prompts, `init.sh` or `pyproject.toml`.

## Visual Design Impact

- UI involved: no. This is a pipeline and data change with CLI output only, with no browser-visible change, so browser validation is exempt (AGENTS.md).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - The header list.
  - Models: the partial index and `0007`.
  - Pipeline: `publishing.py`, publish order, the lock, `RunOutcome.publish`, and replacing "publishing is a later feature".
  - Validation: the `validate_run` passed path.
  - The CLI output lines.
- `CONSTRAINTS.md`: update.
  - Dataset Version status MUST change only in `pipeline.publishing.publish_dataset_version`, called from `validate_run`'s passed path in the same commit. The only transitions are `candidate → published` and `published → superseded`.
  - The partial unique index MUST NOT be dropped, and any future batch migration of `dataset_versions` MUST keep it, with its WHERE clause.
  - Amend the existing Pipeline bullet so the status transition is the stated exception to "MUST NOT be updated".
- `docs/domain-model.md`: update.
  - Election: `draft` → `active` on the first publish.
  - Pipeline Run `passed`: publishes unless a newer run's (higher id) version is already Published, in which case its version stays `candidate`.
  - "Election → 0..1 Published Dataset Version" stays.
- `CONTEXT.md`: update Published to "At most one per Election at a time (none before the first passing run)".
- `docs/risks-and-open-questions.md`: update in the same change. No existing entry names this feature.
  - Add a settled Implementation-Time Question: publish order = Pipeline Run id, and an older passing run never replaces a newer Published version (`auto-publish-dataset-version`).
  - Add a Risk: the PostgreSQL `FOR UPDATE` path is unproven in CI (SQLite only). Prove it when PostgreSQL is first deployed (`e2e-real-2023-election` or a deployment feature).
  - Add a Risk: on SQLite a second `validate_run` waits at most pysqlite's 5 s busy timeout. After that it ends `failed: unexpected error: OperationalError`, and the Operator re-runs.
  - Add an Accepted Low: a passed-but-older run's version stays `candidate`, and only run status and ids tell it apart from a failed run's, so `pipeline-run-report` should show the version status.
  - Add an Accepted Low: runs that passed before `0007` are not backfilled.
  - Amend "Runs stuck in `running`": `pipeline validate` now also publishes.
- `AGENTS.md`, `DESIGN.md`, `docs/technical-discovery.md`, `docs/build-brief.md`: not needed.

## Implementation Plan

1. Model index, migration `0007`, and migration tests (Scenario 7 backstop).
2. `publishing.py` and the hook in `validate_run`, with tests for Scenarios 1–6 and the lock statement.
3. CLI second line, then update the existing tests.
4. Docs, then `CI=true ./init.sh`, then evidence.

## Implementation Tasks

- [ ] Add the `DatasetVersion` partial unique index. Autogenerate `0007`, review it, and confirm `alembic check` reports no drift.
- [ ] `publishing.py`: `PublishOutcome`, `election_lock_statement`, `get_published_dataset_version`, `publish_dataset_version` (supersede, flush, publish, Election status).
- [ ] Hook into `validate_run`, add `RunOutcome.publish`, update docstrings and re-exports.
- [ ] CLI `_echo_publish` for `pipeline run` and `pipeline validate`.
- [ ] `tests/test_publishing.py`: Scenarios 1–7, including archived stays archived and superseded versions stay readable.
- [ ] Update the expectations in the migration, validation-run, pipeline-run and CLI tests.
- [ ] Docs as listed.

## Verification Plan

- `CI=true ./init.sh` exits 0 (pytest and node pass).
- `env -u ANTHROPIC_API_KEY .venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` is clean.
- `.venv/bin/python -m pytest tests/test_publishing.py tests/test_migrations.py tests/test_validation_runs.py tests/test_cli_pipeline.py -q` passes. It must cover these `feature_list.json` cases:
  - pass → published, with exactly one Published version per Election;
  - fail → the previous version is unchanged.
- `alembic heads` is `0007`. `alembic check` reports no drift on a scratch DB. `upgrade head --sql` against a PostgreSQL URL shows the partial unique index.
- `grep -rn "DatasetVersionStatus.PUBLISHED\|DatasetVersionStatus.SUPERSEDED\|ElectionStatus.ACTIVE" src/` shows assignments only in `pipeline/publishing.py`.
- `git diff --stat main -- src/ideology_app/validation src/ideology_app/config.py src/ideology_app/pipeline/prompts.py init.sh pyproject.toml` is empty.
- Run an offline CLI smoke in a scratch directory (CliRunner, patched `cli._provider` fake, sockets blocked):
  - first run published;
  - second run supersedes;
  - a failing run keeps the second version live;
  - `election list` shows `active`.
- No E2E harness exists. Browser validation is exempt.

## Evidence To Capture

- Record in `feature_list.json` → `auto-publish-dataset-version.evidence` and in a `PROGRESS.md` session (never `docs/validations/`):
  - test counts;
  - which tests cover each scenario;
  - the alembic outputs;
  - the grep and diff outputs;
  - the smoke results;
  - the note that the PostgreSQL lock is unproven;
  - the "browser validation exempt" note;
  - the docs updated;
  - any deviations.

## Validator Checklist

- [ ] Publish, supersede and the Election `draft → active` change happen only in `validate_run`'s passed path, in the same commit as the results. The rollback test proves nothing partial survives.
- [ ] At most one Published version per Election: the application logic, the threaded SQLite test and the partial index (`0007`) all hold it. The lock statement compiles to `FOR UPDATE` on PostgreSQL.
- [ ] Publish order is by run id: an older passing run never replaces a newer Published version, and its version stays `candidate`.
- [ ] Failing runs change no Dataset Version or Election status. Superseded versions stay readable.
- [ ] No change to checks, `CHECKS` or prompts. No live triggers, report or API. Tests use `FakeProvider` only, with no key and no network.
- [ ] Docs updated as listed. `feature_list.json` and `PROGRESS.md` hold the evidence. No `docs/validations/` directory exists.

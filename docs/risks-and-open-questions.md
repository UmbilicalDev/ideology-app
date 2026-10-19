# Risks and Open Questions

## Blocking Next Phase

None.

## Implementation-Time Questions

- How often URL Source Documents are re-fetched and hashed for change detection in `live` mode.
- Settled: the prompts and chunking for Statements and Party Positions. Statements (`pipeline-generate-statements`): map/reduce over chunks of whole pages of at most 40,000 characters (one `statement_candidates` call per chunk, then one `generate_statements` call), at most 200 LLM calls. Party Positions (`pipeline-extract-positions`): per-chunk findings over the same 40,000-character chunks (one `position_findings` call per chunk), then one `party_positions` reduce per Party, at most 300 calls. All prompts `v1`; real-LLM quality is checked only in `e2e-real-2023-election`.
- The Share Link encoding format and its versioning.
- Settled: Evidence quote matching (`validation-evidence-quotes`). Normalisation only (case, accents, ligatures, whitespace and punctuation), then an exact substring match; no edit distance. The quote must start on the cited page (it may run onto the next one).
- Settled (`public-dataset-api`): the API emits `value` as an integer −2..+2 or the string `"no_stance"` (from `PartyPosition.engine_value`), exactly what the `packages/core` match-score engine consumes; `evidence` is `null` exactly when `value` is `"no_stance"`. JSON keys are snake_case; the `packages/core` HTTP adapter maps keys to camelCase once at load.
- Settled (`web-client-skeleton`): FastAPI serves the Vite build from `config.web_dist_dir()` (`$WEB_DIST_DIR`, else `apps/web/dist` relative to the current directory; outside the Python package, so setuptools package-data is not involved) through a catch-all `GET` route included last. `/api/…` and `/health…` are never served by the fallback (404 JSON); real files are served (hashed `assets/` immutable, the rest `no-cache`); a missing path with a `.` in its last segment is a 404; anything else gets `index.html` (`no-cache`). `init.sh` runs `npm ci`, type-check, Vitest and `vite build`.
- The container image (first deployment feature, not yet listed) must build the client with `npm ci && npm run build` and set `WEB_DIST_DIR` to where it copies `apps/web/dist`.
- Settled (`web-client-skeleton`): the Match Score engine is `packages/core/src/domain/match-score.ts`, a line-by-line port with the same exports, checks and messages; the 41 `node:test` cases run under Vitest with the same titles, and a 20,000-case differential run against the old `match-score.js` found 0 mismatches before it was deleted.
- Whether the per-Party unique content hash is right when a URL is re-fetched and its content changes (`live-mode-url-refetch`).
- Which document is a coalition's joint manifesto: currently the Party's lowest-id parsed document (register it first). An explicit Operator flag is undecided.
- Settled (`validation-party-coverage`): a Party below the coverage threshold fails the whole run; Parties are never excluded and nothing is published with a notice.
- Per-Election coverage thresholds (an override mentioned in `technical-discovery.md`) are not built: `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` is one process-wide value. Add a per-Election override only if a real Election needs it.
- Compound-proposition detection (the "single proposition, no and/or" half of domain check 1) is deferred by `validation-questionnaire-shape`: a lexical "y/o" heuristic would fail whole runs on legitimate Spanish Statements ("investigación y desarrollo") and still miss real compounds. Only the prompts require single propositions today. Revisit with real output in `e2e-real-2023-election`.
- Settled (`auto-publish-dataset-version`): publish order is the Pipeline Run id (queue order). A passing run publishes unless the Election's Published version belongs to a run with a higher id; an older passing run never replaces a newer Published version, and its Dataset Version stays `candidate`.
- LLM cost estimate per run: tokens are recorded and shown by `ideology pipeline report`, but there is no price table, so the report prints `cost: not estimated (no price table)`. Add one with the `live` mode cost cap (`live-mode-source-change-trigger`).
- Evidence links for uploaded Source Documents (`results-breakdown-evidence`): the API gives `url` only for URL documents (link `url#page=N`); uploaded manifestos have no public URL or file endpoint, so their Evidence shows the page only. Decide whether to serve stored PDFs.
- Archived Elections (`landing-election-picker` or the feature that archives): `GET /api/v1/elections` lists only `active` Elections; `/api/v1/elections/{id}` and Dataset Versions by id still serve archived ones. Nothing sets `archived` yet.
- The minimum number of answered Statements before showing a ranking.
- Order in which Statements are shown (random or by topic) to reduce order bias.

## Later / Not MVP

- iOS and Android app: one Expo (React Native) app in `apps/mobile/` reusing `packages/core`. Open: how Share Links open in the app (universal links / deep links with the fragment).
- Regional, municipal and European elections; other countries.
- Optional human review, or parties confirming their positions.
- Anonymous aggregate statistics.
- OCR for scanned manifestos.
- Showing parties' past parliamentary voting record alongside the manifesto.

## Assumptions

- Parties with seats publish a text-based manifesto for each general election.
- An LLM can place parties on Statements reliably enough when it has to cite verbatim Evidence.
- The 2023 general election manifestos are a valid test set until the next election is called (2027 at the latest).

## Risks

- **AI-only accuracy (high).** A wrong Position means a wrong recommendation, with no human in the loop. Mitigations: required Evidence that is verified against the source, automatic Validation, visible quotes, and the provider/model/prompt recorded per run.
- **Perceived bias in Statements (high).** AI-generated wording or topic selection may favour some parties. Mitigations: the topic spread check (enforced since `validation-questionnaire-shape`: no topic above 30% of the Statements by default, `VALIDATION_MAX_TOPIC_SHARE_PERCENT`), the separation check, a neutral-wording rule in prompts, and a public methodology page.
- **Quote verified but stance misread.** A quote can exist and still not support the assigned value. Validation can't catch this; it can only be detected by the Voter reading the Evidence. The `party_positions` reduce may also cite a candidate quote that was found for a different Statement, which makes this more likely.
- **Electoral and legal exposure.** Possible scrutiny under electoral rules (LOREG, Junta Electoral Central) close to election day, and claims of misrepresentation. Needs a disclaimer, a methodology page and a legal check before a public launch.
- **Non-determinism.** Re-runs yield different Questionnaires; Share Links pin Dataset Versions to contain this. In `live` mode a regeneration after a source change can replace the Questionnaire mid-campaign.
- **Provider cost/availability**, especially in `live` mode.
- **Runs stuck in `running`.** Ctrl-C now ends a run `failed: interrupted`. A hard kill or crash between a Pipeline Run's commits (after `running`, before the result is recorded) still leaves it in `running`, with no recovery command, so the Operator queues a new run. Recovery is deferred to `live-mode-source-change-trigger`, the first unattended runner. A run left in `validating` (a crash between the Dataset Version commit and Validation, or a run created before `validation-evidence-quotes`) is recoverable with `ideology pipeline validate --run N`, which since `auto-publish-dataset-version` also publishes it when it passes (unless a newer run's version is already Published).
- **PostgreSQL publish lock unproven (`e2e-real-2023-election` or the first deployment feature).** `auto-publish-dataset-version` serialises publishers of one Election with `SELECT … FOR UPDATE` on the Election row. CI runs SQLite only, so tests prove the logic, SQLite's write-lock serialisation (threaded test), the partial unique index and that the statement compiles to `FOR UPDATE`, but not real PostgreSQL row-lock behaviour under READ COMMITTED. Prove it with two concurrent `validate_run` calls when PostgreSQL is first deployed. The partial unique index still prevents two Published versions.
- **SQLite busy timeout on concurrent finishers (`auto-publish-dataset-version`).** On SQLite a second `validate_run` waits for the first one's write lock for at most pysqlite's default 5 s busy timeout; after that it ends `failed: unexpected error: OperationalError` with nothing stored, and the Operator re-runs. Only reachable with overlapping runs (`live` mode or two Operator shells).
- **Public API caching (`public-dataset-api`).** Dataset Version bodies are cached for one day as `immutable`, so a serialisation fix or Party-name correction reaches browsers that cached a version only after expiry; the Election list and Published pointer can be 60 s stale after a publish. A feature that lets Party or Election fields change must revisit this.
- **Query strings in server access logs (deployment).** The API ignores query strings, but uvicorn's access log records the full request line (seen in the `public-dataset-api` smoke test with `?answers=…`). Since `web-client-skeleton`, `CONSTRAINTS.md` forbids client code from putting Answers in any request (only the URL fragment carries them). The first deployment feature should decide whether to disable or redact access logs.
- **Real-LLM behaviour unverified (`e2e-real-2023-election`).** All tests use `FakeProvider`, so none of these have been checked against a real model:
  - prompt quality: neutral wording, single propositions, the topic list;
  - the 40,000-character chunking;
  - the Party Position prompts (`position_findings`, `party_positions`) and whether the 300-call cap fits real manifestos. A run now makes about 2 × chunks + Parties + 1 calls;
  - the model ids `claude-sonnet-5-5` / `claude-haiku-5-5`.

  Anthropic structured output may not enforce every JSON-schema constraint (`maxItems`, `pattern`), so a violation surfaces as `LLMOutputError` and the run ends `failed`.
- **Quote matching unverified on real manifestos (`e2e-real-2023-election`).** `evidence_quotes` has only been run on fake data. On real manifestos:
  - the cited-page rule fails the whole run on any page slip by the model;
  - extraction errors (wrong characters, interleaved columns) make real quotes fail;
  - quotes with `…` or `[...]` elisions fail;
  - very short quotes (e.g. "no") can match by chance.

  If the failure rate is high, relax to document-level matching or tune the prompts. Never edit the output.
- **Coverage threshold vs real manifestos (`e2e-real-2023-election`).** Since `validation-party-coverage` any Party below 70% coverage fails the whole run, so one small Party with a short or partial manifesto blocks publishing for every Party. Mitigation: a deliberate threshold change (`VALIDATION_MIN_PARTY_COVERAGE_PERCENT`) or better Source Documents, then a re-run. Never edit the output or drop the Party.
- **Separation vs real manifestos (`e2e-real-2023-election`).** Since `validation-statement-separation` any Statement with fewer than two different values among its stances fails the whole run: consensus Statements, and Statements where most Parties have `no stance`. The generation prompt does not see Party Positions and does not ask for divisive Statements, so on real manifestos runs may fail often. Mitigation: re-run, or a later prompt change or a deliberate threshold (a `ValidationSettings` field). Never drop Statements or edit the output.
- **Questionnaire shape vs real output (`e2e-real-2023-election`).** Since `validation-questionnaire-shape` a run fails when the model returns fewer than 25 or more than 35 Statements (the schema allows 1..60), when two Statements have the same normalised text, or when one topic has more than 30% of the Statements. Paraphrased near-duplicates are not caught. On a real model any of these fails the whole run. Mitigation: re-run, a deliberate threshold change (`VALIDATION_MIN_STATEMENTS`, `VALIDATION_MAX_STATEMENTS`, `VALIDATION_MAX_TOPIC_SHARE_PERCENT`) or a prompt change. Never edit the output or drop Statements.
- **Operator cleanup gaps.** A Source Document that ends `failed` can't be retried or deleted; a retry adds a new row. A storage `OSError` can leave an orphan content-addressed file. Multi-line failure reasons (e.g. a redirect loop) break the tab-separated rows of `ideology source list`. Fine for an MVP CLI; revisit before the Operator workflow gets heavier.
- **Fetching manifests by URL.** There is no host allow-list, so an Operator can point a fetch at a private or loopback address. That's acceptable while fetching is Operator-only via the CLI; add an allow-list before any web or admin surface or `live` mode triggers fetches. Some party sites block non-browser clients or hide the PDF behind a JavaScript page; those end `failed`, and the Operator can fall back to `--file`. AES-encrypted PDFs are reported as encrypted because `cryptography` isn't installed.
- **Parallel branches and migration ids.** Features developed in parallel can both add the same Alembic revision id (e.g. `0004`). Whichever merges second must renumber its revision and its `down_revision` before merging, then re-run `alembic check`.
- **SQLite downgrades that recreate a table.** Migrations run with `PRAGMA foreign_keys=ON`, so a batch downgrade that recreates a table referenced by `ON DELETE CASCADE` deletes every child row. `0003`'s downgrade (recreates `source_documents`) deletes all `source_document_pages` (and would delete Party Positions and run links). `0008` avoids it with a native `DROP COLUMN` (see `CONSTRAINTS.md`). Fix `0003` (or disable foreign keys around batch recreates in `env.py`) before anyone relies on downgrading a database with data; no feature owns it yet.
- **Toolchain.** The `.venv` runs Python 3.15, which is very new, so check that new dependencies have wheels for it. `init.sh` requires Node.js ≥ 22.13 (Vite 8, Vitest 5, jsdom 29). npm installs are reproducible (`npm ci` from the committed `package-lock.json`), but there's no Python dependency lockfile, so Python installs aren't.

### Accepted Low findings

Not worth fixing now. Fix one when you touch that code anyway.
- Duplicate-party errors don't say whether the name or the short name clashed.
- A `DuplicateError` rolls back the whole session, so batched writes lose earlier rows too.
- The first command on a missing SQLite file creates an empty file, then reports "not initialised".
- An explicit `api_key` passed to `AnthropicProvider` is hidden from `repr` but visible through `vars()`.
- `_read_pdf_file` checks the size with `stat()` and then reads without a limit.
- URL validation accepts Unicode whitespace (NBSP, U+2028).
- The 60 s fetch timeout applies per socket operation, not per request.
- A body shorter than its `Content-Length` is stored truncated and fails as a PDF.
- In the TypeScript match-score engine (`packages/core`), `lowCoverageThreshold: null` falls back to 5, and `NaN`, `Infinity` and `""` are accepted as Statement ids.
- In the `party_positions` reduce input each candidate quote sits on one line, so a quote containing a newline or `»` makes the input ambiguous (the stored quote is unaffected). Check in `e2e-real-2023-election`.
- When a Party has no stances, `ideology pipeline checks` lists one `statement_separation` entry per Statement (in a two-Party Election, all of them) as well as the one `party_coverage` entry. Intended: checks stay independent, and each separation message names the cause (`only party P has a stance`).
- The Statement duplicate check reuses `normalize_for_match`, which drops separators, so different numbers can collide (`2,1 %` vs `21 %`) and a Statement with no letters or digits normalises to `""`. Both can only cause a false failure, never a false pass.
- Runs that passed before migration `0007` are not backfilled: their Dataset Versions stay `candidate`, and the Operator re-runs to publish (`auto-publish-dataset-version`).
- The Election lock select in `publish_dataset_version` does not use `populate_existing()`, so an `Election` or `DatasetVersion` already loaded in the session could hold stale attributes. Harmless today (the Published-version query filters on database status and `draft` → `active` is idempotent); revisit if more state is read under the lock (`auto-publish-dataset-version`).
- `party_positions.evidence_source_document_id` cascades on Source Document delete, which would remove Party Positions from an immutable Dataset Version. There is no delete path today; revisit before one is added.
- Runs validated before migration `0008` have no recorded thresholds and `ideology pipeline report` shows `validation_settings: not recorded` (no backfill). The report's `duration` covers generation only (`started_at` → `generation_finished_at`); Validation time is shown as its own `validated_at` timestamp, which can be much later when the run was finished with `pipeline validate` (`pipeline-run-report`).
- The public API on a database not migrated to head answers `500` (no `503` or initialisation check per request).
- TypeScript 7 (the native port, `typescript@7.0.2`) may not be supported by tools that need the TypeScript compiler API (typescript-eslint, Expo). A feature that adds one should pin `typescript@6` instead (`web-client-skeleton`).
- The web client catch-all matches before Starlette's trailing-slash redirect, so `/api/v1/elections/` and `/health/` now answer `404 {"detail": "Not Found"}` instead of a `307` to the slash-less path, and `HEAD /` gets `405` (the route is `GET` only). Clients use the exact paths (`web-client-skeleton`).

## Research Tasks

- Review the methodologies of established VAAs (Wahl-O-Mat, EUandI, Kieskompas) for statement design and matching.
- Collect the 2023 manifestos of parties with seats and check their text extractability.
- Run a quick legal check on publishing VAAs during Spanish campaign periods.

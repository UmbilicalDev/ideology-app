# Risks and Open Questions

## Blocking Next Phase

None.

## Implementation-Time Questions

- How often URL Source Documents are re-fetched and hashed for change detection in `live` mode.
- The exact prompts for Party Position extraction and how to chunk manifestos for it. Settled for Statements (`pipeline-generate-statements`): map/reduce over chunks of whole pages of at most 40,000 characters (one `statement_candidates` call per chunk, then one `generate_statements` call), prompts `v1`, at most 200 LLM calls per run; real-LLM quality is checked only in `e2e-real-2023-election`.
- The Share Link encoding format and its versioning.
- The fuzzy-match tolerance for Evidence quote verification (`validation-evidence-quotes`). Page text is stored as pypdf extracts it, and its quality on real manifestos (columns, ligatures, hyphenation) is unverified, so normalise when matching, not when storing.
- The Party Position encoding the browser expects (`public-dataset-api`). `match-score-engine` already uses integers −2..+2 and the string `"no_stance"`, so the API must emit these values or map them once at load.
- Shipping the web build (`web-client-skeleton`). `src/ideology_app/static/` is not in setuptools package-data, so a non-editable install would not include it; decide how the container gets `apps/web/dist` (build stage, mount path, SPA fallback that doesn't shadow the API) and how `init.sh` runs the npm build.
- Porting `match-score.js` to TypeScript in `packages/core` (`web-client-skeleton`) must keep the exact semantics and the `node:test` scenarios (moved to Vitest), since `match-score-engine` is already accepted.
- Which Source Documents a Pipeline Run used is not recorded (`pipeline-extract-positions` or `live-mode-source-change-trigger`). Also decide whether the per-Party unique content hash is right when a URL is re-fetched and its content changes (`live-mode-url-refetch`).
- What happens when a Party fails coverage: fail the whole run, or exclude the Party and publish with a notice? Initial position: fail the run.
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
- **Perceived bias in Statements (high).** AI-generated wording or topic selection may favour some parties. Mitigations: the topic spread and separation checks, a neutral-wording rule in prompts, and a public methodology page.
- **Quote verified but stance misread.** A quote can exist and still not support the assigned value. Validation can't catch this; it can only be detected by the Voter reading the Evidence.
- **Electoral and legal exposure.** Possible scrutiny under electoral rules (LOREG, Junta Electoral Central) close to election day, and claims of misrepresentation. Needs a disclaimer, a methodology page and a legal check before a public launch.
- **Non-determinism.** Re-runs yield different Questionnaires; Share Links pin Dataset Versions to contain this. In `live` mode a regeneration after a source change can replace the Questionnaire mid-campaign.
- **Provider cost/availability**, especially in `live` mode.
- **Runs stuck in `running`.** A crash between a Pipeline Run's commits (after `running`, before the result is recorded) leaves it in `running`; there is no recovery command yet, so the Operator queues a new run. The Source Documents a run used are not recorded per run either; revisit in `pipeline-extract-positions` or `live-mode-source-change-trigger`.
- **Real-LLM behaviour unverified (`e2e-real-2023-election`).** All tests use `FakeProvider`, so none of these have been checked against a real model:
  - prompt quality: neutral wording, single propositions, the topic list;
  - the 40,000-character chunking;
  - the model ids `claude-sonnet-5-5` / `claude-haiku-5-5`.

  Anthropic structured output may not enforce every JSON-schema constraint (`maxItems`, `pattern`), so a violation surfaces as `LLMOutputError` and the run ends `failed`.
- **Operator cleanup gaps.** A Source Document that ends `failed` can't be retried or deleted; a retry adds a new row. A storage `OSError` can leave an orphan content-addressed file. Multi-line failure reasons (e.g. a redirect loop) break the tab-separated rows of `ideology source list`. Fine for an MVP CLI; revisit before the Operator workflow gets heavier.
- **Fetching manifests by URL.** There is no host allow-list, so an Operator can point a fetch at a private or loopback address. That's acceptable while fetching is Operator-only via the CLI; add an allow-list before any web or admin surface or `live` mode triggers fetches. Some party sites block non-browser clients or hide the PDF behind a JavaScript page; those end `failed`, and the Operator can fall back to `--file`. AES-encrypted PDFs are reported as encrypted because `cryptography` isn't installed.
- **Parallel branches and migration ids.** Features developed in parallel can both add the same Alembic revision id (e.g. `0004`). Whichever merges second must renumber its revision and its `down_revision` before merging, then re-run `alembic check`.
- **Toolchain.** The `.venv` runs Python 3.15, which is very new, so check that new dependencies have wheels for it. `init.sh` requires Node.js ≥ 22. There's no Python dependency lockfile, so installs aren't reproducible.

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
- In the JS engine, `lowCoverageThreshold: null` falls back to 5, and `NaN`, `Infinity` and `""` are accepted as Statement ids.

## Research Tasks

- Review the methodologies of established VAAs (Wahl-O-Mat, EUandI, Kieskompas) for statement design and matching.
- Collect the 2023 manifestos of parties with seats and check their text extractability.
- Run a quick legal check on publishing VAAs during Spanish campaign periods.

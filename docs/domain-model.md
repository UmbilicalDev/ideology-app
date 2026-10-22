# Domain Model

## Core Concepts

- **Country** — e.g. Spain. Container for Elections.
- **Election** — country, type (`general` for the MVP), date, name.
- **Party** — a ballot ticket (single party or coalition): name, short name, logo (optional). Linked to an Election (inclusion is per Election; the same real party can appear in several).
- **Source Document** — belongs to a Party in an Election; origin `upload` or `url`; stored text plus page mapping for locators, and a content hash for change detection. A coalition's joint manifesto is its main Source Document (the first registered version of it, which stays main when a re-fetch replaces it); member parties' manifestos may be attached as extra ones.
- **Pipeline Run** — belongs to an Election; records the LLM provider, model, prompt versions, Generation Mode, timestamps, LLM usage (calls and tokens), status, the Validation thresholds it was validated with, and Validation report. Every successful LLM call is recorded as it returns (task, request fingerprint, validated output, tokens); a run started with `--resume-from` (an unfinished run) or `--reuse-from` (any earlier run, even one with a Dataset Version) names the earlier run whose identical calls it reuses (`pipeline-run-checkpoint`, `pipeline-coverage-selection`). It also records its Statement Selection: the Statement Pool with each Statement's scores, which Statements were kept and why (`pipeline-coverage-selection`), and the findings discarded during extraction because their quote was not on the cited page, with the stances they cleared (`pipeline-verified-findings`). `ideology pipeline report` shows all of it, read-only.
- **Dataset Version** — produced by one successful Pipeline Run; contains the Questionnaire and the Party Positions. Immutable.
- **Statement** — text, topic tag, order; belongs to a Dataset Version.
- **Party Position** — (Dataset Version, Statement, Party) → value in {−2..+2, no stance} + Evidence.
- **Evidence** — quote, Source Document reference, page and/or URL anchor.

## Relationships

- Country 1—N Election 1—N Party
- Party 1—N Source Document (per Election)
- Election 1—N Pipeline Run 1—0..1 Dataset Version
- Dataset Version 1—N Statement; Dataset Version × Statement × Party → 1 Party Position
- Party Position 0..1—1 Evidence (required unless `no stance`)
- Election → 0..1 Published Dataset Version

## States and Lifecycles

**Election**: `draft` → `active` (has a Published Dataset Version; set by its first publish, in the same transaction) → `archived` (after the election day; still viewable, labelled as historical).

**Source Document**: `registered` → `fetched` (URL downloaded or upload stored) → `parsed` (text extracted) | `failed`. A `parsed` URL document can also be marked **replaced** (`replaced_by_id`, not a status) when a re-fetch found new bytes: a new `parsed` row for the same Party and URL takes its place, and the old row keeps its hash, pages and file for the Evidence of older Dataset Versions. Pipeline Runs read only current (not replaced) documents. A document imported from a Source Text Bundle (`ideology data import`) has `bundle_file` set (the `.md` name): it is created directly `parsed` with no stored file, its `content_hash` is the SHA-256 of the `.md` file, its origin is `url` when the file has a `source_url` (Evidence links to it) and `upload` otherwise, it is replaced only by a re-import of a changed file (same replacement rule as a re-fetch), and it is never re-fetched.

**Pipeline Run**: `queued` → `running` → `validating` → `passed` | `failed`.
- `passed` → its Dataset Version is published automatically, in the same transaction as its Validation results, and replaces the previous one, unless the Published version belongs to a newer run (higher Pipeline Run id): then it stays `candidate` and the newer version stays live. Publish order is queue order, so an older run never rolls Voters back to staler data.
- `failed` → nothing is published and the previous Published version stays live; the Validation report says why. The Operator can re-run.
- A run that fails Validation keeps its `candidate` Dataset Version, which is never published.

**Run triggers**: in `precomputed` mode, the Operator. In `live` mode, a Pipeline Run is queued automatically when a Source Document is added (ending `parsed`) or its content hash changes, in the same transaction as the document, and executed by the Operator's queue command (`ideology pipeline run-queued`). A `data import` that adds or replaces a bundle document counts as "added / content changes" (one run per import at most, in the import transaction). At most one run per Election is `queued`: later changes join it, since it reads every parsed document when it starts. A run already `running` or `validating` does not absorb a change; a new run is queued. Same bytes for the same Party are a duplicate, so nothing is queued. URL sources are re-fetched by the Operator's `ideology source refetch` (to be scheduled, e.g. by cron) once their last check is at least `SOURCE_REFETCH_INTERVAL_HOURS` old (default 6), in both modes: new bytes register a replacement document, and in `live` that queues (or joins) a run in the same transaction; the same bytes only record the check time; bytes another document of the same Party already has are reported as a duplicate and change nothing; a failed download keeps the old document and queues nothing.

**Dataset Version**: `candidate` → `published` → `superseded`. Superseded versions stay readable so old Share Links keep working. The status is the only thing that ever changes; a superseded version is never published again.

## Validation Checks (initial set)

1. Every Statement is unique (same text after normalisation: case, accents, whitespace and punctuation ignored); otherwise the whole run fails. Single-proposition detection (no "and/or" compounds) is not automated yet; only the prompts require it.
2. Every non-`no stance` Position has Evidence whose quote, normalised, starts on the cited page (or runs onto the next) of a Source Document the run read for that Party. Normalisation folds case, accents and ligatures and drops whitespace and punctuation; otherwise the match is exact.
3. Each Party has positions (not `no stance`) on at least the configured share of Statements (default 50%); otherwise the whole run fails.
4. Each Statement separates the parties: at least two different Position values among them, ignoring `no stance` (so a Statement with fewer than two stances fails; an Election with fewer than two Parties fails); otherwise the whole run fails.
5. The Statement count is within the configured range (default 25–35); otherwise the whole run fails.
6. Topics are spread out: no single topic accounts for more than a configured share of the Statements (default 30%; a topic fails when strictly above it); otherwise the whole run fails.

## Important Scenarios

- An Operator adds a URL manifesto; it is fetched, parsed, and included in the next run.
- A run fails check 2 for one party; nothing is published; the Operator re-runs it.
- A Voter marks 5 Statements Important and skips 3; the scores reflect weights and exclusions.
- A Voter opens a Share Link from a superseded Dataset Version; they see that version's result and a notice that newer data exists.

## Edge Cases

- A coalition whose joint manifesto contradicts a member party's own manifesto: the joint manifesto takes precedence (prompt rule).
- A party that split from a ticket after the election (e.g. Podemos from Sumar) is not a separate Party for that Election.
- A manifesto available only as a scanned PDF (no text layer).
- A party with no manifesto for the Election → 0% coverage → Validation fails the run (Parties are never excluded). In a two-Party Election no Statement then separates the Parties either, so check 4 also names every Statement.
- The user skips every Statement → no ranking; prompt them to answer more.
- In `live` mode a source change can supersede the Questionnaire a Voter is in the middle of; their session keeps the Dataset Version it started with.

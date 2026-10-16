# Domain Model

## Core Concepts

- **Country** — e.g. Spain. Container for Elections.
- **Election** — country, type (`general` for the MVP), date, name.
- **Party** — a ballot ticket (single party or coalition): name, short name, logo (optional). Linked to an Election (inclusion is per Election; the same real party can appear in several).
- **Source Document** — belongs to a Party in an Election; origin `upload` or `url`; stored text plus page mapping for locators, and a content hash for change detection. A coalition's joint manifesto is its main Source Document; member parties' manifestos may be attached as extra ones.
- **Pipeline Run** — belongs to an Election; records the LLM provider, model, prompt versions, Generation Mode, timestamps, status, and Validation report.
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

**Election**: `draft` → `active` (has a Published Dataset Version) → `archived` (after the election day; still viewable, labelled as historical).

**Source Document**: `registered` → `fetched` (URL downloaded or upload stored) → `parsed` (text extracted) | `failed`.

**Pipeline Run**: `queued` → `running` → `validating` → `passed` | `failed`.
- `passed` → its Dataset Version is published automatically and replaces the previous one.
- `failed` → nothing is published and the previous Published version stays live; the Validation report says why. The Operator can re-run.

**Run triggers**: in `precomputed` mode, the Operator. In `live` mode, a Source Document being added or its content hash changing (URL sources are re-fetched periodically to detect this).

**Dataset Version**: `candidate` → `published` → `superseded`. Superseded versions stay readable so old Share Links keep working.

## Validation Checks (initial set)

1. Every Statement is unique and a single proposition (no "and/or" compounds).
2. Every non-`no stance` Position has Evidence whose quote is found in the Source Document's text (normalized match).
3. Each Party has positions on ≥ 70% of Statements.
4. Each Statement separates the parties: at least two different Position values among them.
5. The Statement count is within the configured range (initially 25–35).
6. Topics are spread out: no single topic accounts for more than a configured share of the Statements.

## Important Scenarios

- An Operator adds a URL manifesto; it is fetched, parsed, and included in the next run.
- A run fails check 2 for one party; nothing is published; the Operator re-runs it.
- A Voter marks 5 Statements Important and skips 3; the scores reflect weights and exclusions.
- A Voter opens a Share Link from a superseded Dataset Version; they see that version's result and a notice that newer data exists.

## Edge Cases

- A coalition whose joint manifesto contradicts a member party's own manifesto: the joint manifesto takes precedence (prompt rule).
- A party that split from a ticket after the election (e.g. Podemos from Sumar) is not a separate Party for that Election.
- A manifesto available only as a scanned PDF (no text layer).
- A party with no manifesto for the Election → not enough coverage → Validation fails or the party is excluded (see open questions).
- The user skips every Statement → no ranking; prompt them to answer more.
- In `live` mode a source change can supersede the Questionnaire a Voter is in the middle of; their session keeps the Dataset Version it started with.

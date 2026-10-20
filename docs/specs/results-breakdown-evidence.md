# Feature Implementation Spec: Results breakdown shows each Party's Evidence

## Source Feature

- `id`: results-breakdown-evidence (GitHub issue #45)
- `area`: web
- `depends_on`: results-ranking (`accepted`). Builds on `public-dataset-api`, `questionnaire-answer-flow`, `questionnaire-important-flag` (all `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: browser test where expanding a position shows the quote and a working locator, and no stance is labelled. Notes: quotes use a serif font, DESIGN.md.)

## Goal

Below the ranking on the results end screen, the Voter sees one row per Statement: the Statement, their own Answer (or that they skipped it, and whether it was Important) and every Party's Position. Each Position is a native disclosure. Opening it shows the verbatim Evidence quote in Georgia, then its locator: a link to `url#page=N` for URL Source Documents, the page alone for uploads. A `no_stance` Position says so. Everything is built in memory from the Dataset Version already loaded and the reducer state. No new request, URL change or storage.

## Decisions

- **Placement: the same end screen, no new route or view.** `results-ranking` keeps Answers inside `QuestionnaireFlow`'s reducer, and a separate view would need router state (which counts as browser storage, see the `results-ranking` spec) or a context. The breakdown is a new component, `features/results/ResultsBreakdown.tsx`. `EndScreen` renders it in one place: after the methodology-link `<p>` and before the privacy note (`RESULTS_NOTE`). The ranking and the `Revisar mis respuestas` controls stay at the top, and the long detail comes after them. The breakdown shows on the ranking path and on the all-skipped prompt path, because the Parties' Evidence is useful even with no Answers.
- **Headings.** The section is `<section aria-labelledby="breakdown-title">` with `<h3 id="breakdown-title">Detalle por afirmación</h3>`. Each row's Statement is an `<h4>`. It is a subsection of `Tus resultados` (the h2), and existing tests that call `getByRole("heading", { level: 2 })` keep working.
- **Party order within a row: the `rankParties` order, the same in every row.**
  - CONSTRAINTS.md already says results order MUST come from `rankParties` and the UI MUST NOT re-sort. DESIGN.md: "show party order by score only; ties alphabetically".
  - Using the ranking order means one auditable rule, a Party sits in the same place as in the ranking above, and the order is earned by the Voter's Answers, not by the Party's name.
  - A second (alphabetical) order would be a new rule that always favours the same names. The API order (by id) reflects Operator registration order, which is not neutral.
  - With every score `null` (all skipped), `rankParties` already falls back to `es` name collation, then id.
  - Every Position item has identical markup and style whatever the Party, value or rank. No Party is emphasised.
- **Answer line.** `Tu respuesta: <strong>{label}</strong>`, where the label is:
  - for a rating, the scale label (`Muy en desacuerdo` … `Muy de acuerdo`);
  - for a skip, `Saltada (no cuenta para la afinidad)`;
  - for no entry, `Sin responder`. This is defensive: it cannot happen on the end screen.
  - When the Statement is rated **and** flagged, `<span className="important-mark">Importante (cuenta el doble)</span>` follows. A flagged skip shows no mark, consistent with `summarize` and the engine, which ignore the flag on a skip.
- **Position summary text.** The summary reads `{name} {shortName}`, then the value label: the same five scale labels, or `Sin posición en el programa` for `no_stance`.
- **Expanded content.**
  - Stance: `<blockquote className="evidence__quote">{quote}</blockquote>`, rendered as a React text child (never `dangerouslySetInnerHTML`), then the locator.
    - With `href`: `<a className="text-link" href={href} target="_blank" rel="noopener noreferrer">Ver en el programa, página {page} (se abre en una pestaña nueva)</a>`. A new tab, because navigating away loses the Answers.
    - Without `href`: `<p className="evidence__page">Página {page} del programa electoral. Este documento no tiene un enlace público.</p>`.
  - `no_stance`: `<p className="evidence__none">El programa de este partido no trata esta afirmación, así que no cuenta para su afinidad.</p>`.
  - Every Position is expandable, `no_stance` too, so all items behave the same.
- **Expandable control:** native `<details>`/`<summary>`, all closed initially. It is keyboard and screen-reader accessible with no ARIA wiring, and Chrome's find-in-page opens it. Rows are keyed by Statement id and items by Party id, so the open state follows a Party when the order changes. The default marker is hidden. A CSS-drawn chevron (`content: ""`, borders, rotated on `details[open]`) is decorative, so nothing extra is announced. The summary is ≥ 48px high.
- **Locator href (core):** `evidenceHref({ url, page })` returns:
  - `null` when `url` is `null`, or is not an absolute `http:`/`https:` URL (case-insensitive `^https?://\S+$` after trimming; this guards against `javascript:` and the like);
  - otherwise the URL without any existing fragment, plus `#page={page}`.
  - Core has no `URL` global (`lib: ES2022`, `types: []`), so this is string logic.
- **Uploaded documents (risks entry): defer serving stored PDFs.** Uploads show the page only. A public file endpoint needs decisions this feature should not take: the licensing of reproducing manifestos, which documents are public (only those cited by a Published or superseded Dataset Version?), and caching. Workaround: Operators register manifestos with `source add --url` to get links. The risks entry is rewritten (see Documentation). New risk found: a URL link points at the URL's *current* content, so after a party replaces its PDF, the Evidence of an older Dataset Version (Share Links) may cite a page of a document that is no longer there.
- **Responsive.** Stacked rows at every width. DESIGN.md's "breakdown becomes a table at ≥ 900px" is dropped: the main column is 720px, and a Party-per-column table with real names does not fit it. DESIGN.md is updated.
- **Merge seam with `share-link-create`** (developed in parallel; it adds a share button to the same end screen):
  - all new UI goes in new files;
  - `QuestionnaireFlow.tsx` gets only small edits: imports, the `SCALE_OPTIONS` labels, one `useMemo`, one `EndScreen` prop and one render line;
  - `QuestionnairePage.test.tsx` and `fetch-mocks.ts` stay untouched, and the flow tests go in a new file.
  - `buildBreakdown` takes engine `Answer[]`, so `share-link-open` can feed decoded fragment Answers.

## Non-Goals

- Share button and encoding (`share-link-create`), opening links (`share-link-open`), serving stored PDFs or any server, API, Python or migration change (alembic head stays `0009`).
- Agreement indicators per Party and Statement, filters, "expand all", a table layout, Party logos or colours, persisting open state, new npm dependencies.

## Job Story

When I see my ranking,
I want to check, Statement by Statement, what I answered and what each Party's manifesto actually says,
so I can judge whether the AI read each Party correctly before trusting the result.

## Users And Permissions

- Voter (anonymous): reads the breakdown in memory. The only new requests are the ones the Voter starts by opening an Evidence link in a new tab: a `GET` of the party's PDF URL. It carries no Answers, no referrer (`noreferrer`) and no opener.

## Acceptance Scenarios

The Vitest fixture is `datasetVersionJson({ statements: 6 })`, with Party Uno's Evidence given `url: "https://example.org/uno.pdf"` and page 3 (built inline in the new test file).

### Scenario 1: rows and answers
Given the Voter rates 1–4 `De acuerdo` (Statement 2 flagged Important), skips 5, and flags then skips 6
When the end screen shows
Then:
- `Detalle por afirmación` lists 6 rows in Statement order, each with `Afirmación {position}` and the text;
- row 2 shows `Tu respuesta: De acuerdo` and `Importante (cuenta el doble)`;
- rows 5 and 6 show `Saltada (no cuenta para la afinidad)` with no Important mark.

### Scenario 2: party order follows the ranking
Then every row lists the Parties in the ranking's order (`Partido Uno`, then `Partido Dos`). After `Revisar mis respuestas`, rating 1–6 `Muy en desacuerdo` and walking to the end, every row lists `Partido Dos` first, matching the new ranking.

### Scenario 3: expanding a stance with a URL document
When the Voter opens `Partido Uno` in row 1
Then the quote shows in a `blockquote.evidence__quote`, and a link `Ver en el programa, página 3 (se abre en una pestaña nueva)` has href `https://example.org/uno.pdf#page=3`, `target="_blank"` and `rel="noopener noreferrer"`.

### Scenario 4: uploaded document
When the Voter opens `Partido Dos` in row 2 (`url: null`)
Then it shows the quote and `Página 1 del programa electoral. Este documento no tiene un enlace público.`, and no link.

### Scenario 5: no stance
Then `Partido Dos` in row 1 reads `Sin posición en el programa`, and opening it shows the `no_stance` sentence with no quote or link.

### Scenario 6: all skipped
Given every Statement is skipped
Then the prompt shows instead of the ranking, and the breakdown still lists every row, with Parties in name order.

### Scenario 7: nothing leaves the browser
Then only the two GETs from the Dataset Version load are made, the location is unchanged, and storage and cookies are empty.

## Repository Research

### Files Inspected
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md` (Client-side Matching, Public API Client, Web Client), `docs/domain-model.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`, `docs/specs/results-ranking.md`, `docs/specs/landing-election-picker.md` (scratch recipe), `.agents/skills/github-flow/references/practical-notes.md`, `.claude/launch.json`.
- `packages/core/src/{index.ts,domain/dataset-version.ts,domain/ranking.ts,domain/questionnaire.ts,domain/match-score.ts}`.
- `apps/web/src/features/questionnaire/{QuestionnaireFlow.tsx,QuestionnairePage.test.tsx}`, `features/results/ResultsRanking.tsx`, `features/methodology/MethodologyPage.tsx`, `test/fetch-mocks.ts`, `ui/{components,tokens}.css`.
- `tests/pipeline_fixtures.py` (`fake_provider`, `positions_response`, `candidate_lines`; omitted Statements become `no stance`), `tests/pdf_factory.py`, `src/ideology_app/http_fetch.py` (http/https, no host allow-list), `src/ideology_app/pipeline/positions.py` (`url=cited.document.source_url`).
- Not inspected: jsdom's `<details>` toggle-on-click support (`node_modules` is not installed in this worktree).

### Existing Patterns To Follow
- Pure core function plus thin React. Components take plain data props. Spanish copy. The flow is tested by rendering `App` in `MemoryRouter` with a mocked `FetchLike`. Card styles come from `.ranking-row`. `.text-link` gives a 48px target.

### Current Gaps
- No breakdown builder, no href builder, no breakdown UI. The scale labels live only in `QuestionnaireFlow.tsx`. The methodology copy says "Podrás consultar la cita", which becomes stale once this ships.

## Technical Approach

Core `packages/core/src/domain/breakdown.ts` (pure, no React or DOM):

```ts
export interface EvidenceView { readonly quote: string; readonly page: number; readonly href: string | null }
export interface BreakdownPosition { readonly partyId: number; readonly name: string; readonly shortName: string;
  readonly value: ScaleValue | typeof NO_STANCE; readonly evidence: EvidenceView | null }
export interface BreakdownRow { readonly statementId: number; readonly position: number; readonly text: string;
  readonly answer: ScaleValue | typeof SKIP | null; readonly important: boolean;
  readonly positions: readonly BreakdownPosition[] }
export function evidenceHref(evidence: { readonly url: string | null; readonly page: number }): string | null;
export function buildBreakdown(statements: readonly Statement[], parties: readonly Party[],
  answers: readonly Answer[], partyOrder: readonly number[]): BreakdownRow[];
```

- Rows follow `statements` order. Answers are matched by `String(statementId)`, as in the engine. `important` is `true` only for a rated Answer with `important === true`.
- Parties are ordered by their index in `partyOrder`. Ids not in `partyOrder` come after, in input order. Unknown ids are ignored.
- A Party's Position for a Statement is found by Statement id. A missing one is treated as `no_stance` with `evidence: null`. `evidence` is `null` for `no_stance`, otherwise `{ quote, page, href: evidenceHref(evidence) }`.
- Returns new arrays and leaves inputs unchanged. Export everything from `index.ts`.

Web:
- `apps/web/src/features/scale-labels.ts` exports `SCALE_LABELS: Readonly<Record<ScaleValue, string>>`. `QuestionnaireFlow`'s `SCALE_OPTIONS` takes its labels from it, so the text and order stay the same.
- `apps/web/src/features/results/ResultsBreakdown.tsx` takes `{ rows: readonly BreakdownRow[] }` and renders the section described in Decisions:
  - `<ol className="breakdown" role="list" aria-labelledby="breakdown-title">` of `<li className="breakdown-row">`;
  - inside each row, `<ul className="breakdown-positions" role="list" aria-label="Posiciones de los partidos">` of `<li><details className="position"><summary className="position__summary">…</summary><div className="position__body">…</div></details></li>`.
  - Intro under the h3: `Tu respuesta y la posición de cada partido en cada afirmación. Las posiciones y las citas las ha extraído una inteligencia artificial de los programas electorales: abre una posición para leer la cita en la que se basa y comprobarla.`
- `QuestionnaireFlow.tsx`:
  - `const breakdown = useMemo(() => buildBreakdown(datasetVersion.statements, datasetVersion.parties, toMatchScoreAnswers(state), ranking.map((p) => p.partyId)), [state, datasetVersion, ranking]);`
  - pass `breakdown` to `EndScreen`, which renders `<ResultsBreakdown rows={breakdown} />` at the place given in Decisions.

## Expected File Changes
- Create: `packages/core/src/domain/breakdown.ts`, `packages/core/test/domain/breakdown.test.ts`, `apps/web/src/features/scale-labels.ts`, `apps/web/src/features/results/ResultsBreakdown.tsx`, `apps/web/src/features/results/ResultsBreakdown.test.tsx` (component), `apps/web/src/features/results/ResultsBreakdownFlow.test.tsx` (Scenarios 1–7 through `App`, with its own copy of the `routes`/`renderAt` helpers).
- Modify:
  - `packages/core/src/index.ts`: exports;
  - `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: the edits listed above only;
  - `apps/web/src/ui/components.css`: append the breakdown block, and add `summary:focus-visible` to the focus rule;
  - `apps/web/src/features/methodology/MethodologyPage.tsx` and its test: present tense, see Documentation;
  - docs below, `PROGRESS.md`, `feature_list.json`.
- Unchanged: `QuestionnairePage.test.tsx`, `ResultsRanking.*`, `fetch-mocks.ts`, `tokens.css`, everything in Python. Existing tests must pass unmodified.

## Visual Design Impact
- UI: yes. Source: `DESIGN.md` (Breakdown row, quote typography `--font-quote` 15px, 720px column, 48px targets, amber only for Important and focus, no party colours). No new token.
- `.breakdown`: list reset, grid, 16px gap. `.breakdown-row`: the same card style as `.ranking-row`. `.breakdown-row__number`: `--color-secondary`, 15px. h4 at body size, weight 600.
- `.breakdown-positions`: list reset, grid, 8px gap. `.position`: 1px `--color-border`, `--radius-md`, surface.
- `.position__summary`: `list-style: none`, `::-webkit-details-marker { display: none }`, flex with wrap, `min-height: 48px`, padding 8px 16px, `cursor: pointer`, the chevron, name 600, short name `--color-secondary`, value `margin-left: auto`, weight 600.
- `.position__body`: padding 0 16px 16px. `.evidence__quote`: Georgia (`var(--font-quote)`), 15px, `margin: 0 0 8px`, `padding-left: 12px`, `border-left: 3px solid var(--color-border)`, `overflow-wrap: anywhere`.
- `.important-mark`: like `.coverage-badge`, but with a 1px `--color-accent` border and `--color-text` text.
- At 375px the summary wraps (value under the name) with no horizontal scroll. All Parties look the same in every state.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update.
  - Client-side Matching gets a Breakdown bullet: `breakdown.ts`, `buildBreakdown`, `evidenceHref` rules, the order from `partyOrder`, tests.
  - Web Client's end-screen paragraph gets: `ResultsBreakdown` after the methodology link, details/summary, Party order = ranking, the locator rules, `scale-labels.ts`.
- `CONSTRAINTS.md`: update "Client-side Matching".
  - Extend the results-order rule: "including the Party order inside each breakdown row".
  - Add: "AI-generated text (Statements, Evidence quotes) MUST be rendered as text, never through `dangerouslySetInnerHTML`; Evidence links MUST come from `evidenceHref` (http/https only) and open with `target="_blank" rel="noopener noreferrer"`." Reason: LLM output and Operator URLs are untrusted, and a same-tab navigation loses the Answers.
- `DESIGN.md`:
  - Breakdown row: "Statement, the Voter's answer (Saltada / Importante), and each party's position in ranking order as a native disclosure revealing the Evidence quote (serif) and its locator: a link to `url#page=N`, or the page alone for uploaded documents; `Sin posición en el programa` for no stance."
  - Responsive Baseline: "the breakdown stays stacked at every width (720px column)".
- `MethodologyPage.tsx` (CONSTRAINTS "Public Copy"): replace "Podrás consultar la cita de cada posición para comprobarla." with "En los resultados puedes abrir la posición de cada partido en cada afirmación para leer la cita y comprobarla." Add an assertion for it to `MethodologyPage.test.tsx`. Leave the privacy paragraph alone (owned by `share-link-create`).
- `docs/risks-and-open-questions.md`:
  - replace the entry "Evidence links for uploaded Source Documents (`results-breakdown-evidence`) …" with: "Deferred (`results-breakdown-evidence`): Evidence from uploaded Source Documents shows the quote and its page with no link; URL documents link to `url#page=N` in a new tab. Serving stored PDFs (a public file endpoint) is not built: it needs decisions on manifesto licensing, which documents are public, and caching. Workaround: register manifestos with `source add --url`. No owner yet."
  - add under Risks: "**Evidence links point at a URL's current content (`results-breakdown-evidence`).** A link opens whatever the party's URL serves now. After a re-fetch replaces the document, older Dataset Versions (Share Links, `share-link-open`) may cite a page that no longer matches. Options: serve the stored file of the cited Source Document (see the deferred entry), or a notice when the cited document has been replaced. No owner yet."
- `AGENTS.md`, `CONTEXT.md`: not needed (no workflow or term change; "no stance in the manifesto" is already the domain term).

## Implementation Plan
1. Core: `breakdown.ts` and its tests, then the exports.
2. Web: `scale-labels.ts` and the `SCALE_OPTIONS` change, `ResultsBreakdown` and its component tests, the `QuestionnaireFlow` wiring, CSS, the flow tests, the MethodologyPage copy.
3. `CI=true ./init.sh`, greps, the browser walk-through, then docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks
- [ ] `breakdown.test.ts`:
  - rows follow Statement order with position and text;
  - Answer cases: rating, skip, missing → `null`; `important` true only for rated + flagged (flagged skip → false);
  - string Statement ids match;
  - `partyOrder` order is the same in every row; unknown ids ignored; missing ids appended in input order;
  - the order equals `rankParties(...).map(p => p.partyId)` for a fixture;
  - `no_stance` gives `evidence: null`; a missing Position gives `no_stance`;
  - inputs not mutated.
- [ ] `evidenceHref` tests:
  - `null` url → `null`;
  - `https://x.org/a.pdf`, page 3 → `https://x.org/a.pdf#page=3`;
  - `HTTP://X.ORG/a.pdf` accepted;
  - an existing `#frag` is replaced;
  - query kept;
  - surrounding whitespace trimmed;
  - `javascript:alert(1)`, `ftp://…`, `/relative.pdf`, `""`, and a URL with inner whitespace → `null`.
- [ ] `ResultsBreakdown.test.tsx`:
  - h3 and the intro; `Afirmación n` and the h4 text;
  - answer labels; the Important mark only when `important`;
  - one `<details>` per row × Party, all closed;
  - summary text with scale labels and `Sin posición en el programa`;
  - the quote in `blockquote.evidence__quote`; a quote `<b>x</b>` renders literally;
  - link attributes when `href` is set; the page sentence and no `<a>` when it is not;
  - the `no_stance` sentence;
  - identical class names for every Party item, and no `style` attribute in the breakdown.
- [ ] `ResultsBreakdownFlow.test.tsx`: Scenarios 1–7. Open with `fireEvent.click(summary)` and assert `details.open`. If jsdom does not toggle `<details>`, assert the content inside the closed `<details>` instead, note it in the evidence, and rely on the browser check for toggling.
- [ ] CSS, the MethodologyPage copy and its test, docs.

## Verification Plan
- `CI=true ./init.sh` exits 0: pytest unchanged (966), Vitest = 196 plus the new tests, with QuestionnairePage and ResultsRanking tests unmodified; typecheck and build ok.
- Greps:
  - `grep -rnE "localStorage|sessionStorage|indexedDB|document\.cookie|history\.(push|replace)State" apps/web/src packages/core/src` → tests only;
  - `grep -rn "fetch(" apps/web/src --include=*.ts --include=*.tsx` → `main.tsx` and tests only;
  - `grep -rn "dangerouslySetInnerHTML" apps/web/src` → nothing;
  - `grep -rn "#page=" apps/web/src` → nothing (the href is built in core only).
- No E2E harness. Vitest plus the real-browser check cover the flow.
- **Scratch data** (outside the repo; `SCRATCH=$(mktemp -d <session scratchpad>/rbe-XXXXXX)`, `export SOURCE_FILES_DIR=$SCRATCH/source_files DATABASE_URL=sqlite:///$SCRATCH/check.db`, `I=<worktree>/.venv/bin/ideology`; never a real LLM, no API key):
  1. `$I db upgrade`; `election create --country ES --type general --date 2023-07-23 --name "Generales 2023"`; add the Parties `Partido Alfa` PA (1), `Bloque Beta` BB (2) and `Coalición Gamma` CG (3).
  2. Write the PDFs with `.venv/bin/python -I` and a script that does `sys.path.insert(0, <worktree>)`:
     - `alfa.pdf` and `beta.pdf` from `make_text_pdf(PAGES[1|2])`;
     - `$SCRATCH/pdfs/gamma.pdf` from `make_text_pdf(GAMMA)`, with `GAMMA = ["Planes para transporte y energía.", "Planes para cultura y deporte."]` (no Party names).
  3. Uploads: `source add --party 1 --file alfa.pdf`, `--party 2 --file beta.pdf`.
  4. URL document: start `python3 -m http.server 8022 --bind 127.0.0.1 --directory $SCRATCH/pdfs` in the background (another free port if 8022 is taken). Then `source add --party 3 --url http://127.0.0.1:8022/gamma.pdf` (loopback is allowed, no allow-list).
  5. Pipeline run with a fake provider:
     - The script sets `cli._provider = lambda: fake_provider(party_positions=gaps)`. `gaps(request)` calls `positions_response(fill=True)(request)` and, when any `candidate_lines(request)` quote is in `GAMMA`, drops Statements 3, 10 and 20.
     - Then it calls `cli.main(["pipeline", "run", "--election", "1"])`.
     - Expected: `passed` (30 Statements). Coverage for Gamma is 27/30 and separation holds because Alfa +1 and Beta −1 everywhere.
  6. Confirm with `ideology pipeline positions`: Gamma has `no stance` on 3, 10 and 20 and +1 elsewhere, and its Evidence url is `http://127.0.0.1:8022/gamma.pdf`. If the drop does not match, adjust the script (never the output).
- **Serve:** add a temporary `.claude/launch.json` entry `tmp-results-breakdown-evidence`, per practical-notes: `/usr/bin/env WEB_DIST_DIR=<worktree>/apps/web/dist DATABASE_URL=sqlite:///$SCRATCH/check.db <worktree>/.venv/bin/uvicorn ideology_app.main:app --port 8021`, port 8021, never 8000. Start it with `preview_start` or a background shell.
- **Real browser (mandatory)** at 375x812 and 1280x800, starting from the Landing:
  - **Run A:**
    - Rate 1–5 `De acuerdo`, with 3 flagged Important, and skip 6–30.
    - Ranking: `Coalición Gamma 100 %` (4 en común, `Baja cobertura`), `Partido Alfa 100 %`, `Bloque Beta 50 %`. Every breakdown row lists the Parties in that order.
    - Row 3: `De acuerdo` + `Importante (cuenta el doble)`; Gamma reads `Sin posición en el programa` and opening it shows the `no_stance` sentence.
    - Row 6: `Saltada …`.
    - Open Alfa in row 1: Georgia quote `Propuestas sobre vivienda y alquiler.` and the upload page sentence.
    - Open Gamma in row 2: a link to `http://127.0.0.1:8022/gamma.pdf#page=2`. Clicking it opens a new tab where the PDF viewer shows page 2 of 2 (`window.opener` null), and the results tab is unchanged.
    - Keyboard: Tab to a summary, Enter/Space toggles it, and the amber focus ring shows.
  - **Run B:** reload and skip all 30. The prompt shows, and the breakdown order is `Bloque Beta`, `Coalición Gamma`, `Partido Alfa`, with every answer `Saltada`.
  - **Run C:**
    - From Run A, `Revisar mis respuestas` → set Statement 1 to `Muy en desacuerdo` → walk to the end.
    - Ranking: Alfa 88 % (5.25/6), Gamma 81 % (3.25/4), Beta 54 % (3.25/6). The rows follow that order, and open items stay with their Party.
  - Also check:
    - console clean;
    - network: document, assets, the elections/1 and dataset-versions/1 GETs and nothing after, except the PDF GET in the new tab; no `?` or `#` in any request; the static server log shows only `/gamma.pdf`;
    - URL unchanged; storage, cookies and IndexedDB empty;
    - `scrollWidth <= innerWidth`; summaries and links ≥ 48px;
    - identical Party items; quote `font-family` Georgia; amber only on focus and the Important mark.
- **Cleanup:** stop uvicorn and the static server, restore `.claude/launch.json` (`git checkout .claude/launch.json`), delete `$SCRATCH`. `git status` shows only feature files.

## Evidence To Capture
- `init.sh` steps and the Vitest counts, the new test names, the grep results, and the jsdom `<details>` finding.
- Browser: browser and version, both widths, Runs A–C with the observed order, percentages, labels and hrefs, the PDF page opened, the network, storage and console results, and the cleanup. Record only in `feature_list.json` and `PROGRESS.md`, never in `docs/validations/`.

## Implementation Findings

- `QuestionnairePage.test.tsx` Scenario 4 asserted `screen.queryByRole("list")` is `null` on the all-skipped prompt. With the breakdown on the prompt path (Decisions, Scenario 6) the page has lists there, so that one assertion was narrowed to `queryByRole("list", { name: "Tus resultados" })` (the ranking list), which keeps its intent. No other existing test changed.
- jsdom implements the `<summary>` activation behaviour: `fireEvent.click(summary)` toggles `details.open`, so the flow tests open items for real.
- Open state is not kept across `Revisar mis respuestas`: the end screen unmounts while the Voter is on a Statement, so every item is closed again on return (persisting open state is a non-goal). Run C's "open items stay with their Party" holds only within one end-screen visit; keys by Party id keep it there.

## Validator Checklist
- [ ] Only the listed files changed. No route, dependency, API, Python or migration change. `QuestionnaireFlow.tsx` edits are limited to the listed seams, and the existing tests are unmodified.
- [ ] Rows and hrefs come from `buildBreakdown`/`evidenceHref` in core. Party order equals the ranking in every row. Quotes are rendered as text in Georgia.
- [ ] URL documents link to `url#page=N` with `target="_blank" rel="noopener noreferrer"`. Uploads show the page only. `no_stance` reads `Sin posición en el programa`. Skip and Important are shown as specified.
- [ ] Native `<details>`, 48px targets, no horizontal scroll at 375px, identical Party items.
- [ ] The real-browser Runs A–C pass at 375px and desktop: the link opens the right PDF page, the console is clean, and no request, URL or storage carries Answers.
- [ ] ARCHITECTURE, CONSTRAINTS, DESIGN, the MethodologyPage copy and both risks edits are done as specified. Evidence is recorded.

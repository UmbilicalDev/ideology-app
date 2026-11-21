# Feature Implementation Spec: Three-option answer scale and 'N de M coincidencias' in the ranking

## Source Feature

- `id`: three-option-scale
- `area`: core (and the web views that read the Answer scale)
- `depends_on`: ui-2026-focus-tweaks (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json`; user decisions of 2026-11-21 in `docs/risks-and-open-questions.md` "Voter feedback round 1" (settled, not reopened here)

## Goal

Voters answer each Statement with three options, `De acuerdo`, `Neutral / No lo sé` and `En desacuerdo`. `Neutral / No lo sé` leaves the Statement without a value, so it does not count toward the Match Score. It replaces `skip`. Party Positions stay on the stored −2..+2 scale but are read by side: −2/−1 is against, +1/+2 is in favour, and 0 and `no_stance` are excluded. A Statement scores 1 when the Voter and the Party are on the same side and 0 when they are on opposite sides. The Important weight stays 2. Each ranking row reads `N de M coincidencias` (M = Statements compared with that Party, N = same side) instead of `M afirmaciones en común`. Share Links get a new `v2` layout. A `v1` link opens a clear "earlier version of the questionnaire" message with a `Haz el nuevo cuestionario` link and never a broken page.

The fix comes from a diagnosis: `afirmaciones en común` counted Statements compared, not agreements, so with about 40 % no stance a Party with more stances showed a larger count and a lower affinity.

## Non-Goals

- No interaction redesign: no auto-advancing answer buttons, no `Anterior` at the top, no clearing on back, no `Repetir cuestionario` and no Important cap of one third. All of that belongs to `questionnaire-quick-answer`. `Revisar mis respuestas` stays.
- No removal of the matrix, filters, cards or inspector (`results-party-agreements`). They only adapt to three values.
- No pipeline, Validation, API, DB or Dataset Version change. Stored Positions stay −2..+2.
- No decoding of `v1` links into a result (decided below).
- No re-recording of the Landing videos (see Durable Documentation Impact).

## Decisions Taken In This Spec

1. **Saltar is removed now, not in `questionnaire-quick-answer`.** The user settled that Neutral replaces Saltar. Keeping the button would mean two controls for one meaning, or a `skip` value the `v2` layout would have to encode only to throw away one feature later. Removing it now keeps the Answer type at exactly three values in core, the codec and the views. The cost is that until `questionnaire-quick-answer` lands, Neutral takes a select plus `Siguiente` (two taps, where Saltar took one). The two features ship to production together, so Voters never see that interim state. The controls row becomes `Anterior` / `Siguiente`, and the skipped note `Has saltado esta afirmación.` goes.
2. **`v1` links are not decoded into a result.** Mapping v1 to sides (a,b→against, c,s→neutral, d,e→in favour) is technically cheap. But the mapped result would differ from what the sharer saw: the five-point percentages change, and the per-Statement 75/50/25 grades vanish. That would quietly break the Share Link promise of "the same result". The user's chosen message is the honest outcome.
3. **Party Positions are displayed by side** in the matrix, cards and inspector: +1/+2 `De acuerdo`, −1/−2 `En desacuerdo`, 0 `Neutral`. Showing `Muy de acuerdo` would suggest intensity counts when it does not. The Evidence quote keeps the nuance. The double-thumb icons are no longer used for values.
4. **The `Saltadas` filter is dropped.** No skip value exists any more, so the chip would always count 0. `Neutral` covers those Statements. Filters: `Todas`, `De acuerdo`, `Neutral`, `En desacuerdo`, `Importantes`.
5. **An Important flag on a Neutral Answer is kept** in state and in the link, the same way a flagged skip was kept before. The engine ignores it, and the summary counts only Important flags on De acuerdo and En desacuerdo Answers.

## Job Story

When I answer the questionnaire and read my results,
I want three plain options and a ranking that says how many of the compared Statements I share with each Party,
so the count and the percent tell the same story and I am not forced to grade intensity.

## Users And Permissions

- Voter (anonymous): the only actor. Answers stay in memory, and only the URL fragment carries them (CONSTRAINTS.md "Client-side Matching").

## Acceptance Scenarios

### Scenario 1: Engine reads sides
Given Answers `{s1: 1}`, `{s2: -1, important}`, `{s3: "neutral"}`, `{s4: 1}`, `{s5: 1}` and Party positions `s1: 2`, `s2: 1`, `s3: -2`, `s4: 0`, `s5: no_stance`
When `computeMatchScore` runs
Then s1 counts 1 (weight 1) and s2 counts 0 (weight 2), while s3 (neutral), s4 (position 0) and s5 (no stance) are excluded
And `matchScore` = 1/3, `comparedStatementCount` = 2, `coincidenceCount` = 1, `lowCoverage` = true (2 < 5).

### Scenario 2: All neutral gives no ranking
Given every Answer is `neutral`
Then every Party has `matchScore: null`, `comparedStatementCount: 0`, and the end screen shows the "no results" prompt with no ranking and no share card, as today.

### Scenario 3: Questionnaire shows three options and no Saltar
Given any Statement
Then the radiogroup has exactly `De acuerdo`, `Neutral / No lo sé`, `En desacuerdo` in that order (thumb up, up-down and thumb down icons)
And there is no `Saltar` button. The row holds `Anterior` (from Statement 2) and `Siguiente`
And `Siguiente` stays disabled until an option is chosen. Choosing `Neutral / No lo sé` then `Siguiente` advances.

### Scenario 4: Ranking row reads N de M
Given a finished questionnaire where Party P was compared on 12 Statements and agrees on 9 (none Important)
Then P's row reads `9 de 12 coincidencias` and `75 %`
And with M = 1 it reads `N de 1 coincidencia`. A Party with M = 0 reads `0 de 0 coincidencias`, and in place of the percent it shows `Sin afirmaciones comparables`
And `Baja cobertura` shows exactly when M < 5.

### Scenario 5: Percent is the weighted coincidence share
Given Party P has 3 compared Statements, 2 coincidences of which one is Important, and 1 non-coincidence
Then the percent is round(100 × (2+1)/(2+1+1)) = `75 %`, and the row reads `2 de 3 coincidencias`.

### Scenario 6: Results views adapt
Given the end screen at 1024px or wider
Then the legend shows three stance icons with `De acuerdo` / `Neutral` / `En desacuerdo`, the no-stance dash, and two swatches, `Coincide` and `No coincide`
And each cell is tinted `data-match="100"` (same side), `"0"` (opposite) or `"none"` (neutral answer, position 0 or no stance)
And the cell's name reads e.g. `PSOE: De acuerdo, coincide contigo. Ver la cita` or `…, no coincide contigo. Ver la cita`
And the inspector shows `· coincide contigo` / `· no coincide contigo` (`con el enlace` on a shared result)
And the filters are `Todas`, `De acuerdo`, `Neutral`, `En desacuerdo`, `Importantes`, with counts.

### Scenario 7: New Share Link round trip
Given a finished questionnaire on Dataset Version 5
When the Voter copies the link
Then it is `/resultados#v2-5-<letters>` (one letter per Statement: `d` En desacuerdo, `n` Neutral, `a` De acuerdo; upper case = Important)
And opening it shows the same ranking, the same `N de M` counts and the same breakdown as the end screen.

### Scenario 8: An old v1 link shows the outdated message
Given `/resultados#v1-5-ddcbaeS…`, a link made before this change
When it is opened
Then the page shows a heading `Este enlace es de una versión anterior` and text saying it belongs to an earlier version of the questionnaire and that the app has changed since, so its result can no longer be shown
And a `Haz el nuevo cuestionario` link goes to `/elecciones/<electionId>/cuestionario` of that Dataset Version's Election when that Questionnaire is available, and otherwise to `/`
And a v1 link that is malformed or whose Dataset Version does not exist still shows the same message, with the link going to `/`
And no request carries the answer letters (only `GET /api/v1/dataset-versions/5` and `GET /api/v1/elections/<id>`).

### Scenario 9: Other fragments keep their behaviour
Given `#v3-…` (a newer marker) Then the existing "versión más reciente" message shows
Given `#v2-` with a bad letter, a wrong count or an empty fragment Then the existing invalid/missing messages show.

### Scenario 10: Public copy
Given `/metodologia` Then "Cómo se calcula la afinidad" states the three options, the reading by side, 1/0 per Statement, Neutral and no stance excluded, Important counting double, and `N de M coincidencias`. It no longer mentions 25-point steps or skipping
And the Landing step 1 points no longer say `Elige tu grado de acuerdo` or `Puedes saltarte las que quieras`.

## Repository Research

### Files Inspected

- `packages/core/src/domain/match-score.ts`: `SKIP`, `ScaleValue`, `Answer`, `statementAgreement` (`1 − |a−p|/4`), `score()` returns `sharedStatementCount`. It has no imports (CONSTRAINTS), and runtime checks stay because input comes from untrusted fragments.
- `packages/core/src/domain/questionnaire.ts`: `AnswerValue = ScaleValue | SKIP`, `select`/`skip`/`next`/`back`/`first`/`toggleImportant`, and `summarize` → `{answered, skipped, important, total}`.
- `packages/core/src/domain/ranking.ts`: `RankedParty.sharedStatementCount`, `percent = round(matchScore×100)`, sorted by percent, then name (es collation), then id.
- `packages/core/src/domain/breakdown.ts`: `BreakdownRow.answer: ScaleValue | SKIP | null`, and `important` true only when rated.
- `packages/core/src/domain/results.ts`, `shared-result.ts`: unchanged logic.
- `packages/core/src/infrastructure/share-link/share-link-codec.ts`: v1 `^v1-(id)-([a-esA-ES]{1,500})$`, `VERSION_MARKER_PATTERN`, `ShareLinkErrorKind = malformed | unsupported_version | statement_count_mismatch`.
- `packages/core/src/application/open-share-link.ts`: result kinds `missing | invalid | not_found | error | ready`. `isQuestionnaireAvailable` is in `shared-result.ts`.
- `packages/core/src/index.ts`: re-exports `SKIP` and `statementAgreement`.
- Tests: `packages/core/test/{domain/{match-score,questionnaire,ranking,breakdown,results},infrastructure/share-link-codec,application/open-share-link}.test.ts`.
- `apps/web/src/features/scale-labels.ts` and `scale-icons.tsx`: five labels and icons keyed by `ScaleValue`.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: `SCALE_OPTIONS` `[2,1,0,-1,-2]`, the Saltar button (`StepOverIcon`), the skipped note, and `EndScreen` → `ResultsSummary`.
- `apps/web/src/features/results/`: `ResultsRanking.tsx` (`sharedSentence`, `LOW_COVERAGE_EXPLANATION` "Compartes menos de 5…", `Sin afirmaciones en común`), `ResultsSummary.tsx` (skipped copy for the voter and link voices), `breakdown-view.ts` (filters including `skipped`, and `coincidence()` with 100/75/50/25/0), `ResultsMatrix.tsx` (`MATCH_STEPS`, five-value legend, `Saltada` legend item, cell `aria-label`), `Evidence.tsx` (`SKIPPED_LABEL`, `answerLabel`, `ValueIcon` with `StepOverIcon`), `ResultsBreakdown.tsx` (`OWNER_COPY.coincidence`, re-exports `SKIPPED_LABEL`), `EvidenceInspector.tsx` (`· ${coincidencePrefix} ${match} %`).
- `apps/web/src/features/share/SharedResultsPage.tsx`: message switch on `state.kind` and the `UNSUPPORTED` copy. `useSharedResult.ts` passes results through.
- `apps/web/src/features/landing/HowItWorksCarousel.tsx`: step 1 points (lines 33-37) and the `.mp4`/`.webp` recordings in `apps/web/src/assets/how-it-works/`.
- `apps/web/src/features/methodology/MethodologyPage.tsx`: the positions section (line 98, "escala de cinco puntos", which describes extraction and stays true), the matching section (lines 166-184) and the privacy section (lines 195-200, "mismo resultado").
- `apps/web/src/ui/components.css`: `.match-cell[data-match=75|50|25]` (lines 2505-2530) and comments naming Saltar (lines 1279, 1576). `apps/web/src/ui/icons.tsx`: `DoubleThumb*`, `StepOverIcon`.
- Docs: `CONTEXT.md` (Answer, Party Position), `docs/build-brief.md` lines 42 and 45-50, `docs/domain-model.md` lines 52 and 61, `DESIGN.md` lines 178, 185-187, 190-191, 193, 195-197, 207, `ARCHITECTURE.md` lines 135-145 and 169-170, `CONSTRAINTS.md` line 98, `README.md` line 103.
- There is no browser E2E harness (no Playwright). The gate is `CI=true ./init.sh` (pytest, typecheck, Vitest, vite build).

### Existing Patterns To Follow

- Core stays pure, and the web only renders core output (CONSTRAINTS "Client-side Matching": ranking from `rankParties`, both screens from `buildResults`, links only via `encodeShareLink`/`decodeShareLink`/`openShareLink`).
- Labels and icons are defined once (`scale-labels.ts`, `scale-icons.tsx`) and the meaning is in the text.
- Tests query by role and accessible name. Web fixtures come from `test/fetch-mocks.ts`.

## Technical Approach

**Core.**
- `match-score.ts`: replace `SKIP` with `NEUTRAL = "neutral"`. Add `type AnswerSide = -1 | 1` and set `Answer.value: AnswerSide | typeof NEUTRAL`. Keep `ScaleValue` for positions. Add `positionSide(v: ScaleValue): AnswerSide | null` (0 → null). `statementAgreement(answer: AnswerSide, position: ScaleValue): 0 | 1` throws `RangeError` for position 0 or out-of-range input; callers exclude 0 first. `score()` skips neutral, missing, `no_stance` and 0 positions. It counts `comparedStatementCount` (M) and `coincidenceCount` (N), and `lowCoverage = M < threshold`. Rename `sharedStatementCount` to `comparedStatementCount` everywhere. Input validation allows exactly `-1 | 1 | "neutral"` for Answers and `-2..2 | "no_stance"` for positions. Update the header comment.
- `questionnaire.ts`: `AnswerValue = AnswerSide | typeof NEUTRAL`. Remove the `skip` action, and `select` takes `AnswerValue`. `summarize` → `{ answered /* sided */, neutral, important /* sided and flagged */, total }`.
- `breakdown.ts`: `answer: AnswerValue | null`, and `important` is true only for a sided Answer that is flagged.
- `ranking.ts`: `RankedParty` gets `comparedStatementCount` and `coincidenceCount`. Ordering is unchanged.
- `share-link-codec.ts`: `SHARE_LINK_FORMAT_VERSION = 2`. Layout `v2-<id>-<letters>` with letters `[dnaDNA]{1,500}` (`d` −1, `n` neutral, `a` +1). Add error kind `outdated_version` for any fragment whose marker is `v1`, with `ShareLinkError.datasetVersionId?: number` set when `^v1-([1-9][0-9]{0,9})-` parses within range. Markers above 2 are still `unsupported_version`. Update the versioning comment to match the new CONSTRAINTS rule.
- `open-share-link.ts`: new result kind `{ kind: "outdated"; questionnaireElectionId: number | null }`. On `outdated_version` with an id, call `getDatasetVersion(id)` then `getElection(electionId)`. If `isQuestionnaireAvailable`, return that Election id. Any error, a 404 or no id returns `null`. It never throws.
- `index.ts`: export `NEUTRAL`, `AnswerSide`, `positionSide`, and the new kind and type. Drop `SKIP`.

**Web.**
- `scale-labels.ts`: `ANSWER_LABELS` (`-1` En desacuerdo, `neutral` Neutral / No lo sé, `1` De acuerdo) and `stanceSideLabel(ScaleValue)` (De acuerdo / Neutral / En desacuerdo). `scale-icons.tsx`: `SideIcon` for `-1 | 0 | 1` (ThumbDown, ThumbUpDown, ThumbUp). Positions map through their sign. Delete the `DoubleThumb*` icons and `StepOverIcon` from `icons.tsx` if nothing else uses them (check with `rg`).
- `QuestionnaireFlow.tsx`: three options `[1, neutral, -1]`. Remove Saltar, the skipped note and the `StepOverIcon` import. The radio `value` attribute is `"1" | "neutral" | "-1"`.
- `ResultsSummary.tsx`: title `Muestra evaluada: N/T afirmaciones con opinión`. The second line for the voter is `Has respondido «Neutral / No lo sé» en K afirmaciones.` (singular and zero forms as today). For the link: `Se respondió «Neutral / No lo sé» en K afirmaciones.`
- `ResultsRanking.tsx`: meta `N de M coincidencias` (`coincidencia` when M = 1). Null percent: `Sin afirmaciones comparables`. Low-coverage text: `Se pueden comparar menos de 5 afirmaciones con este partido, así que su afinidad se basa en pocos datos.`
- `breakdown-view.ts`: filters without `skipped`, where `agree` is `answer === 1`, `neutral` is `answer === "neutral"` and `disagree` is `answer === -1`. `coincidence()` returns `100 | 0 | null` (null for no Answer, neutral, position 0 or no stance). `stanceLabel` uses `stanceSideLabel`.
- `ResultsMatrix.tsx`: three-icon legend plus the no-stance dash, swatches `Coincide` (100) and `No coincide` (0), no `Saltada` item. Cell name `${name}: ${stance}` + (`, coincide contigo` | `, no coincide contigo` | ``) + `. Ver la cita`. The owner copy feeds the wording, so the matrix gets the owner prefix pair from `ResultsBreakdown`.
- `Evidence.tsx`: replace `SKIPPED_LABEL` with `NEUTRAL_LABEL = "Neutral / No lo sé (no cuenta para la afinidad)"`. `ValueIcon` shows the side icon. `ResultsBreakdown.tsx`: `OWNER_COPY.coincidence` becomes `{ yes: "coincide contigo", no: "no coincide contigo" }`, and `{ yes: "coincide con el enlace", no: "no coincide con el enlace" }` for the link. `EvidenceInspector.tsx` renders `· <yes|no>`.
- `components.css`: delete the `data-match` 75/50/25 rules and fix the Saltar comments.
- `SharedResultsPage.tsx`: add an `outdated` case. It is a `card shared-notice` section with h2 `Este enlace es de una versión anterior`, the text `Este resultado se hizo con una versión anterior del cuestionario. La aplicación ha cambiado desde entonces y ya no puede mostrarlo.`, a `button-primary` `Link` `Haz el nuevo cuestionario` to `questionnairePath(id)` or `/`, and `HomeButton`.
- `HowItWorksCarousel.tsx` step 1 points: `Responde «De acuerdo», «En desacuerdo» o «Neutral / No lo sé».`, `Si no lo tienes claro, elige «Neutral / No lo sé».`, and keep the Important point.
- `MethodologyPage.tsx`: rewrite "Cómo se calcula la afinidad" per Scenario 10. Explain that with Important Statements the percent is weighted, so it can differ slightly from N/M. In the positions paragraph, add that for the affinity only the side of the position counts. In "Tus respuestas", add that links made before this change open a notice instead of the result. Keep the provisional-copy comment.

## Expected File Changes

- Core, modify: `match-score.ts`, `questionnaire.ts`, `breakdown.ts`, `ranking.ts`, `share-link-codec.ts`, `open-share-link.ts`, `index.ts`. `results.ts` and `shared-result.ts` only if types force it.
- Core tests, modify: the seven test files listed above. The new cases are Scenarios 1, 2 and 5, the summary counts, the v2 round trip, every v1 variant giving `outdated_version` (with and without a parseable id), and the `outdated` kind with available, unavailable, 404 and network-error Elections.
- Web, modify: `scale-labels.ts`, `scale-icons.tsx`, `ui/icons.tsx`, `QuestionnaireFlow.tsx`, `ResultsSummary.tsx`, `ResultsRanking.tsx`, `breakdown-view.ts`, `ResultsMatrix.tsx`, `Evidence.tsx`, `ResultsBreakdown.tsx`, `EvidenceInspector.tsx`, `SharedResultsPage.tsx`, `HowItWorksCarousel.tsx`, `MethodologyPage.tsx`, `ui/components.css`.
- Web tests, modify: `QuestionnairePage.test.tsx`, `ResultsRanking.test.tsx`, `ResultsBreakdown.test.tsx`, `ResultsBreakdownFlow.test.tsx`, `ResultsMatrix.test.tsx`, `ShareApp.test.tsx`, `ShareResults.test.tsx`, `SharedResultsPage.test.tsx` (outdated case: heading, link target for both branches, no answer letters in any request URL), `app/App.test.tsx`, `HowItWorksCarousel.test.tsx`, `MethodologyPage.test.tsx`. Every test that clicks `Saltar` switches to selecting `Neutral / No lo sé` and pressing `Siguiente`.
- Docs: see Durable Documentation Impact. Status and evidence go in `feature_list.json` and `PROGRESS.md`.

## Visual Design Impact

- UI involved: yes. The source is `DESIGN.md`, and no new design artifact is needed. The components already exist; only their contents change.
- States: three scale options, a two-button controls row (on Statement 1 only `Siguiente`, taking the full row), the summary card, ranking meta, legend, two-step cell tint, filters, inspector line, and the outdated-link notice (same style as the superseded notice).
- Party treatment stays identical. The tint stays the single accent, never a colour per side.

## Durable Documentation Impact

- `CONTEXT.md`: update Answer (three options, Neutral = no value, no skip) and Party Position (stored on −2..+2 and read by side for matching, with 0 excluded). Add a "Coincidence" note under Match Score: N of M.
- `docs/build-brief.md`: rewrite the Matching Rule (sides, 1/0, Neutral, 0 and no stance excluded, weight 2, `N de M coincidencias`, low coverage on M < 5) and update line 42.
- `DESIGN.md`: Buttons (drop Saltar), Statement card (3-option scale, no skipped note, `Anterior` / `Siguiente`), Step transition, Scale option order (`De acuerdo`, `Neutral / No lo sé`, `En desacuerdo`), Summary card, Ranking row (`N de M coincidencias`), Breakdown filters, Statement matrix legend and tint, Inspector (`coincide contigo`), Icons (side icons), and the outdated-link notice under Core Screens 5.
- `CONSTRAINTS.md`: update the line 98 rule. Layout changes still need a new marker, and decoders must accept every earlier marker, unless a user decision retires one. A retired marker must be recognised and opened as the outdated-version message, never a generic error (`v1` retired 2026-11-21, `three-option-scale`). The Public Copy rule is unchanged but applies.
- `ARCHITECTURE.md`: update the Client-side Matching bullets (exports, inputs, `comparedStatementCount`/`coincidenceCount`, questionnaire actions, codec v2 and `outdated_version`, the `outdated` kind) and the Questionnaire and Shared result bullets.
- `docs/domain-model.md`: lines 52 and 61, from "skips" to "answers Neutral". Add the scenario of opening a `v1` link and getting the outdated notice.
- `README.md`: line 103.
- `AGENTS.md`: not needed.
- `docs/risks-and-open-questions.md`: edit "Voter feedback round 1". Line 71 becomes settled (v1 not decoded, with the reason from Decision 2). Line 76 should name step 2 too (see open questions). Add the open questions below.
- Recordings: none re-recorded here. Step 1 (five options, Saltar) is re-recorded by `questionnaire-quick-answer`, which ships with this feature. Steps 2 and 3 show `afirmaciones en común` and graded cells until re-recorded. Record this as an Accepted Low on the line-192 entry.

## Implementation Plan

1. `./init.sh` baseline.
2. Core engine, questionnaire, breakdown and ranking, with tests (red then green).
3. Codec v2 and v1 → `outdated_version`, then `openShareLink` `outdated`, with tests.
4. Web labels and icons, questionnaire, summary, ranking, breakdown, matrix, inspector and CSS, with tests.
5. Shared page outdated notice, carousel copy and methodology copy, with tests.
6. Docs (above), then `CI=true ./init.sh`.
7. Browser walk, then evidence in `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks

- [ ] Engine: `NEUTRAL`, `AnswerSide`, `positionSide`, the 0/1 `statementAgreement`, and M/N counts.
- [ ] Questionnaire: no `skip`, and the `summarize` neutral count.
- [ ] Breakdown and ranking fields.
- [ ] Codec v2 and `outdated_version` with an optional id. `openShareLink` `outdated`.
- [ ] `index.ts` exports. `rg -n "SKIP|sharedStatementCount|skipped" packages apps/web/src` has no hits.
- [ ] Web components and CSS per the Technical Approach.
- [ ] `SharedResultsPage` outdated notice.
- [ ] Carousel and methodology copy, plus their tests.
- [ ] Docs, CONSTRAINTS and risks edits.

## Verification Plan

- `CI=true ./init.sh` exits 0, with the Vitest count changed by the new and removed cases.
- `rg -n "Saltar|Saltada|saltad|afirmaciones en común|Muy de acuerdo|Muy en desacuerdo|cinco puntos" apps/web/src DESIGN.md README.md CONTEXT.md docs/build-brief.md` shows only intended hits (e.g. the methodology extraction sentence, if kept).
- Browser (required by AGENTS.md): `npm run build`, then `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app`, and open `http://127.0.0.1:8000/` at 375×812 and 1280×800:
  1. Landing step 1 copy.
  2. 2026 Questionnaire: three options, no Saltar, Siguiente disabled until a choice, Neutral then Siguiente advances, Anterior keeps the choice, Important on a Neutral Statement.
  3. End screen: summary neutral count, ranking `N de M coincidencias` (check one row by hand against the matrix), the `Baja cobertura` rule, filters and counts, cell tint 100/0/none, inspector `coincide contigo`, cards at 375.
  4. Copy the link: `#v2-5-…`. Open it to see the identical ranking and counts, with `con el enlace` wording.
  5. Open `/resultados#v1-5-` followed by 32 v1 letters: the outdated notice, and `Haz el nuevo cuestionario` goes to `/elecciones/2/cuestionario`. A v1 link to a nonexistent version (`#v1-999999-ab`) and a junk v1 link (`#v1-x`) show the notice, with the link going to `/`.
  6. `/metodologia` copy.
  7. Console has no errors, no request failed unexpectedly, and the Network panel shows no request containing answer letters or a fragment.
- E2E: there is no persistent harness. Core and component tests plus the real-browser walk cover this feature.

## Evidence To Capture

- `CI=true ./init.sh` result with pytest and Vitest counts.
- Browser name, widths, and the result of each walk step. One hand-checked row (Party, N, M, percent). The v2 link prefix seen. The outdated-link targets for both branches.

## Validator Checklist

- [ ] Scenarios 1-10 pass, with the engine tests covering same side, opposite side, neutral, 0, no stance and the Important weight.
- [ ] No Saltar anywhere in the UI, and no auto-advance or Important cap (out of scope).
- [ ] The matrix, filters and inspector still exist and read three values.
- [ ] The v1 notice is never a broken page, and the new-questionnaire link works.
- [ ] CONTEXT, build-brief, DESIGN, CONSTRAINTS, ARCHITECTURE, domain-model, README and risks are updated, and the methodology copy matches the engine.
- [ ] Real-browser evidence at 375px and desktop is recorded, with no answers in any request. No `docs/validations/`.

## Open Questions (not settled by the docs; flagged, not decided)

1. **Separation check vs sides.** Validation's separation check (and Statement Selection) counts distinct values, so a Statement where every positioned Party is +1 or +2 passes but separates no one under the side rule. This needs a pipeline owner (e.g. `pipeline-statement-priority-tiers`). Add it to the risks doc.
2. **Weighted percent vs N/M.** With Important flags, a Party with more coincidences can rank below one with fewer (e.g. `4 de 5` at 67 % vs `3 de 4` at 75 %). The methodology explains it, but the user may want something else (e.g. N weighted too). Revisit with the Important cap in `questionnaire-quick-answer`.
3. **Step 2 recording owner.** The ranking recording shows `afirmaciones en común`, and no planned feature re-records step 2. Proposed owner: `results-party-agreements`, which changes the ranking rows anyway.

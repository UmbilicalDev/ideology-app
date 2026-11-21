# Feature Implementation Spec: Answer buttons that advance, back means re-answer, 'Repetir cuestionario'

## Source Feature

- `id`: questionnaire-quick-answer
- `area`: web, plus the pure questionnaire reducer in `packages/core`
- `depends_on`: three-option-scale (accepted; PR #110 into `v2`, this branch is stacked on it)
- `status`: not_started at planning time
- `source`: `feature_list.json`; user decisions of 2026-11-21 in `docs/risks-and-open-questions.md` "Voter feedback round 1" (settled, not reopened here), including the three answers the user gave to this spec's first draft (button order, Neutral label, confirmation on `Repetir cuestionario`)

## Goal

Answering takes one tap. The radio scale and the `Anterior` / `Siguiente` row go away. The bottom of the Statement card holds three answer buttons in the order `En desacuerdo`, `Neutral`, `De acuerdo`. A tap records the Answer and shows the next Statement (or the end screen after the last one). A small `Anterior` at the top of the card goes back one Statement and clears that Statement's Answer, so it must be answered again. The Important toggle stays (pressed before answering, weight 2), but at most `ceil(n/3)` Statements can be marked, and at the cap the toggle says why it does nothing. `Revisar mis respuestas` is replaced by `Repetir cuestionario`. After a short confirmation dialog, it starts over from Statement 1 with no Answers and no flags. The Landing step 1 recording is re-recorded.

## Non-Goals

- No change to the matching rule, the engine, the ranking, the breakdown, the matrix or the inspector. The weighted percent vs N/M question is deferred (Decision 6).
- No Share Link change: format stays `v2`. The decoder keeps accepting any number of upper-case letters, including an upper-case `n`, so links made under `three-option-scale` still open (Decision 5).
- No length picker or context note (`questionnaire-length-and-context`). The cap is written as a function of the Statement count so that feature can reuse it.
- No re-recording of Landing steps 2 and 3 (`results-party-agreements`).
- No visible Important counter beyond the hint and the cap message.
- No reordering of the results legend or the breakdown filters (see Open Question 1).

## Decisions Taken In This Spec

1. **Button order (user decision 2026-11-21).** Left to right the buttons read `En desacuerdo` · `Neutral` · `De acuerdo`, and DOM and Tab order follow. This replaces DESIGN.md "Scale option › Order" (`De acuerdo`, `Neutral / No lo sé`, `En desacuerdo`, from `three-option-scale`), which described the vertical radio stack that this feature removes. The DESIGN rule is rewritten for the answer buttons. The results legend and the breakdown filters keep their current order (`De acuerdo`, `Neutral`, `En desacuerdo`). Whether to align them is flagged in Open Question 1, and this feature does not change them.
2. **Neutral label (user decision 2026-11-21).** Each button shows its side icon above the label. The Neutral button shows `Neutral` on the first line and a smaller `No lo sé` under it. A visually hidden ` / ` sits between them, so its accessible name is `Neutral / No lo sé`, the term the summary, inspector, CONTEXT.md and the Landing quote already use. The other names are `En desacuerdo` and `De acuerdo`.
3. **A Neutral Answer drops the Important flag and frees the slot.** A flag on Neutral has no effect (the engine and `summarize` already ignore it). Letting it use up one of the scarce `ceil(n/3)` slots would penalise the Voter for nothing. The reducer's `answer` action removes the current Statement from `important` when the value is `NEUTRAL`. The cap then counts `state.important.size`, which can only hold flags that can matter, the current Statement's pending flag, and flags left on Statements ahead after `Anterior` (Decision 4). Links made from this flow never carry an upper-case `n`.
4. **`Anterior` clears the Answer but keeps the flag.** The flag is a separate choice made before answering. Keeping it shows the toggle still pressed when the Voter returns, and they can unpress it before re-answering. It also means a back-and-forth never silently changes the cap count. A flag on the Statement being left (pressed, then `Anterior`) also stays and is still pressed on return. Only `Repetir cuestionario` clears all flags.
5. **The cap applies when marking, not when decoding.** `reduceQuestionnaire` refuses to add a flag at the cap, and removing a flag is always allowed. `decodeShareLink` and the shared result do not enforce it, because a link shows what it says. The `v2` layout is unchanged.
6. **Weighted percent vs N/M: explicitly deferred.** It is a matching-rule choice the user owns, and the cap already limits how far the percent can drift from N/M (at most a third of the Statements weigh double). The risks entry is reworded to "revisit after feedback on the cap, together with the remove-Important alternative". No engine or methodology change beyond the cap sentence.
7. **Double-tap guard.** After every move (answer, `Anterior`, `Repetir`), answer buttons and `Anterior` ignore activations for `ANSWER_LOCK.ms` (default 300 ms, longer than the 0.22 s step transition). The check uses `performance.now()` in the click handler. Buttons are not `disabled`, so focus and hover are never lost. A guard in the reducer cannot do this: React re-renders between two taps, so the second tap would carry the new Statement. `ANSWER_LOCK` is a mutable `{ ms }` exported from `features/questionnaire/answer-lock.ts`. `src/test/setup.ts` sets it to 0 before each test, and the double-tap test sets 300 and stubs `performance.now`. Keyboard repeat is covered too, because focus leaves the button on every move.
8. **`Repetir cuestionario` asks first (user decision 2026-11-21).** Pressing it opens a small modal confirmation built the same way as the feedback dialog and the inspector: a native `<dialog>` opened with `showModal()`, so the page behind it is inert.
   - Content: the `h2` `¿Repetir el cuestionario?` (the dialog's `aria-labelledby`) and the text `Se borrarán tus respuestas y el resultado. Copia antes el enlace si quieres guardarlo.` (`aria-describedby`).
   - Buttons, in this DOM order: `Cancelar` (`button-secondary`) and `Sí, repetir` (`button-primary`).
   - Focus starts on `Cancelar`, the safe choice.
   - `Cancelar`, Escape (the `cancel` event, with the default prevented and closed through `close()`) and a backdrop click all close it with nothing changed. Focus then returns to `Repetir cuestionario`.
   - `Sí, repetir` closes it and dispatches `restart`. Focus goes to Statement 1's heading, not back to the trigger.
   - Tab stays inside the dialog: wrap from the last button to the first, as `FeedbackDialog` does.
   - Every close goes through `dialog.close()`, with the follow-up done in the `close` handler, as in `FeedbackButton`.
   - The dialog lives in `features/questionnaire/RestartDialog.tsx` and receives only `onConfirm`, never Questionnaire state.

## Job Story

When I go through the questionnaire on my phone,
I want one tap per Statement and a way to redo the last one,
so I finish quickly and only weigh a few Statements double.

## Users And Permissions

- Voter (anonymous): the only actor. Answers and flags stay in reducer memory. Only a Share Link fragment carries them (CONSTRAINTS.md "Client-side Matching").

## Acceptance Scenarios

### Scenario 1: One tap answers and advances
Given Statement 1 of 3
Then there is no radiogroup, no `Siguiente`, no `Saltar` and no `Anterior`. A group named by the Statement holds three buttons, `En desacuerdo`, `Neutral / No lo sé` and `De acuerdo`, in that order, each with its side icon
When the Voter taps `De acuerdo`
Then Statement 2 shows (`Afirmación 2 de 3`), focus is on its heading, the polite status says `Respuesta guardada: De acuerdo.`, and the Answer for Statement 1 is `1`.

### Scenario 2: Neutral advances without a value
When the Voter taps `Neutral / No lo sé` on Statement 2
Then Statement 3 shows and Statement 2's Answer is `neutral` (excluded from the Match Score, counted in the summary's Neutral sentence).

### Scenario 3: Last Statement goes to the end screen
When the Voter answers Statement 3
Then the end screen shows with focus on `Tus resultados`. The summary reads `Muestra evaluada: 2/3 afirmaciones con opinión`.

### Scenario 4: Anterior clears that Answer
Given Statement 3 is shown and Statements 1-2 are answered
Then `Anterior` (a small control at the top of the card) is present from Statement 2 on, and absent on Statement 1 with the row keeping its height
When the Voter presses `Anterior`
Then Statement 2 shows with focus on its heading, it has no Answer (no button looks chosen, and the summary would not count it), the status says `Respuesta borrada. Vuelve a responder esta afirmación.`, and its Important flag is unchanged
And the invariant `answers.size === currentIndex` holds after every action.

### Scenario 5: Important cap
Given a questionnaire of 32 Statements (cap 11) and the hint under the toggle reads `Las afirmaciones importantes cuentan el doble al calcular la afinidad. Puedes marcar hasta 11.`
When the Voter has marked 11 Statements (each pressed before answering) and reaches Statement 20
Then the toggle has `aria-disabled="true"`, keeps `aria-pressed="false"`, stays focusable, does nothing on activation, and shows visibly (and through `aria-describedby`) `Ya has marcado 11 afirmaciones como importantes, el máximo (un tercio del cuestionario).` (`1 afirmación como importante` when the cap is 1)
And on a Statement that is already marked the toggle stays enabled, so it can be unpressed
And `importantLimit(n)` = `Math.ceil(n / 3)`: 1→1, 3→1, 4→2, 26→9, 32→11, 0→0.

### Scenario 6: Neutral frees the slot
Given 11 of 11 marked, with the 11th pressed on the current Statement
When the Voter taps `Neutral / No lo sé`
Then that flag is dropped, the next Statement's toggle is enabled again, and the end screen's Important count does not include it.

### Scenario 7: Repetir cuestionario, confirmed
Given the end screen
Then `Revisar mis respuestas` is gone and `Repetir cuestionario` (solid) sits in its place, right after the summary
When it is pressed
Then a modal dialog named `¿Repetir el cuestionario?` opens, described by `Se borrarán tus respuestas y el resultado. Copia antes el enlace si quieres guardarlo.`, with `Cancelar` then `Sí, repetir`, and focus on `Cancelar`
When `Sí, repetir` is pressed
Then the dialog closes, and Statement 1 shows with no Answers, no flags (toggle not pressed) and no `Anterior`. Focus is on its heading, and the status says `Cuestionario reiniciado.`.

### Scenario 7b: Repetir cuestionario, cancelled
Given the confirmation dialog is open
When the Voter presses `Cancelar`, presses Escape, or clicks the backdrop
Then the dialog closes, the end screen is unchanged (same ranking, summary and share link), and focus is back on `Repetir cuestionario`
And while it is open, Tab cycles only between `Cancelar` and `Sí, repetir`.

### Scenario 8: All-Neutral prompt
Given every Answer is Neutral
Then the end screen reads `Todavía no se puede calcular tu afinidad: no has respondido con opinión ninguna afirmación en la que los partidos tengan posición. Pulsa «Repetir cuestionario» y responde al menos una con «De acuerdo» o «En desacuerdo».`, with no ranking and no share card.

### Scenario 9: Double tap answers one Statement
Given Statement 4 is shown
When `De acuerdo` is activated twice within 300 ms (double tap, or double click)
Then only Statement 4 is answered and Statement 5 shows unanswered. A tap after the lock answers Statement 5.

### Scenario 10: Keyboard and motion
Given a keyboard user
Then Tab order is `Anterior` → (heading, when it holds focus) → Important toggle → the three answer buttons. Enter or Space on an answer advances, and focus lands on the new heading, which is described by `Afirmación N de M`
And the step transition (only the Statement and the Important row slide, 16px over 0.22s; the controls row and the `Anterior` row never move) has no animation under reduced motion.

### Scenario 11: Share Link unchanged
Given a finished questionnaire
Then `Copiar enlace` gives `/resultados#v2-<id>-<letters>` that opens the same result, and no request carries an answer letter.

### Scenario 12: Landing step 1
Given `/`
Then step 1 points read `Pulsa «En desacuerdo», «Neutral» o «De acuerdo» y pasarás a la siguiente.`, `Si no lo tienes claro, elige «Neutral / No lo sé».` and `Antes de responder, marca como importantes las que más te importan (hasta un tercio).`
And the recording (dark and light) shows the answer buttons, the Important toggle and the auto-advance, and no radio scale, `Saltar` or `Siguiente`.

## Repository Research

### Files Inspected

- `packages/core/src/domain/questionnaire.ts` — actions `select`/`next`/`back`/`first`/`toggleImportant`. The invariant comment covers Statements before `currentIndex`. Also `summarize` and `toMatchScoreAnswers`.
- `packages/core/test/domain/questionnaire.test.ts`, `packages/core/test/domain/ranking.test.ts` (lines 208-217 dispatch `select`/`next`).
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx` — `SCALE_OPTIONS`, the radiogroup, `step-controls`, `move()` with `focusPending` and the heading focus effect, `ImportantToggle` (tooltip hint `#important-hint`, flash), `EndScreen` with `Revisar mis respuestas` (`onFirst`), and `NO_RESULTS_PROMPT`.
- `QuestionnairePage.tsx` (loader only, unchanged) and `QuestionnairePage.test.tsx` (`backToLast` via Revisar, `radio()`).
- Tests that walk the questionnaire with radios plus `Siguiente`: `app/App.test.tsx`, `donate/DonationBlock.test.tsx`, `results/ResultsBreakdownFlow.test.tsx` (also asserts `NO_RESULTS_PROMPT`), `share/ShareApp.test.tsx`, `share/SharedResultsPage.test.tsx`, `share/ShareResults.test.tsx`.
- `apps/web/src/features/results/ResultsSummary.tsx` — unchanged (its copy already says `con opinión`).
- `apps/web/src/features/scale-labels.ts`, `scale-icons.tsx` (`SideIcon`, `answerSide`).
- `apps/web/src/ui/components.css` — `.statement-step[data-enter]` (1278-1308), `.scale` and `.scale-option*` (1346-1430), `.important-toggle` (1443+), `.questionnaire__controls`, `.step-controls` (1558-1591), `.results-dashboard .questionnaire__controls` (2217). `tokens.css` — `--button-height-tall` 52/56px.
- `apps/web/src/features/landing/HowItWorksCarousel.tsx` (step 1 points, lines 33-37) and `assets/how-it-works/answer-{dark,light}.{mp4,webp}`.
- `apps/web/src/features/methodology/MethodologyPage.tsx` lines 172-188 (matching section).
- `feature_list.json` `landing-carousel-scale-order` evidence and notes. Recipe: Playwright driving the installed Chrome at 1080x720, with a scripted on-page cursor, against uvicorn and the shared DB, encoded with imageio-ffmpeg in a throwaway venv. The script is not committed.
- Docs: DESIGN.md lines 125-126, 174, 178, 182, 185-188, 193, 214, 272. CONTEXT.md (Answer, Important). ARCHITECTURE.md lines 139, 169. docs/domain-model.md lines 52, 61. docs/build-brief.md line 42. README.md line 103. Risks lines 69-70, 77-78, 195.
- There is no browser E2E harness. The gate is `CI=true ./init.sh`.

### Existing Patterns To Follow

- The core reducer is pure and the web dispatches actions. Focus follows navigation via `focusPending` plus the effect on `currentIndex`, not on the first load.
- Tests query by role and accessible name, with fixtures from `test/fetch-mocks.ts`.
- Equal treatment: every answer button has identical markup and style. The side is carried by text and icon, never colour.

## Technical Approach

**Core (`questionnaire.ts`).**
- Actions become `answer {value: AnswerValue}`, `back`, `restart` and `toggleImportant`. Remove `select`, `next` and `first`. Unknown actions stay no-ops.
- `answer`: a no-op on the end screen. Otherwise it sets the current Answer, deletes the current id from `important` when `value === NEUTRAL`, and advances by 1.
- `back`: a no-op at index 0 and on the end screen. It goes to `i − 1` and deletes that Statement's Answer, leaving flags untouched.
- `restart`: returns `startQuestionnaire(state.statementIds)`.
- `toggleImportant`: a no-op on the end screen. Removing is always allowed. Adding only happens when `state.important.size < importantLimit(state.statementIds.length)`.
- Export `importantLimit(count) = Math.ceil(count / 3)` and `isImportantCapReached(state)` (`size >= limit`). Update the header invariant to: exactly the Statements before `currentIndex` have an Answer.
- `summarize` and `toMatchScoreAnswers` are unchanged. Update the `index.ts` exports.

**Web (`QuestionnaireFlow.tsx`).**
- Remove `SCALE_OPTIONS`, the radiogroup, `Siguiente` and `onFirst`. `ANSWER_OPTIONS = [-1, NEUTRAL, 1]`.
- The card order is:
  1. A `.statement-card__top` row holding `Anterior` (from index 1; `button-text`-style compact control with `ArrowBackIcon`, `label` type, `text-muted`, accent on hover, min 44px tall, 48px on coarse pointers, an empty placeholder of the same height on Statement 1) and the progress label at the end.
  2. The bar.
  3. The keyed `.statement-step` with the `h2` (`tabIndex=-1`, `aria-describedby="questionnaire-progress"`) and the Important row.
  4. `<div role="group" aria-labelledby="statement-text" class="questionnaire__controls answer-controls">` with three `<button type="button" class="answer-button" data-answer="-1|neutral|1">`.
- Each button holds `SideIcon` (aria-hidden) and a label span. The Neutral button carries a `.answer-button__sub` `No lo sé` and a visually hidden ` / `.
- `move(action)` checks `ANSWER_LOCK`. If unlocked, it sets the lock, `focusPending` and the direction (`back` for `back`, `null` for `restart`, `forward` otherwise), dispatches, and sets the status message.
- A visually hidden `<p role="status">` placed outside the step and the end screen carries the three messages (Scenarios 1, 4 and 7). Clear it before each new message so a repeat is announced again.
- `ImportantToggle` gets `atCap` (the cap is reached and this Statement is not marked) and `limit`. At the cap: `aria-disabled="true"`, the click is a no-op with no flash, and a visible `p#important-cap` with the message is added to `aria-describedby` (`important-hint important-cap`). Hint text: `… Puedes marcar hasta ${limit}.`
- `EndScreen`: `Repetir cuestionario` (`button-primary`, `aria-haspopup="dialog"`) opens `RestartDialog` (Decision 8). Its confirm dispatches `restart` through `move()`. `NO_RESULTS_PROMPT` per Scenario 8.

**CSS.**
- Remove `.scale` and `.scale-option*` (check with `rg` that nothing else uses them) and `.step-controls`.
- `.answer-controls`: a grid of three equal `minmax(0,1fr)` columns, `sm` gap, under the existing hairline.
- `.answer-button`: column flex, icon 32x24 above the label, `surface-sunken` with a `border-control` frame and `md` corners, `min-height: var(--button-height-tall)`. Labels wrap inside the button and the height grows equally for all three. Add `touch-action: manipulation`.
  - Hover (`surface-raised`, `border-strong`) only in `@media (hover: hover)`, so a tap does not leave the next Statement's button looking hovered.
  - `:active`: `accent-soft` with an `accent` frame. Focus ring per DESIGN. Identical for all three.
- Toggle `[aria-disabled="true"]`: the disabled look (`surface-raised`, `text-subtle` label, outline star) and `cursor: not-allowed`. `.important-cap`: `body-sm`, `text-muted`, always visible.
- `.confirm-dialog`: the feedback dialog's look (`surface`, `border-strong` frame, `lg` corners, `shadow-lg`, over the blurred `scrim`), at most 24rem wide, with the buttons in one row of equal columns at 48px on coarse pointers. No entry animation.
- Under reduced motion, keep `animation: none`. The step transition rule is unchanged (only `.statement-step` animates).

**Landing.**
- Step 1 points per Scenario 12.
- Re-record `answer-dark.mp4`, `answer-light.mp4` and their `.webp` posters with the `landing-carousel-scale-order` recipe, against this branch's build (`npm run build`, uvicorn with `DATABASE_URL=sqlite:///data/ideology.db`, 2026 Election):
  - Recording: 1080x720 viewport, `color_scheme` dark then light, scripted on-page cursor. Steps: hover then press `Importante para mí`, tap `De acuerdo` (slides to Afirmación 2), tap `Neutral` (Afirmación 3), hold about 1 s.
  - Encoding: 960x640 H.264, libx264 CRF 26, yuv420p, faststart, 25 fps, about 8 s, no audio. Poster = first frame as WebP q80.
  - Tools go in a throwaway venv in the session scratchpad, never the repo `.venv`. No script and no dependency is committed.
- The implementer makes the recording. If Chrome or Playwright cannot run there, the feature stays `in_progress` with the reason, and the user is asked to record it to the same acceptance. It must not be marked `passing` with the old recording.

## Expected File Changes

- Core: `packages/core/src/domain/questionnaire.ts`, `packages/core/src/index.ts`, and tests `test/domain/questionnaire.test.ts` and `test/domain/ranking.test.ts`.
- Web:
  - `features/questionnaire/QuestionnaireFlow.tsx`
  - `features/questionnaire/answer-lock.ts` (new)
  - `features/questionnaire/RestartDialog.tsx` (new)
  - `ui/components.css`
  - `features/landing/HowItWorksCarousel.tsx`
  - `features/methodology/MethodologyPage.tsx`. Add one sentence: up to a third of the Statements, rounded up, can be marked, and a Neutral Answer drops the mark because it would not count.
  - `assets/how-it-works/answer-{dark,light}.{mp4,webp}` (replaced)
  - `scale-labels.ts` only if a short label constant is added.
- Web tests:
  - New `src/test/questionnaire.ts` helper: `answerButton(name)`, `answerAll(values)`.
  - `src/test/setup.ts`: `ANSWER_LOCK.ms = 0`.
  - Rewrite `QuestionnairePage.test.tsx` per Scenarios 1-10, including 7 and 7b. The dialog stand-ins already exist in `src/test/setup.ts`.
  - Move the other six walking tests to the helper.
  - `ResultsBreakdownFlow.test.tsx`: the prompt copy.
  - `HowItWorksCarousel.test.tsx`, `MethodologyPage.test.tsx`: the new copy.
- Docs: see below. Status and evidence go in `feature_list.json` and `PROGRESS.md`.

## Visual Design Impact

- UI: yes. The source is DESIGN.md. No new design artifact is needed: the buttons reuse the scale-option look (sunken, control frame, side icon).
- States: Statement 1 (no `Anterior`, placeholder), Statement ≥ 2, the toggle normal, pressed, and at cap (aria-disabled plus message), the button `:active`, the end screen with `Repetir cuestionario`, the confirmation dialog at 375px and at desktop width, and the all-Neutral prompt.
- At 375px the three buttons share the row and labels may wrap to two lines. No horizontal scroll.
- Party treatment is unaffected.

## Durable Documentation Impact

- `DESIGN.md`:
  - Neutrality lines 125-126: the scale's meaning is carried by the label and icon (no radio dot).
  - Targets line 174: answer buttons and `Anterior` at 48px on coarse pointers.
  - Buttons line 178: `Repetir cuestionario` replaces `Revisar`, `Siguiente` is gone, add the answer button.
  - Carousel line 182: step 1 shows Important plus answer buttons.
  - Statement card line 185: the top row with `Anterior`, the answer row, and the button order with the Decision 1 note.
  - Step transition line 186: after an answer, `Anterior` or `Repetir`.
  - Replace "Scale option" line 187 with "Answer buttons". The order is `En desacuerdo` · `Neutral` · `De acuerdo` (user decision 2026-11-21, replaces the `three-option-scale` order). Neutral shows a second line `No lo sé`. State that the legend and filters keep their order.
  - Important toggle line 188: the cap state and hint.
  - Dashboard and Core Screens lines 193 and 214: `Repetir cuestionario` and its confirmation dialog. Add a "Restart confirmation" component entry next to "Feedback dialog".
  - Line 272: answer buttons in a labelled group, the focus move and the status line.
- `CONTEXT.md`: Important, capped at a third (rounded up) of the questionnaire's Statements; a Neutral Answer drops it.
- `ARCHITECTURE.md`: line 139 (the new actions, `importantLimit`, `isImportantCapReached`, the invariant) and line 169 (answer buttons, `Anterior` row, status region, `ANSWER_LOCK`, `Repetir`).
- `docs/domain-model.md`: line 52 becomes "marks 5 Important and answers Neutral on 3 of them; those 3 marks are dropped". Line 61 prompt: "repeat the questionnaire".
- `docs/build-brief.md` line 42: Important (up to a third), one tap per Answer.
- `README.md` line 103: buttons that advance, `Anterior` re-answers, Important up to a third, `Repetir cuestionario`.
- `CONSTRAINTS.md`: not needed, because no new MUST. The memory-only and fragment-only rules already cover this.
- `AGENTS.md`: not needed.
- `docs/risks-and-open-questions.md`:
  - Lines 69-70: implemented by this feature.
  - Line 77: step 1 re-recorded.
  - Line 78: deferred per Decision 6.
  - Line 195: Accepted Low narrowed to steps 2-3.
  - The three user decisions of 2026-11-21 on this spec (button order, Neutral label, confirmation) are already recorded as Decided entries in "Voter feedback round 1".
  - Add Open Question 1 below if it is still open when the implementation lands.

## Implementation Plan

1. `./init.sh` baseline.
2. Core reducer, cap and tests (red, then green). Update `ranking.test.ts`.
3. `answer-lock.ts`, the test setup and the shared test helper.
4. `QuestionnaireFlow` (buttons, top `Anterior`, status, toggle cap, end screen, prompt) and CSS, with the rewritten `QuestionnairePage.test.tsx`.
5. Migrate the other walking tests, then the carousel and methodology copy with their tests.
6. Docs, then `CI=true ./init.sh`.
7. Re-record step 1 (dark and light), then rebuild.
8. Browser walk, then evidence in `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks

- [ ] Reducer: `answer` (Neutral drops the flag), `back` clears, `restart`, the capped `toggleImportant`, `importantLimit`, `isImportantCapReached`. Tests cover Scenarios 4-7, the invariant property over random action sequences (seeded), and end-screen no-ops.
- [ ] `rg -n '"select"|"next"|"first"|Revisar mis respuestas|step-controls|scale-option|radiogroup' packages apps/web/src` shows only intended hits.
- [ ] Answer buttons, the `Anterior` row, the status region, focus and the double-tap lock.
- [ ] Toggle cap state, hint and message. `Repetir cuestionario` with `RestartDialog`, covering confirm, cancel, Escape, backdrop, focus and the Tab wrap. The all-Neutral prompt.
- [ ] CSS per the Technical Approach.
- [ ] Carousel copy and recordings. Methodology sentence.
- [ ] Docs and the risks edits.

## Verification Plan

- `CI=true ./init.sh` exits 0. The Vitest count changes with the rewritten and new cases. The feature's Vitest list is covered: advance, `Anterior` clears, Neutral leaves no value, no `Saltar`, cap = ceil(n/3), and `Repetir` resets Answers and flags.
- Browser (required by AGENTS.md): run `npm run build`, then `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app`. Check 375x812 and 1280x800, each in light and dark:
  1. Landing step 1: copy, the new recording for the theme (check `currentSrc`), and reduced motion shows the paused poster.
  2. 2026 Questionnaire (32 Statements, cap 11) with the pointer. Scenarios 1-4 and 6, then mark 11 and see Scenario 5 at a twelfth Statement. Double-click an answer (Scenario 9). Labels fit at 375 with no horizontal scroll (`scrollWidth` 375).
  3. Keyboard only: Tab order, Enter and Space answer, focus on the new heading after each move, and focus on `Tus resultados` at the end. A screen-reader check is optional; at least confirm the `role="status"` text changes.
  4. Reduced motion (emulated): no step slide.
  5. End screen: `Repetir cuestionario` opens the dialog. `Cancelar`, Escape and a backdrop click each keep the result and return focus to the button (Scenario 7b). `Sí, repetir` resets (Scenario 7). Check with the pointer and the keyboard, at 375 and 1280. All-Neutral run gives the Scenario 8 prompt. Copy a link (`#v2-5-…`) and open it to see the same result.
  6. Console has no errors. The Network panel shows no request with answer letters or a fragment. Storage is empty.
- E2E: there is no persistent harness. Reducer and component tests plus the real-browser walk cover this.

## Evidence To Capture

- `CI=true ./init.sh` counts.
- Browser name, widths, themes, and the result of each walk step: the cap seen at 11, the double-click result, the focus targets, and the link prefix.
- Recording facts: duration, size, dimensions, the poster, the tool versions, and that they ran in a throwaway venv.

## Validator Checklist

- [ ] Scenarios 1-12 pass. No radio scale, `Siguiente`, `Saltar` or `Revisar mis respuestas` anywhere.
- [ ] The cap and the Neutral/back flag rules match Decisions 3-5. The Share Link is still `v2`, and old `v2` links with upper-case `n` still open.
- [ ] Engine, ranking and matrix are untouched (Decision 6). The legend and filter order are unchanged.
- [ ] `Repetir cuestionario` always confirms first. Cancelling never loses the result.
- [ ] Step 1 recording replaced in both themes to the recipe's specs.
- [ ] Real-browser evidence at 375px and desktop, light and dark, pointer and keyboard, reduced motion, console clean, no answers in requests. No `docs/validations/`.

## Open Questions (not settled by the docs; flagged, not decided)

1. **Results legend and filter order vs the answer row.** The Questionnaire now reads `En desacuerdo · Neutral · De acuerdo` left to right. The matrix legend and the breakdown filters still read `De acuerdo, Neutral, En desacuerdo`. Aligning them would make the order consistent across screens. `results-party-agreements` removes the matrix and filters from the results anyway, so this feature does not touch them. It is flagged for the user, not changed.

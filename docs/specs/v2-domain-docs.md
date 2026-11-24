# Feature Implementation Spec: Domain docs for constituencies, Proposals and guided ingestion

## Source Feature

- `id`: v2-domain-docs
- `area`: docs
- `depends_on`: none
- `status`: not_started at planning time (2026-11-24)
- `source`: `feature_list.json` (verification: docs reviewed against every decision in "Constituency redesign", with no contradiction left in `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md` or `AGENTS.md`; `CI=true ./init.sh` passes)
- Branch: `feature/v2-domain-docs`, cut from `v2`, merged into `v2` by PR (never `main`).

## Goal

Rewrite the four domain docs so they describe the v2 model the round-2 user decisions (2026-11-24) settled: Constituencies, candidatures, Proposals, the Ingestion Ledger and its phases, Excluded Parties, per-Constituency validity, Operator conflict decisions and Statement Rewording. Every later round-2 spec reads these docs as its base. The source of truth for the decisions is `docs/risks-and-open-questions.md`, section "Constituency redesign (2026-11-24, v2 round 2)". Treat each "Decided" bullet there as settled. Do not decide any "Open" bullet. Reference it by its owning feature instead.

The docs must keep Dataset Versions 1–5 valid. Those versions are immutable, stay readable, and were produced under the old rules. Each changed rule therefore states the **v2** rule and, where it differs, the **Legacy** rule that still describes existing data.

## Non-Goals

- No code, test, migration, `init.sh`, `data/` or web change.
- No change to `CONSTRAINTS.md`, `ARCHITECTURE.md`, `DESIGN.md`, `README.md` or `docs/technical-discovery.md`. Their rules describe code that exists today. Each later feature changes the rules its own code changes (see the handoff list below).
- Do not decide any open question: per-Constituency minimums, topic spread per Constituency, extraction cost or chunking, Proposal grouping, pool size, shared manifestos between candidatures, map source or licence, or the CIS question.
- No storage choices (columns, file formats, state identifiers). The docs name concepts. Each owning feature fixes the identifiers.
- Do not reorder or re-plan `feature_list.json` (only this feature's status and evidence change).

## Job Story

When I plan or implement any round-2 feature,
I want the glossary, domain model and brief to state the v2 rules and mark which old rules still describe Dataset Versions 1–5,
so I can build on one settled model without re-reading chat history or breaking existing data.

## Users And Permissions

- Planner, implementer and validator agents: read the docs. The implementer of this feature edits them.
- No runtime actor is affected.

## Conventions The Edits Must Follow

- **Labels.** Mark v2 rules with **v2** and the owning feature id in backticks, e.g. "(v2, `constituency-selection-validation`)". Mark old rules with an italic lead-in *Legacy (Dataset Versions 1–5):*. Feature status lives in `feature_list.json`, so the docs do not say "planned" or "done".
- **Model generation note.** Add a short note at the top of the `CONTEXT.md` Glossary and of `docs/domain-model.md`. It says: Legacy rules describe Dataset Versions 1–5 (Election 1 = 2023: versions 1–3; Election 2 = 2026: versions 4–5) and the current national pipeline until `statements-from-proposals` and `constituency-selection-validation` replace it. v2 rules describe the Dataset Versions that pipeline produces; the first real one comes from `e2e-2026-constituencies`. Older versions stay readable and are never rewritten. How a Dataset Version is marked as v2 is decided by `constituency-selection-validation`.
- **Share Link layouts.** Always write them as "layout `v1` / `v2` / `v3`", never bare "v2", so they are not confused with the v2 model.
- **Open questions.** Write "open, owned by `<feature>`; see `docs/risks-and-open-questions.md`". Never give a value for them.
- **Style.** Use the domain terms as written in `CONTEXT.md`, keep the existing headings, and do not repeat implementation details that belong to specs.

## Required Edits

### 1. `CONTEXT.md`

New entries (place each near the related term):

- **Constituency**: one of the 52 circunscripciones of the Congreso de los Diputados (50 provinces, Ceuta, Melilla). Congreso only, no Senado. It is reference data with an INE code and a Spanish name (`constituencies-and-candidatures`). A Voter picks it first. Questionnaire, results and Comparador follow it. In a Dataset Version a Constituency is available, or unavailable with a reason (e.g. lack of manifestos): an unavailable Constituency is disabled in the list and the map with that reason, and it never fails a run.
- **Proposal**: a verbatim concrete measure or commitment from a Source Document (a point or paragraph; diagnosis or context only when relevant), with its page, one or more main categories from the topic catalog (`topic-catalog`, usually one) and free secondary tags. It is kept only if its text is on the cited page (the same normalised match as Evidence). It is extracted once per document, reused while the document is unchanged, and extracted incrementally over several runs (`proposal-extraction`). It is never edited. "Propuesta" in Spanish copy.
- **Ingestion Ledger**: the committed per-Election file next to the Source Text Bundle (`ingestion-ledger`). It records, per Party, the phase reached or the Excluded reason, and the Operator's conflict decisions (`proposal-conflicts`). Phases: 1 candidatures per Constituency, 2 provide and review manifestos, 3 extract Proposals, 4 generate Statements. Phase 4 starts only when every Party is Extracted or Excluded and no conflict is pending. The guided procedure that reads it is `ingestion-guide`.
- **Excluded Party**: a Party with no manifesto, a manifesto the Operator discarded at review (no text layer, not a manifesto, clearly incomplete) or a manifesto with fewer than N validated Proposals (configurable, default 30; checked automatically after phase 3). It is recorded with its reason. It appears only in the results note of each Constituency where it runs, never in the ranking and never with a score. *Legacy:* Parties were never excluded (a Party below coverage failed the run). The 2026 note is hard-coded in the web client until `results-by-constituency` reads it from the Dataset Version.
- **Statement Rewording**: an Operator's rewording of a confusing Statement without changing its meaning (`statement-rewording`). It is an input file of a new run, so it produces a new Dataset Version and published versions stay untouched. The AI text, the new text and the reason are stored. Party Positions and Evidence stay unchanged. An automatic LLM equivalence check rejects a rewording that changes the meaning. Voters see only the final text, with no marker. `/metodologia` says the authors may reword AI-generated Statements judged confusing.

Changed entries (v2 rule first, then the *Legacy* line when it differs):

- **Party**: v2 = a candidature with its own name and logo that runs in a list of Constituencies (a regional coalition is its own Party). The Operator enters which Party runs where from the proclaimed candidatures (BOE, source recorded). This is never generated by AI. Inclusion = every candidature with a manifesto of enough content; the others are Excluded Parties. Keep the logo sentence. Candidatures that share a manifesto under different names are open, owned by `constituencies-and-candidatures`. *Legacy:* a ballot ticket with seats from the previous general election, national scope.
- **Source Document**: add that it declares the Constituencies it applies to. A coalition's joint manifesto takes precedence over a member's. Other contradictions between documents of the same Party and Constituency are flagged and decided by the Operator (see Operator). At phase 2 the Operator reviews it and may discard it with a reason. Keep the replacement rule.
- **Statement**: v2 = built from a group of similar Proposals (recording which), carries one category from the topic catalog, and may be valid in some Constituencies only (`statements-from-proposals`). A Statement in a Dataset Version is never edited; a Statement Rewording yields a new Dataset Version. *Legacy:* generated from the Party-balanced Agenda, with a topic tag. Also mark **Party-balanced Agenda**, **Statement Pool** and **Anchor** as legacy pipeline terms. Whether v2 keeps Anchors and how big its pool is are for `statements-from-proposals`.
- **Party Position**: Evidence is now one or more of that Party's Proposals. A Party may be against a Statement only when one of its Proposals backs that. A Party with no related Proposal has no stance. The side reading is unchanged.
- **Evidence**: v2 = one or more of the Party's Proposals (verbatim text, page, Source Document locator). *Legacy:* a verbatim quote plus a locator.
- **Questionnaire**: v2 = the Statements valid in one Constituency of one Dataset Version, in that Constituency's priority order (`constituency-selection-validation`). *Legacy:* one national order per Dataset Version.
- **Questionnaire Length**: v2 = 20, 30, 40 and 50, each offered only when the Constituency has that many valid Statements, or `Todas (N)` when it has fewer than 20. Each is a prefix of the priority order. After the chosen length the Voter may pick `Contestar 5 más`, `Contestar 10 más` (or the exact number left) or `Ver resultado`, repeatedly, so any count may be answered (`questionnaire-length-and-context`). *Legacy:* 15, 30 and the full count, all validated.
- **Important**: v2 = no cap. Any Statement may be Important (weight 2), and a Neutral Answer still drops the flag (`important-unlimited`). *Legacy rule (round 1):* at most a third, rounded up, which the web client enforces until `important-unlimited` lands.
- **Share Link**: v2 = the fragment carries the Dataset Version, the Constituency and the Answers with their Important flags for however many Statements were answered (`share-link-v3`, layout `v3`). Every older layout (`v1`, `v2`, so every link to Dataset Versions 1–5) opens the outdated-version notice. Never stored on the server.
- **Pipeline Run**: v2 = the phase 4 run. It reads the Extracted Proposals, the conflict decisions and any rewording file, builds Statements and Positions, then applies the per-Constituency selection and Validation. Whether phase 3 extraction is recorded as a Pipeline Run is decided by `proposal-extraction`. *Legacy:* agenda → pool → positions → selection.
- **Statement Selection**: v2 = deterministic and Party-identical; per Constituency, a Statement is valid when, among the Parties running there, at least one is in favour and one against. The priority order is computed per Constituency, and a Constituency below the minimums is unavailable with its reason. The minimums and the topic spread are open, owned by `constituency-selection-validation`. Keep the current text as *Legacy*. Replace "Selected Statements are never edited" with the Statement Rewording rule.
- **Validation**: still automatic and the only way to publish. Some checks are per Constituency, where a failure makes that Constituency unavailable rather than failing the run. There is no human review. The only Operator inputs are recorded conflict decisions and Statement Rewordings, which go through a run and Validation.
- **Operator**: v2 duties: declare candidatures per Constituency, provide and review manifestos (discard with a reason), decide flagged contradictions (with a reason), reword Statements through a rewording file, and trigger runs, guided by `ingestion-guide`. The Operator never edits Proposals or Party Positions. Keep the Feedback sentence.

"Rejected / Ambiguous Terms" additions:

- **Propuesta**: means Proposal, not Statement (the UI calls Statements `afirmaciones`).
- **Provincia / circunscripción / distrito**: use Constituency.
- **Candidatura / coalición**: use Party (each candidature is one Party).
- **Edit (a Statement)**: use Statement Rewording. Nothing else is ever edited.
- **Topic / tema / categoría**: a main category of the topic catalog. Secondary tags are free and are not topics.
- **Excluded vs left out**: an Excluded Party is never scored; a Statement left out by Statement Selection is a different thing.

### 2. `docs/domain-model.md`

- **Core Concepts**: add Constituency, Candidature (Election × Party × Constituency, from the BOE, source recorded), Source Document scope (the Constituencies it applies to), Proposal, Ingestion Ledger (per-Party phase or exclusion reason, plus conflict decisions), Conflict (flagged contradiction between Proposals of two documents applying to the same Party and Constituency; joint manifesto precedes automatically, else an Operator decision: which document prevails, plus a reason), Statement Rewording, Excluded Party, and Constituency availability in a Dataset Version (available, or unavailable with reason; the per-Constituency ordered Statements and offered lengths; the Excluded Parties per Constituency with reasons). Update Party, Source Document, Statement (source Proposals, category), Party Position and Evidence as in `CONTEXT.md`, and keep the current text as *Legacy*.
- **Relationships**: add Election 1—N Party N—M Constituency (candidatures); Source Document N—M Constituency; Source Document 1—N Proposal; Proposal N—M main category, plus free tags; Statement N—M Proposal (source group); Party Position → 1..N Proposals of the same Party as Evidence (v2) or 0..1 quote (Legacy); Dataset Version × Constituency → availability, ordered Statements, lengths, Excluded Parties; Election 1—1 Ingestion Ledger.
- **States and Lifecycles**: add the ingestion phases 1–4 and the per-Party ledger states, described in words (candidature declared → manifesto provided and reviewed → Proposals extracted, or Excluded with reason at any of those steps). The file values belong to `ingestion-ledger`. Add the conflict states (flagged → decided, or auto-resolved by joint-manifesto precedence). State the **phase 4 gate**: refused while any Party is neither Extracted nor Excluded or any conflict is pending. Add Constituency availability (fixed when the Dataset Version is created, immutable). Keep the Election, Source Document, Pipeline Run, triggers and Dataset Version lifecycles. Statement Rewording adds no state, because it only feeds a new run.
- **Validation Checks**: keep checks 1–7 as written, under a sub-heading *Legacy (Dataset Versions 1–5 and the current pipeline)*. Add a v2 subsection:
  - Unchanged: 1 (uniqueness), 2 (Evidence on the cited page, now applied to Evidence Proposals, which must belong to the positioned Party) and 7 (Context Note).
  - Per Constituency (`constituency-selection-validation`): 3 (coverage, per-Party minimum open), 4 (separation among the Parties running there), and 5 (count and lengths, replaced by the offered lengths 20/30/40/50/`Todas (N)` and a minimum valid count, open). Whether 6 (topic spread) is checked per Constituency is open. A Constituency failing these becomes unavailable with its reason; the run does not fail.
  - New gates outside the numbered checks: a Proposal kept only when verbatim on its page (`proposal-extraction`); the Excluded threshold (`proposal-extraction`); the phase-4 gate (`ingestion-ledger`, `proposal-conflicts`); the rewording equivalence check (`statement-rewording` decides where it runs and what a rejection does).
- **Important Scenarios**: mark the 15/30/full-coverage scenario as *Legacy*. Keep the Important scenario (now uncapped). Change the Share Link scenarios: a layout `v1` or `v2` link opens the outdated notice; a current-layout link from a superseded Dataset Version shows that version's result and the newer-data notice. Add:
  - a Granada Voter is scored only against the Parties running in Granada (ERC is not shown);
  - an Operator follows phases 1–4 and phase 4 refuses while one Party is pending;
  - a Voter answers 20, then `Contestar 5 más`, then `Ver resultado`, and the Share Link reopens that result.
- **Edge Cases**: replace the coalition prompt rule with joint-manifesto precedence plus flagged conflicts. Mark "Parties are never excluded" as *Legacy*. Add:
  - **Unavailable Constituency**: published unavailable with its reason, disabled in the list and the map. The rest of the Dataset Version publishes. Expected never to happen in practice.
  - **Excluded Party**: listed with its reason in the note of every Constituency where it runs, never ranked. A Constituency whose remaining Parties cannot separate falls under the unavailable rule.
  - **Flagged conflict**: phase 4 waits for the decision. The decision and reason are recorded in the ledger and applied by the run. Proposals are not edited.
  - **Reworded Statement**: the new Dataset Version holds the final text. The AI text and the reason are stored. Positions and Evidence are identical. The previous version and its Share Links are untouched. A meaning change is rejected.
  - Ceuta and Melilla, with few candidatures.
  - A Party running in a single Constituency.
  - Candidatures sharing a manifesto: open, owned by `constituencies-and-candidatures`.

### 3. `docs/build-brief.md`

- **Problem**: add that a Voter can vote only for the candidatures in their Constituency (a Granada Voter cannot vote ERC).
- **Target Users**: update the Operator duties, as in `CONTEXT.md`.
- **Goals**:
  - Score each Voter only against their Constituency's Parties.
  - Generate Proposals, Statements and Positions with AI. The Operator's only inputs are the candidatures, manifesto review, conflict decisions and Statement Rewordings, all recorded.
  - Keep: visible Evidence (now Proposals), publishing only through Validation, no user data, several Elections.
  - Ingest 2026 again as the reference for future Elections.
- **Non-Goals**:
  - Remove "per-province filtering".
  - Remove "Parties without seats in the previous Congreso" (it contradicts the v2 inclusion rule).
  - Add: Senado; the 2023 Election in v2's UI (its data is kept); AI-generated candidature lists; editing Proposals or Party Positions, or human review beyond the two recorded Operator decisions (this replaces "Manual editing or human review of AI output").
- **MVP Slice** (v2):
  1. The Operator ingests with the guide (phases 1–4).
  2. A run builds Statements and Positions from Proposals.
  3. Validation passes, possibly with unavailable Constituencies, and the version publishes.
  4. The Voter picks a Constituency (list or map), then a length, and answers (three options; Important uncapped), with +5/+10.
  5. The Voter sees the ranking of the Constituency's Parties, the Excluded-Party note, `¿En qué coincido?` per Party, and the Comparador with the same Constituency filter.
  6. The Share Link reopens the same result.

  Keep the old slice in one *Legacy* sentence (it was delivered for 2023 and 2026, Dataset Versions 3 and 5).
- **Matching Rule**: keep the three-option rule. The weight is 2 for any Important Statement, with no cap (`important-unlimited`). Scores are computed only for the Constituency's non-excluded Parties, over the Statements answered. Keep the low-coverage flag (M < 5).
- **Validation Plan**: tests use the fake provider and the fictional dev dataset (`dev-dataset`: no real Party names, never published, refused on the shared database). The end-to-end run is the 2026 re-ingestion (`e2e-2026-constituencies`). The 2023 run stays as *Legacy* history.
- **Success Criteria**:
  - A v2 Dataset Version for 2026 is published with no edits beyond the recorded conflict decisions and rewordings.
  - 100 % of sided Positions have Evidence Proposals of that Party, found on their page.
  - Every Constituency is available or unavailable with a reason.
  - A Voter completes the flow for a Constituency on mobile and desktop, and the Share Link reopens it.
  - The provider and Generation Mode stay configuration.
  - Mark the 2023 criterion as met (*Legacy*).

### 4. `AGENTS.md`

In Project Invariants, replace only the line "AI output is never edited by hand. It is published only through Validation." with this exact text:

> - Proposals and Party Positions are never edited; the Operator may only decide flagged contradictions and reword a Statement without changing its meaning, both recorded and published only through Validation.

Keep every other invariant word for word. Nothing else in `AGENTS.md` changes.

### 5. `docs/risks-and-open-questions.md` (narrow)

- In the "Decided (invariant change, written by `v2-domain-docs`)" bullet, say it is now written to `AGENTS.md`, `CONTEXT.md` and `docs/domain-model.md`.
- Add one "Open (handoff)" bullet under "Constituency redesign" listing the `CONSTRAINTS.md` rules that contradict v2 and their owners:
  - Party coverage must fail the run and never exclude; strict lengths; a non-separating Statement fails the run; count range; selection v3; `select_statements`: `constituency-selection-validation` (exclusion side: `ingestion-ledger`, `proposal-extraction`).
  - Agenda, Anchors, `StatementDraft` / `_COMMON_RULES`, Party Position finding rules: `statements-from-proposals`.
  - "Statements/selected text stored exactly as the provider returned"; reasons citing "AI output is never edited" (pipeline report, context notes, verified findings): `statement-rewording`.
- Add these "Decided (user, 2026-11-24, `v2-domain-docs` spec review)" bullets under "Constituency redesign", and state them in `CONTEXT.md` / `docs/domain-model.md` where the term is defined:
  - `CONSTRAINTS.md` is not edited by this feature; each rule there is changed by the feature that changes its code (the handoff bullet above).
  - A rewording that the equivalence check rejects does not fail the run: the Statement keeps its AI text and the pipeline report shows the rejected rewording (`statement-rewording`).
  - The exclusion threshold (N validated Proposals, default 30) counts per Party, summing all its Source Documents; a Party is Excluded only if the total is below N (`proposal-extraction`, `ingestion-ledger`).
  - `Todas (N)` is offered only when the Constituency has fewer than 20 valid Statements; with 20 or more, the Voter picks 20/30/40/50 and extends with +5/+10 (`questionnaire-length-and-context`).
- Do not touch any other entry. Every "Open" bullet stays open, except that the gaps the planner found (Anchors in v2, mapping of the existing 2026 Party rows, a Statement valid in no Constituency) are added as "Open" bullets owned by `statements-from-proposals`, `constituencies-and-candidatures` and `constituency-selection-validation` respectively.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md` (head), `feature_list.json` (the 21 round-2 entries): scope, owners, integration rule.
- `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md`: the current v1 text being edited (checks 1–7, scenarios, edge cases, non-goals).
- `docs/risks-and-open-questions.md`, sections "Voter feedback round 1", "Constituency redesign" and "Later / Not MVP" (the Excluded-Party note entry, owned by `results-by-constituency`).
- `CONSTRAINTS.md`, Pipeline and Validation sections: the rules that conflict with v2 (handoff list above).
- `DESIGN.md` (Important toggle cap copy), `README.md` line 262, `docs/technical-discovery.md` (grep only): UI and runbook docs that belong to later features.
- `data/ideology.db` (read-only): Dataset Versions 1–3 belong to Election 1 (2023, version 3 published) and 4–5 to Election 2 (2026, version 5 published).
- `init.sh` (head): no step reads these docs. A grep of `tests/`, `apps/web/src` and `packages/` shows no test that parses them, so the gate cannot catch doc mistakes.

### Current Gaps

- Nothing enforces doc consistency automatically. The review checklist below is the real verification.

## Expected File Changes

- `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md`, `AGENTS.md`: modify as above.
- `docs/risks-and-open-questions.md`: two narrow edits as above.
- `feature_list.json`, `PROGRESS.md`: status, evidence and a session entry.

## Visual Design Impact

- UI involved: no. This feature is exempt from browser validation (docs only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: not needed, because no code or boundary changes.
- `CONSTRAINTS.md`: not needed now. Its rules describe today's code; the handoff entry assigns each conflicting rule to the feature that changes that code.
- `AGENTS.md`: update one invariant (above).
- Other docs: `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md` and `docs/risks-and-open-questions.md` as above. `DESIGN.md`, `README.md` and `/metodologia` belong to `important-unlimited`, `ingestion-guide` and `methodology-v2`.

## Implementation Tasks

- [ ] Run `./init.sh` for the baseline.
- [ ] Edit `CONTEXT.md` (generation note, 5 new terms, 13 changed terms, legacy labels, rejected terms).
- [ ] Edit `docs/domain-model.md` (generation note, concepts, relationships, lifecycles and gate, Validation split, scenarios, edge cases).
- [ ] Edit `docs/build-brief.md` (problem, users, goals, non-goals, MVP slice, matching rule, validation plan, success criteria).
- [ ] Replace the one invariant in `AGENTS.md`.
- [ ] Make the two edits to `docs/risks-and-open-questions.md`.
- [ ] Run the review checklist and the stale-phrase grep, and fix any finding.
- [ ] Run `CI=true ./init.sh`, then update `feature_list.json` and `PROGRESS.md`.

## Acceptance Scenarios

### Scenario 1: every decision is stated

Given the "Constituency redesign" section
When the reviewer walks the checklist below
Then each Decided bullet maps to at least one named section that states it without contradiction.

### Scenario 2: legacy data stays valid

Given Dataset Versions 1–5 (national Questionnaire, quote Evidence, 15/30/full lengths, Important cap, layout `v2` links)
When a reader applies the docs to them
Then every rule they were built under is still stated as *Legacy*, and no v2 rule claims to apply to them retroactively.

### Scenario 3: open questions stay open

Given the five "Open" bullets of "Constituency redesign" and the `topic-catalog` CIS question
When the docs are read
Then each is referenced by its owner and none has a value chosen.

### Scenario 4: invariant replaced, others intact

Given `git diff v2 -- AGENTS.md`
Then exactly one line changed, and it equals the quoted text.

## Verification Plan

The review checklist maps each Decided bullet to the doc sections that must state it. The implementer records it, filled in, in the `feature_list.json` evidence.

| Decided bullet | Must be stated in |
|---|---|
| Problem: Voters can vote only in their Constituency | build-brief Problem and Goals; domain-model scenario (Granada/ERC) |
| Constituency = 52, Congreso only | CONTEXT Constituency; domain-model Core Concepts; build-brief Non-Goals (Senado) |
| Party = candidature; Operator from BOE, never AI | CONTEXT Party and Operator; domain-model Candidature; build-brief Non-Goals |
| Document scope; joint precedence; flagged conflicts decided with reason | CONTEXT Source Document and Operator; domain-model Conflict, lifecycle and edge case |
| Inclusion; two filters (review discard, N=30); Excluded in note, not ranking | CONTEXT Party and Excluded Party; domain-model ledger and edge case; build-brief MVP slice |
| Proposal definition, verbatim/page, reuse, incremental | CONTEXT Proposal; domain-model Core Concepts and v2 gates |
| Ingestion Ledger, phases 1–4, phase-4 gate, guide | CONTEXT Ingestion Ledger; domain-model lifecycles; build-brief MVP slice |
| Statements from Proposal groups; category; Evidence = Proposals; against with backing; no stance | CONTEXT Statement, Party Position, Evidence; domain-model Relationships and checks 2 |
| Per-Constituency validity and order; unavailable is not a failure; disabled with reason | CONTEXT Constituency, Statement Selection, Validation; domain-model v2 checks and edge case |
| Flow: Constituency first; 20/30/40/50/`Todas (N)`; +5/+10; ranking per Constituency; Comparador filter | CONTEXT Questionnaire and Questionnaire Length; build-brief MVP slice and Matching Rule |
| Important has no cap; Neutral drops it | CONTEXT Important; build-brief Matching Rule; domain-model scenario |
| Share Link carries the Constituency; old links show the notice; 2023 out of the UI; 2026 re-ingested | CONTEXT Share Link; domain-model scenarios; build-brief Goals and Non-Goals |
| Invariant change and rewording details, plus the `/metodologia` line | AGENTS.md invariant; CONTEXT Statement Rewording; domain-model edge case |
| Fictional dev dataset | build-brief Validation Plan |

Stale-phrase grep. Each hit must be gone or sit under a *Legacy* label:

```sh
grep -n -i "per-province\|a third\|never excluded\|with seats\|Cannot edit AI output\|no human review or manual editing\|AI output is never edited by hand" CONTEXT.md docs/domain-model.md docs/build-brief.md AGENTS.md
```

- `git diff --stat v2` lists only the files in Expected File Changes.
- `CI=true ./init.sh` exits 0. It is not a docs check; it proves the repo still starts.
- No browser check, because the feature has no browser-visible change.

## Evidence To Capture

- The filled checklist table, the stale-phrase grep output with each hit explained, the `git diff --stat v2` output, and the `CI=true ./init.sh` summary (pytest and Vitest counts). Record them in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist

- [ ] Every row of the checklist holds when the named sections are read, with no contradiction across the four docs.
- [ ] Legacy rules for Dataset Versions 1–5 are still stated and labelled. No v2 rule invalidates them.
- [ ] No open question was decided. Owners are referenced.
- [ ] `AGENTS.md` differs from `v2` only in the invariant line, and the line matches exactly.
- [ ] The risks doc changed only in the two planned places.
- [ ] No code, `CONSTRAINTS.md`, `DESIGN.md` or `README.md` change.
- [ ] `CI=true ./init.sh` passes. `feature_list.json` and `PROGRESS.md` are updated.

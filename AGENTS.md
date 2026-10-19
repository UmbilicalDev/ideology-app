# Project Agent Instructions

This repository contains an AI-generated voting advice application (VAA): for a Spanish general election, voters rate AI-generated Statements and get a ranking of parties by affinity. Each party position is backed by a verbatim quote from its manifesto.

## Read First

- `CONTEXT.md` — domain language. Use these terms in code and UI (Statement, Party Position, Evidence, Dataset Version...).
- `docs/build-brief.md` — goals, non-goals, MVP slice, and the matching rule.
- `docs/domain-model.md` — entities, lifecycles, and Validation checks.
- `docs/risks-and-open-questions.md` — risks and unresolved questions.

Read optional docs only when relevant:

- `docs/technical-discovery.md` — when touching stack, configuration, LLM providers, storage, deployment, or testing.
- `DESIGN.md` — when touching any UI.
- `docs/specs/` — per-feature implementation specs, once they exist.

## Startup Workflow

Before writing code:

1. Confirm the working directory with `pwd`.
2. Read `PROGRESS.md` for the current verified state and next step.
3. Read `feature_list.json` and pick the first ready unfinished feature in list order (every `depends_on` feature `accepted`).
4. Run `./init.sh`.
5. If baseline verification fails, fix the baseline before adding new feature work.

## Working Rules

- Work on one feature at a time.
- Do not mark a feature complete just because code was added.
- Keep changes inside the selected feature's scope unless a blocker requires a narrow supporting fix.
- Do not silently change verification rules during implementation.
- Update durable repo artifacts instead of relying on chat summaries.
- Record validation results only as evidence in `feature_list.json` and `PROGRESS.md`; do not create `docs/validations/`.

## Browser Validation For UI Features

A feature that adds or changes anything a user sees in a browser (pages, forms, navigation, client-side behavior) is not `passing` or `accepted` until it has been checked in a real browser. Automated tests and rendered-HTML assertions do not replace this.

- Start the app with the documented start command and open it in a real browser. Any browser automation tool is fine.
- Walk through every acceptance scenario of the feature's spec as a user would: click, type, navigate, go back.
- Check at a mobile width (375px) and at desktop width, following `DESIGN.md`.
- Check that the browser console has no errors and no request failed unexpectedly.
- For voter flows, confirm that no request carries voter answers (see Project Invariants).
- Record what was checked and the result as evidence in `feature_list.json` and `PROGRESS.md`. Name the browser and widths, and attach screenshots only if the user asks.
- If no browser is available, the feature stays `in_progress` or `blocked` with the reason recorded. Do not mark it `passing`.

Both the implementer (self-verification) and the validator (independent check) apply this rule. Features with no browser-visible change (CLI, data, pipeline) are exempt.

## Project Invariants

- Never store voter answers on the server. Share Links carry them in the URL fragment.
- AI output is never edited by hand. It is published only through Validation.
- Every Party Position other than `no stance` must have Evidence.
- Dataset Versions are immutable once created.
- Tests never call a real LLM; use the fake provider.
- The LLM provider and Generation Mode are configuration, not code branches scattered around.
- The UI treats all parties identically (see `DESIGN.md`).

## Required Artifacts

- `feature_list.json`: source of truth for feature state.
- `PROGRESS.md`: current verified state and lightweight session log.
- `init.sh`: standard startup and verification path.

## Definition Of Done

A feature is done only when all are true:

- the target behavior is implemented,
- the required verification actually ran,
- evidence is recorded in `feature_list.json` or `PROGRESS.md`,
- the repository can still be restarted from the standard startup path,
- relevant docs are updated if product behavior, domain rules, the API, or verification changed.

## End Of Session

Before ending a session:

1. Update `PROGRESS.md`.
2. Update `feature_list.json`.
3. Record unresolved risks or blockers in `docs/risks-and-open-questions.md` (see below).
4. Leave the repo clean enough for the next session to run `./init.sh` immediately.

## Risks And Open Questions

`docs/risks-and-open-questions.md` is the durable list of what is still unknown or risky. `PROGRESS.md` is only a log, and future planners will not dig through it.

- Before planning or implementing a feature, read it and check whether any entry names that feature. If one does, the spec must address it or explicitly defer it.
- When a feature finds a new risk, open question or accepted Low finding that outlives the session, add it to the right section. Name the feature that should deal with it when you know it, e.g. `(public-dataset-api)`.
- When a feature settles a question or removes a risk, edit or delete that entry in the same change. Don't leave stale entries behind.
- In `PROGRESS.md`, a session's "Known risk" line may point to the doc instead of repeating it.

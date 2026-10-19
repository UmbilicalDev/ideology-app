# Risks and Open Questions

## Blocking Next Phase

None.

## Implementation-Time Questions

- How often URL Source Documents are re-fetched and hashed for change detection in `live` mode.

- The exact prompts for Party Position extraction and how to chunk manifestos for it. Settled for Statements (`pipeline-generate-statements`): map/reduce over chunks of whole pages of at most 40,000 characters (one `statement_candidates` call per chunk, then one `generate_statements` call), prompts `v1`, at most 200 LLM calls per run; real-LLM quality is checked only in `e2e-real-2023-election`.
- The Share Link encoding format and its versioning.
- The fuzzy-match tolerance for Evidence quote verification.
- What happens when a Party fails coverage: fail the whole run, or exclude the Party and publish with a notice? Initial position: fail the run.
- The minimum number of answered Statements before showing a ranking.
- Order in which Statements are shown (random or by topic) to reduce order bias.

## Later / Not MVP

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

## Research Tasks

- Review the methodologies of established VAAs (Wahl-O-Mat, EUandI, Kieskompas) for statement design and matching.
- Collect the 2023 manifestos of parties with seats and check their text extractability.
- Run a quick legal check on publishing VAAs during Spanish campaign periods.

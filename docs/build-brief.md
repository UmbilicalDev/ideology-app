# Build Brief

## Problem

Voters find it hard to know which party's proposals for an election best match their own views. Manifestos are long, and comparing them across parties takes effort most people won't put in. And a Voter can vote only for the candidatures in their Constituency (a Granada Voter cannot vote ERC), so a ranking against every national Party misleads.

## Current Workaround / Existing System

Reading manifestos, the media, or existing voting advice applications (VAAs) such as Wahl-O-Mat, EUandI or Isidewith. Those tools rely on editorial teams or on parties answering questionnaires. This project tests whether a fully AI-generated, evidence-backed VAA is viable.

## Target Users

- **Voter** (anonymous): answers the Questionnaire and gets a ranking. No account.
- **Operator**: declares the candidatures per Constituency (from the BOE), provides and reviews manifestos (discarding one with a reason), decides flagged contradictions (with a reason), rewords confusing Statements through a rewording file, and triggers runs, guided by `ingestion-guide`. Never edits Proposals or Party Positions. *Legacy (Dataset Versions 1–5):* set up Elections, Parties and Source Documents, and triggered Pipeline Runs.

## Goals

- For a given Election, let a voter rate the Statements and get a Match Score per Party, scored only against the Parties running in the Voter's Constituency.
- Generate Proposals, Statements and Party Positions with AI from the Source Documents. The Operator's only inputs are the candidatures, manifesto review, conflict decisions and Statement Rewordings, all recorded.
- Make every Party Position auditable through visible Evidence (v2: the Party's Proposals, verbatim with their page; *Legacy:* a verbatim quote and a locator).
- Publish automatically only output that passes Validation.
- Store no user data on the server; results are shared through a Share Link.
- Support several Elections per country from day one, even though only Spanish general elections are loaded.
- Ingest the 2026 Election again with the v2 model (`e2e-2026-constituencies`) as the reference for future Elections.

## Non-Goals

- Regional, municipal and European elections (the model allows them; no data is loaded).
- Countries other than Spain.
- User accounts, saved history and server-side analytics on answers.
- Editing Proposals or Party Positions, or human review beyond the two recorded Operator decisions (conflict decisions and Statement Rewordings).
- Political compass / 2D maps.
- The Senado (Constituencies are Congreso only).
- The 2023 Election in v2's UI (its data is kept).
- AI-generated candidature lists (the Operator enters them from the BOE).
- Voting recommendations beyond the affinity ranking.

## MVP Slice

One complete flow with real data (v2):

1. The Operator ingests the Election with the guide (`ingestion-guide`): phase 1 candidatures per Constituency, phase 2 provide and review manifestos, phase 3 extract Proposals (Parties without enough content become Excluded Parties), phase 4 generate Statements.
2. A Pipeline Run (through a configurable LLM provider) builds Statements and Party Positions from the Proposals.
3. Validation passes, possibly with unavailable Constituencies (each with its reason), and the Dataset Version is published automatically.
4. The Voter picks a Constituency (list or map), then a length, and answers, one tap each (three options: En desacuerdo, Neutral / No lo sé, De acuerdo; Important uncapped), extending with `Contestar 5 más` / `Contestar 10 más`.
5. The Voter sees the ranking of the Constituency's Parties, the note on its Excluded Parties, `¿En qué coincido?` per Party, and the Comparador with the same Constituency filter.
6. The Share Link reopens the same result.

*Legacy:* the first slice (national Questionnaire, a national Party set chosen per Election, quote Evidence, Important up to a third) was delivered for 2023 and 2026 (Dataset Versions 3 and 5).

## Matching Rule (initial position)

Three-option rule (user decision 2026-11-21, `three-option-scale`; it replaces the five-point distance rule):

- Answers: `De acuerdo` = +1, `En desacuerdo` = −1, `Neutral / No lo sé` = no value (excluded).
- Party Positions stay stored on −2..+2 and are read by side: −2/−1 against, +1/+2 in favour. Position 0 and `no stance` are excluded for that pair.
- Per compared Statement: agreement = 1 on the same side, 0 on opposite sides.
- Weight 2 for any Important Statement, otherwise 1; there is no cap on Important marks (`important-unlimited`). An Important flag on a Neutral Answer has no effect.
- Scores are computed only for the non-excluded Parties running in the Voter's Constituency, over the Statements answered.
- Match Score = Σ(weight × agreement) / Σ(weight) over the compared Statements, or none when nothing is compared.
- Each ranking row reads `N de M coincidencias`: M = Statements compared with that Party, N = same side. With Important flags the percent is weighted, so it can differ slightly from N/M.
- If fewer than N Statements (initially 5) can be compared with a Party (M < 5), its score is flagged as "low coverage".

## Validation Plan

- Automated tests for the matching rule, Share Link encode/decode, and every Validation check. Tests use the fake provider and the fictional dev dataset (`dev-dataset`: no real Party names, never published, refused on the shared database).
- The end-to-end run is the 2026 re-ingestion with the v2 model (`e2e-2026-constituencies`): ingestion → pipeline → validation → publish → questionnaire → share. *Legacy:* the end-to-end run over the 2023 manifestos.
- A manual sanity read of the published output by the team (an observation, not an editing step).

## Success Criteria

- A v2 Dataset Version for 2026 is published with no edits beyond the recorded conflict decisions and Statement Rewordings.
- 100% of sided Party Positions have Evidence Proposals of that Party, found on their page.
- Every Constituency is available or unavailable with a reason.
- A Voter completes the flow for a Constituency on mobile and desktop, and the Share Link reopens the identical result.
- Switching the LLM provider or Generation Mode is a configuration change, not a code change.
- *Legacy (met):* a real Dataset Version for the 2023 general election was published without manual edits.

## Notes

See `docs/technical-discovery.md` for the stack and configuration points, and `docs/risks-and-open-questions.md` for risks, especially those of AI-only extraction.

# Build Brief

## Problem

Voters find it hard to know which party's proposals for an election best match their own views. Manifestos are long, and comparing them across parties takes effort most people won't put in.

## Current Workaround / Existing System

Reading manifestos, the media, or existing voting advice applications (VAAs) such as Wahl-O-Mat, EUandI or Isidewith. Those tools rely on editorial teams or on parties answering questionnaires. This project tests whether a fully AI-generated, evidence-backed VAA is viable.

## Target Users

- **Voter** (anonymous): answers the Questionnaire and gets a ranking. No account.
- **Operator**: sets up Elections, Parties and Source Documents, and triggers Pipeline Runs.

## Goals

- For a given Election, let a voter rate the Statements and get a Match Score per Party.
- Generate Statements and Party Positions purely with AI from the Source Documents, without manual editing.
- Make every Party Position auditable through visible Evidence (a verbatim quote and a locator).
- Publish automatically only output that passes Validation.
- Store no user data on the server; results are shared through a Share Link.
- Support several Elections per country from day one, even though only Spanish general elections are loaded.

## Non-Goals

- Regional, municipal and European elections (the model allows them; no data is loaded).
- Countries other than Spain.
- User accounts, saved history and server-side analytics on answers.
- Manual editing or human review of AI output.
- Political compass / 2D maps.
- Parties without seats in the previous Congreso, and per-province filtering.
- Voting recommendations beyond the affinity ranking.

## MVP Slice

One complete flow with real data:

1. The Operator registers the latest Spanish general election, its parties with seats, and their manifestos (upload or URL).
2. A Pipeline Run (through a configurable LLM provider) generates the Questionnaire and Party Positions with Evidence.
3. Validation passes → the Dataset Version is published automatically.
4. A Voter answers the Statements, one tap each (three options: En desacuerdo, Neutral / No lo sé, De acuerdo; Important, up to a third of the Statements), sees the ranking by Match Score and a per-Statement breakdown with each Party's Position and Evidence.
5. The Voter copies a Share Link that reproduces the same result.

## Matching Rule (initial position)

Three-option rule (user decision 2026-11-21, `three-option-scale`; it replaces the five-point distance rule):

- Answers: `De acuerdo` = +1, `En desacuerdo` = −1, `Neutral / No lo sé` = no value (excluded).
- Party Positions stay stored on −2..+2 and are read by side: −2/−1 against, +1/+2 in favour. Position 0 and `no stance` are excluded for that pair.
- Per compared Statement: agreement = 1 on the same side, 0 on opposite sides.
- Weight 2 if Important, otherwise 1 (an Important flag on a Neutral Answer has no effect).
- Match Score = Σ(weight × agreement) / Σ(weight) over the compared Statements, or none when nothing is compared.
- Each ranking row reads `N de M coincidencias`: M = Statements compared with that Party, N = same side. With Important flags the percent is weighted, so it can differ slightly from N/M.
- If fewer than N Statements (initially 5) can be compared with a Party (M < 5), its score is flagged as "low coverage".

## Validation Plan

- Automated tests for the matching rule, Share Link encode/decode, and every Validation check.
- An end-to-end run over the 2023 manifestos: the pipeline → validation → publish → questionnaire → share.
- A manual sanity read of the published output by the team (an observation, not an editing step).

## Success Criteria

- A real Dataset Version for the 2023 general election is published without manual edits.
- 100% of non-`no stance` Party Positions have Evidence whose quote appears in the Source Document.
- A Voter completes the flow on mobile and desktop, and the Share Link reopens the identical result.
- Switching the LLM provider or Generation Mode is a configuration change, not a code change.

## Notes

See `docs/technical-discovery.md` for the stack and configuration points, and `docs/risks-and-open-questions.md` for risks, especially those of AI-only extraction.

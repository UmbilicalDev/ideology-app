# Feature Implementation Spec: Real run on the 29 November 2026 general election

## Source Feature

- `id`: e2e-real-2026-election
- `area`: validation (data, pipeline, plus one Landing change)
- `depends_on`: e2e-real-2023-election (`accepted`)
- `source`: user request of 2026-11-19 ("generar el cuestionario para 2026"). This spec was written after the fact, in the same session, to record the decisions.

## Goal

Publish a Dataset Version for the 29 November 2026 general election (Election 2 in `data/ideology.db`), built from the official 2026 manifestos through the normal pipeline and Validation. Then remove the fixed `Próximamente` 2026 card from the Landing in the same change (see `docs/risks-and-open-questions.md`).

## Decisions (user decisions of 2026-11-19 unless stated)

1. **Parties.** The parties with a seat in the 40dB/EL PAÍS projection of 19 Nov 2026 and an official 2026 manifesto, plus Podemos and SALF: PP, PSOE, VOX, Frente Amplio, Podemos, ERC, EH Bildu, BNG, Compromís, Adelante Andalucía, SALF (11), and Junts since 2026-11-20 (12; step 10).
   - Junts was excluded at first: it had no 2026 manifesto. It was added on 2026-11-20 (step 10).
   - CC and EAJ-PNV were in run 5 and were then excluded. In the 58-Statement pool their manifestos gave stances on about 5 (CC) and 9–12 (EAJ-PNV) Statements, so neither can reach the 50% coverage minimum.
   - The 50% default is unchanged.
2. **Bundle.** `data/elections/es-general-2026-11-29/` is a Source Text Bundle written by `ideology source extract` from the official PDFs. Every `source_url` is the party's own URL. SALF's PDF was downloaded by the user in a browser, and its SHA-256 equals the file the official URL serves. Logos: the six Parties from 2023 reuse their 2023 file; the user supplied the rest.
3. **Pipeline change: Statement batches in `position_findings` (prompt v4).**
   - Run 5 recorded two SALF `position_findings` calls that returned 7 and 5 findings (11 Statements). Byte-identical repeats of the same requests (same `request_hash`) found stances on 23–25 Statements. One call over the whole pool (up to 60 Statements) is unreliable.
   - Each chunk now gets one call per batch of at most `FINDINGS_STATEMENTS_PER_CALL = 20` consecutive Statements, keeping their global numbers. A finding for a Statement outside its batch is ignored.
   - The template header says the list is part of the questionnaire, so the prompt becomes `v4`. The system text is unchanged.
   - `plan_position_calls` multiplies chunks by the batch count for the largest pool (`POOL_MAX_STATEMENTS` = 60, so 3 batches). `MAX_POSITION_CALLS_PER_RUN` stays 300. For this election that is 59 chunks × 3 + 11 = 188 calls.
   - Experiment (SALF, 4 repeats each): stances on 23–25 Statements with one call over the whole pool, 25–26 with batches. EAJ-PNV: 9 vs 12. VOX: 21 vs 21.
4. **Runs.**
   - Run 4: failed before any call (expired Claude Code login).
   - Run 5: 13 Parties, `position_findings` v3; failed `party_coverage`.
   - Runs 4 and 5 lived only in the local DB, which was reset to the committed one before the 11-Party import. A copy is kept outside the repo at `~/ideology-e2e-2026-logs/ideology.db.pre-cc-pnv-removal`.
   - The next run is a fresh run on the rebuilt Election 2, with `claude_code` / `claude-sonnet-5-5` / `precomputed` and default thresholds.
5. **Landing.** The fixed `Próximamente` card is removed. The grid shows exactly the API's Elections. The card CSS stays, unused, for a future upcoming Election.
6. **Run 4 on the re-imported DB (run ids restarted).** 11 Parties, `position_findings` v4, pool 45..60. It failed `party_coverage` only: PP, PSOE, VOX and SALF 12/25 (48%), ERC 11/25 (44%).
   - The pool had 53 Statements, 34 of them separating. ERC had a stance on 16 of the 53 and on 11 of the 34, so no selection could reach 50% (local search over the stored pool).
   - Four stances were cleared by model copy slips. A dropped phrase (PP), a one-letter typo across a line-break hyphen (VOX) and two verbatim quotes cited on the wrong page of their chunk (PSOE, ERC). Without them, PP, PSOE and VOX would have had 13/25.
7. **Pipeline changes after run 4 (user decisions of 2026-11-19).**
   - **Wider pool:** `POOL_MIN/MAX/TARGET_STATEMENTS` 60/80/70 (were 45/60/55), so the selection has more Statements on which each Party has a stance. The Questionnaire stays 25..35 (the user's ceiling is about 40-50). With 4 batches of 20 Statements the call budget is 59 chunks × 4 + 11 = 247, under the 300 cap.
   - **Quote repair** (`pipeline/quote_repair.py`, findings check v2). It applies only to pages of the finding's own chunk:
     - `other_page`: the page is corrected;
     - `not_found`: a near-identical copy (at least 40 letters and digits, similarity ≥ 0.85 on normalised text, blocks of at least 4 characters) is replaced by the source's own text, with whitespace collapsed.
     - Statement and value never change. `page_not_in_chunk` and `no_letters` are never repaired. Validation's exact `evidence_quotes` check is unchanged and still guards the stored Evidence.
     - `pipeline report` shows a `repaired findings` table.
   - **Self-contained Statements** (`generate_statements` v5). The user found some 2023 Statements cryptic ("change the current policy on X" without saying what it is).
     - The rule against naming laws, figures or deadlines is relaxed: figures and deadlines are allowed when they are the core of the proposal.
     - A new rule says every Statement must be understandable on its own. It names the law or reform it would repeal or keep, or says what it does, and never refers to "la política actual" without saying what that policy is.
   - `position_findings` becomes `v5`: same text as v4, but its schema now allows up to 80 findings, and run 4 recorded v4 calls with the old schema.
   - `/metodologia` copy updated: about 70 Statements, pool 60..80, self-contained wording, quote repair.
8. **Hand-off.** The next real run is left to Kike on this branch (`PROGRESS.md`, Session 092). `--reuse-from 4` replays the 59 `statement_candidates` calls (v1 is unchanged and the chunks are identical). Everything after them is called fresh: about 1 + 247 calls.
9. **Run 5** (2026-11-19, `--reuse-from 4`, run by the main session because Kike could not yet). It passed and published Dataset Version 5: 30 Statements from an 80-Statement pool, worst coverage 50% (PP, PSOE, VOX, EH Bildu), 3 findings repaired, none discarded. Superseded by step 10: that database is not the committed one.
10. **12 Parties with Junts** (2026-11-20, user decisions). Junts's manifesto appeared on tualcentre.cat on 18 Nov and was added to the bundle. A 13-Party run that also had EAJ-PNV's official 2026 manifesto failed `party_coverage`: EAJ-PNV reached 3/25. The committed database was then reset to the hand-off state (run 4 failed), Junts was imported, and run 5 (`--reuse-from 4`) passed. It published Dataset Version 5: 12 Parties, 32 Statements from a 77-Statement pool, worst coverage 50% (VOX, ERC, SALF), 2 findings repaired, none discarded. This is the committed database.

## Verification

- `CI=true ./init.sh` passes.
- Tests cover batching: batch split; each request lists only its batch with global numbers; out-of-batch findings ignored; budget with the batch multiplier; prompt v4 pinned.
- Tests cover the wider pool (60..80), `generate_statements` v5, and quote repair on the real run-4 slips. They also check that invented, paraphrased, short, out-of-chunk and no-letter quotes are never repaired.
- `ideology pipeline report --run R` shows `status: passed` and `publication: published: live for election 2`.
- A sample of positions is read against their Evidence (observation only).
- Browser walk at 375px and desktop: the Landing lists both Elections and no `Próximamente` card; the 2026 Questionnaire → results → Share Link flow works; the console is clean; no request carries answers.

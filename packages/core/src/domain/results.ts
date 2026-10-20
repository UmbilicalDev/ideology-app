// The results of a finished Questionnaire: ranking, per-Statement breakdown
// and whether any Match Score exists. Pure: no React, DOM, storage or
// network. The end screen and the shared result (Share Link) both call this,
// so both show identical scores and order by construction (CONSTRAINTS.md,
// Client-side Matching).
import { buildBreakdown, type BreakdownRow } from "./breakdown";
import type { DatasetVersion } from "./dataset-version";
import { toMatchScoreAnswers, type QuestionnaireState } from "./questionnaire";
import { rankParties, type RankedParty } from "./ranking";

export interface Results {
  readonly ranking: readonly RankedParty[];
  readonly breakdown: readonly BreakdownRow[];
  /** `true` when at least one Party has a Match Score (not `null`). */
  readonly hasScores: boolean;
}

/** `rankParties` then `buildBreakdown` in the ranking's Party order. */
export function buildResults(
  version: Pick<DatasetVersion, "statements" | "parties">,
  state: QuestionnaireState,
): Results {
  const answers = toMatchScoreAnswers(state);
  const ranking = rankParties(answers, version.parties);
  const breakdown = buildBreakdown(
    version.statements,
    version.parties,
    answers,
    ranking.map((party) => party.partyId),
  );
  return { ranking, breakdown, hasScores: ranking.some((party) => party.matchScore !== null) };
}

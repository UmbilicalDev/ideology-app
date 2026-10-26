// Party ranking for the results screen. Pure: no React, DOM, storage or
// network. Scores come only from the Match Score engine (`computeMatchScores`
// with its default threshold); this module only rounds them for display and
// orders the Parties.
//
// Order: displayed percentage descending, `null` scores last; a tie on the
// displayed percentage is broken by name with Spanish collation, then by
// Party id, so the order is fully deterministic and checkable from the screen
// ("en caso de empate, alfabéticamente", MethodologyPage).
import type { Party } from "./dataset-version";
import { computeMatchScores, type Answer } from "./match-score";

export interface RankedParty {
  readonly partyId: number;
  readonly name: string;
  readonly shortName: string;
  /** Same-origin logo path from `Party.logoUrl`, or `null` (placeholder). */
  readonly logoUrl: string | null;
  /** The engine's score from 0 to 1, or `null` when no Statement is shared. */
  readonly matchScore: number | null;
  /** `Math.round(matchScore * 100)`, or `null` with `matchScore`. */
  readonly percent: number | null;
  readonly sharedStatementCount: number;
  readonly lowCoverage: boolean;
}

const NAME_COLLATOR = new Intl.Collator("es");

function compareRanked(a: RankedParty, b: RankedParty): number {
  if (a.percent !== b.percent) {
    if (a.percent === null) return 1;
    if (b.percent === null) return -1;
    return b.percent - a.percent;
  }
  const byName = NAME_COLLATOR.compare(a.name, b.name);
  if (byName !== 0) return byName;
  return a.partyId - b.partyId;
}

/** Every Party of the Dataset Version with its Match Score, in display order. */
export function rankParties(answers: readonly Answer[], parties: readonly Party[]): RankedParty[] {
  const results = computeMatchScores(
    answers,
    parties.map((party) => ({ partyId: party.id, positions: party.positions })),
  );
  const ranked = parties.map((party, i): RankedParty => {
    const result = results[i]!;
    return {
      partyId: party.id,
      name: party.name,
      shortName: party.shortName,
      logoUrl: party.logoUrl,
      matchScore: result.matchScore,
      percent: result.matchScore === null ? null : Math.round(result.matchScore * 100),
      sharedStatementCount: result.sharedStatementCount,
      lowCoverage: result.lowCoverage,
    };
  });
  return ranked.sort(compareRanked);
}

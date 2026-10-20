import { LOW_COVERAGE_THRESHOLD, type RankedParty } from "@ideology-app/core";

export const LOW_COVERAGE_LABEL = "Baja cobertura";

const LEGEND =
  `${LOW_COVERAGE_LABEL}: compartes menos de ${LOW_COVERAGE_THRESHOLD} afirmaciones con ese ` +
  "partido, así que su afinidad se basa en pocos datos.";

/**
 * The party ranking (DESIGN.md "Ranking row"). Renders `ranking` in the order
 * given (it comes from `rankParties`) and treats every Party the same: no
 * colour, logo, highlight or position marker per Party. The meaning is in the
 * text; the bar is decorative. Expects a heading with id `results-title`.
 */
export function ResultsRanking({ ranking }: { readonly ranking: readonly RankedParty[] }) {
  const anyLowCoverage = ranking.some((party) => party.lowCoverage);
  return (
    <>
      <ol className="ranking" role="list" aria-labelledby="results-title">
        {ranking.map((party) => (
          <RankingRow key={party.partyId} party={party} />
        ))}
      </ol>
      {anyLowCoverage ? <p className="ranking-legend">{LEGEND}</p> : null}
    </>
  );
}

// A no-break space keeps the number and "%" together, as in MethodologyPage.
function RankingRow({ party }: { readonly party: RankedParty }) {
  return (
    <li className="ranking-row">
      <div className="ranking-row__head">
        <span className="ranking-row__name">{party.name}</span>{" "}
        <span className="ranking-row__short">{party.shortName}</span>{" "}
        <span className="ranking-row__percent">
          {party.percent === null ? "Sin afirmaciones en común" : `${party.percent}\u00a0%`}
        </span>
      </div>
      <div className="ranking-bar" aria-hidden="true">
        <div className="ranking-bar__fill" style={{ width: `${party.percent ?? 0}%` }} />
      </div>
      <p className="ranking-row__meta">
        {sharedSentence(party.sharedStatementCount)}
        {party.lowCoverage ? (
          <>
            {" "}
            <span className="coverage-badge">{LOW_COVERAGE_LABEL}</span>
          </>
        ) : null}
      </p>
    </li>
  );
}

function sharedSentence(count: number): string {
  return count === 1 ? "1 afirmación en común" : `${count} afirmaciones en común`;
}

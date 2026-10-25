import { useEffect, useId, useRef, useState } from "react";

import { LOW_COVERAGE_THRESHOLD, type RankedParty } from "@ideology-app/core";

import { InfoIcon } from "../../ui/icons";

export const LOW_COVERAGE_LABEL = "Baja cobertura";

export const LOW_COVERAGE_EXPLANATION =
  `Compartes menos de ${LOW_COVERAGE_THRESHOLD} afirmaciones con este partido, así que su ` +
  "afinidad se basa en pocos datos.";

/**
 * The party ranking (DESIGN.md "Ranking row"). Renders `ranking` in the order
 * given (it comes from `rankParties`) and treats every Party the same: no
 * colour, logo, highlight or position marker per Party. The meaning is in the
 * text; the bar is decorative. Expects a heading with id `results-title`.
 */
export function ResultsRanking({ ranking }: { readonly ranking: readonly RankedParty[] }) {
  return (
    <ol className="ranking" role="list" aria-labelledby="results-title">
      {ranking.map((party) => (
        <RankingRow key={party.partyId} party={party} />
      ))}
    </ol>
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
            <CoverageChip />
          </>
        ) : null}
      </p>
    </li>
  );
}

function sharedSentence(count: number): string {
  return count === 1 ? "1 afirmación en común" : `${count} afirmaciones en común`;
}

// Grace period so the pointer can move from the chip onto the tooltip.
const HOVER_CLOSE_DELAY_MS = 150;

/**
 * The `Baja cobertura` chip (DESIGN.md "Coverage chip and tooltip"). Its
 * explanation opens on hover, focus or tap, stays while hovered and closes
 * with Escape, on blur or when the pointer leaves. The tooltip stays in the
 * DOM, hidden when closed, so the chip is always described by it.
 */
function CoverageChip() {
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const chipRef = useRef<HTMLButtonElement>(null);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  // Escape closes it however it was opened, wherever focus is (WCAG 1.4.13).
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        window.clearTimeout(closeTimer.current);
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  function show() {
    window.clearTimeout(closeTimer.current);
    setOpen(true);
  }

  function hideSoon() {
    window.clearTimeout(closeTimer.current);
    // A focused chip keeps its tooltip until blur or Escape.
    if (document.activeElement === chipRef.current) return;
    closeTimer.current = window.setTimeout(() => setOpen(false), HOVER_CLOSE_DELAY_MS);
  }

  return (
    <span className="coverage-chip" onMouseEnter={show} onMouseLeave={hideSoon}>
      <button
        ref={chipRef}
        type="button"
        className="coverage-badge"
        aria-describedby={tooltipId}
        onFocus={show}
        onClick={show}
        onBlur={() => setOpen(false)}
      >
        <InfoIcon />
        <span>{LOW_COVERAGE_LABEL}</span>
      </button>
      <span id={tooltipId} role="tooltip" className="coverage-tooltip" hidden={!open}>
        {LOW_COVERAGE_EXPLANATION}
      </span>
    </span>
  );
}

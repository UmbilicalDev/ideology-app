import { StarIcon } from "../../ui/icons";

/** Who gave the answers: the Voter (end screen) or a Share Link (shared result). */
export type SummaryVoice = "voter" | "link";

const COPY: Record<
  SummaryVoice,
  {
    readonly skipped: (count: number) => string;
    readonly important: (count: number) => string;
  }
> = {
  voter: {
    skipped: (count) =>
      count === 0
        ? "No has saltado ninguna afirmación."
        : count === 1
          ? "Has saltado 1 afirmación."
          : `Has saltado ${count} afirmaciones.`,
    important: (count) =>
      count === 0
        ? "No has marcado ninguna afirmación como importante."
        : count === 1
          ? "Has marcado 1 afirmación como importante."
          : `Has marcado ${count} afirmaciones como importantes.`,
  },
  link: {
    skipped: (count) =>
      count === 0
        ? "No se saltó ninguna afirmación."
        : count === 1
          ? "Se saltó 1 afirmación."
          : `Se saltaron ${count} afirmaciones.`,
    important: (count) =>
      count === 0
        ? "No se marcó ninguna afirmación como importante."
        : count === 1
          ? "Se marcó 1 afirmación como importante."
          : `Se marcaron ${count} afirmaciones como importantes.`,
  },
};

export function summaryTitle(answered: number, total: number): string {
  return `Muestra evaluada: ${answered}/${total} afirmaciones contestadas`;
}

/**
 * The results summary card (DESIGN.md "Summary card"): how many Statements
 * were answered, as text and as a decorative donut, plus the skipped count
 * and the Important sentence. The text carries every number.
 */
export function ResultsSummary({
  answered,
  skipped,
  important,
  total,
  voice,
}: {
  readonly answered: number;
  readonly skipped: number;
  readonly important: number;
  readonly total: number;
  readonly voice: SummaryVoice;
}) {
  const copy = COPY[voice];
  const percent = total === 0 ? 0 : Math.round((answered / total) * 100);
  return (
    <section className="summary-card" aria-labelledby="summary-title">
      <div className="summary-donut" aria-hidden="true">
        <svg viewBox="0 0 36 36" width="64" height="64" focusable="false">
          <circle className="summary-donut__track" cx="18" cy="18" r="15.5" />
          {/* No arc at 0 %: a round cap on an empty dash would still draw a dot. */}
          {percent > 0 ? (
            <circle
              className="summary-donut__value"
              cx="18"
              cy="18"
              r="15.5"
              pathLength="100"
              strokeDasharray={`${percent} 100`}
            />
          ) : null}
        </svg>
        <span className="summary-donut__label">{`${percent} %`}</span>
      </div>
      <div className="summary-card__text">
        <h3 id="summary-title">{summaryTitle(answered, total)}</h3>
        <p>{copy.skipped(skipped)}</p>
        <p className="summary-card__important" data-marked={important > 0}>
          <StarIcon className="summary-card__star" />
          {copy.important(important)}
        </p>
      </div>
    </section>
  );
}

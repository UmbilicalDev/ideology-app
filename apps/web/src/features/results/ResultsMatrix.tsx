import { NO_STANCE, type BreakdownRow } from "@ideology-app/core";
import type { FocusEvent } from "react";

import { StarIcon } from "../../ui/icons";
import { SideIcon, answerSide, stanceSide, type Side } from "../scale-icons";
import { coincidence, stanceLabel } from "./breakdown-view";
import { answerLabel, NO_STANCE_LABEL } from "./Evidence";
import { PartyLogo } from "./PartyLogo";
import type { CoincidenceCopy } from "./ResultsBreakdown";

// The two cell tints: same side (100) and opposite sides (0).
const MATCH_STEPS = [
  { step: 100, label: "Coincide" },
  { step: 0, label: "No coincide" },
] as const;

// Legend order, as the options read: De acuerdo, Neutral, En desacuerdo.
const LEGEND_SIDES: readonly { readonly side: Side; readonly label: string }[] = [
  { side: 1, label: "De acuerdo" },
  { side: 0, label: "Neutral" },
  { side: -1, label: "En desacuerdo" },
];

// No stance (and no Answer) keep a dash: there is no side to draw.
const NO_VALUE = "—";

/**
 * The Statement matrix (DESIGN.md "Statement matrix", 1024px and up): one
 * row per Statement, one column per Party in ranking order, every column
 * built the same way and `--matrix-party-width` wide (logo-only headers). A
 * cell shows the Party's stance as its side icon and is tinted when it
 * coincides with the Answer (one accent, never a colour per side or per
 * Party); its accessible name has the stance and whether it coincides. A cell opens that Position in the inspector, a Statement opens
 * every Party's.
 */
export function ResultsMatrix({
  rows,
  answerHeading,
  coincidenceCopy,
  onOpenPosition,
  onOpenStatement,
}: {
  readonly rows: readonly BreakdownRow[];
  readonly answerHeading: string;
  readonly coincidenceCopy: CoincidenceCopy;
  readonly onOpenPosition: (row: BreakdownRow, partyId: number, trigger: HTMLElement) => void;
  readonly onOpenStatement: (row: BreakdownRow, trigger: HTMLElement) => void;
}) {
  const parties = rows[0]?.positions ?? [];
  return (
    <>
      <div className="matrix-legend">
        <p className="matrix-legend__icons">
          {LEGEND_SIDES.map(({ side, label }) => (
            <span key={side} className="matrix-legend__item">
              <SideIcon side={side} className="matrix-legend__icon" />
              {label}
            </span>
          ))}
          <span className="matrix-legend__item">
            <strong aria-hidden="true">{NO_VALUE}</strong>
            {NO_STANCE_LABEL}
          </span>
        </p>
        <p className="matrix-legend__scale">
          <span>Coincidencia con la respuesta:</span>
          {MATCH_STEPS.map(({ step, label }) => (
            <span key={step} className="matrix-legend__step">
              <span className="match-swatch" data-match={step} aria-hidden="true" />
              {label}
            </span>
          ))}
        </p>
      </div>
      <div
        className="matrix-scroll"
        role="region"
        aria-label="Matriz de posiciones"
        tabIndex={0}
        onFocus={revealFocusedCell}
      >
        <table className="matrix">
          <caption className="visually-hidden">
            Posición de cada partido en cada afirmación y su coincidencia con la respuesta
          </caption>
          <thead>
            <tr>
              <th scope="col" className="matrix__statement-head">
                Afirmación
              </th>
              <th scope="col" className="matrix__answer-head">
                {answerHeading}
              </th>
              {parties.map((party) => (
                <th key={party.partyId} scope="col" className="matrix__party-head">
                  {/* Logo only (ui-2026-focus-tweaks): every Party column is
                      the same width; the full name is the header's name. */}
                  <PartyLogo logoUrl={party.logoUrl} shortName={party.shortName} size="breakdown" />
                  <span className="visually-hidden">{party.name}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.statementId}>
                <th scope="row" className="matrix__statement">
                  <button
                    type="button"
                    className="matrix__statement-button"
                    onClick={(event) => onOpenStatement(row, event.currentTarget)}
                  >
                    <span className="matrix__number">{row.position}</span>
                    <span className="matrix__text">{row.text}</span>
                  </button>
                </th>
                {/* A pointer shortcut to the Statement button beside it, which
                    stays the one keyboard stop and the focus to return to. */}
                <td
                  className="matrix__answer"
                  onClick={(event) => {
                    const statement = event.currentTarget
                      .closest("tr")
                      ?.querySelector<HTMLButtonElement>(".matrix__statement-button");
                    if (statement) onOpenStatement(row, statement);
                  }}
                >
                  <AnswerChip row={row} />
                </td>
                {row.positions.map((position) => {
                  const match = coincidence(row, position);
                  const stance = stanceLabel(position, NO_STANCE_LABEL);
                  const name =
                    `${position.name}: ${stance}` +
                    (match === null ? "" : `, ${match === 100 ? coincidenceCopy.yes : coincidenceCopy.no}`) +
                    (position.value === NO_STANCE ? "" : ". Ver la cita");
                  return (
                    <td key={position.partyId} className="matrix__cell">
                      <button
                        type="button"
                        className="match-cell"
                        data-match={match ?? "none"}
                        aria-label={name}
                        onClick={(event) => onOpenPosition(row, position.partyId, event.currentTarget)}
                      >
                        {position.value === NO_STANCE ? (
                          NO_VALUE
                        ) : (
                          <SideIcon side={stanceSide(position.value)} className="match-cell__icon" />
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// The browser's own focus scrolling moves a cell only when it is fully
// hidden, so a partly visible cell would stay under the sticky columns or past
// the box's edge. scrollIntoView honours the box's scroll-padding.
function revealFocusedCell(event: FocusEvent<HTMLDivElement>) {
  const target = event.target;
  if (target instanceof HTMLElement && target.classList.contains("match-cell")) {
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

// The Answer as its icon; the full label stays for screen readers.
function AnswerChip({ row }: { readonly row: BreakdownRow }) {
  return (
    <span className="answer-chip">
      {row.answer === null ? (
        <span aria-hidden="true">{NO_VALUE}</span>
      ) : (
        <SideIcon side={answerSide(row.answer)} className="answer-chip__icon" />
      )}
      <span className="visually-hidden">{answerLabel(row.answer)}</span>
      {row.important ? (
        <>
          <StarIcon className="answer-chip__star" />
          <span className="visually-hidden">, importante</span>
        </>
      ) : null}
    </span>
  );
}

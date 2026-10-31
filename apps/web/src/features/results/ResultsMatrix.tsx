import { NO_STANCE, SKIP, type BreakdownRow } from "@ideology-app/core";

import { StarIcon } from "../../ui/icons";
import { coincidence, SHORT_LABELS, stanceLabel } from "./breakdown-view";
import { answerLabel, NO_STANCE_LABEL } from "./Evidence";
import { PartyLogo } from "./PartyLogo";

const MATCH_STEPS = [100, 75, 50, 25, 0] as const;

/**
 * The Statement matrix (DESIGN.md "Statement matrix", 1024px and up): one
 * row per Statement, one column per Party in ranking order, every column
 * built the same way. A cell shows the Party's stance as a short label and is
 * tinted by its coincidence with the Answer (one accent, never a colour per
 * side or per Party); its accessible name has the full stance and the
 * coincidence. A cell opens that Position in the inspector, a Statement opens
 * every Party's.
 */
export function ResultsMatrix({
  rows,
  answerHeading,
  onOpenPosition,
  onOpenStatement,
}: {
  readonly rows: readonly BreakdownRow[];
  readonly answerHeading: string;
  readonly onOpenPosition: (row: BreakdownRow, partyId: number, trigger: HTMLElement) => void;
  readonly onOpenStatement: (row: BreakdownRow, trigger: HTMLElement) => void;
}) {
  const parties = rows[0]?.positions ?? [];
  return (
    <>
      <div className="matrix-scroll" role="region" aria-label="Matriz de posiciones" tabIndex={0}>
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
                  <PartyLogo logoUrl={party.logoUrl} shortName={party.shortName} size="breakdown" />
                  <span aria-hidden="true" className="matrix__party-short">
                    {party.shortName}
                  </span>
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
                <td className="matrix__answer">
                  <AnswerChip row={row} />
                </td>
                {row.positions.map((position) => {
                  const match = coincidence(row, position);
                  const stance = stanceLabel(position, NO_STANCE_LABEL);
                  const name =
                    `${position.name}: ${stance}` +
                    (match === null ? "" : `, coincidencia ${match} %`) +
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
                        {SHORT_LABELS[position.value]}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="matrix-legend">
        <p>
          <strong>MA</strong> Muy de acuerdo · <strong>A</strong> De acuerdo · <strong>N</strong> Ni de
          acuerdo ni en desacuerdo · <strong>D</strong> En desacuerdo · <strong>MD</strong> Muy en
          desacuerdo · <strong>—</strong> Sin posición en el programa
        </p>
        <p className="matrix-legend__scale">
          <span>Coincidencia con la respuesta:</span>
          {MATCH_STEPS.map((step) => (
            <span key={step} className="matrix-legend__step">
              <span className="match-swatch" data-match={step} aria-hidden="true" />
              {`${step} %`}
            </span>
          ))}
        </p>
      </div>
    </>
  );
}

// The Answer as a short label; the full one stays for screen readers.
function AnswerChip({ row }: { readonly row: BreakdownRow }) {
  const short = row.answer === null ? "—" : row.answer === SKIP ? "Salt." : SHORT_LABELS[row.answer];
  return (
    <span className="answer-chip">
      <span aria-hidden="true">{short}</span>
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

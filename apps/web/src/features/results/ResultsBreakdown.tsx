import { NO_STANCE, SKIP, type BreakdownPosition, type BreakdownRow } from "@ideology-app/core";

import { SCALE_LABELS } from "../scale-labels";

const INTRO_REST =
  "y la posición de cada partido en cada afirmación. Las posiciones y las citas " +
  "las ha extraído una inteligencia artificial de los programas electorales: abre una posición " +
  "para leer la cita en la que se basa y comprobarla.";

/**
 * Whose Answers the rows show: the Voter's own (end screen) or a Share
 * Link's (shared result, which the opener may not have written).
 */
export type AnswerOwner = "voter" | "link";

const OWNER_COPY: Readonly<Record<AnswerOwner, { readonly intro: string; readonly answer: string }>> = {
  voter: { intro: `Tu respuesta ${INTRO_REST}`, answer: "Tu respuesta:" },
  link: { intro: `La respuesta del enlace ${INTRO_REST}`, answer: "Respuesta del enlace:" },
};

export const NO_STANCE_LABEL = "Sin posición en el programa";
export const SKIPPED_LABEL = "Saltada (no cuenta para la afinidad)";
export const UNANSWERED_LABEL = "Sin responder";
export const IMPORTANT_MARK = "Importante (cuenta el doble)";

const NO_STANCE_SENTENCE =
  "El programa de este partido no trata esta afirmación, así que no cuenta para su afinidad.";

/**
 * The results breakdown (DESIGN.md "Breakdown row"): one row per Statement
 * with the Voter's Answer and every Party's Position as a native disclosure
 * revealing its Evidence. Renders `rows` as given (from `buildBreakdown`, so
 * Parties follow the ranking order) and treats every Party the same.
 * AI-generated text is rendered as React text, never as HTML.
 */
export function ResultsBreakdown({
  rows,
  answerOwner = "voter",
}: {
  readonly rows: readonly BreakdownRow[];
  readonly answerOwner?: AnswerOwner;
}) {
  const copy = OWNER_COPY[answerOwner];
  return (
    <section className="breakdown-section" aria-labelledby="breakdown-title">
      <h3 id="breakdown-title" className="breakdown-section__title">Detalle por afirmación</h3>
      <p>{copy.intro}</p>
      <ol className="breakdown" role="list" aria-labelledby="breakdown-title">
        {rows.map((row) => (
          <Row key={row.statementId} row={row} answerPrefix={copy.answer} />
        ))}
      </ol>
    </section>
  );
}

function answerLabel(answer: BreakdownRow["answer"]): string {
  if (answer === null) return UNANSWERED_LABEL;
  if (answer === SKIP) return SKIPPED_LABEL;
  return SCALE_LABELS[answer];
}

function Row({ row, answerPrefix }: { readonly row: BreakdownRow; readonly answerPrefix: string }) {
  return (
    <li className="breakdown-row">
      <p className="breakdown-row__number">{`Afirmación ${row.position}`}</p>
      <h4 className="breakdown-row__statement">{row.text}</h4>
      <p className="breakdown-row__answer">
        {answerPrefix} <strong>{answerLabel(row.answer)}</strong>
        {row.important ? (
          <>
            {" "}
            <span className="important-mark">{IMPORTANT_MARK}</span>
          </>
        ) : null}
      </p>
      <ul className="breakdown-positions" role="list" aria-label="Posiciones de los partidos">
        {row.positions.map((position) => (
          <li key={position.partyId}>
            <Position position={position} />
          </li>
        ))}
      </ul>
    </li>
  );
}

function Position({ position }: { readonly position: BreakdownPosition }) {
  const value = position.value === NO_STANCE ? NO_STANCE_LABEL : SCALE_LABELS[position.value];
  return (
    <details className="position">
      <summary className="position__summary">
        <span className="position__name">{position.name}</span>{" "}
        <span className="position__short">{position.shortName}</span>{" "}
        <span className="position__value">{value}</span>
      </summary>
      <div className="position__body">
        {position.evidence === null ? (
          <p className="evidence__none">{NO_STANCE_SENTENCE}</p>
        ) : (
          <>
            <blockquote className="evidence__quote">{position.evidence.quote}</blockquote>
            {position.evidence.href === null ? (
              <p className="evidence__page">
                {`Página ${position.evidence.page} del programa electoral. Este documento no tiene un enlace público.`}
              </p>
            ) : (
              <p className="evidence__link">
                <a
                  className="text-link"
                  href={position.evidence.href}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {`Ver en el programa, página ${position.evidence.page} (se abre en una pestaña nueva)`}
                </a>
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}

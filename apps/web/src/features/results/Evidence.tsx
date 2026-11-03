import { NO_STANCE, SKIP, type BreakdownPosition, type BreakdownRow } from "@ideology-app/core";

import { StarIcon, StepOverIcon } from "../../ui/icons";
import { ScaleIcon } from "../scale-icons";
import { SCALE_LABELS } from "../scale-labels";

export const NO_STANCE_LABEL = "Sin posición en el programa";
export const SKIPPED_LABEL = "Saltada (no cuenta para la afinidad)";
export const UNANSWERED_LABEL = "Sin responder";
export const IMPORTANT_MARK = "Importante (cuenta el doble)";

const NO_STANCE_SENTENCE =
  "El programa de este partido no trata esta afirmación, así que no cuenta para su afinidad.";

export function answerLabel(answer: BreakdownRow["answer"]): string {
  if (answer === null) return UNANSWERED_LABEL;
  if (answer === SKIP) return SKIPPED_LABEL;
  return SCALE_LABELS[answer];
}

/** The decorative icon of an Answer or stance: its scale icon, step-over when skipped, none otherwise. */
export function ValueIcon({ value }: { readonly value: BreakdownRow["answer"] | BreakdownPosition["value"] }) {
  if (value === null || value === NO_STANCE) return null;
  if (value === SKIP) return <StepOverIcon className="value-icon" />;
  return <ScaleIcon value={value} className="value-icon" />;
}

/** `Tu respuesta: <label>` plus the Important mark, as on every breakdown view. */
export function AnswerLine({
  row,
  prefix,
  className,
}: {
  readonly row: BreakdownRow;
  readonly prefix: string;
  readonly className: string;
}) {
  return (
    <p className={className}>
      {prefix}{" "}
      <strong className="value-label">
        <ValueIcon value={row.answer} />
        {answerLabel(row.answer)}
      </strong>
      {row.important ? (
        <>
          {" "}
          <span className="important-mark">
            <StarIcon className="important-mark__star" />
            {IMPORTANT_MARK}
          </span>
        </>
      ) : null}
    </p>
  );
}

/**
 * A Position's Evidence (DESIGN.md "Evidence quote"): the verbatim quote as
 * text and its locator, or the no-stance sentence. AI-generated text is
 * rendered as React text, never as HTML.
 */
export function EvidenceBody({ position }: { readonly position: BreakdownPosition }) {
  if (position.value === NO_STANCE || position.evidence === null) {
    return <p className="evidence__none">{NO_STANCE_SENTENCE}</p>;
  }
  const { quote, page, href } = position.evidence;
  return (
    <>
      <blockquote className="evidence__quote">{quote}</blockquote>
      {href === null ? (
        <p className="evidence__page">
          {`Página ${page} del programa electoral. Este documento no tiene un enlace público.`}
        </p>
      ) : (
        <p className="evidence__link">
          <a className="text-link" href={href} target="_blank" rel="noopener noreferrer">
            {`Ver en el programa, página ${page} (se abre en una pestaña nueva)`}
          </a>
        </p>
      )}
    </>
  );
}

import { useRef, useState } from "react";

import type { BreakdownPosition, BreakdownRow } from "@ideology-app/core";

import { useMediaQuery } from "../common/useMediaQuery";
import { BREAKDOWN_FILTERS, matchesFilter, stanceLabel, type BreakdownFilter } from "./breakdown-view";
import { AnswerLine, EvidenceBody, NO_STANCE_LABEL, ValueIcon } from "./Evidence";
import { EvidenceInspector, type InspectorTarget } from "./EvidenceInspector";
import { PartyLogo } from "./PartyLogo";
import { ResultsMatrix } from "./ResultsMatrix";

export { IMPORTANT_MARK, NO_STANCE_LABEL, SKIPPED_LABEL, UNANSWERED_LABEL } from "./Evidence";

const INTRO =
  "Haz click en una afirmación o posición para ver las citas coincidentes extraídas de los " +
  "programas electorales.";

/** From this width the breakdown is the Statement matrix (DESIGN.md "Statement matrix"). */
export const MATRIX_QUERY = "(min-width: 1024px)";

/**
 * Whose Answers the rows show: the Voter's own (end screen) or a Share
 * Link's (shared result, which the opener may not have written).
 */
export type AnswerOwner = "voter" | "link";

const OWNER_COPY: Readonly<
  Record<
    AnswerOwner,
    {
      readonly title: string;
      readonly answer: string;
      readonly answerHeading: string;
      readonly coincidence: string;
    }
  >
> = {
  voter: {
    title: "Comprueba de dónde salen tus coincidencias",
    answer: "Tu respuesta:",
    answerHeading: "Tú",
    coincidence: "coincidencia contigo",
  },
  link: {
    title: "Comprueba de dónde salen las coincidencias del enlace",
    answer: "Respuesta del enlace:",
    answerHeading: "Enlace",
    coincidence: "coincidencia con el enlace",
  },
};

/**
 * The results breakdown (DESIGN.md "Breakdown row", "Breakdown filters",
 * "Statement matrix", "Inspector panel"). Answer filters, then from 1024px
 * the Statement matrix with the Evidence inspector, and below it one card per
 * Statement with every Party's Position as a native disclosure revealing its
 * Evidence. Renders `rows` as given (from `buildBreakdown`, so Parties follow
 * the ranking order) and treats every Party the same.
 */
export function ResultsBreakdown({
  rows,
  answerOwner = "voter",
}: {
  readonly rows: readonly BreakdownRow[];
  readonly answerOwner?: AnswerOwner;
}) {
  const copy = OWNER_COPY[answerOwner];
  const wide = useMediaQuery(MATRIX_QUERY);
  const [filter, setFilter] = useState<BreakdownFilter>("all");
  const [inspector, setInspector] = useState<InspectorTarget | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const shown = rows.filter((row) => matchesFilter(row, filter));

  function open(target: InspectorTarget, from: HTMLElement) {
    trigger.current = from;
    setInspector(target);
  }

  return (
    <section className="breakdown-section" aria-labelledby="breakdown-title">
      <h3 id="breakdown-title" className="breakdown-section__title" tabIndex={-1} ref={headingRef}>
        {copy.title}
      </h3>
      <p>{INTRO}</p>
      <div className="breakdown-filters" role="group" aria-label="Filtrar afirmaciones">
        {BREAKDOWN_FILTERS.map((option) => (
          <button
            key={option.id}
            type="button"
            className="filter-chip"
            aria-pressed={filter === option.id}
            onClick={() => setFilter(option.id)}
          >
            {option.label}
            <span className="filter-chip__count">
              {rows.filter((row) => matchesFilter(row, option.id)).length}
            </span>
          </button>
        ))}
      </div>
      <p className="visually-hidden" role="status">
        {`${shown.length} de ${rows.length} afirmaciones`}
      </p>
      {shown.length === 0 && rows.length > 0 ? (
        <p className="breakdown-empty">Ninguna afirmación coincide con este filtro.</p>
      ) : wide ? (
        <ResultsMatrix
          rows={shown}
          answerHeading={copy.answerHeading}
          onOpenPosition={(row, partyId, from) => open({ kind: "position", row, partyId }, from)}
          onOpenStatement={(row, from) => open({ kind: "statement", row }, from)}
        />
      ) : (
        <ol className="breakdown" role="list" aria-labelledby="breakdown-title">
          {shown.map((row) => (
            <Row key={row.statementId} row={row} answerPrefix={copy.answer} />
          ))}
        </ol>
      )}
      {inspector === null ? null : (
        <EvidenceInspector
          target={inspector}
          answerPrefix={copy.answer}
          coincidencePrefix={copy.coincidence}
          onClosed={() => {
            setInspector(null);
            // The opener is gone if the layout switched (matrix <-> cards)
            // while the inspector was open: fall back to the section heading.
            if (trigger.current?.isConnected === true) {
              trigger.current.focus();
            } else {
              headingRef.current?.focus();
            }
          }}
        />
      )}
    </section>
  );
}

function Row({ row, answerPrefix }: { readonly row: BreakdownRow; readonly answerPrefix: string }) {
  return (
    <li className="breakdown-row">
      <p className="breakdown-row__number">{`Afirmación ${row.position}`}</p>
      <h4 className="breakdown-row__statement">{row.text}</h4>
      <AnswerLine row={row} prefix={answerPrefix} className="breakdown-row__answer" />
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
  return (
    <details className="position">
      <summary className="position__summary">
        <PartyLogo logoUrl={position.logoUrl} shortName={position.shortName} size="breakdown" />
        <span className="position__label">
          <span className="position__name">{position.name}</span>{" "}
          <span className="position__short">{position.shortName}</span>{" "}
          <span className="position__value">
            <ValueIcon value={position.value} />
            {stanceLabel(position, NO_STANCE_LABEL)}
          </span>
        </span>
      </summary>
      <div className="position__body">
        <EvidenceBody position={position} />
      </div>
    </details>
  );
}

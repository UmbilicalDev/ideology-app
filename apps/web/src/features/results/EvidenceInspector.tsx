import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { BreakdownRow } from "@ideology-app/core";

import { CloseIcon } from "../../ui/icons";
import { coincidence, stanceLabel } from "./breakdown-view";
import { AnswerLine, EvidenceBody, NO_STANCE_LABEL, ValueIcon } from "./Evidence";
import { PartyLogo } from "./PartyLogo";

/** What the inspector shows: one Party's Position on a Statement, or every Party's. */
export type InspectorTarget =
  | { readonly kind: "position"; readonly row: BreakdownRow; readonly partyId: number }
  | { readonly kind: "statement"; readonly row: BreakdownRow };

/**
 * The Evidence inspector (DESIGN.md "Inspector panel"): a modal side sheet
 * (native `<dialog>`, `showModal`) over the Statement matrix that shows the
 * Evidence of a cell, or of every Party on a Statement, without leaving the
 * results. Escape, the close button or a backdrop click close it; the caller
 * returns focus to the cell. Every Party is shown the same way, in ranking order.
 */
export function EvidenceInspector({
  target,
  answerPrefix,
  coincidencePrefix,
  onClosed,
}: {
  readonly target: InspectorTarget;
  readonly answerPrefix: string;
  readonly coincidencePrefix: string;
  readonly onClosed: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const pressedBackdrop = useRef(false);
  const closed = useRef(false);
  // "Ver todos los partidos" switches a cell view to the Statement view.
  const [view, setView] = useState<InspectorTarget>(target);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const switched = useRef(false);

  // StrictMode-safe: a second run finds the dialog already open.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog !== null && !dialog.open) {
      dialog.showModal();
    }
    closeRef.current?.focus();
  }, []);

  // "Ver todos" unmounts itself: focus moves to the Statement heading.
  useEffect(() => {
    if (switched.current) {
      titleRef.current?.focus();
    }
  }, [view]);

  function finish() {
    if (!closed.current) {
      closed.current = true;
      onClosed();
    }
  }

  function close() {
    dialogRef.current?.close();
    finish();
  }

  const { row } = view;
  const positions =
    view.kind === "position" ? row.positions.filter((p) => p.partyId === view.partyId) : row.positions;

  return (
    <dialog
      ref={dialogRef}
      className="inspector"
      aria-labelledby="inspector-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClose={finish}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (pressedBackdrop.current && event.target === event.currentTarget) {
          close();
        }
        pressedBackdrop.current = false;
      }}
    >
      <div className="inspector__surface">
        <div className="inspector__header">
          <p className="inspector__number">{`Afirmación ${row.position}`}</p>
          <button
            type="button"
            className="icon-button"
            aria-label="Cerrar"
            ref={closeRef}
            onClick={close}
          >
            <CloseIcon />
          </button>
        </div>
        <h2 id="inspector-title" className="inspector__statement" tabIndex={-1} ref={titleRef}>
          {row.text}
        </h2>
        <AnswerLine row={row} prefix={answerPrefix} className="inspector__answer" />
        <ul className="inspector__positions" role="list" aria-label="Posiciones de los partidos">
          {positions.map((position) => {
            const match = coincidence(row, position);
            return (
              <li key={position.partyId} className="inspector-position">
                <div className="inspector-position__head">
                  <PartyLogo logoUrl={position.logoUrl} shortName={position.shortName} size="breakdown" />
                  <span className="inspector-position__label">
                    <span className="inspector-position__name">{position.name}</span>{" "}
                    <span className="inspector-position__short">{position.shortName}</span>
                  </span>
                </div>
                <p className="inspector-position__stance">
                  <strong className="value-label">
                    <ValueIcon value={position.value} />
                    {stanceLabel(position, NO_STANCE_LABEL)}
                  </strong>
                  {match === null ? null : (
                    <span className="inspector-position__match">{` · ${coincidencePrefix} ${match} %`}</span>
                  )}
                </p>
                <EvidenceBody position={position} />
              </li>
            );
          })}
        </ul>
        {view.kind === "position" ? (
          <p className="inspector__more">
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                switched.current = true;
                setView({ kind: "statement", row });
              }}
            >
              Ver todos los partidos en esta afirmación
            </button>
          </p>
        ) : null}
      </div>
    </dialog>
  );
}

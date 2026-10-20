import { useEffect, useReducer, useRef, type RefObject } from "react";
import { Link } from "react-router";

import {
  SKIP,
  currentStatementId,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  type AnswerValue,
  type DatasetVersion,
  type Election,
  type QuestionnaireAction,
  type QuestionnaireState,
  type ScaleValue,
  type Statement,
} from "@ideology-app/core";

import { HOME_PATH } from "../paths";

// The five options in scale order. Meaning is carried by the text, never by
// colour alone (DESIGN.md).
const SCALE_OPTIONS: readonly { readonly value: ScaleValue; readonly label: string }[] = [
  { value: -2, label: "Muy en desacuerdo" },
  { value: -1, label: "En desacuerdo" },
  { value: 0, label: "Ni de acuerdo ni en desacuerdo" },
  { value: 1, label: "De acuerdo" },
  { value: 2, label: "Muy de acuerdo" },
];

const NOTE =
  "Las afirmaciones las ha generado una inteligencia artificial a partir de los programas " +
  "electorales. Tus respuestas se quedan en este navegador: no se envían a ningún servidor y " +
  "se pierden si recargas o sales de la página.";

function init(datasetVersion: DatasetVersion): QuestionnaireState {
  return startQuestionnaire(datasetVersion.statements.map((statement) => statement.id));
}

const IMPORTANT_HINT = "Las afirmaciones importantes cuentan el doble al calcular la afinidad.";

/**
 * The Questionnaire itself (DESIGN.md Core Screens 2). Answers and Important
 * flags live only in this component's reducer state: never in a request, the
 * URL or browser storage, so a reload or leaving the page discards them.
 */
export function QuestionnaireFlow({
  election,
  datasetVersion,
}: {
  readonly election: Election;
  readonly datasetVersion: DatasetVersion;
}) {
  const [state, dispatch] = useReducer(reduceQuestionnaire, datasetVersion, init);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Focus follows navigation, but not the initial load.
  const focusPending = useRef(false);

  useEffect(() => {
    if (focusPending.current) {
      focusPending.current = false;
      headingRef.current?.focus();
    }
  }, [state.currentIndex]);

  function move(action: QuestionnaireAction) {
    focusPending.current = true;
    dispatch(action);
  }

  const statementId = currentStatementId(state);
  const statement = datasetVersion.statements.find((s) => s.id === statementId);

  return (
    <>
      <p className="questionnaire__election">{election.name}</p>
      {statement === undefined ? (
        <EndScreen state={state} headingRef={headingRef} onBack={() => move({ type: "back" })} />
      ) : (
        <StatementStep
          key={statement.id}
          statement={statement}
          index={state.currentIndex}
          total={state.statementIds.length}
          answer={state.answers.get(statement.id)}
          important={state.important.has(statement.id)}
          headingRef={headingRef}
          onSelect={(value) => dispatch({ type: "select", value })}
          onToggleImportant={() => dispatch({ type: "toggleImportant" })}
          onMove={move}
        />
      )}
    </>
  );
}

function StatementStep({
  statement,
  index,
  total,
  answer,
  important,
  headingRef,
  onSelect,
  onToggleImportant,
  onMove,
}: {
  readonly statement: Statement;
  readonly index: number;
  readonly total: number;
  readonly answer: AnswerValue | undefined;
  readonly important: boolean;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly onSelect: (value: ScaleValue) => void;
  readonly onToggleImportant: () => void;
  readonly onMove: (action: QuestionnaireAction) => void;
}) {
  const n = index + 1;
  return (
    <>
      <p id="questionnaire-progress" className="questionnaire__progress-label">
        {`Afirmación ${n} de ${total}`}
      </p>
      <progress
        className="questionnaire__progress"
        max={total}
        value={n}
        aria-labelledby="questionnaire-progress"
      />
      <h2 id="statement-text" className="questionnaire__statement" tabIndex={-1} ref={headingRef}>
        {statement.text}
      </h2>
      <button
        type="button"
        className="important-toggle"
        aria-pressed={important}
        aria-describedby="important-hint"
        onClick={onToggleImportant}
      >
        <StarIcon />
        <span>Importante para mí</span>
      </button>
      <p id="important-hint" className="questionnaire__hint">
        {IMPORTANT_HINT}
      </p>
      <div role="radiogroup" aria-labelledby="statement-text" className="scale">
        {SCALE_OPTIONS.map((option) => (
          <label key={option.value} className="scale-option">
            <input
              type="radio"
              name={`answer-${statement.id}`}
              value={option.value}
              checked={answer === option.value}
              onChange={() => onSelect(option.value)}
            />{" "}
            <span>{option.label}</span>
          </label>
        ))}
      </div>
      {answer === SKIP ? <p className="questionnaire__skipped">Has saltado esta afirmación.</p> : null}
      <div className="questionnaire__controls">
        <button
          type="button"
          className="button-primary"
          disabled={answer === undefined}
          onClick={() => onMove({ type: "next" })}
        >
          Siguiente
        </button>
        <button type="button" className="button-secondary" onClick={() => onMove({ type: "skip" })}>
          Saltar esta afirmación
        </button>
        {index > 0 ? (
          <button type="button" className="button-secondary" onClick={() => onMove({ type: "back" })}>
            Anterior
          </button>
        ) : null}
      </div>
      <p className="questionnaire__note">{NOTE}</p>
    </>
  );
}

function EndScreen({
  state,
  headingRef,
  onBack,
}: {
  readonly state: QuestionnaireState;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly onBack: () => void;
}) {
  const { answered, skipped, important, total } = summarize(state);
  return (
    <>
      <h2 tabIndex={-1} ref={headingRef}>
        Has llegado al final del cuestionario
      </h2>
      <p>
        {`Has respondido ${answered} de ${total} afirmaciones y has saltado ${skipped}.`}
      </p>
      <p>{importantSentence(important)}</p>
      <p>Los resultados estarán disponibles muy pronto.</p>
      <div className="questionnaire__controls">
        <button type="button" className="button-secondary" onClick={onBack}>
          Volver a la última afirmación
        </button>
      </div>
      <p>
        <Link className="back-link" to={HOME_PATH}>
          Volver al inicio
        </Link>
      </p>
    </>
  );
}

// Outline when not pressed, filled amber when pressed (components.css): the
// shape carries the state, not only the colour.
function StarIcon() {
  return (
    <svg
      className="important-toggle__star"
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
    >
      <path
        d="M12 2.5l2.94 5.96 6.56.95-4.75 4.63 1.12 6.54L12 17.5l-5.87 3.08 1.12-6.54L2.5 9.41l6.56-.95z"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function importantSentence(count: number): string {
  if (count === 0) {
    return "No has marcado ninguna afirmación como importante.";
  }
  if (count === 1) {
    return "Has marcado 1 afirmación como importante.";
  }
  return `Has marcado ${count} afirmaciones como importantes.`;
}

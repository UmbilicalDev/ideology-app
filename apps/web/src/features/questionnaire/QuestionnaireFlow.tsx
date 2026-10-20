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

/**
 * The Questionnaire itself (DESIGN.md Core Screens 2). Answers live only in
 * this component's reducer state: never in a request, the URL or browser
 * storage, so a reload or leaving the page discards them.
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
          headingRef={headingRef}
          onSelect={(value) => dispatch({ type: "select", value })}
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
  headingRef,
  onSelect,
  onMove,
}: {
  readonly statement: Statement;
  readonly index: number;
  readonly total: number;
  readonly answer: AnswerValue | undefined;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly onSelect: (value: ScaleValue) => void;
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
  const { answered, skipped, total } = summarize(state);
  return (
    <>
      <h2 tabIndex={-1} ref={headingRef}>
        Has llegado al final del cuestionario
      </h2>
      <p>
        {`Has respondido ${answered} de ${total} afirmaciones y has saltado ${skipped}.`}
      </p>
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

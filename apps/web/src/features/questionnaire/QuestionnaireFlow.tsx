import { useEffect, useMemo, useReducer, useRef, type RefObject } from "react";
import { Link } from "react-router";

import {
  SKIP,
  buildResults,
  currentStatementId,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  type AnswerValue,
  type DatasetVersion,
  type Election,
  type QuestionnaireAction,
  type QuestionnaireState,
  type Results,
  type ScaleValue,
  type Statement,
} from "@ideology-app/core";

import { ExternalLinkIcon, StarIcon } from "../../ui/icons";
import { HomeButton } from "../common/HomeButton";
import { NoticeCard } from "../common/NoticeCard";
import { METHODOLOGY_PATH } from "../paths";
import { ResultsBreakdown } from "../results/ResultsBreakdown";
import { ResultsRanking } from "../results/ResultsRanking";
import { ResultsSummary } from "../results/ResultsSummary";
import { SCALE_LABELS } from "../scale-labels";
import { ShareApp } from "../share/ShareApp";
import { ShareResults } from "../share/ShareResults";

// The five options in scale order. Meaning is carried by the text, never by
// colour alone (DESIGN.md).
const SCALE_OPTIONS: readonly { readonly value: ScaleValue; readonly label: string }[] = (
  [-2, -1, 0, 1, 2] as const
).map((value) => ({ value, label: SCALE_LABELS[value] }));

const NOTE =
  "Las afirmaciones las ha generado una inteligencia artificial a partir de los programas " +
  "electorales. Tus respuestas se quedan en este navegador: no se envían a ningún servidor y " +
  "se pierden si recargas o sales de la página.";

const DISCLOSURE_TITLE = "Transparencia algorítmica y privacidad garantizada";

function init(datasetVersion: DatasetVersion): QuestionnaireState {
  return startQuestionnaire(datasetVersion.statements.map((statement) => statement.id));
}

const RESULTS_INTRO = "Afinidad entre tus respuestas y el programa de cada partido, de mayor a menor.";

const NO_RESULTS_PROMPT =
  "Todavía no se puede calcular tu afinidad: no has respondido ninguna afirmación en la que " +
  "los partidos tengan posición. Responde al menos una para ver los resultados.";

const DISCLAIMER =
  "Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los " +
  "programas, según una inteligencia artificial que puede equivocarse.";

const RESULTS_NOTE =
  "Tus respuestas siguen solo en este navegador: si recargas la página, vuelves atrás con el " +
  "navegador o sales de aquí, se pierden.";

// Only when there is a share section to point at.
const RESULTS_NOTE_SHARE =
  "Para volver a verlo más tarde, copia antes el enlace de «Comparte tu resultado».";

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
  // Recomputed from the in-memory state on every change; nothing is cached
  // or sent anywhere. The shared result (Share Link) uses the same function.
  const results = useMemo(() => buildResults(datasetVersion, state), [state, datasetVersion]);

  return (
    <>
      <p className="questionnaire__election">{election.name}</p>
      {statement === undefined ? (
        <EndScreen
          datasetVersionId={datasetVersion.id}
          state={state}
          results={results}
          headingRef={headingRef}
          onBack={() => move({ type: "back" })}
          onFirst={() => move({ type: "first" })}
        />
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
      <div className="statement-card">
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
        <div className="important-row">
          <button
            type="button"
            className="important-toggle"
            aria-pressed={important}
            aria-describedby="important-hint"
            onClick={onToggleImportant}
          >
            <StarIcon className="important-toggle__star" />
            <span>Importante para mí</span>
          </button>
          <p id="important-hint" className="questionnaire__hint">
            {IMPORTANT_HINT}
          </p>
        </div>
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
      </div>
      <section className="disclosure-card" aria-labelledby="ai-privacy-title">
        <span className="disclosure-card__icon">
          <ShieldIcon />
        </span>
        <div>
          <h3 id="ai-privacy-title" className="disclosure-card__title">
            {DISCLOSURE_TITLE}
          </h3>
          <p className="questionnaire__note">{NOTE}</p>
        </div>
      </section>
    </>
  );
}

function EndScreen({
  datasetVersionId,
  state,
  results,
  headingRef,
  onBack,
  onFirst,
}: {
  readonly datasetVersionId: number;
  readonly state: QuestionnaireState;
  readonly results: Results;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly onBack: () => void;
  readonly onFirst: () => void;
}) {
  const { answered, skipped, important, total } = summarize(state);
  // A ranking needs one rated Statement on which some Party has a stance.
  const { ranking, breakdown, hasScores } = results;
  return (
    <>
      <h2 id="results-title" tabIndex={-1} ref={headingRef}>
        Tus resultados
      </h2>
      <ResultsSummary
        answered={answered}
        skipped={skipped}
        important={important}
        total={total}
        voice="voter"
      />
      {hasScores ? (
        <>
          <p>{RESULTS_INTRO}</p>
          <ResultsRanking ranking={ranking} />
        </>
      ) : (
        <p>{NO_RESULTS_PROMPT}</p>
      )}
      <div className="share-card">
        {hasScores ? <ShareResults datasetVersionId={datasetVersionId} state={state} /> : null}
        <ShareApp />
      </div>
      <div className="questionnaire__controls">
        <button type="button" className="button-primary" onClick={onFirst}>
          Revisar mis respuestas
        </button>
        <button type="button" className="button-secondary" onClick={onBack}>
          Volver a la última afirmación
        </button>
      </div>
      <NoticeCard text={DISCLAIMER} />
      <p>
        <Link className="text-link" to={METHODOLOGY_PATH} target="_blank" rel="noopener">
          Cómo se calcula la afinidad{" "}
          <span className="visually-hidden">(se abre en una pestaña nueva)</span>
          <ExternalLinkIcon />
        </Link>
      </p>
      <HomeButton />
      <ResultsBreakdown rows={breakdown} />
      <p className="questionnaire__note">
        {hasScores ? `${RESULTS_NOTE} ${RESULTS_NOTE_SHARE}` : RESULTS_NOTE}
      </p>
      <HomeButton />
    </>
  );
}

// Decorative shield on the disclosure card (an original drawing).
function ShieldIcon() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path d="M12 3l7 3v5c0 4.5-3 8.3-7 9.5-4-1.2-7-5-7-9.5V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

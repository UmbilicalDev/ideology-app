import { useEffect, useMemo, useReducer, useRef, useState, type RefObject } from "react";
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
  type FeedbackApi,
  type QuestionnaireAction,
  type QuestionnaireState,
  type Results,
  type ScaleValue,
  type Statement,
} from "@ideology-app/core";

import {
  ArrowBackIcon,
  ArrowForwardIcon,
  ExternalLinkIcon,
  ShieldIcon,
  StarIcon,
  StepOverIcon,
} from "../../ui/icons";
import { FeedbackButton } from "../feedback/FeedbackButton";
import { METHODOLOGY_PATH } from "../paths";
import { useMediaQuery } from "../common/useMediaQuery";
import { MATRIX_QUERY, ResultsBreakdown } from "../results/ResultsBreakdown";
import { RankingHeader } from "../results/RankingHeader";
import { ResultsRanking } from "../results/ResultsRanking";
import { ResultsSummary } from "../results/ResultsSummary";
import { ScaleIcon } from "../scale-icons";
import { SCALE_LABELS } from "../scale-labels";
import { ShareApp } from "../share/ShareApp";
import { ShareResults } from "../share/ShareResults";

// The five options from most to least favourable (Muy de acuerdo first).
// Meaning is carried by the text, never by colour alone (DESIGN.md).
const SCALE_OPTIONS: readonly { readonly value: ScaleValue; readonly label: string }[] = (
  [2, 1, 0, -1, -2] as const
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

const IMPORTANT_HINT = "Las afirmaciones importantes cuentan el doble al calcular la afinidad.";

/**
 * The Questionnaire itself (DESIGN.md Core Screens 2). Answers and Important
 * flags live only in this component's reducer state: never in a request, the
 * URL or browser storage, so a reload or leaving the page discards them.
 */
export function QuestionnaireFlow({
  datasetVersion,
  feedbackApi,
}: {
  readonly datasetVersion: DatasetVersion;
  /** Only the feedback port: the dialog never receives Questionnaire state. */
  readonly feedbackApi: FeedbackApi;
}) {
  const [state, dispatch] = useReducer(reduceQuestionnaire, datasetVersion, init);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Focus follows navigation, but not the initial load.
  const focusPending = useRef(false);
  // Which way the last move went, for the step transition; none on load.
  const [direction, setDirection] = useState<StepDirection | null>(null);

  useEffect(() => {
    if (focusPending.current) {
      focusPending.current = false;
      headingRef.current?.focus();
    }
  }, [state.currentIndex]);

  function move(action: QuestionnaireAction) {
    focusPending.current = true;
    setDirection(action.type === "back" || action.type === "first" ? "back" : "forward");
    dispatch(action);
  }

  const statementId = currentStatementId(state);
  const statement = datasetVersion.statements.find((s) => s.id === statementId);
  // Recomputed from the in-memory state on every change; nothing is cached
  // or sent anywhere. The shared result (Share Link) uses the same function.
  const results = useMemo(() => buildResults(datasetVersion, state), [state, datasetVersion]);

  return (
    <>
      {statement === undefined ? (
        <EndScreen
          datasetVersionId={datasetVersion.id}
          state={state}
          results={results}
          headingRef={headingRef}
          feedbackApi={feedbackApi}
          onFirst={() => move({ type: "first" })}
        />
      ) : (
        <StatementStep
          statement={statement}
          direction={direction}
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

type StepDirection = "forward" | "back";

function StatementStep({
  statement,
  direction,
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
  readonly direction: StepDirection | null;
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
        {/* Remounted per Statement, so it slides in from the side the Voter
            moved towards (DESIGN.md "Step transition"); the progress, the
            card and the controls stay put. */}
        <div key={statement.id} className="statement-step" data-enter={direction ?? undefined}>
          <h2 id="statement-text" className="questionnaire__statement" tabIndex={-1} ref={headingRef}>
            {statement.text}
          </h2>
          <ImportantToggle important={important} onToggle={onToggleImportant} />
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
                <ScaleIcon value={option.value} className="scale-option__icon" />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
          {answer === SKIP ? <p className="questionnaire__skipped">Has saltado esta afirmación.</p> : null}
        </div>
        {/* One row of equal buttons in reading order: Anterior (from the
            second Statement), Saltar, Siguiente. */}
        <div className="questionnaire__controls step-controls">
          {index > 0 ? (
            <button type="button" className="button-secondary" onClick={() => onMove({ type: "back" })}>
              <ArrowBackIcon />
              <span>Anterior</span>
            </button>
          ) : null}
          <button type="button" className="button-secondary" onClick={() => onMove({ type: "skip" })}>
            <StepOverIcon />
            <span>Saltar esta afirmación</span>
          </button>
          <button
            type="button"
            className="button-primary"
            disabled={answer === undefined}
            onClick={() => onMove({ type: "next" })}
          >
            <span>Siguiente</span>
            <ArrowForwardIcon />
          </button>
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

function ImportantToggle({
  important,
  onToggle,
}: {
  readonly important: boolean;
  readonly onToggle: () => void;
}) {
  // A short glow when the Voter turns the flag on; not on mount, so going
  // back to an Important Statement does not replay it.
  const [flash, setFlash] = useState(false);
  return (
    <div className="important-row">
      <button
        type="button"
        className={flash ? "important-toggle important-toggle--flash" : "important-toggle"}
        aria-pressed={important}
        aria-describedby="important-hint"
        onClick={() => {
          setFlash(!important);
          onToggle();
        }}
        onAnimationEnd={(event) => {
          // The star's own animation bubbles up too; wait for the button's.
          if (event.target === event.currentTarget) setFlash(false);
        }}
      >
        <StarIcon className="important-toggle__star" />
        <span>Importante para mí</span>
      </button>
      {/* Shown as a tooltip on hover or keyboard focus; always the
          toggle's description for screen readers. */}
      <p id="important-hint" role="tooltip" className="questionnaire__hint important-hint">
        {IMPORTANT_HINT}
      </p>
    </div>
  );
}

function EndScreen({
  datasetVersionId,
  state,
  results,
  headingRef,
  feedbackApi,
  onFirst,
}: {
  readonly datasetVersionId: number;
  readonly state: QuestionnaireState;
  readonly results: Results;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly feedbackApi: FeedbackApi;
  readonly onFirst: () => void;
}) {
  const { answered, skipped, important, total } = summarize(state);
  // A ranking needs one rated Statement on which some Party has a stance.
  const { ranking, breakdown, hasScores } = results;
  const wide = useMediaQuery(MATRIX_QUERY);
  return (
    <>
      <h2 id="results-title" tabIndex={-1} ref={headingRef}>
        Tus resultados
      </h2>
      {/* DESIGN.md "Results dashboard": from 1024px the ranking is a sticky
          right column beside the summary and actions; DOM order is the
          reading order at every width. */}
      <div className="results-dashboard">
        <ResultsSummary
          answered={answered}
          skipped={skipped}
          important={important}
          total={total}
          voice="voter"
        />
        <div className="questionnaire__controls">
          <button type="button" className="button-primary" onClick={onFirst}>
            Revisar mis respuestas
          </button>
        </div>
        <div
          className="results-dashboard__ranking"
          role="region"
          aria-label="Afinidad por partido"
          // Scrollable (and so a tab stop) only in the wide layout.
          tabIndex={wide ? 0 : undefined}
        >
          <RankingHeader text={hasScores ? RESULTS_INTRO : NO_RESULTS_PROMPT} warning={DISCLAIMER} />
          {hasScores ? <ResultsRanking ranking={ranking} /> : null}
        </div>
        <div className="share-card">
          {hasScores ? <ShareResults datasetVersionId={datasetVersionId} state={state} /> : null}
          <ShareApp />
        </div>
        <div className="feedback-entry">
          <FeedbackButton api={feedbackApi} origin="results" />
        </div>
        <p>
          <Link className="text-link" to={METHODOLOGY_PATH} target="_blank" rel="noopener">
            Cómo se calcula la afinidad{" "}
            <span className="visually-hidden">(se abre en una pestaña nueva)</span>
            <ExternalLinkIcon />
          </Link>
        </p>
      </div>
      <ResultsBreakdown rows={breakdown} />
    </>
  );
}

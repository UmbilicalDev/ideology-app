import { useEffect, useMemo, useReducer, useRef, useState, type RefObject } from "react";
import { Link } from "react-router";

import {
  NEUTRAL,
  buildResults,
  currentStatementId,
  importantLimit,
  isImportantCapReached,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  type AnswerValue,
  type DatasetVersion,
  type FeedbackApi,
  type QuestionnaireAction,
  type QuestionnaireState,
  type Results,
  type Statement,
} from "@ideology-app/core";

import { ArrowBackIcon, ExternalLinkIcon, ShieldIcon, StarIcon } from "../../ui/icons";
import { DonationBlock } from "../donate/DonationBlock";
import { ExcludedPartiesNotice } from "../results/ExcludedPartiesNotice";
import { FeedbackButton } from "../feedback/FeedbackButton";
import { METHODOLOGY_PATH } from "../paths";
import { useMediaQuery } from "../common/useMediaQuery";
import { MATRIX_QUERY, ResultsBreakdown } from "../results/ResultsBreakdown";
import { RankingHeader } from "../results/RankingHeader";
import { ResultsRanking } from "../results/ResultsRanking";
import { ResultsSummary } from "../results/ResultsSummary";
import { SideIcon, answerSide } from "../scale-icons";
import { answerLabel } from "../scale-labels";
import { ShareApp } from "../share/ShareApp";
import { ShareResults } from "../share/ShareResults";
import { ANSWER_LOCK } from "./answer-lock";
import { RestartButton } from "./RestartDialog";

// The three answer buttons, left to right and in Tab order: En desacuerdo,
// Neutral / No lo sé, De acuerdo (user decision 2026-11-21). Neutral leaves
// the Statement without a value (it does not count for the Match Score).
// Meaning is carried by the text and icon, never by colour (DESIGN.md).
const ANSWER_OPTIONS: readonly AnswerValue[] = [-1, NEUTRAL, 1];

const STATUS_BACK = "Respuesta borrada. Vuelve a responder esta afirmación.";
const STATUS_RESTART = "Cuestionario reiniciado.";

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
  "Todavía no se puede calcular tu afinidad: no has respondido con opinión ninguna afirmación " +
  "en la que los partidos tengan posición. Pulsa «Repetir cuestionario» y responde al menos " +
  "una con «De acuerdo» o «En desacuerdo».";

const DISCLAIMER =
  "Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los " +
  "programas, según una inteligencia artificial que puede equivocarse.";

function importantHint(limit: number): string {
  return `Las afirmaciones importantes cuentan el doble al calcular la afinidad. Puedes marcar hasta ${limit}.`;
}

function importantCapText(limit: number): string {
  const marked = limit === 1 ? "1 afirmación como importante" : `${limit} afirmaciones como importantes`;
  return `Ya has marcado ${marked}, el máximo (un tercio del cuestionario).`;
}

/**
 * The Questionnaire itself (DESIGN.md Core Screens 2). Answers and Important
 * flags live only in this component's reducer state: never in a request, the
 * URL or browser storage, so a reload or leaving the page discards them.
 */
export function QuestionnaireFlow({
  datasetVersion,
  feedbackApi,
  excludedParties = [],
}: {
  readonly datasetVersion: DatasetVersion;
  /** Notes on Parties left out of this Election (ExcludedPartiesNotice). */
  readonly excludedParties?: readonly string[];
  /** Only the feedback port: the dialog never receives Questionnaire state. */
  readonly feedbackApi: FeedbackApi;
}) {
  const [state, dispatch] = useReducer(reduceQuestionnaire, datasetVersion, init);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Focus follows navigation, but not the initial load.
  const focusPending = useRef(false);
  // Which way the last move went, for the step transition; none on load.
  const [direction, setDirection] = useState<StepDirection | null>(null);

  // The polite status line: what the last move did. `seq` remounts its text
  // so a repeated message is announced again.
  const [status, setStatus] = useState({ text: "", seq: 0 });
  // Double-tap guard (answer-lock.ts): moves before this time are ignored.
  const lockedUntil = useRef(0);

  useEffect(() => {
    if (focusPending.current) {
      focusPending.current = false;
      headingRef.current?.focus();
    }
  }, [state.currentIndex]);

  function move(action: QuestionnaireAction) {
    const now = performance.now();
    // `restart` comes from the confirmation dialog, never from a double tap.
    if (action.type !== "restart" && now < lockedUntil.current) {
      return;
    }
    lockedUntil.current = now + ANSWER_LOCK.ms;
    focusPending.current = true;
    setDirection(action.type === "back" ? "back" : action.type === "restart" ? null : "forward");
    dispatch(action);
    const text =
      action.type === "answer"
        ? `Respuesta guardada: ${answerLabel(action.value)}.`
        : action.type === "back"
          ? STATUS_BACK
          : STATUS_RESTART;
    setStatus((previous) => ({ text, seq: previous.seq + 1 }));
  }

  const statementId = currentStatementId(state);
  const statement = datasetVersion.statements.find((s) => s.id === statementId);
  // Recomputed from the in-memory state on every change; nothing is cached
  // or sent anywhere. The shared result (Share Link) uses the same function.
  const results = useMemo(() => buildResults(datasetVersion, state), [state, datasetVersion]);
  const limit = importantLimit(state.statementIds.length);

  return (
    <>
      <p role="status" className="visually-hidden">
        <span key={status.seq}>{status.text}</span>
      </p>
      {statement === undefined ? (
        <EndScreen
          datasetVersionId={datasetVersion.id}
          state={state}
          results={results}
          headingRef={headingRef}
          feedbackApi={feedbackApi}
          excludedParties={excludedParties}
          onRestart={() => move({ type: "restart" })}
        />
      ) : (
        <StatementStep
          statement={statement}
          direction={direction}
          index={state.currentIndex}
          total={state.statementIds.length}
          important={state.important.has(statement.id)}
          atCap={isImportantCapReached(state) && !state.important.has(statement.id)}
          limit={limit}
          headingRef={headingRef}
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
  important,
  atCap,
  limit,
  headingRef,
  onToggleImportant,
  onMove,
}: {
  readonly statement: Statement;
  readonly direction: StepDirection | null;
  readonly index: number;
  readonly total: number;
  readonly important: boolean;
  /** The cap is reached and this Statement is not marked. */
  readonly atCap: boolean;
  readonly limit: number;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly onToggleImportant: () => void;
  readonly onMove: (action: QuestionnaireAction) => void;
}) {
  const n = index + 1;
  return (
    <>
      <div className="statement-card">
        {/* Anterior (from the second Statement; an empty placeholder keeps
            the row's height on the first) and the progress label. */}
        <div className="statement-card__top">
          {index > 0 ? (
            <button type="button" className="step-back" onClick={() => onMove({ type: "back" })}>
              <ArrowBackIcon />
              <span>Anterior</span>
            </button>
          ) : (
            <span className="step-back-placeholder" aria-hidden="true" />
          )}
          <p id="questionnaire-progress" className="questionnaire__progress-label">
            {`Afirmación ${n} de ${total}`}
          </p>
        </div>
        <progress
          className="questionnaire__progress"
          max={total}
          value={n}
          aria-labelledby="questionnaire-progress"
        />
        {/* Remounted per Statement, so it slides in from the side the Voter
            moved towards (DESIGN.md "Step transition"); the top row, the bar
            and the answer buttons stay put. */}
        <div key={statement.id} className="statement-step" data-enter={direction ?? undefined}>
          <h2
            id="statement-text"
            className="questionnaire__statement"
            tabIndex={-1}
            ref={headingRef}
            aria-describedby="questionnaire-progress"
          >
            {statement.text}
          </h2>
          <ImportantToggle
            important={important}
            atCap={atCap}
            limit={limit}
            onToggle={onToggleImportant}
          />
        </div>
        {/* One tap answers and shows the next Statement. Identical markup
            and style for the three; the side is in the text and icon. */}
        <div role="group" aria-labelledby="statement-text" className="questionnaire__controls answer-controls">
          {ANSWER_OPTIONS.map((value) => (
            <button
              key={String(value)}
              type="button"
              className="answer-button"
              data-answer={String(value)}
              onClick={() => onMove({ type: "answer", value })}
            >
              <SideIcon side={answerSide(value)} className="answer-button__icon" />
              {value === NEUTRAL ? (
                // Accessible name `Neutral / No lo sé`; the spaces sit outside
                // the hidden slash so every name computation keeps them.
                <span className="answer-button__label">
                  Neutral{" "}
                  <span className="visually-hidden">/</span>{" "}
                  <span className="answer-button__sub">No lo sé</span>
                </span>
              ) : (
                <span className="answer-button__label">{answerLabel(value)}</span>
              )}
            </button>
          ))}
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
  atCap,
  limit,
  onToggle,
}: {
  readonly important: boolean;
  readonly atCap: boolean;
  readonly limit: number;
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
        // At the cap it stays focusable and says why it does nothing.
        aria-disabled={atCap ? true : undefined}
        aria-describedby={atCap ? "important-hint important-cap" : "important-hint"}
        onClick={() => {
          if (atCap) return;
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
        {importantHint(limit)}
      </p>
      {atCap ? (
        <p id="important-cap" className="important-cap">
          {importantCapText(limit)}
        </p>
      ) : null}
    </div>
  );
}

function EndScreen({
  datasetVersionId,
  state,
  results,
  headingRef,
  feedbackApi,
  excludedParties,
  onRestart,
}: {
  readonly datasetVersionId: number;
  readonly state: QuestionnaireState;
  readonly results: Results;
  readonly headingRef: RefObject<HTMLHeadingElement | null>;
  readonly feedbackApi: FeedbackApi;
  readonly excludedParties: readonly string[];
  readonly onRestart: () => void;
}) {
  const { answered, neutral, important, total } = summarize(state);
  // A ranking needs one sided Answer on which some Party has a sided stance.
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
          neutral={neutral}
          important={important}
          total={total}
          voice="voter"
        />
        <div className="questionnaire__controls">
          <RestartButton onConfirm={onRestart} />
        </div>
        <div
          className="results-dashboard__ranking"
          role="region"
          aria-label="Afinidad por partido"
          // Scrollable (and so a tab stop) only in the wide layout.
          tabIndex={wide ? 0 : undefined}
        >
          <RankingHeader text={hasScores ? RESULTS_INTRO : NO_RESULTS_PROMPT} warning={DISCLAIMER} />
          <ExcludedPartiesNotice notes={excludedParties} />
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
      <DonationBlock />
    </>
  );
}

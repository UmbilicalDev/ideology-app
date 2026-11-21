// Questionnaire answer state: which Statement is shown, the Voter's Answers
// so far and which Statements the Voter marked Important. Pure: no React,
// DOM, storage or network. Answers and Important flags live only in memory
// (see CONSTRAINTS.md, Client-side Matching).
//
// `currentIndex` runs from 0 to `statementIds.length`; `length` is the end
// screen. Invariant: exactly the Statements before `currentIndex` have an
// Answer (-1, 1 or NEUTRAL), so `answers.size === currentIndex`. An `answer`
// records the current Statement and advances; `back` steps back and clears
// that Statement's Answer, so it must be answered again. The Important flag
// is kept apart from the Answer, so a Statement can be marked before it is
// answered. At most `importantLimit(n)` Statements can be marked, and a
// Neutral Answer drops the current Statement's mark (it would not count).
import { NEUTRAL, type Answer, type AnswerSide } from "./match-score";

export type AnswerValue = AnswerSide | typeof NEUTRAL;

export interface QuestionnaireState {
  readonly statementIds: readonly number[];
  readonly currentIndex: number;
  /** Keyed by Statement id; an unanswered Statement has no entry. */
  readonly answers: ReadonlyMap<number, AnswerValue>;
  /** Statement ids the Voter marked Important, whatever their Answer. */
  readonly important: ReadonlySet<number>;
}

export type QuestionnaireAction =
  | { readonly type: "answer"; readonly value: AnswerValue }
  | { readonly type: "back" }
  | { readonly type: "restart" }
  | { readonly type: "toggleImportant" };

export interface QuestionnaireSummary {
  /** Statements answered De acuerdo or En desacuerdo (with an opinion). */
  readonly answered: number;
  /** Statements answered Neutral / No lo sé. */
  readonly neutral: number;
  /** Sided (not Neutral) Statements marked Important: the ones that count double. */
  readonly important: number;
  readonly total: number;
}

export function startQuestionnaire(statementIds: readonly number[]): QuestionnaireState {
  return {
    statementIds: [...statementIds],
    currentIndex: 0,
    answers: new Map(),
    important: new Set(),
  };
}

export function isAtEnd(state: QuestionnaireState): boolean {
  return state.currentIndex >= state.statementIds.length;
}

/** The Statement id shown now, or `null` on the end screen. */
export function currentStatementId(state: QuestionnaireState): number | null {
  return state.statementIds[state.currentIndex] ?? null;
}

/**
 * How many Statements a Voter can mark Important: a third of the
 * questionnaire, rounded up (1 -> 1, 3 -> 1, 4 -> 2, 32 -> 11, 0 -> 0).
 */
export function importantLimit(count: number): number {
  return Math.ceil(count / 3);
}

/** True when no further Statement can be marked Important. */
export function isImportantCapReached(state: QuestionnaireState): boolean {
  return state.important.size >= importantLimit(state.statementIds.length);
}

function withAnswer(
  state: QuestionnaireState,
  statementId: number,
  value: AnswerValue,
): QuestionnaireState {
  const answers = new Map(state.answers);
  answers.set(statementId, value);
  let important = state.important;
  if (value === NEUTRAL && important.has(statementId)) {
    // A flag on Neutral has no effect; drop it so it frees a slot.
    const next = new Set(important);
    next.delete(statementId);
    important = next;
  }
  return { ...state, currentIndex: state.currentIndex + 1, answers, important };
}

function withToggledImportant(state: QuestionnaireState, statementId: number): QuestionnaireState {
  const important = new Set(state.important);
  if (important.has(statementId)) {
    important.delete(statementId);
  } else if (isImportantCapReached(state)) {
    return state;
  } else {
    important.add(statementId);
  }
  return { ...state, important };
}

export function reduceQuestionnaire(
  state: QuestionnaireState,
  action: QuestionnaireAction,
): QuestionnaireState {
  if (action.type === "restart") {
    // `Repetir cuestionario`: Statement 1, no Answers, no flags.
    return startQuestionnaire(state.statementIds);
  }
  const statementId = currentStatementId(state);
  if (statementId === null) {
    // The end screen: only `restart` leaves it.
    return state;
  }
  switch (action.type) {
    case "answer":
      return withAnswer(state, statementId, action.value);
    case "back": {
      if (state.currentIndex === 0) {
        return state;
      }
      const previous = state.currentIndex - 1;
      const answers = new Map(state.answers);
      answers.delete(state.statementIds[previous]!);
      return { ...state, currentIndex: previous, answers };
    }
    case "toggleImportant":
      return withToggledImportant(state, statementId);
    default:
      // Unknown actions (e.g. the retired `skip`, `select`, `next`, `first`) change nothing.
      return state;
  }
}

export function summarize(state: QuestionnaireState): QuestionnaireSummary {
  let answered = 0;
  let neutral = 0;
  let important = 0;
  for (const id of state.statementIds) {
    const value = state.answers.get(id);
    if (value === NEUTRAL) {
      neutral += 1;
    } else if (value !== undefined) {
      answered += 1;
      if (state.important.has(id)) {
        important += 1;
      }
    }
  }
  return { answered, neutral, important, total: state.statementIds.length };
}

/**
 * The Answers in the shape the Match Score engine takes, in Statement order:
 * one entry per Statement with an Answer, `important` always a boolean.
 * Unanswered Statements are left out (the engine treats them like Neutral),
 * even when flagged. The engine ignores a flag on a Neutral Answer (the
 * reducer drops such flags, but a decoded Share Link may still carry one).
 */
export function toMatchScoreAnswers(state: QuestionnaireState): Answer[] {
  const result: Answer[] = [];
  for (const statementId of state.statementIds) {
    const value = state.answers.get(statementId);
    if (value !== undefined) {
      result.push({ statementId, value, important: state.important.has(statementId) });
    }
  }
  return result;
}

// Questionnaire answer state: which Statement is shown, the Voter's Answers
// so far and which Statements the Voter marked Important. Pure: no React,
// DOM, storage or network. Answers and Important flags live only in memory
// (see CONSTRAINTS.md, Client-side Matching).
//
// `currentIndex` runs from 0 to `statementIds.length`; `length` is the end
// screen. Invariant: every Statement before `currentIndex` has an Answer
// (-1, 1 or NEUTRAL). The Important flag is kept apart from the Answer, so a
// Statement can be marked before it is answered, and a Neutral Answer keeps
// it (the engine ignores it).
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
  | { readonly type: "select"; readonly value: AnswerValue }
  | { readonly type: "next" }
  | { readonly type: "back" }
  | { readonly type: "first" }
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

function withAnswer(
  state: QuestionnaireState,
  statementId: number,
  value: AnswerValue,
  advance: boolean,
): QuestionnaireState {
  const answers = new Map(state.answers);
  answers.set(statementId, value);
  return {
    ...state,
    currentIndex: advance ? state.currentIndex + 1 : state.currentIndex,
    answers,
  };
}

function withToggledImportant(state: QuestionnaireState, statementId: number): QuestionnaireState {
  const important = new Set(state.important);
  if (important.has(statementId)) {
    important.delete(statementId);
  } else {
    important.add(statementId);
  }
  return { ...state, important };
}

export function reduceQuestionnaire(
  state: QuestionnaireState,
  action: QuestionnaireAction,
): QuestionnaireState {
  if (action.type === "first") {
    // Back to Statement 1 from anywhere (the end screen's "Revisar mis
    // respuestas"); Answers and flags are kept.
    if (state.currentIndex === 0) {
      return state;
    }
    return { ...state, currentIndex: 0, answers: new Map(state.answers) };
  }
  if (action.type === "back") {
    if (state.currentIndex === 0) {
      return state;
    }
    return { ...state, currentIndex: state.currentIndex - 1, answers: new Map(state.answers) };
  }
  const statementId = currentStatementId(state);
  if (statementId === null) {
    return state;
  }
  switch (action.type) {
    case "select":
      return withAnswer(state, statementId, action.value, false);
    case "toggleImportant":
      return withToggledImportant(state, statementId);
    case "next":
      if (!state.answers.has(statementId)) {
        return state;
      }
      return { ...state, currentIndex: state.currentIndex + 1, answers: new Map(state.answers) };
    default:
      // Unknown actions (e.g. the retired `skip`) change nothing.
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
 * even when flagged. A flagged Neutral Answer keeps its flag; the engine
 * ignores it.
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

// Questionnaire answer state: which Statement is shown, the Voter's Answers
// so far and which Statements the Voter marked Important. Pure: no React,
// DOM, storage or network. Answers and Important flags live only in memory
// (see CONSTRAINTS.md, Client-side Matching).
//
// `currentIndex` runs from 0 to `statementIds.length`; `length` is the end
// screen. Invariant: every Statement before `currentIndex` has an Answer
// (a ScaleValue or SKIP). The Important flag is kept apart from the Answer,
// so a Statement can be marked before it is rated, and a skip keeps it.
import { SKIP, type Answer, type ScaleValue } from "./match-score";

export type AnswerValue = ScaleValue | typeof SKIP;

export interface QuestionnaireState {
  readonly statementIds: readonly number[];
  readonly currentIndex: number;
  /** Keyed by Statement id; an unanswered Statement has no entry. */
  readonly answers: ReadonlyMap<number, AnswerValue>;
  /** Statement ids the Voter marked Important, whatever their Answer. */
  readonly important: ReadonlySet<number>;
}

export type QuestionnaireAction =
  | { readonly type: "select"; readonly value: ScaleValue }
  | { readonly type: "skip" }
  | { readonly type: "next" }
  | { readonly type: "back" }
  | { readonly type: "toggleImportant" };

export interface QuestionnaireSummary {
  readonly answered: number;
  readonly skipped: number;
  /** Rated (not skipped) Statements marked Important: the ones that count double. */
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
    case "skip":
      return withAnswer(state, statementId, SKIP, true);
    case "toggleImportant":
      return withToggledImportant(state, statementId);
    case "next":
      if (!state.answers.has(statementId)) {
        return state;
      }
      return { ...state, currentIndex: state.currentIndex + 1, answers: new Map(state.answers) };
  }
}

export function summarize(state: QuestionnaireState): QuestionnaireSummary {
  let answered = 0;
  let skipped = 0;
  let important = 0;
  for (const id of state.statementIds) {
    const value = state.answers.get(id);
    if (value === SKIP) {
      skipped += 1;
    } else if (value !== undefined) {
      answered += 1;
      if (state.important.has(id)) {
        important += 1;
      }
    }
  }
  return { answered, skipped, important, total: state.statementIds.length };
}

/**
 * The Answers in the shape the Match Score engine takes, in Statement order:
 * one entry per Statement with an Answer, `important` always a boolean.
 * Unanswered Statements are left out (the engine treats them like a skip),
 * even when flagged. A flagged skip keeps its flag; the engine ignores it.
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

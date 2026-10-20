// Questionnaire answer state: which Statement is shown and the Voter's
// Answers so far. Pure: no React, DOM, storage or network. The Answers live
// only in memory (see CONSTRAINTS.md, Client-side Matching).
//
// `currentIndex` runs from 0 to `statementIds.length`; `length` is the end
// screen. Invariant: every Statement before `currentIndex` has an Answer
// (a ScaleValue or SKIP).
import { SKIP, type ScaleValue } from "./match-score";

export type AnswerValue = ScaleValue | typeof SKIP;

export interface QuestionnaireState {
  readonly statementIds: readonly number[];
  readonly currentIndex: number;
  /** Keyed by Statement id; an unanswered Statement has no entry. */
  readonly answers: ReadonlyMap<number, AnswerValue>;
}

export type QuestionnaireAction =
  | { readonly type: "select"; readonly value: ScaleValue }
  | { readonly type: "skip" }
  | { readonly type: "next" }
  | { readonly type: "back" };

export interface QuestionnaireSummary {
  readonly answered: number;
  readonly skipped: number;
  readonly total: number;
}

export function startQuestionnaire(statementIds: readonly number[]): QuestionnaireState {
  return { statementIds: [...statementIds], currentIndex: 0, answers: new Map() };
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
    statementIds: state.statementIds,
    currentIndex: advance ? state.currentIndex + 1 : state.currentIndex,
    answers,
  };
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
  for (const id of state.statementIds) {
    const value = state.answers.get(id);
    if (value === SKIP) {
      skipped += 1;
    } else if (value !== undefined) {
      answered += 1;
    }
  }
  return { answered, skipped, total: state.statementIds.length };
}

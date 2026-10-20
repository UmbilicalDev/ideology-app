import { describe, expect, test } from "vitest";

import {
  SKIP,
  currentStatementId,
  isAtEnd,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  type QuestionnaireAction,
  type QuestionnaireState,
} from "../../src/index";

const IDS = [11, 12, 13] as const;

function run(state: QuestionnaireState, ...actions: QuestionnaireAction[]): QuestionnaireState {
  return actions.reduce(reduceQuestionnaire, state);
}

describe("startQuestionnaire", () => {
  test("starts at index 0 with no Answers", () => {
    const state = startQuestionnaire(IDS);
    expect(state.currentIndex).toBe(0);
    expect(state.statementIds).toEqual([11, 12, 13]);
    expect(state.answers.size).toBe(0);
    expect(currentStatementId(state)).toBe(11);
    expect(isAtEnd(state)).toBe(false);
  });

  test("zero Statements start on the end screen", () => {
    const state = startQuestionnaire([]);
    expect(isAtEnd(state)).toBe(true);
    expect(currentStatementId(state)).toBeNull();
    expect(summarize(state)).toEqual({ answered: 0, skipped: 0, total: 0 });
  });
});

describe("reduceQuestionnaire", () => {
  test("select records the value and does not advance; a second select overwrites", () => {
    const once = run(startQuestionnaire(IDS), { type: "select", value: 1 });
    expect(once.currentIndex).toBe(0);
    expect(once.answers.get(11)).toBe(1);
    const twice = reduceQuestionnaire(once, { type: "select", value: -2 });
    expect(twice.currentIndex).toBe(0);
    expect(twice.answers.get(11)).toBe(-2);
    expect(twice.answers.size).toBe(1);
  });

  test("skip records SKIP and advances", () => {
    const state = run(startQuestionnaire(IDS), { type: "skip" });
    expect(state.currentIndex).toBe(1);
    expect(state.answers.get(11)).toBe(SKIP);
  });

  test("next is a no-op without an Answer", () => {
    const start = startQuestionnaire(IDS);
    const state = reduceQuestionnaire(start, { type: "next" });
    expect(state).toBe(start);
    expect(state.currentIndex).toBe(0);
  });

  test("next advances with a value or with a skip", () => {
    const answered = run(startQuestionnaire(IDS), { type: "select", value: 0 }, { type: "next" });
    expect(answered.currentIndex).toBe(1);
    const skippedThenBack = run(answered, { type: "skip" }, { type: "back" });
    expect(skippedThenBack.currentIndex).toBe(1);
    expect(reduceQuestionnaire(skippedThenBack, { type: "next" }).currentIndex).toBe(2);
  });

  test("a value replaces a skip and a skip replaces a value", () => {
    const skipped = run(startQuestionnaire(IDS), { type: "skip" }, { type: "back" });
    const valued = reduceQuestionnaire(skipped, { type: "select", value: 2 });
    expect(valued.answers.get(11)).toBe(2);
    const reskipped = reduceQuestionnaire(valued, { type: "skip" });
    expect(reskipped.answers.get(11)).toBe(SKIP);
    expect(reskipped.currentIndex).toBe(1);
  });

  test("back clamps at 0 and keeps the Answers", () => {
    const start = startQuestionnaire(IDS);
    expect(reduceQuestionnaire(start, { type: "back" }).currentIndex).toBe(0);
    const state = run(start, { type: "select", value: 1 }, { type: "next" }, { type: "back" });
    expect(state.currentIndex).toBe(0);
    expect(state.answers.get(11)).toBe(1);
  });

  test("the last Statement leads to the end screen, and back works from there", () => {
    const end = run(
      startQuestionnaire(IDS),
      { type: "select", value: 1 },
      { type: "next" },
      { type: "skip" },
      { type: "select", value: -1 },
      { type: "next" },
    );
    expect(isAtEnd(end)).toBe(true);
    expect(end.currentIndex).toBe(3);
    const back = reduceQuestionnaire(end, { type: "back" });
    expect(back.currentIndex).toBe(2);
    expect(back.answers.get(13)).toBe(-1);
  });

  test.each<QuestionnaireAction>([
    { type: "select", value: 2 },
    { type: "skip" },
    { type: "next" },
  ])("$type is a no-op on the end screen", (action) => {
    const end = run(startQuestionnaire([5]), { type: "skip" });
    const after = reduceQuestionnaire(end, action);
    expect(after).toBe(end);
    expect(after.answers.get(5)).toBe(SKIP);
  });

  test("returns a new state with a new Map and never mutates the old one", () => {
    const start = startQuestionnaire(IDS);
    const selected = reduceQuestionnaire(start, { type: "select", value: 1 });
    expect(selected).not.toBe(start);
    expect(selected.answers).not.toBe(start.answers);
    expect(start.answers.size).toBe(0);
    const next = reduceQuestionnaire(selected, { type: "next" });
    expect(next.answers).not.toBe(selected.answers);
    const back = reduceQuestionnaire(next, { type: "back" });
    expect(back.answers).not.toBe(next.answers);
    expect(next.currentIndex).toBe(1);
    expect(selected.currentIndex).toBe(0);
  });

  test("keeps its own copy of the Statement ids", () => {
    const ids = [1, 2];
    const state = startQuestionnaire(ids);
    ids.push(3);
    expect(state.statementIds).toEqual([1, 2]);
  });
});

describe("summarize", () => {
  test("counts answered, skipped and total", () => {
    const state = run(
      startQuestionnaire(IDS),
      { type: "select", value: -2 },
      { type: "next" },
      { type: "skip" },
    );
    expect(summarize(state)).toEqual({ answered: 1, skipped: 1, total: 3 });
  });

  test("counts a neutral 0 as answered", () => {
    const state = run(startQuestionnaire(IDS), { type: "select", value: 0 });
    expect(summarize(state)).toEqual({ answered: 1, skipped: 0, total: 3 });
  });
});

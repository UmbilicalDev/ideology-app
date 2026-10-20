import { describe, expect, test } from "vitest";

import {
  SKIP,
  computeMatchScores,
  currentStatementId,
  isAtEnd,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  toMatchScoreAnswers,
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
    expect(state.important.size).toBe(0);
    expect(currentStatementId(state)).toBe(11);
    expect(isAtEnd(state)).toBe(false);
  });

  test("zero Statements start on the end screen", () => {
    const state = startQuestionnaire([]);
    expect(isAtEnd(state)).toBe(true);
    expect(currentStatementId(state)).toBeNull();
    expect(summarize(state)).toEqual({ answered: 0, skipped: 0, important: 0, total: 0 });
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
    { type: "toggleImportant" },
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
    expect(summarize(state)).toEqual({ answered: 1, skipped: 1, important: 0, total: 3 });
  });

  test("counts a neutral 0 as answered", () => {
    const state = run(startQuestionnaire(IDS), { type: "select", value: 0 });
    expect(summarize(state)).toEqual({ answered: 1, skipped: 0, important: 0, total: 3 });
  });
});

const TOGGLE: QuestionnaireAction = { type: "toggleImportant" };

describe("toggleImportant", () => {
  test("adds then removes the current Statement without advancing or touching the Answers", () => {
    const start = run(startQuestionnaire(IDS), { type: "select", value: 1 });
    const on = reduceQuestionnaire(start, TOGGLE);
    expect([...on.important]).toEqual([11]);
    expect(on.currentIndex).toBe(0);
    expect(on.answers).toBe(start.answers);
    expect(on.answers.get(11)).toBe(1);
    const off = reduceQuestionnaire(on, TOGGLE);
    expect(off.important.size).toBe(0);
    expect(off.currentIndex).toBe(0);
    expect(off.answers.get(11)).toBe(1);
  });

  test("returns a new state with a new Set and leaves the old Set unchanged", () => {
    const start = startQuestionnaire(IDS);
    const on = reduceQuestionnaire(start, TOGGLE);
    expect(on).not.toBe(start);
    expect(on.important).not.toBe(start.important);
    expect(start.important.size).toBe(0);
    const off = reduceQuestionnaire(on, TOGGLE);
    expect(off.important).not.toBe(on.important);
    expect(on.important.has(11)).toBe(true);
  });

  test("works before any rating, and next stays a no-op without an Answer", () => {
    const flagged = reduceQuestionnaire(startQuestionnaire(IDS), TOGGLE);
    expect(flagged.important.has(11)).toBe(true);
    expect(flagged.answers.has(11)).toBe(false);
    expect(reduceQuestionnaire(flagged, { type: "next" })).toBe(flagged);
  });

  test("select, skip, next and back keep the Set", () => {
    const state = run(
      startQuestionnaire(IDS),
      TOGGLE,
      { type: "select", value: 2 },
      { type: "next" },
      TOGGLE,
      { type: "skip" },
      { type: "back" },
      { type: "back" },
    );
    expect(state.currentIndex).toBe(0);
    expect([...state.important].sort()).toEqual([11, 12]);
    expect(state.answers.get(11)).toBe(2);
    expect(state.answers.get(12)).toBe(SKIP);
  });

  test("skip keeps the flag, and rating the skipped Statement keeps it too", () => {
    const skipped = run(startQuestionnaire(IDS), TOGGLE, { type: "skip" }, { type: "back" });
    expect(skipped.important.has(11)).toBe(true);
    expect(skipped.answers.get(11)).toBe(SKIP);
    const rated = reduceQuestionnaire(skipped, { type: "select", value: 2 });
    expect(rated.important.has(11)).toBe(true);
    expect(rated.answers.get(11)).toBe(2);
  });
});

describe("summarize important", () => {
  test("counts only rated and flagged Statements", () => {
    const state = run(
      startQuestionnaire([1, 2, 3, 4]),
      TOGGLE,
      { type: "select", value: 1 },
      { type: "next" },
      TOGGLE,
      { type: "skip" },
      { type: "select", value: -1 },
      { type: "next" },
      TOGGLE,
    );
    // 1 rated + flagged, 2 skipped + flagged, 3 rated, 4 flagged without Answer.
    expect(summarize(state)).toEqual({ answered: 2, skipped: 1, important: 1, total: 4 });
  });
});

describe("first", () => {
  const FIRST: QuestionnaireAction = { type: "first" };

  test("goes from the end screen to 0 and keeps the Answers and the flags", () => {
    const end = run(
      startQuestionnaire(IDS),
      { type: "select", value: 1 },
      TOGGLE,
      { type: "next" },
      { type: "skip" },
      TOGGLE,
      { type: "select", value: -2 },
      { type: "next" },
    );
    expect(isAtEnd(end)).toBe(true);
    const first = reduceQuestionnaire(end, FIRST);
    expect(first.currentIndex).toBe(0);
    expect(currentStatementId(first)).toBe(11);
    expect([...first.answers]).toEqual([
      [11, 1],
      [12, SKIP],
      [13, -2],
    ]);
    expect([...first.important].sort()).toEqual([11, 13]);
    expect(first.answers).not.toBe(end.answers);
    expect(end.currentIndex).toBe(3);
  });

  test("goes from the middle to 0", () => {
    const middle = run(startQuestionnaire(IDS), { type: "skip" }, { type: "skip" });
    expect(middle.currentIndex).toBe(2);
    const first = reduceQuestionnaire(middle, FIRST);
    expect(first.currentIndex).toBe(0);
    expect(first.answers.get(11)).toBe(SKIP);
    expect(first.answers.get(12)).toBe(SKIP);
  });

  test("is a no-op at 0", () => {
    const start = reduceQuestionnaire(startQuestionnaire(IDS), { type: "select", value: 2 });
    expect(reduceQuestionnaire(start, FIRST)).toBe(start);
  });

  test("works with zero Statements", () => {
    const empty = startQuestionnaire([]);
    const after = reduceQuestionnaire(empty, FIRST);
    expect(after).toBe(empty);
    expect(isAtEnd(after)).toBe(true);
  });
});

describe("toMatchScoreAnswers", () => {
  test("one entry per answered Statement in order, important always a boolean", () => {
    const state = run(
      startQuestionnaire([30, 10, 20, 40]),
      { type: "select", value: -2 },
      TOGGLE,
      { type: "next" },
      TOGGLE,
      { type: "skip" },
      { type: "select", value: 0 },
      { type: "next" },
      TOGGLE,
    );
    expect(toMatchScoreAnswers(state)).toEqual([
      { statementId: 30, value: -2, important: true },
      { statementId: 10, value: SKIP, important: true },
      { statementId: 20, value: 0, important: false },
    ]);
  });

  test("omits unanswered Statements, flagged or not", () => {
    const flaggedOnly = reduceQuestionnaire(startQuestionnaire(IDS), TOGGLE);
    expect(toMatchScoreAnswers(flaggedOnly)).toEqual([]);
    expect(toMatchScoreAnswers(startQuestionnaire(IDS))).toEqual([]);
  });

  test("its output gives a rated Important Statement weight 2 and a flagged skip no effect", () => {
    // Statement 1: Voter 2, party 2 (agreement 1). Statement 2: Voter -2, party 2 (agreement 0).
    // Statement 3: skipped and flagged, party 2.
    const parties = [
      {
        partyId: "A",
        positions: [
          { statementId: 1, value: 2 as const },
          { statementId: 2, value: 2 as const },
          { statementId: 3, value: 2 as const },
        ],
      },
    ];
    const base = run(
      startQuestionnaire([1, 2, 3]),
      { type: "select", value: 2 },
      { type: "next" },
      { type: "select", value: -2 },
      { type: "next" },
      TOGGLE,
      { type: "skip" },
    );
    const [plain] = computeMatchScores(toMatchScoreAnswers(base), parties);
    expect(plain?.matchScore).toBe(0.5);
    expect(plain?.sharedStatementCount).toBe(2);

    const flagFirst = run(base, { type: "back" }, { type: "back" }, { type: "back" }, TOGGLE);
    const [weighted] = computeMatchScores(toMatchScoreAnswers(flagFirst), parties);
    expect(weighted?.matchScore).toBeCloseTo(2 / 3);
    expect(weighted?.sharedStatementCount).toBe(2);
  });
});

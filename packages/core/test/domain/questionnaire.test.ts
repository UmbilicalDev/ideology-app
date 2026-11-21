import { describe, expect, test } from "vitest";

import {
  NEUTRAL,
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
const SELECT_NEUTRAL: QuestionnaireAction = { type: "select", value: NEUTRAL };
const NEXT: QuestionnaireAction = { type: "next" };

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
    expect(summarize(state)).toEqual({ answered: 0, neutral: 0, important: 0, total: 0 });
  });
});

describe("reduceQuestionnaire", () => {
  test("select records the value and does not advance; a second select overwrites", () => {
    const once = run(startQuestionnaire(IDS), { type: "select", value: 1 });
    expect(once.currentIndex).toBe(0);
    expect(once.answers.get(11)).toBe(1);
    const twice = reduceQuestionnaire(once, { type: "select", value: -1 });
    expect(twice.currentIndex).toBe(0);
    expect(twice.answers.get(11)).toBe(-1);
    expect(twice.answers.size).toBe(1);
  });

  test("select NEUTRAL records it without advancing; next advances", () => {
    const selected = run(startQuestionnaire(IDS), SELECT_NEUTRAL);
    expect(selected.currentIndex).toBe(0);
    expect(selected.answers.get(11)).toBe(NEUTRAL);
    const state = reduceQuestionnaire(selected, NEXT);
    expect(state.currentIndex).toBe(1);
    expect(state.answers.get(11)).toBe(NEUTRAL);
  });

  test("next is a no-op without an Answer", () => {
    const start = startQuestionnaire(IDS);
    const state = reduceQuestionnaire(start, { type: "next" });
    expect(state).toBe(start);
    expect(state.currentIndex).toBe(0);
  });

  test("there is no skip action", () => {
    const start = startQuestionnaire(IDS);
    const after = reduceQuestionnaire(start, { type: "skip" } as unknown as QuestionnaireAction);
    expect(after.currentIndex).toBe(0);
    expect(after.answers.size).toBe(0);
  });

  test("next advances with a side or with Neutral", () => {
    const answered = run(startQuestionnaire(IDS), { type: "select", value: NEUTRAL }, { type: "next" });
    expect(answered.currentIndex).toBe(1);
    const neutralThenBack = run(answered, SELECT_NEUTRAL, NEXT, { type: "back" });
    expect(neutralThenBack.currentIndex).toBe(1);
    expect(reduceQuestionnaire(neutralThenBack, { type: "next" }).currentIndex).toBe(2);
  });

  test("a side replaces Neutral and Neutral replaces a side", () => {
    const neutralOne = run(startQuestionnaire(IDS), SELECT_NEUTRAL, NEXT, { type: "back" });
    const valued = reduceQuestionnaire(neutralOne, { type: "select", value: 1 });
    expect(valued.answers.get(11)).toBe(1);
    const reNeutral = run(valued, SELECT_NEUTRAL, NEXT);
    expect(reNeutral.answers.get(11)).toBe(NEUTRAL);
    expect(reNeutral.currentIndex).toBe(1);
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
      SELECT_NEUTRAL,
      NEXT,
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
    { type: "select", value: 1 },
    SELECT_NEUTRAL,
    { type: "next" },
    { type: "toggleImportant" },
  ])("$type is a no-op on the end screen", (action) => {
    const end = run(startQuestionnaire([5]), SELECT_NEUTRAL, NEXT);
    const after = reduceQuestionnaire(end, action);
    expect(after).toBe(end);
    expect(after.answers.get(5)).toBe(NEUTRAL);
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
  test("counts answered (sided), neutral and total", () => {
    const state = run(
      startQuestionnaire(IDS),
      { type: "select", value: -1 },
      { type: "next" },
      SELECT_NEUTRAL,
      NEXT,
    );
    expect(summarize(state)).toEqual({ answered: 1, neutral: 1, important: 0, total: 3 });
  });

  test("counts a Neutral Answer as neutral, not answered", () => {
    const state = run(startQuestionnaire(IDS), { type: "select", value: NEUTRAL });
    expect(summarize(state)).toEqual({ answered: 0, neutral: 1, important: 0, total: 3 });
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

  test("select, next and back keep the Set", () => {
    const state = run(
      startQuestionnaire(IDS),
      TOGGLE,
      { type: "select", value: 1 },
      { type: "next" },
      TOGGLE,
      SELECT_NEUTRAL,
      NEXT,
      { type: "back" },
      { type: "back" },
    );
    expect(state.currentIndex).toBe(0);
    expect([...state.important].sort()).toEqual([11, 12]);
    expect(state.answers.get(11)).toBe(1);
    expect(state.answers.get(12)).toBe(NEUTRAL);
  });

  test("Neutral keeps the flag, and choosing a side afterwards keeps it too", () => {
    const neutralOne = run(startQuestionnaire(IDS), TOGGLE, SELECT_NEUTRAL, NEXT, { type: "back" });
    expect(neutralOne.important.has(11)).toBe(true);
    expect(neutralOne.answers.get(11)).toBe(NEUTRAL);
    const rated = reduceQuestionnaire(neutralOne, { type: "select", value: 1 });
    expect(rated.important.has(11)).toBe(true);
    expect(rated.answers.get(11)).toBe(1);
  });
});

describe("summarize important", () => {
  test("counts only sided and flagged Statements", () => {
    const state = run(
      startQuestionnaire([1, 2, 3, 4]),
      TOGGLE,
      { type: "select", value: 1 },
      { type: "next" },
      TOGGLE,
      SELECT_NEUTRAL,
      NEXT,
      { type: "select", value: -1 },
      { type: "next" },
      TOGGLE,
    );
    // 1 sided + flagged, 2 neutral + flagged, 3 sided, 4 flagged without Answer.
    expect(summarize(state)).toEqual({ answered: 2, neutral: 1, important: 1, total: 4 });
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
      SELECT_NEUTRAL,
      NEXT,
      TOGGLE,
      { type: "select", value: -1 },
      { type: "next" },
    );
    expect(isAtEnd(end)).toBe(true);
    const first = reduceQuestionnaire(end, FIRST);
    expect(first.currentIndex).toBe(0);
    expect(currentStatementId(first)).toBe(11);
    expect([...first.answers]).toEqual([
      [11, 1],
      [12, NEUTRAL],
      [13, -1],
    ]);
    expect([...first.important].sort()).toEqual([11, 13]);
    expect(first.answers).not.toBe(end.answers);
    expect(end.currentIndex).toBe(3);
  });

  test("goes from the middle to 0", () => {
    const middle = run(startQuestionnaire(IDS), SELECT_NEUTRAL, NEXT, SELECT_NEUTRAL, NEXT);
    expect(middle.currentIndex).toBe(2);
    const first = reduceQuestionnaire(middle, FIRST);
    expect(first.currentIndex).toBe(0);
    expect(first.answers.get(11)).toBe(NEUTRAL);
    expect(first.answers.get(12)).toBe(NEUTRAL);
  });

  test("is a no-op at 0", () => {
    const start = reduceQuestionnaire(startQuestionnaire(IDS), { type: "select", value: 1 });
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
      { type: "select", value: -1 },
      TOGGLE,
      { type: "next" },
      TOGGLE,
      SELECT_NEUTRAL,
      NEXT,
      { type: "select", value: NEUTRAL },
      { type: "next" },
      TOGGLE,
    );
    expect(toMatchScoreAnswers(state)).toEqual([
      { statementId: 30, value: -1, important: true },
      { statementId: 10, value: NEUTRAL, important: true },
      { statementId: 20, value: NEUTRAL, important: false },
    ]);
  });

  test("omits unanswered Statements, flagged or not", () => {
    const flaggedOnly = reduceQuestionnaire(startQuestionnaire(IDS), TOGGLE);
    expect(toMatchScoreAnswers(flaggedOnly)).toEqual([]);
    expect(toMatchScoreAnswers(startQuestionnaire(IDS))).toEqual([]);
  });

  test("its output gives a sided Important Statement weight 2 and a flagged Neutral no effect", () => {
    // Statement 1: Voter 1, party 2 (agreement 1). Statement 2: Voter -1, party 2 (agreement 0).
    // Statement 3: Neutral and flagged, party 2.
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
      { type: "select", value: 1 },
      { type: "next" },
      { type: "select", value: -1 },
      { type: "next" },
      TOGGLE,
      SELECT_NEUTRAL,
      NEXT,
    );
    const [plain] = computeMatchScores(toMatchScoreAnswers(base), parties);
    expect(plain?.matchScore).toBe(0.5);
    expect(plain?.comparedStatementCount).toBe(2);

    const flagFirst = run(base, { type: "back" }, { type: "back" }, { type: "back" }, TOGGLE);
    const [weighted] = computeMatchScores(toMatchScoreAnswers(flagFirst), parties);
    expect(weighted?.matchScore).toBeCloseTo(2 / 3);
    expect(weighted?.comparedStatementCount).toBe(2);
  });
});

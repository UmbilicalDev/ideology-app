import { describe, expect, test } from "vitest";

import {
  NEUTRAL,
  computeMatchScores,
  currentStatementId,
  importantLimit,
  isAtEnd,
  isImportantCapReached,
  reduceQuestionnaire,
  startQuestionnaire,
  summarize,
  toMatchScoreAnswers,
  type AnswerValue,
  type QuestionnaireAction,
  type QuestionnaireState,
} from "../../src/index";

const IDS = [11, 12, 13] as const;
const ANSWER_NEUTRAL: QuestionnaireAction = { type: "answer", value: NEUTRAL };
const AGREE: QuestionnaireAction = { type: "answer", value: 1 };
const DISAGREE: QuestionnaireAction = { type: "answer", value: -1 };
const BACK: QuestionnaireAction = { type: "back" };
const RESTART: QuestionnaireAction = { type: "restart" };
const TOGGLE: QuestionnaireAction = { type: "toggleImportant" };

function run(state: QuestionnaireState, ...actions: QuestionnaireAction[]): QuestionnaireState {
  return actions.reduce(reduceQuestionnaire, state);
}

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i + 1);
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

  test("keeps its own copy of the Statement ids", () => {
    const ids = [1, 2];
    const state = startQuestionnaire(ids);
    ids.push(3);
    expect(state.statementIds).toEqual([1, 2]);
  });
});

describe("answer", () => {
  test("records the value and advances (Scenario 1)", () => {
    const state = reduceQuestionnaire(startQuestionnaire(IDS), AGREE);
    expect(state.currentIndex).toBe(1);
    expect(state.answers.get(11)).toBe(1);
    expect(currentStatementId(state)).toBe(12);
  });

  test("Neutral records NEUTRAL and advances (Scenario 2)", () => {
    const state = run(startQuestionnaire(IDS), AGREE, ANSWER_NEUTRAL);
    expect(state.currentIndex).toBe(2);
    expect(state.answers.get(12)).toBe(NEUTRAL);
    expect(summarize(state)).toEqual({ answered: 1, neutral: 1, important: 0, total: 3 });
  });

  test("the last Statement leads to the end screen (Scenario 3)", () => {
    const end = run(startQuestionnaire(IDS), AGREE, ANSWER_NEUTRAL, DISAGREE);
    expect(isAtEnd(end)).toBe(true);
    expect(end.currentIndex).toBe(3);
    expect([...end.answers]).toEqual([
      [11, 1],
      [12, NEUTRAL],
      [13, -1],
    ]);
    expect(summarize(end)).toEqual({ answered: 2, neutral: 1, important: 0, total: 3 });
  });

  test("returns a new state with a new Map and never mutates the old one", () => {
    const start = startQuestionnaire(IDS);
    const answered = reduceQuestionnaire(start, AGREE);
    expect(answered).not.toBe(start);
    expect(answered.answers).not.toBe(start.answers);
    expect(start.answers.size).toBe(0);
    expect(start.currentIndex).toBe(0);
  });

  test("Neutral drops the current Statement's flag (Decision 3), a side keeps it", () => {
    const sided = run(startQuestionnaire(IDS), TOGGLE, AGREE);
    expect([...sided.important]).toEqual([11]);
    const neutral = run(sided, TOGGLE, ANSWER_NEUTRAL);
    expect([...neutral.important]).toEqual([11]);
    expect(neutral.answers.get(12)).toBe(NEUTRAL);
  });

  test("there are no select, next, first or skip actions", () => {
    const start = startQuestionnaire(IDS);
    for (const type of ["select", "next", "first", "skip"]) {
      const after = reduceQuestionnaire(start, { type, value: 1 } as unknown as QuestionnaireAction);
      expect(after).toBe(start);
    }
  });
});

describe("back", () => {
  test("is a no-op on Statement 1", () => {
    const start = run(startQuestionnaire(IDS), TOGGLE);
    expect(reduceQuestionnaire(start, BACK)).toBe(start);
  });

  test("goes back one and clears that Answer, keeping the flags (Scenario 4, Decision 4)", () => {
    const third = run(startQuestionnaire(IDS), AGREE, TOGGLE, DISAGREE);
    expect(third.currentIndex).toBe(2);
    const back = reduceQuestionnaire(third, BACK);
    expect(back.currentIndex).toBe(1);
    expect(back.answers.has(12)).toBe(false);
    expect(back.answers.get(11)).toBe(1);
    expect([...back.important]).toEqual([12]);
    expect(back.answers).not.toBe(third.answers);
    expect(third.answers.get(12)).toBe(-1);
  });

  test("a flag pressed on the Statement being left stays", () => {
    const state = run(startQuestionnaire(IDS), AGREE, TOGGLE, BACK);
    expect(state.currentIndex).toBe(0);
    expect(state.important.has(12)).toBe(true);
    expect(state.answers.size).toBe(0);
  });

  test("is a no-op on the end screen", () => {
    const end = run(startQuestionnaire([5]), AGREE);
    expect(reduceQuestionnaire(end, BACK)).toBe(end);
  });
});

describe("restart", () => {
  test("goes to Statement 1 with no Answers and no flags (Scenario 7)", () => {
    const end = run(startQuestionnaire(IDS), TOGGLE, AGREE, ANSWER_NEUTRAL, DISAGREE);
    expect(isAtEnd(end)).toBe(true);
    const again = reduceQuestionnaire(end, RESTART);
    expect(again.currentIndex).toBe(0);
    expect(again.answers.size).toBe(0);
    expect(again.important.size).toBe(0);
    expect(again.statementIds).toEqual([11, 12, 13]);
    expect(end.answers.size).toBe(3);
  });

  test("also works mid-questionnaire and with zero Statements", () => {
    const middle = run(startQuestionnaire(IDS), TOGGLE, AGREE);
    expect(reduceQuestionnaire(middle, RESTART)).toEqual(startQuestionnaire(IDS));
    expect(isAtEnd(reduceQuestionnaire(startQuestionnaire([]), RESTART))).toBe(true);
  });
});

describe("end screen", () => {
  test.each<QuestionnaireAction>([AGREE, ANSWER_NEUTRAL, BACK, TOGGLE])(
    "$type is a no-op on the end screen",
    (action) => {
      const end = run(startQuestionnaire([5]), ANSWER_NEUTRAL);
      const after = reduceQuestionnaire(end, action);
      expect(after).toBe(end);
      expect(after.answers.get(5)).toBe(NEUTRAL);
    },
  );
});

describe("importantLimit", () => {
  test.each([
    [0, 0],
    [1, 1],
    [2, 1],
    [3, 1],
    [4, 2],
    [26, 9],
    [32, 11],
  ])("importantLimit(%i) = %i", (count, limit) => {
    expect(importantLimit(count)).toBe(limit);
  });
});

describe("toggleImportant", () => {
  test("adds then removes the current Statement without advancing or touching the Answers", () => {
    const start = run(startQuestionnaire(IDS), AGREE);
    const on = reduceQuestionnaire(start, TOGGLE);
    expect([...on.important]).toEqual([12]);
    expect(on.currentIndex).toBe(1);
    expect(on.answers).toBe(start.answers);
    const off = reduceQuestionnaire(on, TOGGLE);
    expect(off.important.size).toBe(0);
    expect(off.currentIndex).toBe(1);
  });

  test("returns a new state with a new Set and leaves the old Set unchanged", () => {
    const start = startQuestionnaire(IDS);
    const on = reduceQuestionnaire(start, TOGGLE);
    expect(on).not.toBe(start);
    expect(on.important).not.toBe(start.important);
    expect(start.important.size).toBe(0);
  });

  test("refuses a new flag at the cap; removing is always allowed (Scenario 5)", () => {
    // 32 Statements, cap 11: mark and agree with 1..11.
    const ids = range(32);
    let state = startQuestionnaire(ids);
    for (let i = 0; i < 11; i += 1) {
      expect(isImportantCapReached(state)).toBe(false);
      state = run(state, TOGGLE, AGREE);
    }
    expect(state.important.size).toBe(11);
    expect(isImportantCapReached(state)).toBe(true);
    const refused = reduceQuestionnaire(state, TOGGLE);
    expect(refused).toBe(state);
    expect(refused.important.has(12)).toBe(false);

    // Back to Statement 11 (marked): it can be unpressed, then pressed again.
    const back = reduceQuestionnaire(state, BACK);
    expect(back.important.has(11)).toBe(true);
    const off = reduceQuestionnaire(back, TOGGLE);
    expect(off.important.has(11)).toBe(false);
    expect(isImportantCapReached(off)).toBe(false);
    expect(reduceQuestionnaire(off, TOGGLE).important.has(11)).toBe(true);
  });

  test("Neutral on the 11th marked Statement frees the slot (Scenario 6)", () => {
    let state = startQuestionnaire(range(32));
    for (let i = 0; i < 10; i += 1) {
      state = run(state, TOGGLE, AGREE);
    }
    state = reduceQuestionnaire(state, TOGGLE);
    expect(isImportantCapReached(state)).toBe(true);
    state = reduceQuestionnaire(state, ANSWER_NEUTRAL);
    expect(state.important.size).toBe(10);
    expect(isImportantCapReached(state)).toBe(false);
    expect(summarize(state).important).toBe(10);
    expect(reduceQuestionnaire(state, TOGGLE).important.has(12)).toBe(true);
  });

  test("a one-Statement questionnaire allows one flag", () => {
    const on = reduceQuestionnaire(startQuestionnaire([7]), TOGGLE);
    expect(on.important.has(7)).toBe(true);
    expect(isImportantCapReached(on)).toBe(true);
  });
});

describe("summarize", () => {
  test("counts answered (sided), neutral, important (sided and flagged) and total", () => {
    const state = run(startQuestionnaire([1, 2, 3, 4]), TOGGLE, AGREE, ANSWER_NEUTRAL, DISAGREE, TOGGLE);
    // 1 sided + flagged, 2 neutral, 3 sided, 4 flagged without Answer.
    expect(summarize(state)).toEqual({ answered: 2, neutral: 1, important: 1, total: 4 });
  });
});

// A small seeded generator (mulberry32), so the property test is repeatable.
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("invariants over random action sequences", () => {
  test("answers.size === currentIndex, the cap holds and no flag sits on a Neutral Answer", () => {
    const random = mulberry32(20261121);
    const values: AnswerValue[] = [1, -1, NEUTRAL];
    for (let run = 0; run < 300; run += 1) {
      const n = Math.floor(random() * 12);
      const ids = range(n).map((i) => i * 10);
      let state = startQuestionnaire(ids);
      for (let step = 0; step < 60; step += 1) {
        const r = random();
        const action: QuestionnaireAction =
          r < 0.45
            ? { type: "answer", value: values[Math.floor(random() * 3)]! }
            : r < 0.65
              ? BACK
              : r < 0.97
                ? TOGGLE
                : RESTART;
        state = reduceQuestionnaire(state, action);
        expect(state.answers.size).toBe(state.currentIndex);
        ids.slice(0, state.currentIndex).forEach((id) => expect(state.answers.has(id)).toBe(true));
        expect(state.important.size).toBeLessThanOrEqual(importantLimit(n));
        for (const [id, value] of state.answers) {
          if (value === NEUTRAL) expect(state.important.has(id)).toBe(false);
        }
      }
    }
  });
});

describe("toMatchScoreAnswers", () => {
  test("one entry per answered Statement in order, important always a boolean", () => {
    const state = run(
      startQuestionnaire([30, 10, 20, 40]),
      TOGGLE,
      { type: "answer", value: -1 },
      TOGGLE,
      ANSWER_NEUTRAL,
      ANSWER_NEUTRAL,
      TOGGLE,
    );
    // 30 sided + flagged; 10 flagged then Neutral (flag dropped); 20 Neutral;
    // 40 flagged without an Answer (left out).
    expect(toMatchScoreAnswers(state)).toEqual([
      { statementId: 30, value: -1, important: true },
      { statementId: 10, value: NEUTRAL, important: false },
      { statementId: 20, value: NEUTRAL, important: false },
    ]);
  });

  test("omits unanswered Statements, flagged or not", () => {
    const flaggedOnly = reduceQuestionnaire(startQuestionnaire(IDS), TOGGLE);
    expect(toMatchScoreAnswers(flaggedOnly)).toEqual([]);
    expect(toMatchScoreAnswers(startQuestionnaire(IDS))).toEqual([]);
  });

  test("its output gives a sided Important Statement weight 2", () => {
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
      { type: "answer", value: 1 },
      { type: "answer", value: -1 },
      TOGGLE,
      ANSWER_NEUTRAL,
    );
    const [plain] = computeMatchScores(toMatchScoreAnswers(base), parties);
    expect(plain?.matchScore).toBe(0.5);
    expect(plain?.comparedStatementCount).toBe(2);

    const flagFirst = run(
      startQuestionnaire([1, 2, 3]),
      TOGGLE,
      { type: "answer", value: 1 },
      { type: "answer", value: -1 },
      ANSWER_NEUTRAL,
    );
    const [weighted] = computeMatchScores(toMatchScoreAnswers(flagFirst), parties);
    expect(weighted?.matchScore).toBeCloseTo(2 / 3);
    expect(weighted?.comparedStatementCount).toBe(2);
  });
});

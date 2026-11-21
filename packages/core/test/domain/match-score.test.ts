import { describe, expect, test } from "vitest";

import {
  IMPORTANT_WEIGHT,
  LOW_COVERAGE_THRESHOLD,
  NEUTRAL,
  NO_STANCE,
  computeMatchScore,
  computeMatchScores,
  positionSide,
  statementAgreement,
} from "../../src/domain/match-score";
import type {
  Answer,
  AnswerSide,
  PartyInput,
  PositionInput,
  ScaleValue,
  StatementId,
} from "../../src/domain/match-score";

// Passes deliberately invalid input past the type checker.
function untyped<T>(value: unknown): T {
  return value as T;
}

// Like node:test's assert.throws(fn, { name, message }).
function expectThrows(fn: () => unknown, expected: { name: string; message: RegExp }): void {
  let thrown: unknown;
  try {
    fn();
  } catch (err) {
    thrown = err;
  }
  expect(thrown).toBeInstanceOf(Error);
  const err = thrown as Error;
  expect(err.name).toBe(expected.name);
  expect(err.message).toMatch(expected.message);
}

const answer = (statementId: StatementId, value: Answer["value"], important?: boolean): Answer =>
  important === undefined ? { statementId, value } : { statementId, value, important };
const position = (statementId: StatementId, value: PositionInput["value"]): PositionInput => ({
  statementId,
  value,
});

// n compared Statements, each with answer 1 and position 2.
function compared(n: number): { answers: Answer[]; positions: PositionInput[] } {
  const ids = Array.from({ length: n }, (_, i) => i + 1);
  return { answers: ids.map((id) => answer(id, 1)), positions: ids.map((id) => position(id, 2)) };
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value)) deepFreeze(v);
  }
  return value;
}

describe("constants", () => {
  test("exported values", () => {
    expect(NEUTRAL).toBe("neutral");
    expect(NO_STANCE).toBe("no_stance");
    expect(IMPORTANT_WEIGHT).toBe(2);
    expect(LOW_COVERAGE_THRESHOLD).toBe(5);
  });
});

describe("spec scenario 1: the engine reads sides", () => {
  test("same side 1, opposite side 0, neutral, 0 and no stance excluded", () => {
    const answers = [
      answer("s1", 1),
      answer("s2", -1, true),
      answer("s3", NEUTRAL),
      answer("s4", 1),
      answer("s5", 1),
    ];
    const positions = [
      position("s1", 2),
      position("s2", 1),
      position("s3", -2),
      position("s4", 0),
      position("s5", NO_STANCE),
    ];
    expect(computeMatchScore(answers, positions)).toStrictEqual({
      matchScore: 1 / 3,
      comparedStatementCount: 2,
      coincidenceCount: 1,
      lowCoverage: true,
    });
  });
});

describe("positionSide", () => {
  test("-2/-1 against, +1/+2 in favour, 0 has no side", () => {
    expect(positionSide(-2)).toBe(-1);
    expect(positionSide(-1)).toBe(-1);
    expect(positionSide(0)).toBeNull();
    expect(positionSide(1)).toBe(1);
    expect(positionSide(2)).toBe(1);
  });

  test("rejects out-of-range values", () => {
    expect(() => positionSide(untyped(3))).toThrow(RangeError);
    expect(() => positionSide(untyped(NO_STANCE))).toThrow(RangeError);
  });
});

describe("per-Statement agreement", () => {
  test("1 on the same side, 0 on opposite sides, intensity ignored", () => {
    const sides: AnswerSide[] = [-1, 1];
    const values: ScaleValue[] = [-2, -1, 1, 2];
    for (const a of sides) {
      for (const p of values) {
        expect(statementAgreement(a, p)).toBe(Math.sign(p) === a ? 1 : 0);
      }
    }
  });

  test("rejects position 0, neutral, no stance and out-of-range values", () => {
    expect(() => statementAgreement(1, 0)).toThrow(RangeError);
    expect(() => statementAgreement(untyped(NEUTRAL), 1)).toThrow(RangeError);
    expect(() => statementAgreement(1, untyped(NO_STANCE))).toThrow(RangeError);
    expect(() => statementAgreement(untyped(2), 1)).toThrow(RangeError);
    expect(() => statementAgreement(untyped(0), 1)).toThrow(RangeError);
    expect(() => statementAgreement(1, untyped(3))).toThrow(RangeError);
  });
});

describe("identical sides give 100%, opposite sides 0%", () => {
  test("six Statements on matching sides of any intensity", () => {
    const answers = [answer(1, 1), answer(2, 1, true), answer(3, -1), answer(4, -1), answer(5, 1), answer(6, -1)];
    const positions = [position(1, 1), position(2, 2), position(3, -1), position(4, -2), position(5, 2), position(6, -1)];
    expect(computeMatchScore(answers, positions)).toStrictEqual({
      matchScore: 1,
      comparedStatementCount: 6,
      coincidenceCount: 6,
      lowCoverage: false,
    });
  });

  test("five Statements on opposite sides", () => {
    const answers = [answer(1, 1), answer(2, -1), answer(3, 1), answer(4, -1), answer(5, 1)];
    const positions = [position(1, -2), position(2, 1), position(3, -1), position(4, 2), position(5, -2)];
    expect(computeMatchScore(answers, positions)).toStrictEqual({
      matchScore: 0,
      comparedStatementCount: 5,
      coincidenceCount: 0,
      lowCoverage: false,
    });
  });
});

describe("spec scenario 5: Important weighs x2", () => {
  test("2 coincidences (one Important) and 1 non-coincidence give 3/4", () => {
    const answers = [answer(1, 1, true), answer(2, -1), answer(3, 1)];
    const positions = [position(1, 2), position(2, -1), position(3, -2)];
    const result = computeMatchScore(answers, positions);
    expect(result.matchScore).toBe(0.75);
    expect(result.coincidenceCount).toBe(2);
    expect(result.comparedStatementCount).toBe(3);
  });

  test("an Important non-coincidence weighs double too", () => {
    const answers = [answer(1, 1), answer(2, 1, true)];
    const positions = [position(1, 1), position(2, -1)];
    expect(computeMatchScore(answers, positions).matchScore).toBe(1 / 3);
  });

  test("order of the inputs does not matter", () => {
    const answers = [answer(1, 1, true), answer(2, -1), answer(3, 1)];
    const positions = [position(1, 2), position(2, -1), position(3, -2)];
    expect(computeMatchScore([...answers].reverse(), [...positions].reverse()).matchScore).toBe(0.75);
  });
});

describe("neutral, position 0, no stance and missing entries are excluded", () => {
  const baseAnswers = [answer(1, 1), answer(2, -1, true), answer(3, 1)];
  const basePositions = [position(1, 1), position(2, 2), position(3, -2)];

  test("neutral (Important), position 0 and no stance leave numerator and denominator", () => {
    const answers = [...baseAnswers, answer(4, NEUTRAL, true), answer(5, -1), answer(6, 1)];
    const positions = [...basePositions, position(4, -2), position(5, 0), position(6, NO_STANCE)];
    const expected = computeMatchScore(baseAnswers, basePositions);
    expect(computeMatchScore(answers, positions)).toStrictEqual(expected);
    expect(expected.comparedStatementCount).toBe(3);
  });

  test("missing Position or missing Answer is excluded", () => {
    const answers = [...baseAnswers, answer(4, 1, true)];
    const positions = [...basePositions, position(5, -2)];
    expect(computeMatchScore(answers, positions)).toStrictEqual(computeMatchScore(baseAnswers, basePositions));
  });
});

describe("low-coverage threshold counts compared Statements", () => {
  test("default threshold: 4 is low, 5 is not", () => {
    const four = compared(4);
    const five = compared(5);
    expect(computeMatchScore(four.answers, four.positions).lowCoverage).toBe(true);
    expect(computeMatchScore(five.answers, five.positions).lowCoverage).toBe(false);
  });

  test("custom threshold 3: 3 is not low, 2 is", () => {
    const three = compared(3);
    const two = compared(2);
    const options = { lowCoverageThreshold: 3 };
    expect(computeMatchScore(three.answers, three.positions, options).lowCoverage).toBe(false);
    expect(computeMatchScore(two.answers, two.positions, options).lowCoverage).toBe(true);
  });

  test("non-coincidences count toward M", () => {
    const answers = [1, 2, 3, 4, 5].map((id) => answer(id, -1));
    const positions = [1, 2, 3, 4, 5].map((id) => position(id, 1));
    expect(computeMatchScore(answers, positions)).toMatchObject({
      comparedStatementCount: 5,
      coincidenceCount: 0,
      lowCoverage: false,
    });
  });
});

describe("spec scenario 2: zero compared Statements", () => {
  const none = { matchScore: null, comparedStatementCount: 0, coincidenceCount: 0, lowCoverage: true };

  test("every Answer is neutral", () => {
    const answers = [answer(1, NEUTRAL), answer(2, NEUTRAL, true)];
    expect(computeMatchScore(answers, [position(1, 2), position(2, -1)])).toStrictEqual(none);
  });

  test("no stance or 0 on every answered Statement", () => {
    const answers = [answer(1, 1), answer(2, -1)];
    const positions = [position(1, NO_STANCE), position(2, 0)];
    expect(computeMatchScore(answers, positions)).toStrictEqual(none);
  });

  test("empty answers", () => {
    expect(computeMatchScore([], [position(1, 2)])).toStrictEqual(none);
  });
});

describe("several Parties", () => {
  test("results in input order, each equal to computeMatchScore", () => {
    const answers = [answer(7, 1, true), answer(8, -1), answer(9, NEUTRAL)];
    const parties: PartyInput<string | number>[] = [
      { partyId: "c", positions: [position("7", 2), position("8", -1), position("9", 0)] },
      { partyId: "a", positions: [position("7", -2), position("8", -1), position("9", NO_STANCE)] },
      { partyId: 3, positions: [position(7, 0), position("9", 2)] },
    ];
    const results = computeMatchScores(answers, parties);
    expect(results.map((r) => r.partyId)).toStrictEqual(["c", "a", 3]);
    parties.forEach((party, i) => {
      expect(results[i]).toStrictEqual({
        partyId: party.partyId,
        ...computeMatchScore(answers, party.positions),
      });
    });
    // statementId 7 (number) matches "7" (string).
    expect(results[0]).toMatchObject({ matchScore: 1, comparedStatementCount: 2, coincidenceCount: 2 });
    expect(results[1]).toMatchObject({ matchScore: 1 / 3, comparedStatementCount: 2, coincidenceCount: 1 });
    expect(results[2]).toMatchObject({ matchScore: null, comparedStatementCount: 0, coincidenceCount: 0 });
  });

  test("options apply to every Party", () => {
    const { answers, positions } = compared(3);
    const results = computeMatchScores(answers, [{ partyId: "x", positions }], { lowCoverageThreshold: 3 });
    expect(results[0]!.lowCoverage).toBe(false);
  });
});

describe("invalid input fails loudly", () => {
  const goodPositions = [position(1, 1)];

  for (const bad of [0, 2, -2, 1.5, "skip", "agree", null, NaN]) {
    test(`answer value ${String(bad)} -> RangeError`, () => {
      expectThrows(() => computeMatchScore([answer(1, untyped(bad))], goodPositions), {
        name: "RangeError",
        message: /answers.*statementId 1/,
      });
    });
  }

  test('position value "no stance" -> RangeError', () => {
    expectThrows(() => computeMatchScore([answer(1, 1)], [position(1, untyped("no stance"))]), {
      name: "RangeError",
      message: /positions.*statementId 1/,
    });
  });

  test('important: "yes" -> TypeError', () => {
    expectThrows(() => computeMatchScore([answer(4, 1, untyped("yes"))], goodPositions), {
      name: "TypeError",
      message: /important.*statementId 4/,
    });
  });

  test("duplicate statementId in answers -> RangeError", () => {
    expectThrows(() => computeMatchScore([answer(1, 1), answer("1", -1)], goodPositions), {
      name: "RangeError",
      message: /answers.*duplicate statementId 1/,
    });
  });

  test("duplicate statementId in positions -> RangeError", () => {
    expectThrows(() => computeMatchScore([answer(1, 1)], [position(2, 0), position(2, 1)]), {
      name: "RangeError",
      message: /positions.*duplicate statementId 2/,
    });
  });

  test("answers not an array -> TypeError", () => {
    expectThrows(() => computeMatchScore(untyped({}), goodPositions), {
      name: "TypeError",
      message: /answers/,
    });
  });

  test("positions not an array -> TypeError", () => {
    expectThrows(() => computeMatchScore([], untyped(null)), { name: "TypeError", message: /positions/ });
  });

  test("parties not an array -> TypeError", () => {
    expectThrows(() => computeMatchScores([], untyped<PartyInput<string>[]>("x")), { name: "TypeError", message: /parties/ });
  });

  test("bad party positions name the party index", () => {
    expectThrows(
      () => computeMatchScores([], [{ partyId: "p", positions: [position(1, untyped(9))] }]),
      {
        name: "RangeError",
        message: /parties\[0\]\.positions.*statementId 1/,
      },
    );
  });

  for (const bad of [0, -1, 2.5, "5", NaN]) {
    test(`lowCoverageThreshold ${String(bad)} -> RangeError`, () => {
      expectThrows(() => computeMatchScore([], [], { lowCoverageThreshold: untyped(bad) }), {
        name: "RangeError",
        message: /lowCoverageThreshold/,
      });
    });
  }
});

describe("purity", () => {
  test("deeply frozen inputs: no throw, repeatable results", () => {
    const answers = deepFreeze([answer(1, 1, true), answer(2, NEUTRAL, true), answer(3, -1)]);
    const positions = deepFreeze([position(1, 1), position(2, 0), position(3, NO_STANCE)]);
    const parties = deepFreeze([
      { partyId: "a", positions },
      { partyId: "b", positions: [position(1, -2), position(3, 2)] },
    ]);
    const options = deepFreeze({ lowCoverageThreshold: 2 });
    const first = computeMatchScore(answers, positions, options);
    expect(computeMatchScore(answers, positions, options)).toStrictEqual(first);
    const many = computeMatchScores(answers, parties, options);
    expect(computeMatchScores(answers, parties, options)).toStrictEqual(many);
    expect(first).toStrictEqual({
      matchScore: 1,
      comparedStatementCount: 1,
      coincidenceCount: 1,
      lowCoverage: true,
    });
  });

  test("inputs are not mutated", () => {
    const answers = [answer(1, 1), answer(2, -1, true)];
    const positions = [position(1, 1), position(2, 2)];
    const snapshot = JSON.stringify([answers, positions]);
    computeMatchScore(answers, positions);
    computeMatchScores(answers, [{ partyId: 1, positions }]);
    expect(JSON.stringify([answers, positions])).toBe(snapshot);
  });
});

import { describe, expect, test } from "vitest";

import {
  IMPORTANT_WEIGHT,
  LOW_COVERAGE_THRESHOLD,
  NO_STANCE,
  SKIP,
  computeMatchScore,
  computeMatchScores,
  statementAgreement,
} from "../../src/domain/match-score";
import type { Answer, PartyInput, PositionInput, ScaleValue, StatementId } from "../../src/domain/match-score";

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

// n shared Statements, each with answer 0 and position 0.
function shared(n: number): { answers: Answer[]; positions: PositionInput[] } {
  const ids = Array.from({ length: n }, (_, i) => i + 1);
  return { answers: ids.map((id) => answer(id, 0)), positions: ids.map((id) => position(id, 0)) };
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
    expect(SKIP).toBe("skip");
    expect(NO_STANCE).toBe("no_stance");
    expect(IMPORTANT_WEIGHT).toBe(2);
    expect(LOW_COVERAGE_THRESHOLD).toBe(5);
  });
});

describe("scenario 1: identical answers give 100%", () => {
  test("six Statements mixing -2..+2", () => {
    const values: ScaleValue[] = [-2, -1, 0, 1, 2, 1];
    const answers = values.map((v, i) => answer(i + 1, v, i === 2));
    const positions = values.map((v, i) => position(i + 1, v));
    expect(computeMatchScore(answers, positions)).toStrictEqual({
      matchScore: 1,
      sharedStatementCount: 6,
      lowCoverage: false,
    });
  });
});

describe("scenario 2: opposite answers give 0%", () => {
  test("five Statements +2/-2 against -2/+2", () => {
    const values: ScaleValue[] = [2, -2, 2, -2, 2];
    const answers = values.map((v, i) => answer(i + 1, v));
    const positions = values.map((v, i) => position(i + 1, -v as ScaleValue));
    const result = computeMatchScore(answers, positions);
    expect(result.matchScore).toBe(0);
    expect(result.sharedStatementCount).toBe(5);
    expect(result.lowCoverage).toBe(false);
  });
});

describe("scenario 3: per-Statement agreement", () => {
  test("distances 0..4", () => {
    expect(statementAgreement(0, 0)).toBe(1);
    expect(statementAgreement(1, 0)).toBe(0.75);
    expect(statementAgreement(0, 2)).toBe(0.5);
    expect(statementAgreement(-1, 2)).toBe(0.25);
    expect(statementAgreement(-2, 2)).toBe(0);
  });

  test("symmetric over the whole scale", () => {
    for (let a = -2; a <= 2; a++) {
      for (let p = -2; p <= 2; p++) {
        expect(statementAgreement(a as ScaleValue, p as ScaleValue)).toBe(
          statementAgreement(p as ScaleValue, a as ScaleValue),
        );
      }
    }
  });

  test("rejects skip, no stance and out-of-range values", () => {
    expect(() => statementAgreement(untyped(SKIP), 0)).toThrow(RangeError);
    expect(() => statementAgreement(0, untyped(NO_STANCE))).toThrow(RangeError);
    expect(() => statementAgreement(untyped(3), 0)).toThrow(RangeError);
  });
});

describe("scenario 4: Important weighs x2", () => {
  // A: agreement 1; B: agreement 0; fillers: agreement 0.5.
  type Flags = { aImportant?: boolean; bImportant?: boolean };
  type Input = { answers: Answer[]; positions: PositionInput[] };
  const build = ({ aImportant, bImportant }: Flags): Input => ({
    answers: [
      answer("A", 2, aImportant),
      answer("B", 2, bImportant),
      answer("F1", 0),
      answer("F2", 0),
      answer("F3", 0),
    ],
    positions: [
      position("A", 2),
      position("B", -2),
      position("F1", 2),
      position("F2", -2),
      position("F3", 2),
    ],
  });
  const reversed = ({ answers, positions }: Input): Input => ({
    answers: [...answers].reverse(),
    positions: [...positions].reverse(),
  });
  const cases: [string, Flags, number][] = [
    ["A Important", { aImportant: true, bImportant: false }, 3.5 / 6],
    ["B Important", { aImportant: false, bImportant: true }, 2.5 / 6],
    ["no Important flags", {}, 2.5 / 5],
  ];

  for (const [name, flags, expected] of cases) {
    test(name, () => {
      const input = build(flags);
      expect(computeMatchScore(input.answers, input.positions).matchScore).toBe(expected);
      const rev = reversed(input);
      expect(computeMatchScore(rev.answers, rev.positions).matchScore).toBe(expected);
    });
  }

  test("no Important flags is exactly 0.5", () => {
    const input = build({});
    expect(computeMatchScore(input.answers, input.positions).matchScore).toBe(0.5);
  });
});

describe("scenario 5: skip and no stance are excluded", () => {
  const remainingAnswers = [answer(1, 2), answer(2, -1, true), answer(3, 0), answer(4, 1), answer(5, -2)];
  const remainingPositions = [position(1, 1), position(2, 2), position(3, -2), position(4, 1), position(5, 0)];

  test("skip (Important) and no stance leave numerator and denominator", () => {
    const answers = [...remainingAnswers, answer(6, SKIP, true), answer(7, -2)];
    const positions = [...remainingPositions, position(6, -2), position(7, NO_STANCE)];
    const expected = computeMatchScore(remainingAnswers, remainingPositions);
    const result = computeMatchScore(answers, positions);
    expect(result.sharedStatementCount).toBe(5);
    expect(result.matchScore).toBe(expected.matchScore);
    expect(result).toStrictEqual(expected);
  });

  test("missing Position or missing Answer is excluded", () => {
    const answers = [...remainingAnswers, answer(6, 2, true)];
    const positions = [...remainingPositions, position(7, -2)];
    const expected = computeMatchScore(remainingAnswers, remainingPositions);
    expect(computeMatchScore(answers, positions)).toStrictEqual(expected);
  });
});

describe("scenario 6: neutral is an answer, not a skip", () => {
  test("answer 0 against position +2 is included with agreement 0.5", () => {
    const result = computeMatchScore([answer(1, 0)], [position(1, 2)]);
    expect(result.sharedStatementCount).toBe(1);
    expect(result.matchScore).toBe(0.5);
  });
});

describe("scenario 7: low-coverage threshold", () => {
  test("default threshold: 4 is low, 5 is not", () => {
    const four = shared(4);
    const five = shared(5);
    expect(computeMatchScore(four.answers, four.positions).lowCoverage).toBe(true);
    expect(computeMatchScore(five.answers, five.positions).lowCoverage).toBe(false);
  });

  test("custom threshold 3: 3 is not low, 2 is", () => {
    const three = shared(3);
    const two = shared(2);
    const options = { lowCoverageThreshold: 3 };
    expect(computeMatchScore(three.answers, three.positions, options).lowCoverage).toBe(false);
    expect(computeMatchScore(two.answers, two.positions, options).lowCoverage).toBe(true);
  });
});

describe("scenario 8: zero shared Statements", () => {
  const none = { matchScore: null, sharedStatementCount: 0, lowCoverage: true };

  test("every Answer is skip", () => {
    const answers = [answer(1, SKIP), answer(2, SKIP, true)];
    expect(computeMatchScore(answers, [position(1, 2), position(2, 0)])).toStrictEqual(none);
  });

  test("no stance on every answered Statement", () => {
    const answers = [answer(1, 2), answer(2, -1)];
    const positions = [position(1, NO_STANCE), position(2, NO_STANCE)];
    expect(computeMatchScore(answers, positions)).toStrictEqual(none);
  });

  test("empty answers", () => {
    expect(computeMatchScore([], [position(1, 2)])).toStrictEqual(none);
  });
});

describe("scenario 9: several Parties", () => {
  test("results in input order, each equal to computeMatchScore", () => {
    const answers = [answer(7, 2, true), answer(8, -1), answer(9, 0)];
    const parties: PartyInput<string | number>[] = [
      { partyId: "c", positions: [position("7", 2), position("8", -1), position("9", 0)] },
      { partyId: "a", positions: [position("7", -2), position("8", 1), position("9", NO_STANCE)] },
      { partyId: 3, positions: [position(7, 0), position("9", 2)] },
    ];
    const results = computeMatchScores(answers, parties);
    expect(results.length).toBe(3);
    expect(results.map((r) => r.partyId)).toStrictEqual(["c", "a", 3]);
    parties.forEach((party, i) => {
      expect(results[i]).toStrictEqual({
        partyId: party.partyId,
        ...computeMatchScore(answers, party.positions),
      });
    });
    // statementId 7 (number) matches "7" (string).
    expect(results[0]!.matchScore).toBe(1);
    expect(results[0]!.sharedStatementCount).toBe(3);
    expect(results[1]!.sharedStatementCount).toBe(2);
    expect(results[1]!.matchScore).toBe((2 * 0 + 1 * 0.5) / 3);
  });

  test("options apply to every Party", () => {
    const { answers, positions } = shared(3);
    const results = computeMatchScores(answers, [{ partyId: "x", positions }], { lowCoverageThreshold: 3 });
    expect(results[0]!.lowCoverage).toBe(false);
  });
});

describe("scenario 10: invalid input fails loudly", () => {
  const goodPositions = [position(1, 0)];

  for (const bad of [3, 1.5, "agree", null, NaN, -3]) {
    test(`answer value ${String(bad)} -> RangeError`, () => {
      expectThrows(() => computeMatchScore([answer(1, untyped(bad))], goodPositions), {
        name: "RangeError",
        message: /answers.*statementId 1/,
      });
    });
  }

  test('position value "no stance" -> RangeError', () => {
    expectThrows(() => computeMatchScore([answer(1, 0)], [position(1, untyped("no stance"))]), {
      name: "RangeError",
      message: /positions.*statementId 1/,
    });
  });

  test('important: "yes" -> TypeError', () => {
    expectThrows(() => computeMatchScore([answer(4, 0, untyped("yes"))], goodPositions), {
      name: "TypeError",
      message: /important.*statementId 4/,
    });
  });

  test("duplicate statementId in answers -> RangeError", () => {
    expectThrows(() => computeMatchScore([answer(1, 0), answer("1", 2)], goodPositions), {
      name: "RangeError",
      message: /answers.*duplicate statementId 1/,
    });
  });

  test("duplicate statementId in positions -> RangeError", () => {
    expectThrows(() => computeMatchScore([answer(1, 0)], [position(2, 0), position(2, 1)]), {
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

describe("scenario 11: purity", () => {
  test("deeply frozen inputs: no throw, repeatable results", () => {
    const answers = deepFreeze([answer(1, 2, true), answer(2, SKIP, true), answer(3, -1)]);
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
    expect(first).toStrictEqual({ matchScore: 0.75, sharedStatementCount: 1, lowCoverage: true });
  });

  test("inputs are not mutated", () => {
    const answers = [answer(1, 2), answer(2, 0, true)];
    const positions = [position(1, 1), position(2, 2)];
    const snapshot = JSON.stringify([answers, positions]);
    computeMatchScore(answers, positions);
    computeMatchScores(answers, [{ partyId: 1, positions }]);
    expect(JSON.stringify([answers, positions])).toBe(snapshot);
  });
});

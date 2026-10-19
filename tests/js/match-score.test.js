import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  IMPORTANT_WEIGHT,
  LOW_COVERAGE_THRESHOLD,
  NO_STANCE,
  SKIP,
  computeMatchScore,
  computeMatchScores,
  statementAgreement,
} from "../../src/ideology_app/static/js/match-score.js";

const answer = (statementId, value, important) =>
  important === undefined ? { statementId, value } : { statementId, value, important };
const position = (statementId, value) => ({ statementId, value });

// n shared Statements, each with answer 0 and position 0.
function shared(n) {
  const ids = Array.from({ length: n }, (_, i) => i + 1);
  return { answers: ids.map((id) => answer(id, 0)), positions: ids.map((id) => position(id, 0)) };
}

function deepFreeze(value) {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value)) deepFreeze(v);
  }
  return value;
}

describe("constants", () => {
  test("exported values", () => {
    assert.strictEqual(SKIP, "skip");
    assert.strictEqual(NO_STANCE, "no_stance");
    assert.strictEqual(IMPORTANT_WEIGHT, 2);
    assert.strictEqual(LOW_COVERAGE_THRESHOLD, 5);
  });
});

describe("scenario 1: identical answers give 100%", () => {
  test("six Statements mixing -2..+2", () => {
    const values = [-2, -1, 0, 1, 2, 1];
    const answers = values.map((v, i) => answer(i + 1, v, i === 2));
    const positions = values.map((v, i) => position(i + 1, v));
    assert.deepStrictEqual(computeMatchScore(answers, positions), {
      matchScore: 1,
      sharedStatementCount: 6,
      lowCoverage: false,
    });
  });
});

describe("scenario 2: opposite answers give 0%", () => {
  test("five Statements +2/-2 against -2/+2", () => {
    const values = [2, -2, 2, -2, 2];
    const answers = values.map((v, i) => answer(i + 1, v));
    const positions = values.map((v, i) => position(i + 1, -v));
    const result = computeMatchScore(answers, positions);
    assert.strictEqual(result.matchScore, 0);
    assert.strictEqual(result.sharedStatementCount, 5);
    assert.strictEqual(result.lowCoverage, false);
  });
});

describe("scenario 3: per-Statement agreement", () => {
  test("distances 0..4", () => {
    assert.strictEqual(statementAgreement(0, 0), 1);
    assert.strictEqual(statementAgreement(1, 0), 0.75);
    assert.strictEqual(statementAgreement(0, 2), 0.5);
    assert.strictEqual(statementAgreement(-1, 2), 0.25);
    assert.strictEqual(statementAgreement(-2, 2), 0);
  });

  test("symmetric over the whole scale", () => {
    for (let a = -2; a <= 2; a++) {
      for (let p = -2; p <= 2; p++) {
        assert.strictEqual(statementAgreement(a, p), statementAgreement(p, a));
      }
    }
  });

  test("rejects skip, no stance and out-of-range values", () => {
    assert.throws(() => statementAgreement(SKIP, 0), RangeError);
    assert.throws(() => statementAgreement(0, NO_STANCE), RangeError);
    assert.throws(() => statementAgreement(3, 0), RangeError);
  });
});

describe("scenario 4: Important weighs x2", () => {
  // A: agreement 1; B: agreement 0; fillers: agreement 0.5.
  const build = ({ aImportant, bImportant }) => ({
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
  const reversed = ({ answers, positions }) => ({
    answers: [...answers].reverse(),
    positions: [...positions].reverse(),
  });
  const cases = [
    ["A Important", { aImportant: true, bImportant: false }, 3.5 / 6],
    ["B Important", { aImportant: false, bImportant: true }, 2.5 / 6],
    ["no Important flags", {}, 2.5 / 5],
  ];

  for (const [name, flags, expected] of cases) {
    test(name, () => {
      const input = build(flags);
      assert.strictEqual(computeMatchScore(input.answers, input.positions).matchScore, expected);
      const rev = reversed(input);
      assert.strictEqual(computeMatchScore(rev.answers, rev.positions).matchScore, expected);
    });
  }

  test("no Important flags is exactly 0.5", () => {
    const input = build({});
    assert.strictEqual(computeMatchScore(input.answers, input.positions).matchScore, 0.5);
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
    assert.strictEqual(result.sharedStatementCount, 5);
    assert.strictEqual(result.matchScore, expected.matchScore);
    assert.deepStrictEqual(result, expected);
  });

  test("missing Position or missing Answer is excluded", () => {
    const answers = [...remainingAnswers, answer(6, 2, true)];
    const positions = [...remainingPositions, position(7, -2)];
    const expected = computeMatchScore(remainingAnswers, remainingPositions);
    assert.deepStrictEqual(computeMatchScore(answers, positions), expected);
  });
});

describe("scenario 6: neutral is an answer, not a skip", () => {
  test("answer 0 against position +2 is included with agreement 0.5", () => {
    const result = computeMatchScore([answer(1, 0)], [position(1, 2)]);
    assert.strictEqual(result.sharedStatementCount, 1);
    assert.strictEqual(result.matchScore, 0.5);
  });
});

describe("scenario 7: low-coverage threshold", () => {
  test("default threshold: 4 is low, 5 is not", () => {
    const four = shared(4);
    const five = shared(5);
    assert.strictEqual(computeMatchScore(four.answers, four.positions).lowCoverage, true);
    assert.strictEqual(computeMatchScore(five.answers, five.positions).lowCoverage, false);
  });

  test("custom threshold 3: 3 is not low, 2 is", () => {
    const three = shared(3);
    const two = shared(2);
    const options = { lowCoverageThreshold: 3 };
    assert.strictEqual(computeMatchScore(three.answers, three.positions, options).lowCoverage, false);
    assert.strictEqual(computeMatchScore(two.answers, two.positions, options).lowCoverage, true);
  });
});

describe("scenario 8: zero shared Statements", () => {
  const none = { matchScore: null, sharedStatementCount: 0, lowCoverage: true };

  test("every Answer is skip", () => {
    const answers = [answer(1, SKIP), answer(2, SKIP, true)];
    assert.deepStrictEqual(computeMatchScore(answers, [position(1, 2), position(2, 0)]), none);
  });

  test("no stance on every answered Statement", () => {
    const answers = [answer(1, 2), answer(2, -1)];
    const positions = [position(1, NO_STANCE), position(2, NO_STANCE)];
    assert.deepStrictEqual(computeMatchScore(answers, positions), none);
  });

  test("empty answers", () => {
    assert.deepStrictEqual(computeMatchScore([], [position(1, 2)]), none);
  });
});

describe("scenario 9: several Parties", () => {
  test("results in input order, each equal to computeMatchScore", () => {
    const answers = [answer(7, 2, true), answer(8, -1), answer(9, 0)];
    const parties = [
      { partyId: "c", positions: [position("7", 2), position("8", -1), position("9", 0)] },
      { partyId: "a", positions: [position("7", -2), position("8", 1), position("9", NO_STANCE)] },
      { partyId: 3, positions: [position(7, 0), position("9", 2)] },
    ];
    const results = computeMatchScores(answers, parties);
    assert.strictEqual(results.length, 3);
    assert.deepStrictEqual(
      results.map((r) => r.partyId),
      ["c", "a", 3],
    );
    parties.forEach((party, i) => {
      assert.deepStrictEqual(results[i], {
        partyId: party.partyId,
        ...computeMatchScore(answers, party.positions),
      });
    });
    // statementId 7 (number) matches "7" (string).
    assert.strictEqual(results[0].matchScore, 1);
    assert.strictEqual(results[0].sharedStatementCount, 3);
    assert.strictEqual(results[1].sharedStatementCount, 2);
    assert.strictEqual(results[1].matchScore, (2 * 0 + 1 * 0.5) / 3);
  });

  test("options apply to every Party", () => {
    const { answers, positions } = shared(3);
    const results = computeMatchScores(answers, [{ partyId: "x", positions }], { lowCoverageThreshold: 3 });
    assert.strictEqual(results[0].lowCoverage, false);
  });
});

describe("scenario 10: invalid input fails loudly", () => {
  const goodPositions = [position(1, 0)];

  for (const bad of [3, 1.5, "agree", null, NaN, -3]) {
    test(`answer value ${String(bad)} -> RangeError`, () => {
      assert.throws(() => computeMatchScore([answer(1, bad)], goodPositions), {
        name: "RangeError",
        message: /answers.*statementId 1/,
      });
    });
  }

  test('position value "no stance" -> RangeError', () => {
    assert.throws(() => computeMatchScore([answer(1, 0)], [position(1, "no stance")]), {
      name: "RangeError",
      message: /positions.*statementId 1/,
    });
  });

  test('important: "yes" -> TypeError', () => {
    assert.throws(() => computeMatchScore([answer(4, 0, "yes")], goodPositions), {
      name: "TypeError",
      message: /important.*statementId 4/,
    });
  });

  test("duplicate statementId in answers -> RangeError", () => {
    assert.throws(() => computeMatchScore([answer(1, 0), answer("1", 2)], goodPositions), {
      name: "RangeError",
      message: /answers.*duplicate statementId 1/,
    });
  });

  test("duplicate statementId in positions -> RangeError", () => {
    assert.throws(() => computeMatchScore([answer(1, 0)], [position(2, 0), position(2, 1)]), {
      name: "RangeError",
      message: /positions.*duplicate statementId 2/,
    });
  });

  test("answers not an array -> TypeError", () => {
    assert.throws(() => computeMatchScore({}, goodPositions), { name: "TypeError", message: /answers/ });
  });

  test("positions not an array -> TypeError", () => {
    assert.throws(() => computeMatchScore([], null), { name: "TypeError", message: /positions/ });
  });

  test("parties not an array -> TypeError", () => {
    assert.throws(() => computeMatchScores([], "x"), { name: "TypeError", message: /parties/ });
  });

  test("bad party positions name the party index", () => {
    assert.throws(() => computeMatchScores([], [{ partyId: "p", positions: [position(1, 9)] }]), {
      name: "RangeError",
      message: /parties\[0\]\.positions.*statementId 1/,
    });
  });

  for (const bad of [0, -1, 2.5, "5", NaN]) {
    test(`lowCoverageThreshold ${String(bad)} -> RangeError`, () => {
      assert.throws(() => computeMatchScore([], [], { lowCoverageThreshold: bad }), {
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
    assert.deepStrictEqual(computeMatchScore(answers, positions, options), first);
    const many = computeMatchScores(answers, parties, options);
    assert.deepStrictEqual(computeMatchScores(answers, parties, options), many);
    assert.deepStrictEqual(first, { matchScore: 0.75, sharedStatementCount: 1, lowCoverage: true });
  });

  test("inputs are not mutated", () => {
    const answers = [answer(1, 2), answer(2, 0, true)];
    const positions = [position(1, 1), position(2, 2)];
    const snapshot = JSON.stringify([answers, positions]);
    computeMatchScore(answers, positions);
    computeMatchScores(answers, [{ partyId: 1, positions }]);
    assert.strictEqual(JSON.stringify([answers, positions]), snapshot);
  });
});

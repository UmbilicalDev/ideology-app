import { describe, expect, test } from "vitest";

import {
  LOW_COVERAGE_THRESHOLD,
  NO_STANCE,
  NEUTRAL,
  computeMatchScores,
  rankParties,
  reduceQuestionnaire,
  startQuestionnaire,
  toMatchScoreAnswers,
  type Answer,
  type AnswerValue,
  type Party,
  type PartyPosition,
  type ScaleValue,
} from "../../src/index";

function party(
  id: number,
  name: string,
  values: readonly (ScaleValue | typeof NO_STANCE)[],
  shortName = `P${id}`,
): Party {
  const positions: PartyPosition[] = values.map((value, i) => ({
    statementId: i + 1,
    value,
    evidence:
      value === NO_STANCE ? null : { quote: "Cita.", page: 1, url: null, sourceDocumentId: 1 },
  }));
  return { id, name, shortName, logoUrl: null, positions };
}

function answers(...values: readonly AnswerValue[]): Answer[] {
  return values.map((value, i) => ({ statementId: i + 1, value, important: false }));
}

function names(ranked: readonly { readonly name: string }[]): string[] {
  return ranked.map((r) => r.name);
}

describe("rankParties", () => {
  test("orders by percentage, highest first, and copies the Party fields", () => {
    const parties = [party(1, "Bajo", [-2, -1]), party(2, "Alto", [2, 1], "AL"), party(3, "Medio", [1, -2])];
    const ranked = rankParties(answers(1, 1), parties);
    expect(names(ranked)).toEqual(["Alto", "Medio", "Bajo"]);
    expect(ranked[0]).toEqual({
      partyId: 2,
      name: "Alto",
      shortName: "AL",
      logoUrl: null,
      matchScore: 1,
      percent: 100,
      comparedStatementCount: 2,
      coincidenceCount: 2,
      lowCoverage: true,
    });
    expect(ranked.map((r) => r.percent)).toEqual([100, 50, 0]);
  });

  test("copies a non-null logoUrl unchanged", () => {
    const logo = "/api/v1/parties/2/logo?v=0123456789abcdef";
    const parties = [party(1, "Uno", [1]), { ...party(2, "Dos", [2]), logoUrl: logo }];
    const ranked = rankParties(answers(1), parties);
    expect(ranked.map((r) => [r.partyId, r.logoUrl])).toEqual([
      [2, logo],
      [1, null],
    ]);
  });

  test("breaks ties by name with Spanish collation, whatever the input order or ids", () => {
    const tied = ["Ñandú", "bloque", "Nuevo", "Álava", "Bilbao"].map((name, i) =>
      party(50 - i, name, [1]),
    );
    const expected = ["Álava", "Bilbao", "bloque", "Nuevo", "Ñandú"];
    expect(names(rankParties(answers(1), tied))).toEqual(expected);
    expect(names(rankParties(answers(1), [...tied].reverse()))).toEqual(expected);
  });

  test("equal names fall back to the Party id", () => {
    const parties = [party(9, "Igual", [1], "B"), party(3, "Igual", [1], "A"), party(5, "Igual", [1], "C")];
    expect(rankParties(answers(1), parties).map((r) => r.partyId)).toEqual([3, 5, 9]);
  });

  test("different raw scores with the same displayed percentage are a tie", () => {
    // The Voter answers 1 on 25 Statements.
    // Zeta: 22 in favour and 3 against -> 22/25 = 0.88 (88 %).
    // Alfa: in favour on 7 of 8 compared Statements, no stance elsewhere -> 7/8 = 0.875 (88 %).
    const zeta = party(1, "Zeta", [
      ...Array.from({ length: 22 }, () => 2 as const),
      ...Array.from({ length: 3 }, () => -2 as const),
    ]);
    const alfa = party(2, "Alfa", [
      ...Array.from({ length: 7 }, () => 1 as const),
      -1,
      ...Array.from({ length: 17 }, () => NO_STANCE),
    ]);
    const voter = answers(...Array.from({ length: 25 }, () => 1 as const));
    const [zetaScore, alfaScore] = computeMatchScores(voter, [
      { partyId: 1, positions: zeta.positions },
      { partyId: 2, positions: alfa.positions },
    ]);
    expect(zetaScore?.matchScore).toBeCloseTo(0.88);
    expect(alfaScore?.matchScore).toBe(0.875);
    const ranked = rankParties(voter, [zeta, alfa]);
    expect(names(ranked)).toEqual(["Alfa", "Zeta"]);
    expect(ranked.map((r) => r.percent)).toEqual([88, 88]);
    expect(ranked.map((r) => [r.coincidenceCount, r.comparedStatementCount])).toEqual([
      [7, 8],
      [22, 25],
    ]);
  });

  test("null scores come last, sorted by name among themselves", () => {
    const parties = [
      party(1, "Zeta sin datos", [NO_STANCE, 0]),
      party(2, "Bajo", [-2, -2]),
      party(3, "Alfa sin datos", [NO_STANCE, NO_STANCE]),
    ];
    const ranked = rankParties(answers(1, NEUTRAL), parties);
    expect(names(ranked)).toEqual(["Bajo", "Alfa sin datos", "Zeta sin datos"]);
    expect(ranked[0]).toMatchObject({ percent: 0, comparedStatementCount: 1, coincidenceCount: 0 });
    expect(ranked[1]).toMatchObject({
      matchScore: null,
      percent: null,
      comparedStatementCount: 0,
      coincidenceCount: 0,
      lowCoverage: true,
    });
    expect(ranked[2]?.percent).toBeNull();
  });

  test("percent is Math.round of the engine score (12.5 -> 13)", () => {
    // Eight Statements, one coincidence -> 0.125.
    const parties = [party(1, "Uno", [2, -2, -2, -2, -2, -2, -2, -1])];
    const voter = answers(1, 1, 1, 1, 1, 1, 1, 1);
    const [engine] = computeMatchScores(voter, [{ partyId: 1, positions: parties[0]!.positions }]);
    expect(engine?.matchScore).toBe(0.125);
    const [ranked] = rankParties(voter, parties);
    expect(ranked?.matchScore).toBe(0.125);
    expect(ranked?.percent).toBe(13);
    expect(ranked?.coincidenceCount).toBe(1);
  });

  test("spec scenario 4: 9 de 12 coincidencias is 75 %", () => {
    const values: ScaleValue[] = [...Array.from({ length: 9 }, () => 2 as const), -1, -2, -1];
    const [ranked] = rankParties(
      answers(...Array.from({ length: 12 }, () => 1 as const)),
      [party(1, "Uno", values)],
    );
    expect(ranked).toMatchObject({ coincidenceCount: 9, comparedStatementCount: 12, percent: 75 });
  });

  test("spec scenario 5: the percent is the weighted coincidence share", () => {
    const voter: Answer[] = [
      { statementId: 1, value: 1, important: true },
      { statementId: 2, value: -1, important: false },
      { statementId: 3, value: 1, important: false },
    ];
    const [ranked] = rankParties(voter, [party(1, "Uno", [2, -1, -2])]);
    expect(ranked).toMatchObject({ coincidenceCount: 2, comparedStatementCount: 3, percent: 75 });
  });

  test("comparedStatementCount, coincidenceCount and lowCoverage are the engine's, with the boundary at 4/5", () => {
    expect(LOW_COVERAGE_THRESHOLD).toBe(5);
    const four = party(1, "Cuatro", [1, 1, -1, 1, NO_STANCE]);
    const five = party(2, "Cinco", [1, 1, 1, 1, -1]);
    const voter = answers(1, 1, 1, 1, 1);
    const ranked = rankParties(voter, [four, five]);
    const engine = computeMatchScores(voter, [
      { partyId: 1, positions: four.positions },
      { partyId: 2, positions: five.positions },
    ]);
    const byId = new Map(ranked.map((r) => [r.partyId, r]));
    for (const result of engine) {
      expect(byId.get(result.partyId)).toMatchObject({
        matchScore: result.matchScore,
        comparedStatementCount: result.comparedStatementCount,
        coincidenceCount: result.coincidenceCount,
        lowCoverage: result.lowCoverage,
      });
    }
    expect(byId.get(1)).toMatchObject({ comparedStatementCount: 4, coincidenceCount: 3, lowCoverage: true });
    expect(byId.get(2)).toMatchObject({ comparedStatementCount: 5, coincidenceCount: 4, lowCoverage: false });
  });

  test("returns a new array and leaves its inputs unchanged", () => {
    const parties = [party(1, "Zeta", [-2]), party(2, "Alfa", [2])];
    const voter = answers(1);
    const partiesCopy = JSON.parse(JSON.stringify(parties)) as unknown;
    const voterCopy = JSON.parse(JSON.stringify(voter)) as unknown;
    const ranked = rankParties(voter, parties);
    expect(ranked).not.toBe(parties);
    expect(names(ranked)).toEqual(["Alfa", "Zeta"]);
    expect(parties).toEqual(partiesCopy);
    expect(names(parties)).toEqual(["Zeta", "Alfa"]);
    expect(voter).toEqual(voterCopy);
  });

  test("an empty Party list gives an empty ranking", () => {
    expect(rankParties(answers(1), [])).toEqual([]);
  });

  test("with toMatchScoreAnswers, a flagged sided Statement weighs 2", () => {
    // Statement 1: Voter 1 vs party 2 (agreement 1); Statement 2: Voter -1 vs party 2 (agreement 0).
    const parties = [party(1, "Uno", [2, 2])];
    const plain = [
      { type: "select", value: 1 },
      { type: "next" },
      { type: "select", value: -1 },
      { type: "next" },
    ] as const;
    const unflagged = plain.reduce(reduceQuestionnaire, startQuestionnaire([1, 2]));
    expect(rankParties(toMatchScoreAnswers(unflagged), parties)[0]?.percent).toBe(50);

    const flagged = [{ type: "toggleImportant" } as const, ...plain].reduce(
      reduceQuestionnaire,
      startQuestionnaire([1, 2]),
    );
    const [ranked] = rankParties(toMatchScoreAnswers(flagged), parties);
    expect(ranked?.matchScore).toBeCloseTo(2 / 3);
    expect(ranked?.percent).toBe(67);
  });
});

import { describe, expect, test } from "vitest";

import {
  NO_STANCE,
  SKIP,
  buildBreakdown,
  buildResults,
  isQuestionnaireAvailable,
  rankParties,
  sharedVersionStatus,
  toMatchScoreAnswers,
  type AnswerValue,
  type Party,
  type QuestionnaireState,
  type ScaleValue,
  type Statement,
} from "../../src/index";

const STATEMENTS: Statement[] = Array.from({ length: 8 }, (_, i) => ({
  id: 200 + i,
  position: i + 1,
  text: `Afirmación ${i + 1}.`,
  topic: "economía",
}));

function party(id: number, name: string, values: readonly (ScaleValue | typeof NO_STANCE)[]): Party {
  return {
    id,
    name,
    shortName: `P${id}`,
    logoUrl: null,
    positions: values.map((value, i) => ({
      statementId: STATEMENTS[i]!.id,
      value,
      evidence:
        value === NO_STANCE ? null : { quote: `Cita ${i}.`, page: 1, url: null, sourceDocumentId: id },
    })),
  };
}

const PARTIES: Party[] = [
  party(1, "Alfa", [2, 1, 0, -1, -2, 1, NO_STANCE, 0]),
  party(2, "Beta", [-2, -1, 0, 1, 2, NO_STANCE, NO_STANCE, 1]),
  party(3, "Gamma", [0, 0, 0, 0, 0, 0, 0, 0]),
];
const VERSION = { statements: STATEMENTS, parties: PARTIES };

const VALUES: readonly AnswerValue[] = [-2, -1, 0, 1, 2, SKIP];

// Small deterministic generator (mulberry32).
function rng(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randomState(next: () => number): QuestionnaireState {
  const answers = new Map<number, AnswerValue>();
  const important = new Set<number>();
  for (const statement of STATEMENTS) {
    if (next() < 0.9) answers.set(statement.id, VALUES[Math.floor(next() * VALUES.length)]!);
    if (next() < 0.3) important.add(statement.id);
  }
  return {
    statementIds: STATEMENTS.map((s) => s.id),
    currentIndex: STATEMENTS.length,
    answers,
    important,
  };
}

describe("buildResults", () => {
  test("equals the hand-composed pipeline for 100 seeded states", () => {
    const next = rng(20261020);
    for (let i = 0; i < 100; i += 1) {
      const state = randomState(next);
      const answers = toMatchScoreAnswers(state);
      const ranking = rankParties(answers, PARTIES);
      const breakdown = buildBreakdown(
        STATEMENTS,
        PARTIES,
        answers,
        ranking.map((p) => p.partyId),
      );
      expect(buildResults(VERSION, state)).toEqual({
        ranking,
        breakdown,
        hasScores: ranking.some((p) => p.matchScore !== null),
      });
    }
  });

  test("hasScores is false when every Statement is skipped, true with one shared rating", () => {
    const ids = STATEMENTS.map((s) => s.id);
    const skipped: QuestionnaireState = {
      statementIds: ids,
      currentIndex: ids.length,
      answers: new Map(ids.map((id) => [id, SKIP] as const)),
      important: new Set(ids),
    };
    const result = buildResults(VERSION, skipped);
    expect(result.hasScores).toBe(false);
    expect(result.ranking.map((p) => p.matchScore)).toEqual([null, null, null]);
    expect(result.breakdown).toHaveLength(8);

    const one: QuestionnaireState = { ...skipped, answers: new Map([[200, 2]]), important: new Set() };
    expect(buildResults(VERSION, one).hasScores).toBe(true);
  });

  test("breakdown rows list Parties in the ranking order", () => {
    const ids = STATEMENTS.map((s) => s.id);
    const state: QuestionnaireState = {
      statementIds: ids,
      currentIndex: ids.length,
      answers: new Map(ids.map((id) => [id, -2] as const)),
      important: new Set(),
    };
    const { ranking, breakdown } = buildResults(VERSION, state);
    const order = ranking.map((p) => p.partyId);
    for (const row of breakdown) {
      expect(row.positions.map((p) => p.partyId)).toEqual(order);
    }
  });

  test("ranking and breakdown carry each Party's logoUrl", () => {
    const logos = new Map([
      [1, "/api/v1/parties/1/logo?v=0000000000000001"],
      [3, "/api/v1/parties/3/logo?v=0000000000000003"],
    ]);
    const parties = PARTIES.map((p) => ({ ...p, logoUrl: logos.get(p.id) ?? null }));
    const ids = STATEMENTS.map((s) => s.id);
    const state: QuestionnaireState = {
      statementIds: ids,
      currentIndex: ids.length,
      answers: new Map(ids.map((id) => [id, 1] as const)),
      important: new Set(),
    };
    const { ranking, breakdown } = buildResults({ statements: STATEMENTS, parties }, state);
    for (const party of ranking) {
      expect(party.logoUrl).toBe(logos.get(party.partyId) ?? null);
    }
    for (const row of breakdown) {
      for (const position of row.positions) {
        expect(position.logoUrl).toBe(logos.get(position.partyId) ?? null);
      }
    }
  });
});

describe("sharedVersionStatus", () => {
  test("current, superseded and no_current", () => {
    expect(sharedVersionStatus({ publishedDatasetVersionId: 1 }, 1)).toBe("current");
    expect(sharedVersionStatus({ publishedDatasetVersionId: 2 }, 1)).toBe("superseded");
    expect(sharedVersionStatus({ publishedDatasetVersionId: null }, 1)).toBe("no_current");
  });

  test("the Questionnaire is offered only for an active Election with a Published version", () => {
    expect(isQuestionnaireAvailable({ status: "active", publishedDatasetVersionId: 2 })).toBe(true);
    expect(isQuestionnaireAvailable({ status: "active", publishedDatasetVersionId: null })).toBe(false);
    expect(isQuestionnaireAvailable({ status: "archived", publishedDatasetVersionId: 2 })).toBe(false);
    expect(isQuestionnaireAvailable({ status: "draft", publishedDatasetVersionId: 2 })).toBe(false);
  });
});
